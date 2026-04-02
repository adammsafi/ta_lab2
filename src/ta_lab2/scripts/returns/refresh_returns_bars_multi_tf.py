from __future__ import annotations

r"""
refresh_returns_bars_multi_tf.py

Incremental bar returns builder (wide-column, dual-LAG) from bar snapshots.

Source:  public.price_bars_multi_tf_u
Writes:  public.returns_bars_multi_tf_u
State:   public.returns_bars_multi_tf_state  (watermark per (id, venue_id, tf): last_timestamp)

Semantics:
  - Processes BOTH roll=TRUE (snapshot/rolling) and roll=FALSE (bar boundary) rows
    in a unified timeline ordered by "timestamp".
  - _roll columns: unified LAG (previous row regardless of roll). Populated on ALL rows.
  - Canonical columns (no suffix): partitioned LAG within roll=FALSE partition. NULL on roll=TRUE.
  - gap_bars = bar_seq - prev_bar_seq (canonical partition only, NULL on roll=TRUE)
  - range = high - low, range_pct = (high - low) / close
  - true_range = GREATEST(high-low, |high-prev_close|, |low-prev_close|)
  - PK: (id, "timestamp", tf, venue_id); roll is a regular boolean column.

Batch architecture (v2):
  - Iterates over IDs (~492) instead of (id, tf, venue_id) keys (~120K).
  - One SQL CTE per ID computes returns for ALL (tf, venue_id) combos using
    PARTITION BY (tf, venue_id) in all LAG window functions.
  - Per-key watermarks loaded in bulk and injected via a VALUES CTE.
  - Source-advance skip: IDs with no new rows are skipped before SQL execution.

Run (Spyder):
runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_returns_bars_multi_tf.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--ids 1 --full-refresh"
)
"""

import argparse
import os
from dataclasses import dataclass
from functools import partial
from multiprocessing import Pool
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool


DEFAULT_BARS_TABLE = "public.price_bars_multi_tf_u"
DEFAULT_OUT_TABLE = "public.returns_bars_multi_tf_u"
DEFAULT_STATE_TABLE = "public.returns_bars_multi_tf_state"
ALIGNMENT_SOURCE = "multi_tf"

_PRINT_PREFIX = "ret_bars_multi_tf"


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
    # NOTE: z-score columns and is_outlier populated by refresh_returns_zscore.py
]

_INSERT_COLS = (
    'id, venue_id, "timestamp", tf, roll,\n'
    + ",\n".join(_VALUE_COLS)
    + ",\ningested_at, alignment_source"
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
            venue_id                smallint      NOT NULL DEFAULT 1,
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
            ret_arith_zscore_30             double precision,
            delta_ret_arith_zscore_30       double precision,
            ret_log_zscore_30               double precision,
            delta_ret_log_zscore_30         double precision,
            ret_arith_roll_zscore_30        double precision,
            delta_ret_arith_roll_zscore_30  double precision,
            ret_log_roll_zscore_30          double precision,
            delta_ret_log_roll_zscore_30    double precision,
            ret_arith_zscore_90             double precision,
            delta_ret_arith_zscore_90       double precision,
            ret_log_zscore_90               double precision,
            delta_ret_log_zscore_90         double precision,
            ret_arith_roll_zscore_90        double precision,
            delta_ret_arith_roll_zscore_90  double precision,
            ret_log_roll_zscore_90          double precision,
            delta_ret_log_roll_zscore_90    double precision,
            ret_arith_zscore_365            double precision,
            delta_ret_arith_zscore_365      double precision,
            ret_log_zscore_365              double precision,
            delta_ret_log_zscore_365        double precision,
            ret_arith_roll_zscore_365       double precision,
            delta_ret_arith_roll_zscore_365 double precision,
            ret_log_roll_zscore_365         double precision,
            delta_ret_log_roll_zscore_365   double precision,
            is_outlier                  boolean,
            ingested_at             timestamptz   NOT NULL DEFAULT now(),
            PRIMARY KEY (id, "timestamp", tf, venue_id)
        );
        """
    )
    idx_sql = text(
        f"CREATE INDEX IF NOT EXISTS ix_{tbl}_id_tf_vid_ts"
        f' ON {out_table} (id, tf, venue_id, "timestamp");'
    )
    state_sql = text(
        f"""
        CREATE TABLE IF NOT EXISTS {state_table} (
            id              integer       NOT NULL,
            venue_id        smallint      NOT NULL DEFAULT 1,
            tf              text          NOT NULL,
            last_timestamp  timestamptz,
            updated_at      timestamptz   NOT NULL DEFAULT now(),
            PRIMARY KEY (id, venue_id, tf)
        );
        """
    )
    with engine.begin() as cxn:
        cxn.execute(out_sql)
        cxn.execute(idx_sql)
        cxn.execute(state_sql)


def _load_ids(
    engine: Engine,
    bars_table: str,
    ids: Optional[List[int]],
    alignment_source: Optional[str] = None,
    venue_ids: Optional[List[int]] = None,
) -> List[int]:
    """Return distinct IDs from the source bars table."""
    where_parts: list[str] = []
    params: dict[str, Any] = {}
    if ids is not None:
        where_parts.append("id = ANY(:ids)")
        params["ids"] = ids
    if alignment_source is not None:
        where_parts.append("alignment_source = :alignment_source")
        params["alignment_source"] = alignment_source
    if venue_ids is not None:
        where_parts.append("venue_id = ANY(:venue_ids)")
        params["venue_ids"] = venue_ids
    where = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""
    sql = text(f"SELECT DISTINCT id FROM {bars_table} {where} ORDER BY 1;")
    with engine.begin() as cxn:
        rows = cxn.execute(sql, params).fetchall()
    return [int(r[0]) for r in rows]


def _load_watermarks(
    engine: Engine,
    state_table: str,
    id_: int,
) -> Dict[Tuple[str, int], Any]:
    """Bulk-load all (tf, venue_id) -> last_timestamp entries for one ID."""
    sql = text(f"SELECT tf, venue_id, last_timestamp FROM {state_table} WHERE id = :id")
    with engine.begin() as cxn:
        rows = cxn.execute(sql, {"id": id_}).fetchall()
    return {(str(r[0]), int(r[1])): r[2] for r in rows}


def _ensure_state_rows_for_id(
    engine: Engine,
    state_table: str,
    bars_table: str,
    id_: int,
    alignment_source: Optional[str],
    venue_ids: Optional[List[int]],
) -> None:
    """Batch-insert NULL state rows for all (tf, venue_id) combos of one ID."""
    where_parts = ["id = :id"]
    params: dict[str, Any] = {"id": id_}
    if alignment_source is not None:
        where_parts.append("alignment_source = :as_filter")
        params["as_filter"] = alignment_source
    if venue_ids is not None:
        where_parts.append("venue_id = ANY(:venue_ids)")
        params["venue_ids"] = venue_ids
    where = " AND ".join(where_parts)
    sql = text(
        f"""
        INSERT INTO {state_table} (id, venue_id, tf, last_timestamp)
        SELECT DISTINCT id, venue_id, tf, NULL::timestamptz
        FROM {bars_table}
        WHERE {where}
        ON CONFLICT (id, venue_id, tf) DO NOTHING;
        """
    )
    with engine.begin() as cxn:
        cxn.execute(sql, params)


def _full_refresh_id(
    engine: Engine,
    out_table: str,
    state_table: str,
    id_: int,
    venue_ids: Optional[List[int]],
) -> None:
    """Delete output rows and state entries for one ID."""
    venue_filter = ""
    del_out_params: dict[str, Any] = {
        "id": id_,
        "alignment_source": ALIGNMENT_SOURCE,
    }
    del_state_params: dict[str, Any] = {"id": id_}
    if venue_ids is not None:
        venue_filter = "AND venue_id = ANY(:venue_ids)"
        del_out_params["venue_ids"] = venue_ids
        del_state_params["venue_ids"] = venue_ids
    with engine.begin() as cxn:
        cxn.execute(
            text(
                f"DELETE FROM {out_table} WHERE id = :id {venue_filter}"
                " AND alignment_source = :alignment_source;"
            ),
            del_out_params,
        )
        cxn.execute(
            text(f"DELETE FROM {state_table} WHERE id = :id {venue_filter};"),
            del_state_params,
        )


# ---------------------------------------------------------------------------
# RunnerConfig + batch core
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunnerConfig:
    db_url: str
    bars_table: str
    out_table: str
    state_table: str
    start: str
    src_alignment_source: Optional[str]
    venue_ids: Optional[List[int]]


def _build_wm_cte(id_: int, watermarks: Dict[Tuple[str, int], Any]) -> str:
    """Build watermark VALUES CTE string for embedding in batch SQL."""
    if not watermarks:
        return (
            "wm (id, tf, venue_id, last_timestamp) AS ("
            " SELECT NULL::integer, NULL::text, NULL::smallint, NULL::timestamptz"
            " WHERE FALSE),"
        )
    rows = []
    for (tf, vid), ts in watermarks.items():
        ts_expr = f"'{ts}'::timestamptz" if ts is not None else "NULL::timestamptz"
        rows.append(f"({id_!r}::integer, {tf!r}::text, {vid!r}::smallint, {ts_expr})")
    wm_rows = ",\n            ".join(rows)
    return (
        f"wm (id, tf, venue_id, last_timestamp) AS (\n"
        f"            VALUES\n"
        f"            {wm_rows}\n"
        f"        ),"
    )


def _run_one_id(cfg: RunnerConfig, engine: Engine, id_: int) -> int:
    """Process all (tf, venue_id) combos for one ID in a single SQL CTE.

    Returns 1 if processed, 0 if skipped (no new source data).
    """
    # 1. Bulk-load watermarks
    watermarks = _load_watermarks(engine, cfg.state_table, id_)

    min_last_ts = None
    if watermarks:
        non_null = [v for v in watermarks.values() if v is not None]
        if non_null:
            min_last_ts = min(non_null)

    _as_filter = (
        "AND alignment_source = :src_alignment_source"
        if cfg.src_alignment_source
        else ""
    )
    _venue_filter = (
        "AND venue_id = ANY(:venue_ids)" if cfg.venue_ids is not None else ""
    )

    # 2. Source-advance skip
    if min_last_ts is not None:
        skip_params: dict[str, Any] = {"id": id_, "min_last_ts": min_last_ts}
        if cfg.src_alignment_source:
            skip_params["src_alignment_source"] = cfg.src_alignment_source
        if cfg.venue_ids is not None:
            skip_params["venue_ids"] = cfg.venue_ids
        with engine.begin() as cxn:
            has_new = cxn.execute(
                text(
                    f"SELECT 1 FROM {cfg.bars_table} WHERE id = :id"
                    f' AND "timestamp" > :min_last_ts {_as_filter} {_venue_filter}'
                    f" LIMIT 1"
                ),
                skip_params,
            ).fetchone()
        if not has_new:
            return 0

    # 3. Watermark VALUES CTE
    wm_cte = _build_wm_cte(id_, watermarks)

    # 4. Main batch SQL
    sql_text = f"""
    WITH
    {wm_cte}
    min_wm AS (SELECT MIN(last_timestamp) AS min_ts FROM wm WHERE id = :id),
    seed AS (
        SELECT COALESCE(
            (SELECT MIN(sub.ts) FROM (
                SELECT "timestamp" AS ts FROM {cfg.bars_table}
                WHERE id = :id AND is_partial_end = FALSE {_as_filter}
                  AND "timestamp" < COALESCE((SELECT min_ts FROM min_wm), CAST(:start AS timestamptz))
                ORDER BY "timestamp" DESC LIMIT 2
            ) sub),
            (SELECT min_ts FROM min_wm),
            CAST(:start AS timestamptz)
        ) AS seed_ts
    ),
    src AS (
        SELECT
            b.id, b.venue_id, b."timestamp", b.tf, b.tf_days,
            b.bar_seq, b.pos_in_bar, b.count_days, b.count_days_remaining,
            b.is_partial_end AS roll, b.close, b.high, b.low,
            b.time_close, b.time_close_bar, b.time_open_bar
        FROM {cfg.bars_table} b, seed
        WHERE b.id = :id {_as_filter} {_venue_filter}
          AND b."timestamp" >= seed.seed_ts
    ),
    lagged AS (
        SELECT s.*,
            -- Unified LAG: PARTITION BY (tf, venue_id) -- cross-roll transitions
            LAG(s.close)   OVER (PARTITION BY s.tf, s.venue_id ORDER BY s."timestamp") AS prev_close_u,
            LAG(s.high)    OVER (PARTITION BY s.tf, s.venue_id ORDER BY s."timestamp") AS prev_high_u,
            LAG(s.low)     OVER (PARTITION BY s.tf, s.venue_id ORDER BY s."timestamp") AS prev_low_u,
            LAG(s.bar_seq) OVER (PARTITION BY s.tf, s.venue_id ORDER BY s."timestamp") AS prev_bar_seq_u,
            -- Canonical LAG: PARTITION BY (tf, venue_id, roll) -- within-roll transitions
            LAG(s.close)   OVER (PARTITION BY s.tf, s.venue_id, s.roll ORDER BY s."timestamp") AS prev_close_c,
            LAG(s.high)    OVER (PARTITION BY s.tf, s.venue_id, s.roll ORDER BY s."timestamp") AS prev_high_c,
            LAG(s.low)     OVER (PARTITION BY s.tf, s.venue_id, s.roll ORDER BY s."timestamp") AS prev_low_c,
            LAG(s.bar_seq) OVER (PARTITION BY s.tf, s.venue_id, s.roll ORDER BY s."timestamp") AS prev_bar_seq_c
        FROM src s
    ),
    calc AS (
        SELECT
            id, venue_id, "timestamp", tf, tf_days, bar_seq, pos_in_bar,
            count_days, count_days_remaining, roll,
            time_close, time_close_bar, time_open_bar,
            close, high, low,
            prev_close_u, prev_high_u, prev_low_u, prev_bar_seq_u,
            prev_close_c, prev_high_c, prev_low_c, prev_bar_seq_c,
            -- gap_bars: canonical only
            CASE WHEN NOT roll AND prev_bar_seq_c IS NOT NULL
                 THEN bar_seq - prev_bar_seq_c END AS gap_bars,
            -- delta1
            CASE WHEN prev_close_u IS NOT NULL
                 THEN close - prev_close_u END AS delta1_roll,
            CASE WHEN NOT roll AND prev_close_c IS NOT NULL
                 THEN close - prev_close_c END AS delta1,
            -- ret_arith
            CASE WHEN prev_close_u IS NOT NULL AND prev_close_u != 0
                 THEN (close / prev_close_u) - 1 END AS ret_arith_roll,
            CASE WHEN NOT roll AND prev_close_c IS NOT NULL AND prev_close_c != 0
                 THEN (close / prev_close_c) - 1 END AS ret_arith,
            -- ret_log
            CASE WHEN prev_close_u IS NOT NULL AND prev_close_u > 0 AND close > 0
                 THEN LN(close / prev_close_u) END AS ret_log_roll,
            CASE WHEN NOT roll AND prev_close_c IS NOT NULL AND prev_close_c > 0 AND close > 0
                 THEN LN(close / prev_close_c) END AS ret_log,
            -- range
            CASE WHEN prev_close_u IS NOT NULL
                 THEN high - low END AS range_roll,
            CASE WHEN NOT roll AND prev_close_c IS NOT NULL
                 THEN high - low END AS "range",
            -- range_pct
            CASE WHEN prev_close_u IS NOT NULL AND close != 0
                 THEN (high - low) / close END AS range_pct_roll,
            CASE WHEN NOT roll AND prev_close_c IS NOT NULL AND close != 0
                 THEN (high - low) / close END AS range_pct,
            -- true_range
            CASE WHEN prev_close_u IS NOT NULL
                 THEN GREATEST(high - low, ABS(high - prev_close_u), ABS(low - prev_close_u))
                 END AS true_range_roll,
            CASE WHEN NOT roll AND prev_close_c IS NOT NULL
                 THEN GREATEST(high - low, ABS(high - prev_close_c), ABS(low - prev_close_c))
                 END AS true_range,
            -- true_range_pct
            CASE WHEN prev_close_u IS NOT NULL AND close != 0
                 THEN GREATEST(high - low, ABS(high - prev_close_u), ABS(low - prev_close_u)) / close
                 END AS true_range_pct_roll,
            CASE WHEN NOT roll AND prev_close_c IS NOT NULL AND close != 0
                 THEN GREATEST(high - low, ABS(high - prev_close_c), ABS(low - prev_close_c)) / close
                 END AS true_range_pct
        FROM lagged
        WHERE prev_close_u IS NOT NULL
    ),
    calc2 AS (
        SELECT c.*,
            -- delta2 roll: PARTITION BY (tf, venue_id)
            c.delta1_roll - LAG(c.delta1_roll)
                OVER (PARTITION BY c.tf, c.venue_id ORDER BY c."timestamp") AS delta2_roll,
            -- delta2 canonical: PARTITION BY (tf, venue_id, roll)
            CASE WHEN NOT c.roll
                 THEN c.delta1 - LAG(c.delta1)
                     OVER (PARTITION BY c.tf, c.venue_id, c.roll ORDER BY c."timestamp")
            END AS delta2,
            -- delta_ret_arith roll
            c.ret_arith_roll - LAG(c.ret_arith_roll)
                OVER (PARTITION BY c.tf, c.venue_id ORDER BY c."timestamp") AS delta_ret_arith_roll,
            -- delta_ret_arith canonical
            CASE WHEN NOT c.roll
                 THEN c.ret_arith - LAG(c.ret_arith)
                     OVER (PARTITION BY c.tf, c.venue_id, c.roll ORDER BY c."timestamp")
            END AS delta_ret_arith,
            -- delta_ret_log roll
            c.ret_log_roll - LAG(c.ret_log_roll)
                OVER (PARTITION BY c.tf, c.venue_id ORDER BY c."timestamp") AS delta_ret_log_roll,
            -- delta_ret_log canonical
            CASE WHEN NOT c.roll
                 THEN c.ret_log - LAG(c.ret_log)
                     OVER (PARTITION BY c.tf, c.venue_id, c.roll ORDER BY c."timestamp")
            END AS delta_ret_log
        FROM calc c
    ),
    -- Per-key watermark filter: only rows newer than their last_timestamp
    to_insert AS (
        SELECT c2.*
        FROM calc2 c2
        LEFT JOIN wm ON wm.id = c2.id AND wm.tf = c2.tf AND wm.venue_id = c2.venue_id
        WHERE (wm.last_timestamp IS NULL) OR (c2."timestamp" > wm.last_timestamp)
    ),
    ins AS (
        INSERT INTO {cfg.out_table} (
            {_INSERT_COLS}
        )
        SELECT
            id, venue_id, "timestamp", tf, roll,
            {",".join(_VALUE_COLS)},
            now(),
            CAST(:alignment_source AS text)
        FROM to_insert
        ON CONFLICT (id, "timestamp", tf, venue_id, alignment_source) DO UPDATE SET
            {_UPSERT_SET}
        RETURNING id, tf, venue_id, "timestamp"
    )
    -- Bulk state update for this ID
    INSERT INTO {cfg.state_table} (id, venue_id, tf, last_timestamp, updated_at)
    SELECT id, venue_id, tf, MAX("timestamp"), now()
    FROM ins
    GROUP BY id, venue_id, tf
    ON CONFLICT (id, venue_id, tf) DO UPDATE SET
        last_timestamp = GREATEST(EXCLUDED.last_timestamp, {cfg.state_table}.last_timestamp),
        updated_at = now();
    """

    params: dict[str, Any] = {
        "id": id_,
        "start": cfg.start,
        "alignment_source": ALIGNMENT_SOURCE,
    }
    if cfg.src_alignment_source:
        params["src_alignment_source"] = cfg.src_alignment_source
    if cfg.venue_ids is not None:
        params["venue_ids"] = cfg.venue_ids

    with engine.begin() as cxn:
        cxn.execute(text(sql_text), params)

    return 1


def _run_one_id_mp(
    db_url: str,
    bars_table: str,
    out_table: str,
    state_table: str,
    start: str,
    src_alignment_source: Optional[str],
    venue_ids: Optional[List[int]],
    id_: int,
) -> Tuple[int, int]:
    """Multiprocessing-safe wrapper. Returns (id_, signal)."""
    cfg = RunnerConfig(
        db_url=db_url,
        bars_table=bars_table,
        out_table=out_table,
        state_table=state_table,
        start=start,
        src_alignment_source=src_alignment_source,
        venue_ids=venue_ids,
    )
    engine = create_engine(db_url, poolclass=NullPool, future=True)
    try:
        n = _run_one_id(cfg, engine, id_)
        return (id_, n)
    finally:
        engine.dispose()


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
    p.add_argument("--db-url", default=os.getenv("TARGET_DB_URL", ""))
    p.add_argument("--ids", default="all", help="Comma-separated ids, or 'all'.")
    p.add_argument("--start", default="2010-01-01")
    p.add_argument("--bars-table", default=DEFAULT_BARS_TABLE)
    p.add_argument("--out-table", default=DEFAULT_OUT_TABLE)
    p.add_argument("--state-table", default=DEFAULT_STATE_TABLE)
    p.add_argument("--full-refresh", action="store_true")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument(
        "--venue-ids",
        type=lambda s: [int(x) for x in s.split(",")],
        default=None,
    )
    p.add_argument("--src-alignment-source", default=None)
    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit(
            "ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL."
        )

    src_as = args.src_alignment_source
    if src_as is None and args.bars_table.rstrip('"').endswith("_u"):
        src_as = ALIGNMENT_SOURCE
        _print(
            f"Auto-detected _u source table, filtering by alignment_source='{src_as}'"
        )

    _print(
        "Using DB URL from TARGET_DB_URL env."
        if os.getenv("TARGET_DB_URL")
        else "Using DB URL from --db-url."
    )

    engine = _get_engine(db_url)
    ids = _parse_ids(args.ids)

    _ensure_tables(engine, args.out_table, args.state_table)

    id_list = _load_ids(
        engine,
        args.bars_table,
        ids,
        alignment_source=src_as,
        venue_ids=args.venue_ids,
    )
    _print(
        f"Runner config: ids={args.ids}, start={args.start}, "
        f"bars={args.bars_table}, out={args.out_table}, state={args.state_table}, "
        f"full_refresh={args.full_refresh}, workers={args.workers}, "
        f"venue_ids={args.venue_ids}, src_alignment_source={src_as}"
    )
    _print(f"Resolved IDs={len(id_list)}")

    if not id_list:
        _print("No IDs found. Done.")
        return

    cfg = RunnerConfig(
        db_url=db_url,
        bars_table=args.bars_table,
        out_table=args.out_table,
        state_table=args.state_table,
        start=args.start,
        src_alignment_source=src_as,
        venue_ids=args.venue_ids,
    )

    for id_ in id_list:
        _ensure_state_rows_for_id(
            engine,
            args.state_table,
            args.bars_table,
            id_,
            alignment_source=src_as,
            venue_ids=args.venue_ids,
        )

    if args.full_refresh:
        _print(
            f"--full-refresh: deleting rows for {len(id_list)} IDs and resetting state."
        )
        for id_ in id_list:
            _full_refresh_id(
                engine, args.out_table, args.state_table, id_, args.venue_ids
            )
        for id_ in id_list:
            _ensure_state_rows_for_id(
                engine,
                args.state_table,
                args.bars_table,
                id_,
                alignment_source=src_as,
                venue_ids=args.venue_ids,
            )

    if args.workers > 1:
        _print(f"Running {len(id_list)} IDs with {args.workers} workers.")
        worker_fn = partial(
            _run_one_id_mp,
            db_url,
            args.bars_table,
            args.out_table,
            args.state_table,
            args.start,
            src_as,
            args.venue_ids,
        )
        with Pool(processes=args.workers, maxtasksperchild=1) as pool:
            for i, (done_id, _) in enumerate(
                pool.imap_unordered(worker_fn, id_list), start=1
            ):
                _print(f"  ID {done_id} done ({i}/{len(id_list)})")
    else:
        for i, id_ in enumerate(id_list, start=1):
            _print(f"Processing id={id_} ({i}/{len(id_list)})")
            _run_one_id(cfg, engine, id_)

    _print("Done.")


if __name__ == "__main__":
    main()
