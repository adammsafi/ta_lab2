from __future__ import annotations

"""
Refresh CMC EMA pipeline objects after new data is added to cmc_price_histories7.

This script can:
  - Recompute / upsert:
      * cmc_ema_daily
      * cmc_ema_multi_tf
      * cmc_ema_multi_tf_cal
  - (Re)create views:
      * all_emas
      * cmc_price_with_emas
      * cmc_price_with_emas_d1d2

Behavior

- If you provide ONLY --ids (and optional --end/--db-url), with NO --start:

    * For DAILY (cmc_ema_daily):
        - It runs in incremental "dirty-window" mode based on cmc_price_histories7.load_ts:
            * For each id:
                * It looks up the last processed load_ts_daily from cmc_ema_refresh_state.
                * It finds the EARLIEST timeclose where load_ts > last_load_ts_daily.
                * If such a row exists, it recomputes daily EMAs from that date forward
                  with update_existing=True.
                * It then advances last_load_ts_daily to the max(load_ts) for that id.
            * If no rows have load_ts > last_load_ts_daily, daily EMAs are skipped
              for that id (nothing to update).

    * For MULTI-TF (cmc_ema_multi_tf) and CALENDAR MULTI-TF (cmc_ema_multi_tf_cal):
        - They incrementally extend from the existing EMA tables, using cmc_ema_daily
          as the canonical source of "how far we can go":
            * For each id:
                * It reads the min/max ts from cmc_ema_daily.
                * It reads the max ts from cmc_ema_multi_tf (or cmc_ema_multi_tf_cal).
                * If there are daily EMAs beyond the last multi_tf (or cal) ts, it
                  recomputes from:
                      - min(daily.ts) if the target table is empty, or
                      - last_multi_ts.date() / last_cal_ts.date() if not empty,
                    with update_existing=True.
                * It then advances last_load_ts_multi / last_load_ts_cal to the
                  current max(load_ts) in cmc_price_histories7 for that id.
            * If the multi_tf/cal table is already caught up to the daily EMA max ts,
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

    -- Multi-timeframe EMAs
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
    FROM public.cmc_ema_multi_tf m;
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
FROM public.cmc_price_histories7 AS p
LEFT JOIN public.all_emas AS ae
    ON ae.id = p.id
   AND ae.ts = p.timeclose;
"""


# ---------------------------------------------------------------------------
# Refresh state table (per-id load_ts watermarks)
# ---------------------------------------------------------------------------

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
      --ids all   (expands to all distinct ids in cmc_price_histories7)
    """
    ids: List[int] = []
    for token in raw_ids:
        token_str = str(token).strip()
        if not token_str:
            continue

        # Special case: "all" -> pull all distinct ids from cmc_price_histories7
        if token_str.lower() == "all":
            return _load_all_ids()

        # Allow comma-separated or space-separated ints
        parts = token_str.split(",")
        for p in parts:
            p = p.strip()
            if not p:
                continue
            ids.append(int(p))

    return ids


def _get_refresh_state_for_id(
    conn,
    asset_id: int,
) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """
    Return (last_load_ts_daily, last_load_ts_multi, last_load_ts_cal) for this id.
    """
    row = conn.execute(
        text(
            """
            SELECT
                last_load_ts_daily,
                last_load_ts_multi,
                last_load_ts_cal
            FROM public.cmc_ema_refresh_state
            WHERE id = :id
            """
        ),
        {"id": asset_id},
    ).fetchone()
    if row is None:
        return None, None, None
    return row.last_load_ts_daily, row.last_load_ts_multi, row.last_load_ts_cal


def _get_changed_window(
    conn,
    asset_id: int,
    prev_load_ts: Optional[pd.Timestamp],
) -> Tuple[Optional[pd.Timestamp], Optional[pd.Timestamp]]:
    """
    For a given id and previous load_ts watermark, find the earliest timeclose
    that has load_ts > prev_load_ts, and the max(load_ts) for this id.

    Returns (min_timeclose_changed, max_load_ts_for_id).

    If nothing changed, min_timeclose_changed will be None.
    """
    row = conn.execute(
        text(
            """
            SELECT
                MIN(timeclose) AS min_ts_changed,
                MAX(load_ts)   AS max_load_ts
            FROM public.cmc_price_histories7
            WHERE id = :id
              AND (:prev_load_ts IS NULL OR load_ts > :prev_load_ts)
            """
        ),
        {"id": asset_id, "prev_load_ts": prev_load_ts},
    ).fetchone()

    if row is None:
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
    ).fetchone()
    if row is None:
        return None, None
    return row.min_daily_ts, row.max_daily_ts


def _get_max_ema_ts_for_id(
    conn,
    table_name: str,
    asset_id: int,
) -> Optional[pd.Timestamp]:
    """
    Return MAX(ts) from a given EMA table (cmc_ema_multi_tf or cmc_ema_multi_tf_cal)
    for this id.
    """
    row = conn.execute(
        text(
            f"""
            SELECT MAX(ts) AS max_ts
            FROM public.{table_name}
            WHERE id = :id
            """
        ),
        {"id": asset_id},
    ).fetchone()
    if row is None:
        return None
    return row.max_ts


def _get_max_load_ts_for_id(
    conn,
    asset_id: int,
) -> Optional[pd.Timestamp]:
    """
    Return MAX(load_ts) from cmc_price_histories7 for this id.
    """
    row = conn.execute(
        text(
            """
            SELECT MAX(load_ts) AS max_load_ts
            FROM public.cmc_price_histories7
            WHERE id = :id
            """
        ),
        {"id": asset_id},
    ).fetchone()
    if row is None:
        return None
    return row.max_load_ts


# ---------------------------------------------------------------------------
# Main refresh logic
# ---------------------------------------------------------------------------


def refresh(
    ids: Iterable[int],
    start: str | None = None,
    end: str | None = None,
    *,
    db_url: str | None = None,
    update_daily: bool = True,
    update_multi_tf: bool = True,
    update_cal_multi_tf: bool = True,
    refresh_all_emas_view: bool = True,
    refresh_price_emas_view: bool = True,
    refresh_price_emas_d1d2_view: bool = True,
) -> None:
    """
    Perform the requested updates.

    ids/start/end/db_url are passed through to the EMA writers.

    When start is None:
        * DAILY:
            - Use cmc_price_histories7.load_ts and cmc_ema_refresh_state watermarks
              to detect changed rows and recompute only from the earliest changed
              timeclose for each id.
        * MULTI-TF / CAL:
            - Use cmc_ema_daily as the reference, and extend cmc_ema_multi_tf /
              cmc_ema_multi_tf_cal so their max(ts) matches the max(ts) in
              cmc_ema_daily, recomputing from either the first daily ts (if
              table empty) or from last existing ts for that id.

    When start is not None:
        * Recompute from that start date with update_existing=True for the
          selected tables, and advance the corresponding load_ts watermarks to
          the current max(load_ts) per id.
    """
    ids = list(ids)
    if not ids:
        print("No ids provided; nothing to do.")
        return

    engine = _get_engine(db_url)
    _ensure_refresh_state_table(engine)

    # ------------------------------------------------------------------
    # Case 1: User supplied --start => full recompute from that date
    # ------------------------------------------------------------------
    if start is not None:
        print(
            f"[global] Recomputing from explicit start={start!r}, end={end!r} "
            f"for ids={ids}"
        )

        max_load_ts_by_id: dict[int, Optional[pd.Timestamp]] = {}

        with engine.begin() as conn:
            for asset_id in ids:
                row = conn.execute(
                    text(
                        """
                        SELECT MAX(load_ts) AS max_load_ts
                        FROM public.cmc_price_histories7
                        WHERE id = :id
                        """
                    ),
                    {"id": asset_id},
                ).fetchone()
                max_load_ts_by_id[asset_id] = row.max_load_ts if row else None

        # 1) Daily EMAs
        if update_daily:
            print("[daily] Recomputing cmc_ema_daily via write_daily_ema_to_db()")
            rows = write_daily_ema_to_db(
                ids=ids,
                start=start,
                end=end,
                db_url=db_url,
                update_existing=True,
            )
            print(f"[daily] Upserted/updated {rows} rows into cmc_ema_daily.")

        # 2) Multi-TF EMAs
        if update_multi_tf:
            print(
                "[multi_tf] Recomputing cmc_ema_multi_tf "
                "via write_multi_timeframe_ema_to_db()"
            )
            rows = write_multi_timeframe_ema_to_db(
                ids=ids,
                start=start,
                end=end,
                db_url=db_url,
                update_existing=True,
            )
            print(f"[multi_tf] Upserted/updated {rows} rows into cmc_ema_multi_tf.")

        # 3) Calendar Multi-TF EMAs
        if update_cal_multi_tf:
            print(
                "[cal] Recomputing cmc_ema_multi_tf_cal "
                "via write_multi_timeframe_ema_cal_to_db()"
            )
            rows = write_multi_timeframe_ema_cal_to_db(
                ids=ids,
                start=start,
                end=end,
                db_url=db_url,
                update_existing=True,
            )
            print(
                f"[cal] Upserted/updated {rows} rows into cmc_ema_multi_tf_cal."
            )

        # 4) Advance watermarks
        with engine.begin() as conn:
            for asset_id in ids:
                max_load_ts = max_load_ts_by_id.get(asset_id)
                if max_load_ts is None:
                    continue
                _upsert_refresh_state(
                    conn,
                    asset_id,
                    last_load_ts_daily=max_load_ts if update_daily else None,
                    last_load_ts_multi=max_load_ts if update_multi_tf else None,
                    last_load_ts_cal=max_load_ts if update_cal_multi_tf else None,
                )

    # ------------------------------------------------------------------
    # Case 2: start is None => incremental mode
    # ------------------------------------------------------------------
    else:
        print(
            f"[global] Incremental dirty-window mode (start=None, end={end!r}) "
            f"for ids={ids}"
        )

        # First pass: inspect windows and log (no writes yet)
        with engine.begin() as conn:
            for asset_id in ids:
                (
                    prev_daily,
                    prev_multi,
                    prev_cal,
                ) = _get_refresh_state_for_id(conn, asset_id)

                # DAILY: still uses load_ts dirty-window logic
                if update_daily:
                    min_ts_changed, max_load_ts = _get_changed_window(
                        conn, asset_id, prev_daily
                    )
                    if min_ts_changed is None or max_load_ts is None:
                        print(
                            f"[daily] id={asset_id}: no changed price rows "
                            f"(load_ts <= {prev_daily}); skipping daily EMAs."
                        )
                    else:
                        start_date = min_ts_changed.date().isoformat()
                        print(
                            f"[daily] id={asset_id}: recomputing cmc_ema_daily "
                            f"from {start_date} (min changed ts={min_ts_changed}) "
                            f"through end={end!r}"
                        )

                # MULTI-TF: extend based on daily vs multi span
                if update_multi_tf:
                    min_daily_ts, max_daily_ts = _get_daily_bounds_for_id(
                        conn, asset_id
                    )
                    last_multi_ts = _get_max_ema_ts_for_id(
                        conn, "cmc_ema_multi_tf", asset_id
                    )

                    if max_daily_ts is None:
                        print(
                            f"[multi_tf] id={asset_id}: no daily EMAs found; "
                            f"skipping multi-TF EMAs."
                        )
                    else:
                        if last_multi_ts is None:
                            # Table empty: recompute from first daily ts
                            start_date_multi = min_daily_ts.date().isoformat()
                            print(
                                f"[multi_tf] id={asset_id}: table empty; "
                                f"recomputing cmc_ema_multi_tf from {start_date_multi} "
                                f"through end={end!r} (daily span "
                                f"{min_daily_ts} -> {max_daily_ts})."
                            )
                        elif max_daily_ts <= last_multi_ts:
                            print(
                                f"[multi_tf] id={asset_id}: already up to date "
                                f"(last_multi_ts={last_multi_ts}, "
                                f"last_daily_ts={max_daily_ts}); skipping."
                            )
                        else:
                            start_date_multi = last_multi_ts.date().isoformat()
                            print(
                                f"[multi_tf] id={asset_id}: extending "
                                f"cmc_ema_multi_tf from {start_date_multi} "
                                f"(last_multi_ts={last_multi_ts}, "
                                f"last_daily_ts={max_daily_ts}) "
                                f"through end={end!r}."
                            )

                # CALENDAR MULTI-TF: extend based on daily vs cal span
                if update_cal_multi_tf:
                    min_daily_ts, max_daily_ts = _get_daily_bounds_for_id(
                        conn, asset_id
                    )
                    last_cal_ts = _get_max_ema_ts_for_id(
                        conn, "cmc_ema_multi_tf_cal", asset_id
                    )

                    if max_daily_ts is None:
                        print(
                            f"[cal] id={asset_id}: no daily EMAs found; "
                            f"skipping cal EMAs."
                        )
                    else:
                        if last_cal_ts is None:
                            start_date_cal = min_daily_ts.date().isoformat()
                            print(
                                f"[cal] id={asset_id}: table empty; recomputing "
                                f"cmc_ema_multi_tf_cal from {start_date_cal} "
                                f"through end={end!r} (daily span "
                                f"{min_daily_ts} -> {max_daily_ts})."
                            )
                        elif max_daily_ts <= last_cal_ts:
                            print(
                                f"[cal] id={asset_id}: already up to date "
                                f"(last_cal_ts={last_cal_ts}, "
                                f"last_daily_ts={max_daily_ts}); skipping."
                            )
                        else:
                            start_date_cal = last_cal_ts.date().isoformat()
                            print(
                                f"[cal] id={asset_id}: extending "
                                f"cmc_ema_multi_tf_cal from {start_date_cal} "
                                f"(last_cal_ts={last_cal_ts}, "
                                f"last_daily_ts={max_daily_ts}) "
                                f"through end={end!r}."
                            )

        # Second pass: actually recompute and update state
        for asset_id in ids:
            with engine.begin() as conn:
                prev_daily, prev_multi, prev_cal = _get_refresh_state_for_id(
                    conn, asset_id
                )

                # Latest load_ts for this id (used to advance multi/cal watermarks)
                max_load_ts_for_id = _get_max_load_ts_for_id(conn, asset_id)

                # DAILY
                if update_daily:
                    min_ts_changed, max_load_ts = _get_changed_window(
                        conn, asset_id, prev_daily
                    )
                    if min_ts_changed is None or max_load_ts is None:
                        # nothing changed for daily
                        pass
                    else:
                        start_date = min_ts_changed.date().isoformat()
                        print(
                            f"[daily] id={asset_id}: recomputing cmc_ema_daily "
                            f"from {start_date} through end={end!r}"
                        )
                        rows = write_daily_ema_to_db(
                            ids=[asset_id],
                            start=start_date,
                            end=end,
                            db_url=db_url,
                            update_existing=True,
                        )
                        print(
                            f"[daily] id={asset_id}: upserted/updated {rows} "
                            f"rows into cmc_ema_daily."
                        )
                        _upsert_refresh_state(
                            conn,
                            asset_id,
                            last_load_ts_daily=max_load_ts,
                        )

                # MULTI-TF
                if update_multi_tf:
                    min_daily_ts, max_daily_ts = _get_daily_bounds_for_id(
                        conn, asset_id
                    )
                    last_multi_ts = _get_max_ema_ts_for_id(
                        conn, "cmc_ema_multi_tf", asset_id
                    )

                    if max_daily_ts is None:
                        # No daily EMAs; nothing to do.
                        pass
                    else:
                        start_date_multi: Optional[str] = None
                        if last_multi_ts is None:
                            # Empty table: start from first daily ts
                            start_date_multi = min_daily_ts.date().isoformat()
                        elif max_daily_ts > last_multi_ts:
                            # Extend from last multi_tf ts
                            start_date_multi = last_multi_ts.date().isoformat()

                        if start_date_multi is not None:
                            print(
                                f"[multi_tf] id={asset_id}: recomputing "
                                f"cmc_ema_multi_tf from {start_date_multi} "
                                f"through end={end!r}"
                            )
                            rows = write_multi_timeframe_ema_to_db(
                                ids=[asset_id],
                                start=start_date_multi,
                                end=end,
                                db_url=db_url,
                                update_existing=True,
                            )
                            print(
                                f"[multi_tf] id={asset_id}: upserted/updated {rows} "
                                f"rows into cmc_ema_multi_tf."
                            )
                            if max_load_ts_for_id is not None:
                                _upsert_refresh_state(
                                    conn,
                                    asset_id,
                                    last_load_ts_multi=max_load_ts_for_id,
                                )

                # CALENDAR MULTI-TF
                if update_cal_multi_tf:
                    min_daily_ts, max_daily_ts = _get_daily_bounds_for_id(
                        conn, asset_id
                    )
                    last_cal_ts = _get_max_ema_ts_for_id(
                        conn, "cmc_ema_multi_tf_cal", asset_id
                    )

                    if max_daily_ts is None:
                        # No daily EMAs; nothing to do.
                        pass
                    else:
                        start_date_cal: Optional[str] = None
                        if last_cal_ts is None:
                            start_date_cal = min_daily_ts.date().isoformat()
                        elif max_daily_ts > last_cal_ts:
                            start_date_cal = last_cal_ts.date().isoformat()

                        if start_date_cal is not None:
                            print(
                                f"[cal] id={asset_id}: recomputing "
                                f"cmc_ema_multi_tf_cal from {start_date_cal} "
                                f"through end={end!r}"
                            )
                            rows = write_multi_timeframe_ema_cal_to_db(
                                ids=[asset_id],
                                start=start_date_cal,
                                end=end,
                                db_url=db_url,
                                update_existing=True,
                            )
                            print(
                                f"[cal] id={asset_id}: upserted/updated {rows} "
                                f"rows into cmc_ema_multi_tf_cal."
                            )
                            if max_load_ts_for_id is not None:
                                _upsert_refresh_state(
                                    conn,
                                    asset_id,
                                    last_load_ts_cal=max_load_ts_for_id,
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

        print("[view] View refresh complete.")

    print("Done.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
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
            "for daily, and based on ema_daily span for multi_tf / cal."
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
            args.refresh_all_emas_view,
            args.refresh_price_emas_view,
            args.refresh_price_emas_d1d2_view,
        ]
    )
    if not any_flag:
        args.update_daily = True
        args.update_multi_tf = True
        args.update_cal_multi_tf = True
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
        refresh_all_emas_view=args.refresh_all_emas_view,
        refresh_price_emas_view=args.refresh_price_emas_view,
        refresh_price_emas_d1d2_view=args.refresh_price_emas_d1d2_view,
    )


if __name__ == "__main__":
    main()
