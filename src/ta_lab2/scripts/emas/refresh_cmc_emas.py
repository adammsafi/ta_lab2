from __future__ import annotations

"""
Refresh CMC EMA pipeline objects after new data is added to cmc_price_histories7.

This script can:

  - Recompute / upsert:
      * cmc_ema_daily
      * cmc_ema_multi_tf
      * cmc_ema_multi_tf_cal          (daily EMA + bar-space EMA with *_bar fields)
      * cmc_ema_multi_tf_cal_anchor   (year-anchored calendar EMAs with *_bar fields)
  - (Re)create views:
      * all_emas
      * cmc_price_with_emas
      * cmc_price_with_emas_d1d2

Default behavior (no --start):

- Uses a "dirty-window" incremental model driven by cmc_price_histories7.load_ts and
  a small watermark table, cmc_ema_refresh_state.

- For DAILY EMAs (cmc_ema_daily):
    * For each id:
        - It reads the last_load_ts_daily from cmc_ema_refresh_state.
        - It looks for new rows in cmc_price_histories7 where load_ts > last_load_ts_daily.
        - If it finds any:
            * It finds the EARLIEST timeclose where load_ts > last_load_ts_daily.
            * If such a row exists, it recomputes daily EMAs from that date forward
              with update_existing=True.
            * It then advances last_load_ts_daily to the max(load_ts) for that id.
        - If no rows have load_ts > last_load_ts_daily, daily EMAs are skipped
          for that id (nothing to update).

    * For MULTI-TF (cmc_ema_multi_tf), CALENDAR MULTI-TF (cmc_ema_multi_tf_cal), and
      CALENDAR-ANCHOR MULTI-TF (cmc_ema_multi_tf_cal_anchor):
        - They incrementally extend from the existing EMA tables, using cmc_ema_daily
          as the canonical source of "how far we can go":
            * For each id:
                * It reads the min/max ts from cmc_ema_daily.
                * It reads the max ts from the target table.
                * If there are daily EMAs beyond the last ts in that target, it
                  recomputes from:
                      - min(daily.ts) if the target table is empty, or
                      - last_target_ts.date() if not empty,
                    with update_existing=True.
                * It then advances the corresponding cmc_ema_refresh_state.*_load_ts
                  watermark so future runs know how far the tables extend.
                * If the table is already caught up to the daily EMA max ts,
                  it skips that table for the id (nothing to extend).

- If you provide --start:
    * It recomputes from that start date and UPDATEs existing EMA rows in that window
      (update_existing=True), same as before.
    * After recomputing, it sets the cmc_ema_refresh_state.*_load_ts watermark
      to max(load_ts) for those ids, so future incremental runs only look at newer
      load_ts values.
"""

import argparse
from typing import Iterable, List, Optional, Sequence, Tuple

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.features.ema import write_daily_ema_to_db
from ta_lab2.features.m_tf.ema_multi_timeframe import (
    write_multi_timeframe_ema_to_db,
)
from ta_lab2.features.m_tf.ema_multi_tf_cal import (
    write_multi_timeframe_ema_cal_to_db,
)
from ta_lab2.features.m_tf.ema_multi_tf_cal_anchor import (
    write_multi_timeframe_ema_cal_anchor_to_db,
)
from ta_lab2.features.m_tf.ema_multi_tf_v2 import (
    refresh_cmc_ema_multi_tf_v2_incremental,
    TIMEFRAME_TF_DAYS as TIMEFRAME_TF_DAYS_V2,
    DEFAULT_PERIODS as DEFAULT_PERIODS_V2,
)
from ta_lab2.io import load_cmc_ohlcv_daily  # kept for compatibility


# ---------------------------------------------------------------------------
# View definitions
# ---------------------------------------------------------------------------

VIEW_ALL_EMAS_SQL = """
CREATE OR REPLACE VIEW public.all_emas AS
    -- Daily EMAs (tf = '1D')
    SELECT
        d.id,
        d.ts,
        '1D'::text AS tf,
        1          AS tf_days,
        d.period,
        d.ema,
        d.d1_roll AS d1,
        d.d2_roll AS d2,
        d.d1      AS d1_close,
        d.d2      AS d2_close,
        FALSE     AS roll
    FROM public.cmc_ema_daily d

    UNION ALL

    -- Multi-timeframe EMAs (rolling EMA by timeframe)
    SELECT
        m.id,
        m.ts,
        m.tf,
        m.tf_days,
        m.period,
        m.ema,
        m.d1_roll AS d1,
        m.d2_roll AS d2,
        m.d1      AS d1_close,
        m.d2      AS d2_close,
        m.roll
    FROM public.cmc_ema_multi_tf m

    UNION ALL

    -- Calendar-aligned multi-timeframe EMAs
    -- ema, d1, d2, d1_roll, d2_roll here refer to the smooth daily EMA spine
    -- in _cal; *_bar fields (ema_bar, d1_bar, d2_bar, roll_bar, d1_roll_bar,
    -- d2_roll_bar) live only in the table and are not exposed in this view.
    SELECT
        c.id,
        c.ts,
        c.tf,
        c.tf_days,
        c.period,
        c.ema,
        c.d1_roll AS d1,
        c.d2_roll AS d2,
        c.d1      AS d1_close,
        c.d2      AS d2_close,
        c.roll
    FROM public.cmc_ema_multi_tf_cal c;
"""

VIEW_PRICE_WITH_EMAS_SQL = """
CREATE OR REPLACE VIEW public.cmc_price_with_emas AS
SELECT
    p.id,
    p.timeclose AS bar_ts,
    p.close,
    p.volume,
    p.marketcap,
    ae.tf,
    ae.tf_days,
    ae.ts     AS ema_ts,
    ae.period,
    ae.ema
FROM public.cmc_price_histories7 p
LEFT JOIN public.all_emas ae
    ON ae.id = p.id
   AND ae.ts = p.timeclose;
"""

VIEW_PRICE_WITH_EMAS_D1D2_SQL = """
CREATE OR REPLACE VIEW public.cmc_price_with_emas_d1d2 AS
SELECT
    p.id,
    p.timeclose AS bar_ts,
    p.close,
    p.volume,
    p.marketcap,
    ae.tf,
    ae.tf_days,
    ae.ts        AS ema_ts,
    ae.period,
    ae.ema,
    ae.d1,
    ae.d2,
    ae.d1_close,
    ae.d2_close,
    ae.roll
FROM public.cmc_price_histories7 p
LEFT JOIN public.all_emas ae
    ON ae.id = p.id
   AND ae.ts = p.timeclose;
"""

DDL_REFRESH_STATE = """
CREATE TABLE IF NOT EXISTS public.cmc_ema_refresh_state (
    id                   INTEGER PRIMARY KEY,
    last_load_ts_daily   TIMESTAMPTZ,
    last_load_ts_multi   TIMESTAMPTZ,
    last_load_ts_cal     TIMESTAMPTZ
);
"""


def _get_engine(db_url: str | None = None) -> Engine:
    url = db_url or TARGET_DB_URL
    if not url:
        raise RuntimeError(
            "No DB URL provided and TARGET_DB_URL is not set in config."
        )
    return create_engine(url)


def _ensure_refresh_state_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(DDL_REFRESH_STATE))


def _load_all_ids(db_url: str | None = None) -> list[int]:
    """
    Load all asset ids from the database when the user passes --ids all.

    By default, we use distinct ids from cmc_price_histories7, ordered ascending.
    """
    engine = _get_engine(db_url)
    sql = """
        SELECT DISTINCT id
        FROM public.cmc_price_histories7
        ORDER BY id;
    """
    with engine.begin() as conn:
        rows = conn.execute(text(sql)).fetchall()
    return [int(r.id) for r in rows]


def _parse_ids(raw_ids: Sequence[str]) -> List[int]:
    """Parse the --ids argument.

    Supports:
      --ids 1 52 1975
      --ids 1,52,1975
      --ids 1 52,1975
    """
    if len(raw_ids) == 1 and "," in raw_ids[0]:
        parts = raw_ids[0].split(",")
    else:
        parts = raw_ids

    ids: List[int] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        ids.append(int(p))
    return ids


# ---------------------------------------------------------------------------
# New-style incremental helpers (load_ts-based)
# ---------------------------------------------------------------------------


def _get_load_ts_bounds_for_id(
    conn,
    asset_id: int,
    *,
    start: Optional[pd.Timestamp] = None,
    end: Optional[pd.Timestamp] = None,
) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """
    Helper that returns (min_timeclose, max_timeclose) for cmc_price_histories7
    rows belonging to `asset_id` within the given [start, end] date range
    (inclusive).
    """
    clauses = ["id = :id"]
    params = {"id": asset_id}

    if start is not None:
        clauses.append("timeclose >= :start")
        params["start"] = start

    if end is not None:
        clauses.append("timeclose <= :end")
        params["end"] = end

    where_clause = " AND ".join(clauses)
    sql = f"""
        SELECT
            MIN(timeclose) AS min_timeclose,
            MAX(timeclose) AS max_timeclose
        FROM public.cmc_price_histories7
        WHERE {where_clause}
    """
    row = conn.execute(text(sql), params).one()
    return row.min_timeclose, row.max_timeclose


def _get_dirty_window_for_id(
    conn,
    asset_id: int,
    *,
    last_load_ts: Optional[pd.Timestamp],
) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """
    Given an asset id and a last_load_ts watermark, return the earliest
    timeclose where load_ts > last_load_ts, and the max(load_ts) in that
    dirty region.

    Returns (min_ts_changed, max_load_ts) or (None, None) if no rows changed.
    """
    if last_load_ts is None:
        sql = """
            SELECT
                MIN(timeclose) AS min_ts_changed,
                MAX(load_ts)   AS max_load_ts
            FROM public.cmc_price_histories7
            WHERE id = :id
        """
        row = conn.execute(text(sql), {"id": asset_id}).one()
    else:
        sql = """
            WITH changed AS (
                SELECT
                    timeclose,
                    load_ts
                FROM public.cmc_price_histories7
                WHERE id = :id
                  AND load_ts > :last_load_ts
            )
            SELECT
                MIN(timeclose) AS min_ts_changed,
                MAX(load_ts)   AS max_load_ts
            FROM changed
        """
        row = conn.execute(
            text(sql),
            {"id": asset_id, "last_load_ts": last_load_ts},
        ).one()

    if row.min_ts_changed is None:
        return None, None

    min_ts_changed = row.min_ts_changed
    max_load_ts = row.max_load_ts
    return min_ts_changed, max_load_ts


def _upsert_refresh_state(
    conn,
    asset_id: int,
    *,
    last_load_ts_daily: Optional[pd.Timestamp] = None,
    last_load_ts_multi: Optional[pd.Timestamp] = None,
    last_load_ts_cal: Optional[pd.Timestamp] = None,
) -> None:
    """
    Upsert the refresh state for a given id. Only non-None fields are updated
    on existing rows, but all three columns are present in the INSERT VALUES
    so bind parameters are always satisfied.
    """
    # Always include all three params (can be None)
    params = {
        "id": asset_id,
        "last_load_ts_daily": last_load_ts_daily,
        "last_load_ts_multi": last_load_ts_multi,
        "last_load_ts_cal": last_load_ts_cal,
    }

    # Build dynamic SET clause for the ON CONFLICT DO UPDATE part
    set_parts = []
    if last_load_ts_daily is not None:
        set_parts.append("last_load_ts_daily = EXCLUDED.last_load_ts_daily")
    if last_load_ts_multi is not None:
        set_parts.append("last_load_ts_multi = EXCLUDED.last_load_ts_multi")
    if last_load_ts_cal is not None:
        set_parts.append("last_load_ts_cal = EXCLUDED.last_load_ts_cal")

    # If nothing is non-None, there's nothing to update/insert meaningfully
    if not set_parts:
        return

    set_clause = ", ".join(set_parts)

    sql = f"""
        INSERT INTO public.cmc_ema_refresh_state
            (id, last_load_ts_daily, last_load_ts_multi, last_load_ts_cal)
        VALUES
            (:id, :last_load_ts_daily, :last_load_ts_multi, :last_load_ts_cal)
        ON CONFLICT (id) DO UPDATE
        SET {set_clause};
    """
    conn.execute(text(sql), params)


# ---------------------------------------------------------------------------
# New helpers for incremental multi-tf / cal logic
# ---------------------------------------------------------------------------


def _get_daily_bounds_for_id(
    conn,
    asset_id: int,
) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """
    Return (min_daily_ts, max_daily_ts) for this id from cmc_ema_daily.
    """
    row = conn.execute(
        text(
            """
            SELECT
                MIN(ts) AS min_daily_ts,
                MAX(ts) AS max_daily_ts
            FROM public.cmc_ema_daily
            WHERE id = :id
            """
        ),
        {"id": asset_id},
    ).one()
    return row.min_daily_ts, row.max_daily_ts


def _get_multi_tf_max_ts_for_id(
    conn,
    asset_id: int,
) -> Optional[pd.Timestamp]:
    """
    Return the maximum ts in cmc_ema_multi_tf for this id (or None if empty).
    """
    row = conn.execute(
        text(
            """
            SELECT
                MAX(ts) AS max_multi_ts
            FROM public.cmc_ema_multi_tf
            WHERE id = :id
            """
        ),
        {"id": asset_id},
    ).one()
    return row.max_multi_ts


def _get_cal_multi_tf_max_ts_for_id(
    conn,
    asset_id: int,
) -> Optional[pd.Timestamp]:
    """
    Return the maximum ts in cmc_ema_multi_tf_cal for this id (or None if empty).
    """
    row = conn.execute(
        text(
            """
            SELECT
                MAX(ts) AS max_cal_ts
            FROM public.cmc_ema_multi_tf_cal
            WHERE id = :id
            """
        ),
        {"id": asset_id},
    ).one()
    return row.max_cal_ts


def _get_cal_anchor_multi_tf_max_ts_for_id(
    conn,
    asset_id: int,
) -> Optional[pd.Timestamp]:
    """
    Return the maximum ts in cmc_ema_multi_tf_cal_anchor for this id
    (or None if empty).
    """
    row = conn.execute(
        text(
            """
            SELECT
                MAX(ts) AS max_cal_anchor_ts
            FROM public.cmc_ema_multi_tf_cal_anchor
            WHERE id = :id
            """
        ),
        {"id": asset_id},
    ).one()
    return row.max_cal_anchor_ts


def refresh(
    ids: Iterable[int],
    start: str | None = None,
    end: str | None = None,
    *,
    db_url: str | None = None,
    update_daily: bool = True,
    update_multi_tf: bool = True,
    update_cal_multi_tf: bool = True,
    update_cal_multi_tf_anchor: bool = True,
    update_multi_tf_v2: bool = True,
    refresh_all_emas_view: bool = True,
    refresh_price_emas_view: bool = True,
    refresh_price_emas_d1d2_view: bool = True,
) -> None:
    """
    Perform the EMA refresh workflow for the given asset ids.

    Parameters
    ----------
    ids:
        Iterable of asset ids to update.
    start:
        Optional start date (YYYY-MM-DD). If provided, we recompute from
        that date forward and update existing rows (update_existing=True).
    end:
        Optional end date (YYYY-MM-DD), inclusive.
    db_url:
        Optional DB URL. Defaults to TARGET_DB_URL if not provided.
    update_daily:
        Whether to recompute/upsert cmc_ema_daily.
    update_multi_tf:
        Whether to recompute/upsert cmc_ema_multi_tf.
    update_cal_multi_tf:
        Whether to recompute/upsert cmc_ema_multi_tf_cal
        (which includes ema + *_bar fields).
    update_cal_multi_tf_anchor:
        Whether to recompute/upsert cmc_ema_multi_tf_cal_anchor
        (year-anchored calendar EMAs with ema + *_bar fields).
    update_multi_tf_v2:
        Whether to recompute/upsert cmc_ema_multi_tf_v2 (pure daily EMA v2).
    refresh_all_emas_view:
        Whether to (re)create public.all_emas view.
    refresh_price_emas_view:
        Whether to (re)create public.cmc_price_with_emas view.
    refresh_price_emas_d1d2_view:
        Whether to (re)create public.cmc_price_with_emas_d1d2 view.
    """
    engine = _get_engine(db_url)
    _ensure_refresh_state_table(engine)

    start_ts: Optional[pd.Timestamp] = None
    end_ts: Optional[pd.Timestamp] = None

    if start is not None:
        start_ts = pd.Timestamp(start).tz_localize("UTC")
    if end is not None:
        end_ts = pd.Timestamp(end).tz_localize("UTC")

    # Normalize ids into a list since we iterate multiple times
    ids = list(ids)
    if not ids:
        print("No ids provided; nothing to do.")
        return

    with engine.begin() as conn:
        if start_ts is not None or end_ts is not None:
            # ------------------------------------------------------------------
            # Case 1: Explicit [start, end] recompute window
            # ------------------------------------------------------------------
            print(
                f"[global] Running explicit-window recompute for ids={ids}, "
                f"start={start_ts}, end={end_ts}."
            )

            # 1) DAILY EMAs
            if update_daily:
                print("[daily] Recomputing cmc_ema_daily in explicit window.")
                df_prices = load_cmc_ohlcv_daily(
                    conn,
                    ids=ids,
                    start=start_ts,
                    end=end_ts,
                )
                if df_prices.empty:
                    print("[daily] No price data in the given window; skipping.")
                else:
                    write_daily_ema_to_db(
                        df_prices,
                        engine,
                        update_existing=True,
                    )

                    # Update last_load_ts_daily watermark for these ids
                    for asset_id in ids:
                        _, max_load_ts = _get_dirty_window_for_id(
                            conn,
                            asset_id,
                            last_load_ts=None,
                        )
                        if max_load_ts is not None:
                            _upsert_refresh_state(
                                conn,
                                asset_id,
                                last_load_ts_daily=max_load_ts,
                            )

            # 2) MULTI-TF, CAL-MULTI-TF, and CAL-ANCHOR MULTI-TF
            for asset_id in ids:
                # Shared daily bounds for this id
                min_daily_ts, max_daily_ts = _get_daily_bounds_for_id(
                    conn,
                    asset_id,
                )

                if update_multi_tf:
                    print(
                        f"[multi_tf] Recomputing cmc_ema_multi_tf for id={asset_id} "
                        "based on explicit EMA window."
                    )
                    if min_daily_ts is None or max_daily_ts is None:
                        print(
                            f"[multi_tf] No daily EMAs for id={asset_id}; skipping."
                        )
                    else:
                        write_multi_timeframe_ema_to_db(
                            engine,
                            [asset_id],
                            start=min_daily_ts,
                            end=max_daily_ts,
                            update_existing=True,
                        )
                        _, max_load_ts = _get_dirty_window_for_id(
                            conn,
                            asset_id,
                            last_load_ts=None,
                        )
                        if max_load_ts is not None:
                            _upsert_refresh_state(
                                conn,
                                asset_id,
                                last_load_ts_multi=max_load_ts,
                            )

                if update_cal_multi_tf:
                    print(
                        f"[multi_tf_cal] Recomputing cmc_ema_multi_tf_cal for id={asset_id} "
                        "based on explicit EMA window."
                    )
                    if min_daily_ts is None or max_daily_ts is None:
                        print(
                            f"[multi_tf_cal] No daily EMAs for id={asset_id}; skipping."
                        )
                    else:
                        # write_multi_timeframe_ema_cal_to_db will populate all
                        # ema, d1, d2, d1_roll, d2_roll, ema_bar, d1_bar, d2_bar,
                        # roll_bar, d1_roll_bar, d2_roll_bar fields consistently.
                        rows = write_multi_timeframe_ema_cal_to_db(
                            engine,
                            [asset_id],
                            start=min_daily_ts,
                            end=max_daily_ts,
                            update_existing=True,
                        )
                        _, max_load_ts = _get_dirty_window_for_id(
                            conn,
                            asset_id,
                            last_load_ts=None,
                        )
                        print(
                            f"[multi_tf_cal] id={asset_id}: inserted/updated {rows} "
                            f"rows into cmc_ema_multi_tf_cal."
                        )
                        if max_load_ts is not None:
                            _upsert_refresh_state(
                                conn,
                                asset_id,
                                last_load_ts_cal=max_load_ts,
                            )

                if update_cal_multi_tf_anchor:
                    print(
                        f"[multi_tf_cal_anchor] Recomputing cmc_ema_multi_tf_cal_anchor "
                        f"for id={asset_id} based on explicit EMA window."
                    )
                    if min_daily_ts is None or max_daily_ts is None:
                        print(
                            "[multi_tf_cal_anchor] "
                            f"No daily EMAs for id={asset_id}; skipping."
                        )
                    else:
                        rows_anchor = write_multi_timeframe_ema_cal_anchor_to_db(
                            ids=[asset_id],
                            start=min_daily_ts,
                            end=max_daily_ts,
                            db_url=db_url,
                            update_existing=True,
                        )
                        _, max_load_ts = _get_dirty_window_for_id(
                            conn,
                            asset_id,
                            last_load_ts=None,
                        )
                        print(
                            "[multi_tf_cal_anchor] id={asset_id}: "
                            f"inserted/updated {rows_anchor} rows into "
                            "cmc_ema_multi_tf_cal_anchor."
                        )
                        if max_load_ts is not None:
                            # Share the same calendar watermark for cal + cal_anchor
                            _upsert_refresh_state(
                                conn,
                                asset_id,
                                last_load_ts_cal=max_load_ts,
                            )

        else:
            # ------------------------------------------------------------------
            # Case 2: Incremental "dirty-window" mode (no explicit start/end)
            # ------------------------------------------------------------------
            print("[global] Running incremental dirty-window mode.")

            for asset_id in ids:
                print(f"[global] Processing id={asset_id}")

                # --------------------------------------------------------------
                # 1) DAILY EMAs (cmc_ema_daily)
                # --------------------------------------------------------------
                last_load_ts_daily: Optional[pd.Timestamp] = None
                row = conn.execute(
                    text(
                        """
                        SELECT last_load_ts_daily
                        FROM public.cmc_ema_refresh_state
                        WHERE id = :id
                        """
                    ),
                    {"id": asset_id},
                ).fetchone()
                if row is not None:
                    last_load_ts_daily = row.last_load_ts_daily

                min_ts_changed, max_load_ts = _get_dirty_window_for_id(
                    conn,
                    asset_id,
                    last_load_ts=last_load_ts_daily,
                )

                if update_daily and min_ts_changed is not None:
                    print(
                        f"[daily] id={asset_id}: recomputing daily EMAs "
                        f"from {min_ts_changed} onward (dirty region)."
                    )
                    df_prices = load_cmc_ohlcv_daily(
                        conn,
                        ids=[asset_id],
                        start=min_ts_changed,
                        end=None,
                    )
                    if df_prices.empty:
                        print(
                            f"[daily] id={asset_id}: no price data in dirty window; "
                            "skipping."
                        )
                    else:
                        write_daily_ema_to_db(
                            df_prices,
                            engine,
                            update_existing=True,
                        )
                        if max_load_ts is not None:
                            _upsert_refresh_state(
                                conn,
                                asset_id,
                                last_load_ts_daily=max_load_ts,
                            )
                else:
                    if update_daily:
                        print(
                            f"[daily] id={asset_id}: no changes since "
                            f"{last_load_ts_daily}; skipping daily EMAs."
                        )

                # --------------------------------------------------------------
                # 2) MULTI-TF EMAs (cmc_ema_multi_tf)
                # --------------------------------------------------------------
                if update_multi_tf:
                    min_daily_ts, max_daily_ts = _get_daily_bounds_for_id(
                        conn,
                        asset_id,
                    )
                    if min_daily_ts is None or max_daily_ts is None:
                        print(
                            f"[multi_tf] id={asset_id}: no daily EMAs; skipping."
                        )
                    else:
                        last_multi_ts = _get_multi_tf_max_ts_for_id(
                            conn,
                            asset_id,
                        )
                        if last_multi_ts is None:
                            print(
                                f"[multi_tf] id={asset_id}: table empty; "
                                "recomputing from min_daily_ts."
                            )
                            start_ts_for_multi = min_daily_ts
                        else:
                            if max_daily_ts <= last_multi_ts:
                                print(
                                    f"[multi_tf] id={asset_id}: already up to "
                                    f"{max_daily_ts}; nothing to extend."
                                )
                                start_ts_for_multi = None
                            else:
                                start_ts_for_multi = last_multi_ts

                        if start_ts_for_multi is not None:
                            write_multi_timeframe_ema_to_db(
                                engine,
                                [asset_id],
                                start=start_ts_for_multi,
                                end=max_daily_ts,
                                update_existing=True,
                            )
                            _, max_load_ts_for_id = _get_dirty_window_for_id(
                                conn,
                                asset_id,
                                last_load_ts=None,
                            )
                            if max_load_ts_for_id is not None:
                                _upsert_refresh_state(
                                    conn,
                                    asset_id,
                                    last_load_ts_multi=max_load_ts_for_id,
                                )

                # --------------------------------------------------------------
                # 3) CALENDAR MULTI-TF EMAs (_cal and _cal_anchor)
                # --------------------------------------------------------------
                if update_cal_multi_tf or update_cal_multi_tf_anchor:
                    min_daily_ts, max_daily_ts = _get_daily_bounds_for_id(
                        conn,
                        asset_id,
                    )

                    if min_daily_ts is None or max_daily_ts is None:
                        if update_cal_multi_tf:
                            print(
                                f"[multi_tf_cal] id={asset_id}: no daily EMAs; skipping."
                            )
                        if update_cal_multi_tf_anchor:
                            print(
                                "[multi_tf_cal_anchor] "
                                f"id={asset_id}: no daily EMAs; skipping."
                            )
                    else:
                        # ----- _cal -----
                        if update_cal_multi_tf:
                            last_cal_ts = _get_cal_multi_tf_max_ts_for_id(
                                conn,
                                asset_id,
                            )
                            if last_cal_ts is None:
                                print(
                                    f"[multi_tf_cal] id={asset_id}: table empty; "
                                    "recomputing from min_daily_ts."
                                )
                                start_ts_for_cal = min_daily_ts
                            else:
                                if max_daily_ts <= last_cal_ts:
                                    print(
                                        "[multi_tf_cal] id={asset_id}: already up to "
                                        f"{max_daily_ts}; nothing to extend."
                                    )
                                    start_ts_for_cal = None
                                else:
                                    start_ts_for_cal = last_cal_ts

                            if start_ts_for_cal is not None:
                                rows = write_multi_timeframe_ema_cal_to_db(
                                    engine,
                                    [asset_id],
                                    start=start_ts_for_cal,
                                    end=max_daily_ts,
                                    update_existing=True,
                                )
                                _, max_load_ts_for_id = _get_dirty_window_for_id(
                                    conn,
                                    asset_id,
                                    last_load_ts=None,
                                )
                                print(
                                    "[multi_tf_cal] id={asset_id}: inserted/updated "
                                    f"{rows} rows into cmc_ema_multi_tf_cal."
                                )
                                if max_load_ts_for_id is not None:
                                    _upsert_refresh_state(
                                        conn,
                                        asset_id,
                                        last_load_ts_cal=max_load_ts_for_id,
                                    )

                        # ----- _cal_anchor -----
                        if update_cal_multi_tf_anchor:
                            last_cal_anchor_ts = _get_cal_anchor_multi_tf_max_ts_for_id(
                                conn,
                                asset_id,
                            )
                            if last_cal_anchor_ts is None:
                                print(
                                    "[multi_tf_cal_anchor] id={asset_id}: table empty; "
                                    "recomputing from min_daily_ts."
                                )
                                start_ts_for_cal_anchor = min_daily_ts
                            else:
                                if max_daily_ts <= last_cal_anchor_ts:
                                    print(
                                        "[multi_tf_cal_anchor] id={asset_id}: "
                                        "already up to "
                                        f"{max_daily_ts}; nothing to extend."
                                    )
                                    start_ts_for_cal_anchor = None
                                else:
                                    start_ts_for_cal_anchor = last_cal_anchor_ts

                            if start_ts_for_cal_anchor is not None:
                                rows_anchor = (
                                    write_multi_timeframe_ema_cal_anchor_to_db(
                                        ids=[asset_id],
                                        start=start_ts_for_cal_anchor,
                                        end=max_daily_ts,
                                        db_url=db_url,
                                        update_existing=True,
                                    )
                                )
                                _, max_load_ts_for_id = _get_dirty_window_for_id(
                                    conn,
                                    asset_id,
                                    last_load_ts=None,
                                )
                                print(
                                    "[multi_tf_cal_anchor] id={asset_id}: "
                                    f"inserted/updated {rows_anchor} rows into "
                                    "cmc_ema_multi_tf_cal_anchor."
                                )
                                if max_load_ts_for_id is not None:
                                    # Share the same calendar watermark
                                    _upsert_refresh_state(
                                        conn,
                                        asset_id,
                                        last_load_ts_cal=max_load_ts_for_id,
                                    )

    # ------------------------------------------------------------------
    # Optional: refresh v2 multi-timeframe EMA (pure daily EMA, no resets)
    # ------------------------------------------------------------------
    if update_multi_tf_v2:
        print(
            "[global] Refreshing v2 multi-timeframe EMA "
            "(cmc_ema_multi_tf_v2) in incremental mode."
        )
        engine = _get_engine(db_url)
        refresh_cmc_ema_multi_tf_v2_incremental(
            engine=engine,
            periods=DEFAULT_PERIODS_V2,
            timeframe_tf_days=TIMEFRAME_TF_DAYS_V2,
            ids=list(ids),
        )

    # ------------------------------------------------------------------
    # 3) Refresh views (definitions only; views are dynamic)
    # ------------------------------------------------------------------
    if any(
        [
            refresh_all_emas_view,
            refresh_price_emas_view,
            refresh_price_emas_d1d2_view,
        ]
    ):
        engine = _get_engine(db_url)
        with engine.begin() as conn:
            if refresh_all_emas_view:
                print("[view] Creating/refreshing public.all_emas .")
                conn.execute(text(VIEW_ALL_EMAS_SQL))

            if refresh_price_emas_view:
                print("[view] Creating/refreshing public.cmc_price_with_emas .")
                conn.execute(text(VIEW_PRICE_WITH_EMAS_SQL))

            if refresh_price_emas_d1d2_view:
                print(
                    "[view] Creating/refreshing public.cmc_price_with_emas_d1d2 ."
                )
                conn.execute(text(VIEW_PRICE_WITH_EMAS_D1D2_SQL))


def _parse_args(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Refresh CMC EMA tables and views after new price data is loaded."
    )
    parser.add_argument(
        "--ids",
        nargs="+",
        required=True,
        help="Asset ids to update (space- or comma-separated), or 'all'.",
    )
    parser.add_argument(
        "--start",
        default=None,
        help=(
            "Start date (YYYY-MM-DD) for EMA recompute. "
            "If omitted, incremental dirty-window mode is used based on load_ts "
            "from cmc_price_histories7."
        ),
    )
    parser.add_argument(
        "--end",
        default=None,
        help="End date (YYYY-MM-DD), inclusive; default: None (up to latest).",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Override DB URL (otherwise uses TARGET_DB_URL from config).",
    )

    # What to update (if none specified, we assume all True)
    parser.add_argument(
        "--update-daily",
        action="store_true",
        help="Recompute/upsert cmc_ema_daily.",
    )
    parser.add_argument(
        "--update-multi-tf",
        action="store_true",
        help="Recompute/upsert cmc_ema_multi_tf.",
    )
    parser.add_argument(
        "--update-cal-multi-tf",
        action="store_true",
        help="Recompute/upsert cmc_ema_multi_tf_cal.",
    )
    parser.add_argument(
        "--update-cal-multi-tf-anchor",
        action="store_true",
        help="Recompute/upsert cmc_ema_multi_tf_cal_anchor.",
    )
    parser.add_argument(
        "--update-multi-tf-v2",
        action="store_true",
        help="Recompute/upsert cmc_ema_multi_tf_v2 (v2: continuous daily EMA).",
    )
    parser.add_argument(
        "--refresh-all-emas-view",
        action="store_true",
        help="(Re)create public.all_emas view.",
    )
    parser.add_argument(
        "--refresh-price-emas-view",
        action="store_true",
        help="(Re)create public.cmc_price_with_emas view.",
    )
    parser.add_argument(
        "--refresh-price-emas-d1d2-view",
        action="store_true",
        help="(Re)create public.cmc_price_with_emas_d1d2 view.",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    # Support special keyword: --ids all
    if len(args.ids) == 1 and args.ids[0].strip().lower() == "all":
        ids = _load_all_ids(args.db_url)
        print(f"Resolved --ids all to {len(ids)} ids from the database.")
    else:
        ids = _parse_ids(args.ids)

    # If user didn't specify any of the flags, default to "update everything"
    any_flag = any(
        [
            args.update_daily,
            args.update_multi_tf,
            args.update_cal_multi_tf,
            args.update_cal_multi_tf_anchor,
            args.update_multi_tf_v2,
            args.refresh_all_emas_view,
            args.refresh_price_emas_view,
            args.refresh_price_emas_d1d2_view,
        ]
    )
    if not any_flag:
        args.update_daily = True
        args.update_multi_tf = True
        args.update_cal_multi_tf = True
        args.update_cal_multi_tf_anchor = True
        args.update_multi_tf_v2 = True
        args.refresh_all_emas_view = True
        args.refresh_price_emas_view = True
        args.refresh_price_emas_d1d2_view = True

    refresh(
        ids=ids,
        start=args.start,
        end=args.end,
        db_url=args.db_url,
        update_daily=args.update_daily,
        update_multi_tf=args.update_multi_tf,
        update_cal_multi_tf=args.update_cal_multi_tf,
        update_cal_multi_tf_anchor=args.update_cal_multi_tf_anchor,
        update_multi_tf_v2=args.update_multi_tf_v2,
        refresh_all_emas_view=args.refresh_all_emas_view,
        refresh_price_emas_view=args.refresh_price_emas_view,
        refresh_price_emas_d1d2_view=args.refresh_price_emas_d1d2_view,
    )


if __name__ == "__main__":
    _parse_args()
