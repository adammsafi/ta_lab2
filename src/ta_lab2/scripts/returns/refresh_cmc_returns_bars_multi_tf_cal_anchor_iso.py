from __future__ import annotations

r"""
refresh_cmc_returns_bars_multi_tf_cal_anchor_iso.py

Incremental bar returns builder (wide-column, dual-LAG) from bar snapshots.

Source:  public.cmc_price_bars_multi_tf_cal_anchor_iso
Writes:  public.cmc_returns_bars_multi_tf_cal_anchor_iso
State:   public.cmc_returns_bars_multi_tf_cal_anchor_iso_state  (watermark per (id, tf): last_timestamp)

Semantics:
  - Processes BOTH roll=TRUE (snapshot/rolling) and roll=FALSE (bar boundary) rows
    in a unified timeline ordered by "timestamp".
  - _roll columns: unified LAG (previous row regardless of roll). Populated on ALL rows.
  - Canonical columns (no suffix): partitioned LAG within roll=FALSE partition. NULL on roll=TRUE rows.
  - gap_bars = bar_seq - prev_bar_seq (canonical partition only, NULL on roll=TRUE)
  - range = high - low, range_pct = (high - low) / close
  - true_range = GREATEST(high-low, |high-prev_close|, |low-prev_close|),
    true_range_pct = true_range / close
  - PK: (id, "timestamp", tf); roll is a regular boolean column.
  - Incremental: inserts rows where "timestamp" > last_timestamp per (id,tf)
    seeds 2 canonical rows before watermark for delta2 history.

Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_cmc_returns_bars_multi_tf_cal_anchor_iso.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--ids 1 --full-refresh"
)
"""

import argparse
import os
from functools import partial
from multiprocessing import Pool
from typing import List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool


DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf_cal_anchor_iso"
DEFAULT_OUT_TABLE = "public.cmc_returns_bars_multi_tf_cal_anchor_iso"
DEFAULT_STATE_TABLE = "public.cmc_returns_bars_multi_tf_cal_anchor_iso_state"

_PRINT_PREFIX = "ret_bars_cal_anchor_iso"


def _print(msg: str) -> None:
    print(f"[{_PRINT_PREFIX}] {msg}")


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


# ---------------------------------------------------------------------------
# Column lists (used in INSERT and ON CONFLICT DO UPDATE)
# ---------------------------------------------------------------------------

_VALUE_COLS = [
    "tf_days",
    "bar_seq",
    "pos_in_bar",
    "count_days",
    "count_days_remaining",
    "time_close",
    "time_close_bar",
    "time_open_bar",
    "gap_bars",
    # roll columns
    "delta1_roll",
    "delta2_roll",
    "ret_arith_roll",
    "delta_ret_arith_roll",
    "ret_log_roll",
    "delta_ret_log_roll",
    "range_roll",
    "range_pct_roll",
    "true_range_roll",
    "true_range_pct_roll",
    # canonical columns
    "delta1",
    "delta2",
    "ret_arith",
    "delta_ret_arith",
    "ret_log",
    "delta_ret_log",
    "range",
    "range_pct",
    "true_range",
    "true_range_pct",
    # z-scores (canonical, roll=FALSE only)
    "ret_arith_zscore",
    "delta_ret_arith_zscore",
    "ret_log_zscore",
    "delta_ret_log_zscore",
    # z-scores (roll, ALL rows)
    "ret_arith_roll_zscore",
    "delta_ret_arith_roll_zscore",
    "ret_log_roll_zscore",
    "delta_ret_log_roll_zscore",
    # outlier flag
    "is_outlier",
]

_INSERT_COLS = (
    'id, "timestamp", tf, roll,\n' + ",\n".join(_VALUE_COLS) + ",\ningested_at"
)
_UPSERT_SET = ",\n".join(
    f"{c} = EXCLUDED.{c}" for c in ["roll"] + _VALUE_COLS + ["ingested_at"]
)


# ---------------------------------------------------------------------------
# Table management
# ---------------------------------------------------------------------------


def _ensure_tables(engine: Engine, out_table: str, state_table: str) -> None:
    tbl = out_table.split(".")[-1]
    out_sql = text(
        f"""
        CREATE TABLE IF NOT EXISTS {out_table} (
            id                      integer       NOT NULL,
            "timestamp"             timestamptz   NOT NULL,
            tf                      text          NOT NULL,
            tf_days                 integer,
            bar_seq                 integer,
            pos_in_bar              integer,
            count_days              integer,
            count_days_remaining    integer,
            roll                    boolean       NOT NULL,
            time_close              timestamptz,
            time_close_bar          timestamptz,
            time_open_bar           timestamptz,
            gap_bars                integer,
            delta1_roll             double precision,
            delta2_roll             double precision,
            ret_arith_roll          double precision,
            delta_ret_arith_roll    double precision,
            ret_log_roll            double precision,
            delta_ret_log_roll      double precision,
            range_roll              double precision,
            range_pct_roll          double precision,
            true_range_roll         double precision,
            true_range_pct_roll     double precision,
            delta1                  double precision,
            delta2                  double precision,
            ret_arith               double precision,
            delta_ret_arith         double precision,
            ret_log                 double precision,
            delta_ret_log           double precision,
            range                   double precision,
            range_pct               double precision,
            true_range              double precision,
            true_range_pct          double precision,
            ret_arith_zscore            double precision,
            delta_ret_arith_zscore      double precision,
            ret_log_zscore              double precision,
            delta_ret_log_zscore        double precision,
            ret_arith_roll_zscore       double precision,
            delta_ret_arith_roll_zscore double precision,
            ret_log_roll_zscore         double precision,
            delta_ret_log_roll_zscore   double precision,
            is_outlier                  boolean,
            ingested_at             timestamptz   NOT NULL DEFAULT now(),
            PRIMARY KEY (id, "timestamp", tf)
        );
        """
    )
    idx_sql = text(
        f'CREATE INDEX IF NOT EXISTS ix_{tbl}_id_tf_ts ON {out_table} (id, tf, "timestamp");'
    )
    state_sql = text(
        f"""
        CREATE TABLE IF NOT EXISTS {state_table} (
            id              integer       NOT NULL,
            tf              text          NOT NULL,
            last_timestamp  timestamptz,
            updated_at      timestamptz   NOT NULL DEFAULT now(),
            PRIMARY KEY (id, tf)
        );
        """
    )
    with engine.begin() as cxn:
        cxn.execute(out_sql)
        cxn.execute(idx_sql)
        cxn.execute(state_sql)


def _load_keys(
    engine: Engine,
    bars_table: str,
    ids: Optional[List[int]],
) -> List[Tuple[int, str]]:
    if ids is None:
        sql = text(f"SELECT DISTINCT id, tf FROM {bars_table} ORDER BY 1,2;")
        with engine.begin() as cxn:
            rows = cxn.execute(sql).fetchall()
    else:
        sql = text(
            f"SELECT DISTINCT id, tf FROM {bars_table} WHERE id = ANY(:ids) ORDER BY 1,2;"
        )
        with engine.begin() as cxn:
            rows = cxn.execute(sql, {"ids": ids}).fetchall()
    return [(int(r[0]), str(r[1])) for r in rows]


def _ensure_state_rows(
    engine: Engine, state_table: str, keys: List[Tuple[int, str]]
) -> None:
    if not keys:
        return
    ins = text(
        f"""
        INSERT INTO {state_table} (id, tf, last_timestamp)
        VALUES (:id, :tf, NULL)
        ON CONFLICT (id, tf) DO NOTHING;
        """
    )
    with engine.begin() as cxn:
        for i, tf in keys:
            cxn.execute(ins, {"id": i, "tf": tf})


def _full_refresh(
    engine: Engine,
    out_table: str,
    state_table: str,
    keys: List[Tuple[int, str]],
) -> None:
    if not keys:
        return
    _print(
        f"--full-refresh: deleting existing rows for {len(keys)} (id,tf) keys and resetting state."
    )
    del_out = text(f"DELETE FROM {out_table} WHERE id = :id AND tf = :tf;")
    del_state = text(f"DELETE FROM {state_table} WHERE id = :id AND tf = :tf;")
    with engine.begin() as cxn:
        for i, tf in keys:
            params = {"id": i, "tf": tf}
            cxn.execute(del_out, params)
            cxn.execute(del_state, params)
    _ensure_state_rows(engine, state_table, keys)


# ---------------------------------------------------------------------------
# Core: process one (id, tf) key
# ---------------------------------------------------------------------------


def _run_one_key(
    db_url: str,
    bars_table: str,
    out_table: str,
    state_table: str,
    start: str,
    key: Tuple[int, str],
) -> Tuple[int, str, int]:
    """Process one (id, tf) key. Self-contained for multiprocessing."""
    one_id, one_tf = key
    engine = create_engine(db_url, poolclass=NullPool, future=True)

    sql = text(
        f"""
        WITH st AS (
            SELECT last_timestamp
            FROM {state_table}
            WHERE id = :id AND tf = :tf
        ),
        -- Seed: go back 2 canonical (is_partial_end=FALSE) rows before last_timestamp
        -- to provide enough history for both LAG chains (including delta2).
        seed AS (
            SELECT COALESCE(
                (SELECT MIN(sub.ts) FROM (
                    SELECT "timestamp" AS ts FROM {bars_table}
                    WHERE id = :id AND tf = :tf
                      AND is_partial_end = FALSE
                      AND "timestamp" < COALESCE((SELECT last_timestamp FROM st), CAST(:start AS timestamptz))
                    ORDER BY "timestamp" DESC
                    LIMIT 2
                ) sub),
                (SELECT last_timestamp FROM st),
                CAST(:start AS timestamptz)
            ) AS seed_ts
        ),
        -- Pull ALL rows (both canonical and snapshot) from seed point
        src AS (
            SELECT
                b.id,
                b."timestamp",
                b.tf,
                b.tf_days,
                b.bar_seq,
                b.pos_in_bar,
                b.count_days,
                b.count_days_remaining,
                b.is_partial_end AS roll,
                b.close,
                b.high,
                b.low,
                b.time_close,
                b.time_close_bar,
                b.time_open_bar
            FROM {bars_table} b, seed
            WHERE b.id = :id
              AND b.tf = :tf
              AND b."timestamp" >= seed.seed_ts
        ),
        lagged AS (
            SELECT
                s.*,
                -- Unified LAG: previous row regardless of roll (for _roll columns)
                LAG(s.close)   OVER (ORDER BY s."timestamp") AS prev_close_u,
                LAG(s.high)    OVER (ORDER BY s."timestamp") AS prev_high_u,
                LAG(s.low)     OVER (ORDER BY s."timestamp") AS prev_low_u,
                LAG(s.bar_seq) OVER (ORDER BY s."timestamp") AS prev_bar_seq_u,
                -- Canonical LAG: previous row within same roll partition (for non-roll columns)
                LAG(s.close)   OVER (PARTITION BY s.roll ORDER BY s."timestamp") AS prev_close_c,
                LAG(s.high)    OVER (PARTITION BY s.roll ORDER BY s."timestamp") AS prev_high_c,
                LAG(s.low)     OVER (PARTITION BY s.roll ORDER BY s."timestamp") AS prev_low_c,
                LAG(s.bar_seq) OVER (PARTITION BY s.roll ORDER BY s."timestamp") AS prev_bar_seq_c
            FROM src s
        ),
        calc AS (
            SELECT
                id, "timestamp", tf, tf_days, bar_seq, pos_in_bar,
                count_days, count_days_remaining, roll,
                time_close, time_close_bar, time_open_bar,
                close, high, low,
                prev_close_u, prev_high_u, prev_low_u, prev_bar_seq_u,
                prev_close_c, prev_high_c, prev_low_c, prev_bar_seq_c,

                -- gap_bars (canonical partition only)
                CASE WHEN NOT roll AND prev_bar_seq_c IS NOT NULL
                     THEN bar_seq - prev_bar_seq_c END AS gap_bars,

                -- delta1 roll
                CASE WHEN prev_close_u IS NOT NULL
                     THEN close - prev_close_u END AS delta1_roll,
                -- delta1 canonical
                CASE WHEN NOT roll AND prev_close_c IS NOT NULL
                     THEN close - prev_close_c END AS delta1,

                -- ret_arith roll
                CASE WHEN prev_close_u IS NOT NULL AND prev_close_u != 0
                     THEN (close / prev_close_u) - 1 END AS ret_arith_roll,
                -- ret_arith canonical
                CASE WHEN NOT roll AND prev_close_c IS NOT NULL AND prev_close_c != 0
                     THEN (close / prev_close_c) - 1 END AS ret_arith,

                -- ret_log roll
                CASE WHEN prev_close_u IS NOT NULL AND prev_close_u > 0 AND close > 0
                     THEN LN(close / prev_close_u) END AS ret_log_roll,
                -- ret_log canonical
                CASE WHEN NOT roll AND prev_close_c IS NOT NULL AND prev_close_c > 0 AND close > 0
                     THEN LN(close / prev_close_c) END AS ret_log,

                -- range roll (uses current row's high/low)
                CASE WHEN prev_close_u IS NOT NULL
                     THEN high - low END AS range_roll,
                -- range canonical
                CASE WHEN NOT roll AND prev_close_c IS NOT NULL
                     THEN high - low END AS range,

                -- range_pct roll
                CASE WHEN prev_close_u IS NOT NULL AND close != 0
                     THEN (high - low) / close END AS range_pct_roll,
                -- range_pct canonical
                CASE WHEN NOT roll AND prev_close_c IS NOT NULL AND close != 0
                     THEN (high - low) / close END AS range_pct,

                -- true_range roll
                CASE WHEN prev_close_u IS NOT NULL
                     THEN GREATEST(
                         high - low,
                         ABS(high - prev_close_u),
                         ABS(low - prev_close_u)
                     ) END AS true_range_roll,
                -- true_range canonical
                CASE WHEN NOT roll AND prev_close_c IS NOT NULL
                     THEN GREATEST(
                         high - low,
                         ABS(high - prev_close_c),
                         ABS(low - prev_close_c)
                     ) END AS true_range,

                -- true_range_pct roll
                CASE WHEN prev_close_u IS NOT NULL AND close != 0
                     THEN GREATEST(
                         high - low,
                         ABS(high - prev_close_u),
                         ABS(low - prev_close_u)
                     ) / close END AS true_range_pct_roll,
                -- true_range_pct canonical
                CASE WHEN NOT roll AND prev_close_c IS NOT NULL AND close != 0
                     THEN GREATEST(
                         high - low,
                         ABS(high - prev_close_c),
                         ABS(low - prev_close_c)
                     ) / close END AS true_range_pct

            FROM lagged
            WHERE prev_close_u IS NOT NULL
        ),
        calc2 AS (
            SELECT c.*,
                -- delta2 roll
                c.delta1_roll - LAG(c.delta1_roll) OVER (ORDER BY c."timestamp") AS delta2_roll,
                -- delta2 canonical
                CASE WHEN NOT c.roll
                     THEN c.delta1 - LAG(c.delta1) OVER (PARTITION BY c.roll ORDER BY c."timestamp")
                END AS delta2,

                -- delta_ret_arith roll
                c.ret_arith_roll - LAG(c.ret_arith_roll) OVER (ORDER BY c."timestamp") AS delta_ret_arith_roll,
                -- delta_ret_arith canonical
                CASE WHEN NOT c.roll
                     THEN c.ret_arith - LAG(c.ret_arith) OVER (PARTITION BY c.roll ORDER BY c."timestamp")
                END AS delta_ret_arith,

                -- delta_ret_log roll
                c.ret_log_roll - LAG(c.ret_log_roll) OVER (ORDER BY c."timestamp") AS delta_ret_log_roll,
                -- delta_ret_log canonical
                CASE WHEN NOT c.roll
                     THEN c.ret_log - LAG(c.ret_log) OVER (PARTITION BY c.roll ORDER BY c."timestamp")
                END AS delta_ret_log

            FROM calc c
        ),
        to_insert AS (
            SELECT c2.*
            FROM calc2 c2
            CROSS JOIN st
            WHERE (st.last_timestamp IS NULL) OR (c2."timestamp" > st.last_timestamp)
        ),
        ins AS (
            INSERT INTO {out_table} (
                {_INSERT_COLS}
            )
            SELECT
                id, "timestamp", tf, roll,
                {",".join(_VALUE_COLS)},
                now()
            FROM to_insert
            ON CONFLICT (id, "timestamp", tf) DO UPDATE SET
                {_UPSERT_SET}
            RETURNING "timestamp"
        )
        UPDATE {state_table} s
        SET
            last_timestamp = COALESCE((SELECT MAX("timestamp") FROM ins), s.last_timestamp),
            updated_at = now()
        WHERE s.id = :id AND s.tf = :tf;
        """
    )

    with engine.begin() as cxn:
        result = cxn.execute(
            sql,
            {"id": one_id, "tf": one_tf, "start": start},
        )

    engine.dispose()
    return (one_id, one_tf, result.rowcount or 0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_ids(ids_arg: str) -> Optional[List[int]]:
    s = ids_arg.strip().lower()
    if s == "all":
        return None
    return [int(x.strip()) for x in ids_arg.split(",") if x.strip()]


def main() -> None:
    p = argparse.ArgumentParser(
        description="Incremental bar returns builder (wide-column, dual-LAG) from bar snapshots."
    )
    p.add_argument(
        "--db-url",
        default=os.getenv("TARGET_DB_URL", ""),
        help="Postgres DB URL (or set TARGET_DB_URL).",
    )
    p.add_argument("--ids", default="all", help="Comma-separated ids, or 'all'.")
    p.add_argument(
        "--start", default="2010-01-01", help="Start timestamp for full history runs."
    )
    p.add_argument(
        "--bars-table", default=DEFAULT_BARS_TABLE, help="Source bars table."
    )
    p.add_argument(
        "--out-table", default=DEFAULT_OUT_TABLE, help="Output returns table."
    )
    p.add_argument("--state-table", default=DEFAULT_STATE_TABLE, help="State table.")
    p.add_argument(
        "--full-refresh",
        action="store_true",
        help="Recompute history for selected keys from --start.",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel workers (default 1 = sequential).",
    )
    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    _print(
        "Using DB URL from TARGET_DB_URL env."
        if os.getenv("TARGET_DB_URL")
        else "Using DB URL from --db-url."
    )

    engine = _get_engine(db_url)
    ids = _parse_ids(args.ids)

    _ensure_tables(engine, args.out_table, args.state_table)

    keys = _load_keys(engine, args.bars_table, ids)
    _print(
        f"Runner config: ids={args.ids}, start={args.start}, "
        f"bars={args.bars_table}, out={args.out_table}, state={args.state_table}, "
        f"full_refresh={args.full_refresh}, workers={args.workers}"
    )
    _print(f"Resolved keys={len(keys)}")

    if not keys:
        _print("No keys found. Done.")
        return

    _ensure_state_rows(engine, args.state_table, keys)

    if args.full_refresh:
        _full_refresh(engine, args.out_table, args.state_table, keys)

    worker_fn = partial(
        _run_one_key,
        db_url,
        args.bars_table,
        args.out_table,
        args.state_table,
        args.start,
    )

    if args.workers > 1:
        _print(f"Running {len(keys)} keys with {args.workers} workers.")
        with Pool(processes=args.workers) as pool:
            for one_id, one_tf, n_rows in pool.imap_unordered(worker_fn, keys):
                _print(f"  ({one_id},{one_tf}) -> {n_rows} rows")
    else:
        for i, key in enumerate(keys, start=1):
            one_id, one_tf = key
            _print(f"Processing key=({one_id},{one_tf}) ({i}/{len(keys)})")
            _run_one_key(
                db_url,
                args.bars_table,
                args.out_table,
                args.state_table,
                args.start,
                key,
            )

    _print("Done.")


if __name__ == "__main__":
    main()
