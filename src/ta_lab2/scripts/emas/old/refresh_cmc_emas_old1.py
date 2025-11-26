# src/ta_lab2/scripts/refresh_cmc_emas.py
from __future__ import annotations

"""
Refresh CMC EMA pipeline objects after new data is added to cmc_price_histories7.

This script can:
  - Recompute / upsert:
      * cmc_ema_daily
      * cmc_ema_multi_tf
  - (Re)create views:
      * all_emas
      * cmc_price_with_emas
      * cmc_price_with_emas_d1d2

Default behavior:

- If you provide ONLY --ids (and optional --end/--db-url), with NO --start:
    * It will run in incremental insert-only mode:
        - Daily EMAs are extended using the last EMA state from cmc_ema_daily
          and only NEW price rows from cmc_price_histories7.
        - Existing daily EMA rows are NOT touched.
        - Multi-timeframe EMAs are extended from the last multi-TF EMA state
          in cmc_ema_multi_tf, using only NEW price rows, and written
          insert-only (ON CONFLICT DO NOTHING).

- If you provide --start:
    * It will recompute from that start date and UPDATE existing EMA rows
      in that window (ON CONFLICT DO UPDATE), same as before.
"""

import argparse
from typing import Iterable, List, Sequence

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.features.ema import (
    write_daily_ema_to_db,
    build_daily_ema_tail_from_seeds,
)
from ta_lab2.features.m_tf.ema_multi_timeframe import (
    write_multi_timeframe_ema_to_db,
)
from ta_lab2.io import load_cmc_ohlcv_daily

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
# Helpers
# ---------------------------------------------------------------------------


def _get_engine(db_url: str | None = None) -> Engine:
    url = db_url or TARGET_DB_URL
    if not url:
        raise RuntimeError(
            "No DB URL provided and TARGET_DB_URL is not set in config."
        )
    return create_engine(url)


def _load_all_ids(db_url: str | None = None) -> list[int]:
    """
    Load all asset ids from the database when the user passes --ids all.

    By default, we use distinct ids from cmc_price_histories7, ordered ascending.
    If you prefer to use da_ids or another table, adjust the SQL here.
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
    ids: List[int] = []
    for token in raw_ids:
        # Allow comma-separated or space-separated
        parts = str(token).split(",")
        for p in parts:
            p = p.strip()
            if not p:
                continue
            ids.append(int(p))
    return ids


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
    refresh_all_emas_view: bool = True,
    refresh_price_emas_view: bool = True,
    refresh_price_emas_d1d2_view: bool = True,
) -> None:
    """
    Perform the requested updates.

    ids/start/end/db_url are passed through to the EMA writers.

    Behavior:
        - If start is None -> insert-only mode.
            * Daily: incremental from last EMA state using only NEW prices.
            * Multi-TF: incremental from last multi-TF EMA state using only NEW prices.
        - If start is not None -> update-existing mode (same as previous behavior).
    """
    ids = list(ids)
    if not ids:
        print("No ids provided; nothing to do.")
        return

    # If start is None we want "insert-only" (no updates on conflict)
    update_existing = start is not None

    # 1) Update daily EMA table
    if update_daily:
        if start is None:
            # Incremental insert-only mode for daily EMAs
            print(
                f"[daily] Incremental insert-only update for ids={ids}, "
                f"start=None, end={end!r}"
            )
            engine = _get_engine(db_url)

            all_tail_frames: list[pd.DataFrame] = []

            for asset_id in ids:
                # 1) Find last ts in cmc_ema_daily for this id (tf='1D')
                with engine.begin() as conn:
                    last_ts = conn.execute(
                        text(
                            """
                            SELECT MAX(ts) AS last_ts
                            FROM public.cmc_ema_daily
                            WHERE id = :id AND tf = '1D'
                            """
                        ),
                        {"id": asset_id},
                    ).scalar()

                if last_ts is None:
                    # No existing EMA rows for this id: first-time backfill.
                    print(
                        f"[daily] No existing daily EMAs for id={asset_id}; "
                        "running full backfill via write_daily_ema_to_db()."
                    )
                    rows = write_daily_ema_to_db(
                        ids=[asset_id],
                        start="2010-01-01",
                        end=end,
                        db_url=db_url,
                        update_existing=False,  # insert-only
                    )
                    print(
                        f"[daily] Backfilled {rows} rows into cmc_ema_daily for id={asset_id}."
                    )
                    continue

                # 2) Fetch seed EMA state at last_ts (one row per period)
                with engine.begin() as conn:
                    seed_rows = conn.execute(
                        text(
                            """
                            SELECT period, ema, d1_roll, d2_roll, d1, d2
                            FROM public.cmc_ema_daily
                            WHERE id = :id
                              AND tf = '1D'
                              AND ts = (
                                  SELECT MAX(ts)
                                  FROM public.cmc_ema_daily
                                  WHERE id = :id AND tf = '1D'
                              )
                            ORDER BY period
                            """
                        ),
                        {"id": asset_id},
                    ).fetchall()

                if not seed_rows:
                    print(
                        f"[daily] Warning: last_ts exists but no seed rows for id={asset_id}; "
                        "skipping incremental for this id."
                    )
                    continue

                seeds: dict[int, dict[str, float]] = {}
                for r in seed_rows:
                    period = int(r.period)
                    seeds[period] = {
                        "ema": float(r.ema),
                        "d1_roll": float(r.d1_roll) if r.d1_roll is not None else None,
                        "d2_roll": float(r.d2_roll) if r.d2_roll is not None else None,
                        "d1": float(r.d1) if r.d1 is not None else None,
                        "d2": float(r.d2) if r.d2 is not None else None,
                    }

                # 3) Load new daily prices for this id (ts > last_ts)
                start_date = last_ts.date().isoformat()
                daily = load_cmc_ohlcv_daily(
                    ids=[asset_id],
                    start=start_date,
                    end=end,
                    db_url=db_url,
                    tz="UTC",
                )

                if isinstance(daily.index, pd.MultiIndex):
                    idx_names = list(daily.index.names or [])
                    if "id" in idx_names and "ts" in idx_names:
                        daily = daily.reset_index()

                if "timestamp" in daily.columns and "ts" not in daily.columns:
                    daily = daily.rename(columns={"timestamp": "ts"})

                required = {"id", "ts", "close"}
                missing = required - set(daily.columns)
                if missing:
                    raise ValueError(
                        f"Daily OHLCV missing required columns: {missing}"
                    )

                daily["ts"] = pd.to_datetime(daily["ts"], utc=True)
                daily = daily.sort_values(["id", "ts"]).reset_index(drop=True)

                df_id = daily[
                    (daily["id"] == asset_id) & (daily["ts"] > last_ts)
                ].copy()

                if df_id.empty:
                    print(
                        f"[daily] No new daily price rows for id={asset_id} after {last_ts}; skipping."
                    )
                    continue

                # 4) Build EMA tail from seeds
                tail = build_daily_ema_tail_from_seeds(
                    df_id[["ts", "close"]],
                    asset_id=asset_id,
                    seeds=seeds,
                    tf_label="1D",
                    tf_days=1,
                )
                all_tail_frames.append(tail)

            if all_tail_frames:
                df_all = pd.concat(all_tail_frames, ignore_index=True)
                engine = _get_engine(db_url)
                tmp_table = "cmc_ema_daily_tmp_refresh"

                with engine.begin() as conn:
                    conn.execute(
                        text(f"DROP TABLE IF EXISTS public.{tmp_table};")
                    )
                    conn.execute(
                        text(
                            f"""
                            CREATE TEMP TABLE {tmp_table} AS
                            SELECT
                                id,
                                tf,
                                ts,
                                period,
                                ema,
                                tf_days,
                                roll,
                                d1,
                                d2,
                                d1_roll,
                                d2_roll
                            FROM public.cmc_ema_daily
                            LIMIT 0;
                            """
                        )
                    )

                    df_all.to_sql(
                        tmp_table,
                        conn,
                        if_exists="append",
                        index=False,
                        method="multi",
                    )

                    sql = f"""
                    INSERT INTO public.cmc_ema_daily AS t
                        (id, tf, ts, period, ema, tf_days, roll,
                         d1, d2, d1_roll, d2_roll)
                    SELECT
                        id, tf, ts, period, ema, tf_days, roll,
                        d1, d2, d1_roll, d2_roll
                    FROM {tmp_table}
                    ON CONFLICT (id, ts, period) DO NOTHING;
                    """
                    res = conn.execute(text(sql))
                    rows = res.rowcount or 0

                print(
                    f"[daily] Inserted {rows} new incremental daily EMA rows into cmc_ema_daily."
                )
            else:
                print("[daily] No new incremental daily EMA rows to insert.")

        else:
            # start is not None -> full recompute (update_existing=True)
            print(
                f"[daily] Updating cmc_ema_daily for ids={ids}, "
                f"start={start!r}, end={end!r}, "
                f"update_existing={update_existing}"
            )
            rows = write_daily_ema_to_db(
                ids=ids,
                start=start,
                end=end,
                db_url=db_url,
                update_existing=update_existing,
            )
            print(f"[daily] Upserted/updated {rows} rows into cmc_ema_daily.")

    # 2) Update multi-timeframe EMA table
    if update_multi_tf:
        if start is None:
            # Incremental insert-only mode for multi-TF EMAs
            print(
                f"[multi_tf] Incremental insert-only update for ids={ids}, "
                f"start=None, end={end!r}"
            )
            engine = _get_engine(db_url)
            all_rows: list[dict] = []

            for asset_id in ids:
                # 1) Find last ts in cmc_ema_multi_tf for this id
                with engine.begin() as conn:
                    last_ts_multi = conn.execute(
                        text(
                            """
                            SELECT MAX(ts) AS last_ts
                            FROM public.cmc_ema_multi_tf
                            WHERE id = :id
                            """
                        ),
                        {"id": asset_id},
                    ).scalar()

                if last_ts_multi is None:
                    # No existing multi-TF EMAs for this id: first-time backfill.
                    print(
                        f"[multi_tf] No existing multi-TF EMAs for id={asset_id}; "
                        "running full backfill via write_multi_timeframe_ema_to_db()."
                    )
                    rows = write_multi_timeframe_ema_to_db(
                        ids=[asset_id],
                        start="2010-01-01",
                        end=end,
                        db_url=db_url,
                        update_existing=False,
                    )
                    print(
                        f"[multi_tf] Backfilled {rows} rows into cmc_ema_multi_tf for id={asset_id}."
                    )
                    continue

                # 2) Fetch last row (any roll) per (tf, period) as EMA seed
                with engine.begin() as conn:
                    last_any_rows = conn.execute(
                        text(
                            """
                            WITH last_any AS (
                                SELECT
                                    tf,
                                    tf_days,
                                    period,
                                    ts,
                                    ema,
                                    d1_roll,
                                    ROW_NUMBER() OVER (
                                        PARTITION BY tf, period
                                        ORDER BY ts DESC
                                    ) AS rn
                                FROM public.cmc_ema_multi_tf
                                WHERE id = :id
                            )
                            SELECT
                                tf,
                                tf_days,
                                period,
                                ts,
                                ema,
                                d1_roll
                            FROM last_any
                            WHERE rn = 1
                            ORDER BY tf, period;
                            """
                        ),
                        {"id": asset_id},
                    ).fetchall()

                    # 3) Fetch last roll=FALSE row per (tf, period) as canonical seed
                    last_close_rows = conn.execute(
                        text(
                            """
                            WITH last_close AS (
                                SELECT
                                    tf,
                                    period,
                                    ts,
                                    ema,
                                    d1,
                                    ROW_NUMBER() OVER (
                                        PARTITION BY tf, period
                                        ORDER BY ts DESC
                                    ) AS rn
                                FROM public.cmc_ema_multi_tf
                                WHERE id = :id
                                  AND roll = FALSE
                            )
                            SELECT
                                tf,
                                period,
                                ts AS close_ts,
                                ema AS ema_close,
                                d1  AS d1_close
                            FROM last_close
                            WHERE rn = 1
                            ORDER BY tf, period;
                            """
                        ),
                        {"id": asset_id},
                    ).fetchall()

                if not last_any_rows or not last_close_rows:
                    print(
                        f"[multi_tf] Warning: missing seed rows for id={asset_id}; "
                        "falling back to full backfill."
                    )
                    rows = write_multi_timeframe_ema_to_db(
                        ids=[asset_id],
                        start="2010-01-01",
                        end=end,
                        db_url=db_url,
                        update_existing=False,
                    )
                    print(
                        f"[multi_tf] Backfilled {rows} rows into cmc_ema_multi_tf for id={asset_id}."
                    )
                    continue

                # Build seed dict keyed by (tf, period)
                seeds_any: dict[tuple[str, int], dict] = {}
                for r in last_any_rows:
                    key = (str(r.tf), int(r.period))
                    seeds_any[key] = {
                        "tf_days": int(r.tf_days),
                        "last_ts_any": r.ts,
                        "ema_prev": float(r.ema),
                        "d1_roll_prev": float(r.d1_roll) if r.d1_roll is not None else None,
                    }

                seeds_close: dict[tuple[str, int], dict] = {}
                for r in last_close_rows:
                    key = (str(r.tf), int(r.period))
                    seeds_close[key] = {
                        "last_close_ts": r.close_ts,
                        "ema_close_prev": float(r.ema_close),
                        "d1_close_prev": float(r.d1_close) if r.d1_close is not None else None,
                    }

                # Merge seeds where we have both any and close
                seeds_multi: dict[tuple[str, int], dict] = {}
                for key, any_state in seeds_any.items():
                    if key not in seeds_close:
                        # If we don't have a canonical row, skip incremental for this (tf, period)
                        continue
                    close_state = seeds_close[key]
                    state = {
                        "tf": key[0],
                        "period": key[1],
                        "tf_days": any_state["tf_days"],
                        "ema_prev": any_state["ema_prev"],
                        "d1_roll_prev": any_state["d1_roll_prev"],
                        "ema_close_prev": close_state["ema_close_prev"],
                        "d1_close_prev": close_state["d1_close_prev"],
                        "last_close_date": close_state["last_close_ts"].date(),
                    }
                    seeds_multi[key] = state

                if not seeds_multi:
                    print(
                        f"[multi_tf] Warning: no combined seeds for id={asset_id}; "
                        "falling back to full backfill."
                    )
                    rows = write_multi_timeframe_ema_to_db(
                        ids=[asset_id],
                        start="2010-01-01",
                        end=end,
                        db_url=db_url,
                        update_existing=False,
                    )
                    print(
                        f"[multi_tf] Backfilled {rows} rows into cmc_ema_multi_tf for id={asset_id}."
                    )
                    continue

                # 4) Load new daily prices for this id (ts > last_ts_multi)
                start_date_multi = last_ts_multi.date().isoformat()
                daily = load_cmc_ohlcv_daily(
                    ids=[asset_id],
                    start=start_date_multi,
                    end=end,
                    db_url=db_url,
                    tz="UTC",
                )

                if isinstance(daily.index, pd.MultiIndex):
                    idx_names = list(daily.index.names or [])
                    if "id" in idx_names and "ts" in idx_names:
                        daily = daily.reset_index()

                if "timestamp" in daily.columns and "ts" not in daily.columns:
                    daily = daily.rename(columns={"timestamp": "ts"})

                required = {"id", "ts", "close"}
                missing = required - set(daily.columns)
                if missing:
                    raise ValueError(
                        f"Daily OHLCV missing required columns for multi-TF: {missing}"
                    )

                daily["ts"] = pd.to_datetime(daily["ts"], utc=True)
                daily = daily.sort_values(["id", "ts"]).reset_index(drop=True)

                df_id = daily[
                    (daily["id"] == asset_id) & (daily["ts"] > last_ts_multi)
                ].copy()

                if df_id.empty:
                    print(
                        f"[multi_tf] No new daily price rows for id={asset_id} after {last_ts_multi}; skipping."
                    )
                    continue

                # 5) Build multi-TF EMA tail from seeds_multi
                rows_id: list[dict] = []

                # Precompute per-key alpha
                for key, state in seeds_multi.items():
                    period = state["period"]
                    alpha = 2.0 / (period + 1.0)
                    state["alpha"] = alpha

                for _, row in df_id.sort_values("ts").iterrows():
                    ts = row["ts"]
                    close = float(row["close"])
                    date = ts.date()

                    for (tf, period), state in seeds_multi.items():
                        tf_days = state["tf_days"]
                        alpha = state["alpha"]

                        ema_prev = state["ema_prev"]
                        d1_roll_prev = state["d1_roll_prev"]
                        ema_close_prev = state["ema_close_prev"]
                        d1_close_prev = state["d1_close_prev"]
                        last_close_date = state["last_close_date"]

                        # Standard EMA recurrence on daily bars
                        ema_t = alpha * close + (1.0 - alpha) * ema_prev

                        # Rolling (per-day) diffs
                        d1_roll_t = (
                            ema_t - ema_prev if ema_prev is not None else None
                        )
                        d2_roll_t = (
                            d1_roll_t - d1_roll_prev
                            if d1_roll_t is not None and d1_roll_prev is not None
                            else None
                        )

                        # Determine if this day is a canonical TF close
                        # We use integer day differences from the last canonical close.
                        is_close = False
                        if last_close_date is not None:
                            delta_days = (date - last_close_date).days
                            if delta_days > 0 and tf_days > 0 and delta_days % tf_days == 0:
                                is_close = True

                        if is_close:
                            roll = False
                            d1_t = (
                                ema_t - ema_close_prev
                                if ema_close_prev is not None
                                else None
                            )
                            d2_t = (
                                d1_t - d1_close_prev
                                if d1_t is not None and d1_close_prev is not None
                                else None
                            )

                            # Update canonical seeds
                            state["ema_close_prev"] = ema_t
                            state["d1_close_prev"] = d1_t
                            state["last_close_date"] = date
                        else:
                            roll = True
                            d1_t = None
                            d2_t = None

                        # Update rolling seeds
                        state["ema_prev"] = ema_t
                        state["d1_roll_prev"] = d1_roll_t

                        rows_id.append(
                            {
                                "id": asset_id,
                                "tf": tf,
                                "ts": ts,
                                "period": period,
                                "ema": ema_t,
                                "tf_days": tf_days,
                                "roll": roll,
                                "d1": d1_t,
                                "d2": d2_t,
                                "d1_roll": d1_roll_t,
                                "d2_roll": d2_roll_t,
                            }
                        )

                all_rows.extend(rows_id)

            if all_rows:
                df_all = pd.DataFrame(all_rows)
                engine = _get_engine(db_url)
                tmp_table = "cmc_ema_multi_tf_tmp_refresh"

                with engine.begin() as conn:
                    conn.execute(
                        text(f"DROP TABLE IF EXISTS public.{tmp_table};")
                    )
                    conn.execute(
                        text(
                            f"""
                            CREATE TEMP TABLE {tmp_table} AS
                            SELECT
                                id,
                                tf,
                                ts,
                                period,
                                ema,
                                tf_days,
                                roll,
                                d1,
                                d2,
                                d1_roll,
                                d2_roll
                            FROM public.cmc_ema_multi_tf
                            LIMIT 0;
                            """
                        )
                    )

                    df_all.to_sql(
                        tmp_table,
                        conn,
                        if_exists="append",
                        index=False,
                        method="multi",
                    )

                    sql = f"""
                    INSERT INTO public.cmc_ema_multi_tf AS t
                        (id, tf, ts, period, ema, tf_days, roll,
                         d1, d2, d1_roll, d2_roll)
                    SELECT
                        id, tf, ts, period, ema, tf_days, roll,
                        d1, d2, d1_roll, d2_roll
                    FROM {tmp_table}
                    ON CONFLICT (id, tf, ts, period) DO NOTHING;
                    """
                    res = conn.execute(text(sql))
                    rows = res.rowcount or 0

                print(
                    f"[multi_tf] Inserted {rows} new incremental multi-TF EMA rows into cmc_ema_multi_tf."
                )
            else:
                print("[multi_tf] No new incremental multi-TF EMA rows to insert.")

        else:
            # start is not None -> full recompute (update_existing=True)
            print(
                f"[multi_tf] Updating cmc_ema_multi_tf for ids={ids}, "
                f"start={start!r}, end={end!r}, "
                f"update_existing={update_existing}"
            )
            rows = write_multi_timeframe_ema_to_db(
                ids=ids,
                start=start,
                end=end,
                db_url=db_url,
                update_existing=update_existing,
            )
            print(f"[multi_tf] Upserted/updated {rows} rows into cmc_ema_multi_tf.")

    # 3) Refresh views (views are dynamic; we just standardize definitions)
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
            "If omitted, existing EMA rows are NOT updated; "
            "only new timestamps are inserted."
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
            args.refresh_all_emas_view,
            args.refresh_price_emas_view,
            args.refresh_price_emas_d1d2_view,
        ]
    )
    if not any_flag:
        args.update_daily = True
        args.update_multi_tf = True
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
        refresh_all_emas_view=args.refresh_all_emas_view,
        refresh_price_emas_view=args.refresh_price_emas_view,
        refresh_price_emas_d1d2_view=args.refresh_price_emas_d1d2_view,
    )


if __name__ == "__main__":
    main()
