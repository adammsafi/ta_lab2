"""
1D Bar Builder - Canonical daily bars from price_histories7.

Builds daily OHLC bars with:
- One bar per local calendar day per asset
- Deterministic bar_seq (dense_rank by timestamp)
- OHLC repair and validation
- Incremental refresh with lookback window
- Backfill detection and automatic rebuild

Inherits from BaseBarBuilder to standardize:
- CLI parsing and argument handling
- Database connection management
- State table management (tracking last processed timestamp)
- Execution flow (incremental vs full rebuild)
- Logging setup

This builder implements variant-specific:
- Source query (price_histories7 with lookback)
- Bar building logic (SQL CTE for OHLC aggregation + repair)
- Backfill detection (track daily_min_seen)

Usage:
    # Full rebuild
    python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py \\
        --ids 1 1027 --full-rebuild

    # Incremental (default)
    python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py \\
        --ids all --keep-rejects

    # Single ID incremental
    python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py \\
        --ids 1 --keep-rejects
"""

from __future__ import annotations

import argparse
from typing import Any, List, Optional, Sequence, Tuple

from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.base_bar_builder import BaseBarBuilder
from ta_lab2.scripts.bars.bar_builder_config import BarBuilderConfig
from ta_lab2.scripts.bars.common_snapshot_contract import (
    get_engine,
    parse_ids,
    load_all_ids,
    resolve_db_url,
    ensure_coverage_table,
    upsert_coverage,
)

# Prefer psycopg v3, fall back to psycopg2
try:
    import psycopg  # type: ignore

    PSYCOPG3 = True
except Exception:
    psycopg = None
    PSYCOPG3 = False

try:
    import psycopg2  # type: ignore

    PSYCOPG2 = True
except Exception:
    psycopg2 = None
    PSYCOPG2 = False


# =============================================================================
# Database utilities (psycopg for raw SQL performance)
# =============================================================================


def _normalize_db_url(url: str) -> str:
    """Remove SQLAlchemy dialect prefix for psycopg connection."""
    if not url:
        return url
    for prefix in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql+psycopg3://",
        "postgres+psycopg2://",
        "postgres+psycopg://",
        "postgres+psycopg3://",
    ):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


def _connect(db_url: str):
    """Create psycopg connection (v3 preferred, v2 fallback)."""
    url = _normalize_db_url(db_url)
    if PSYCOPG3:
        return psycopg.connect(url, autocommit=True)
    if PSYCOPG2:
        conn = psycopg2.connect(url)
        conn.autocommit = True
        return conn
    raise RuntimeError("Neither psycopg (v3) nor psycopg2 is installed.")


def _exec(conn, sql: str, params: Optional[Sequence[Any]] = None) -> None:
    """Execute SQL statement."""
    params = params or []
    if PSYCOPG3:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return
    cur = conn.cursor()
    cur.execute(sql, params)
    cur.close()


def _fetchall(
    conn, sql: str, params: Optional[Sequence[Any]] = None
) -> List[Tuple[Any, ...]]:
    """Execute SQL and fetch all rows."""
    params = params or []
    if PSYCOPG3:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _fetchone(
    conn, sql: str, params: Optional[Sequence[Any]] = None
) -> Optional[Tuple[Any, ...]]:
    """Execute SQL and fetch one row."""
    params = params or []
    if PSYCOPG3:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return row


# =============================================================================
# State table schema migration
# =============================================================================


def _ensure_state_schema(conn, state: str) -> None:
    """Ensure state table has daily_min_seen column (auto-migration)."""
    check_sql = """
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = 'public'
        AND table_name = %s
        AND column_name = 'daily_min_seen'
    """
    table_name = state.split(".")[-1] if "." in state else state
    row = _fetchone(conn, check_sql, [table_name])

    if not row:
        alter_sql = f"""
            ALTER TABLE {state}
            ADD COLUMN daily_min_seen TIMESTAMPTZ;
        """
        _exec(conn, alter_sql)

        backfill_sql = f"""
            UPDATE {state}
            SET daily_min_seen = last_src_ts
            WHERE daily_min_seen IS NULL;
        """
        _exec(conn, backfill_sql)
        print(f"[1D Builder] Added daily_min_seen column to {state}")


# =============================================================================
# Backfill detection
# =============================================================================


def _get_state(conn, state: str, id_: int) -> Optional[dict]:
    """Load full state for an id (including daily_min_seen)."""
    row = _fetchone(
        conn, f"SELECT last_src_ts, daily_min_seen FROM {state} WHERE id = %s;", [id_]
    )
    if not row:
        return None
    return {
        "last_src_ts": str(row[0]) if row[0] is not None else None,
        "daily_min_seen": str(row[1]) if row[1] is not None else None,
    }


def _check_for_backfill(conn, src: str, id_: int, state_dict: Optional[dict]) -> bool:
    """
    Check if historical data was backfilled before first processed date.

    Returns True if backfill detected (rebuild required).
    """
    if state_dict is None or state_dict.get("daily_min_seen") is None:
        return False  # No state = first run, not a backfill

    row = _fetchone(
        conn, f"SELECT MIN(timestamp) as daily_min_ts FROM {src} WHERE id = %s;", [id_]
    )
    if row and row[0] is not None:
        daily_min_ts = str(row[0])
        daily_min_seen = state_dict["daily_min_seen"]
        if daily_min_ts < daily_min_seen:
            return True
    return False


def _handle_backfill(conn, dst: str, state: str, id_: int) -> None:
    """Delete bars and state for full rebuild."""
    _exec(conn, f"DELETE FROM {dst} WHERE id = %s;", [id_])
    _exec(conn, f"DELETE FROM {state} WHERE id = %s;", [id_])


# =============================================================================
# SQL query builders
# =============================================================================


def _get_last_src_ts(conn, state: str, id_: int) -> Optional[str]:
    """Get last processed timestamp for incremental refresh."""
    row = _fetchone(conn, f"SELECT last_src_ts FROM {state} WHERE id = %s;", [id_])
    if not row or row[0] is None:
        return None
    return str(row[0])


def _build_insert_bars_sql(dst: str, src: str) -> str:
    """
    Build SQL CTE for 1D bar computation with OHLC repair.

    This query:
    1. Computes bar_seq via dense_rank (canonical sequencing)
    2. Applies time_high/time_low repair if outside [time_open, time_close]
    3. Re-enforces OHLC invariants after repair
    4. Upserts into destination table
    5. Returns aggregate stats (upserted, repaired counts, max_src_ts)

    Returns SQL string with placeholders for parameterized execution.
    """
    return f"""
WITH ranked_all AS (
  SELECT
    s.id,
    s."timestamp",
    dense_rank() OVER (PARTITION BY s.id ORDER BY s."timestamp" ASC)::integer AS bar_seq
  FROM {src} s
  WHERE s.id = %s
    AND (%s IS NULL OR s."timestamp" < %s)
),
src_rows AS (
  SELECT
    s.id,
    s.name,
    s.source_file,
    s.load_ts,

    s.timeopen  AS time_open,
    s.timeclose AS time_close,
    s.timehigh  AS time_high,
    s.timelow   AS time_low,

    s."timestamp",

    s.open,
    s.high,
    s.low,
    s.close,
    s.volume,
    s.marketcap AS market_cap,

    r.bar_seq
  FROM {src} s
  JOIN ranked_all r
    ON r.id = s.id
   AND r."timestamp" = s."timestamp"
  WHERE s.id = %s
    AND (%s IS NULL OR s."timestamp" >= %s)
    AND (%s IS NULL OR s."timestamp" <  %s)
    AND (
      %s IS NULL
      OR s."timestamp" > (%s::timestamptz - (%s * INTERVAL '1 day'))
    )
),
base AS (
  SELECT
    id,
    "timestamp",
    bar_seq,

    name,
    source_file,
    load_ts,

    time_open,
    time_close,

    (time_high IS NULL OR time_high < time_open OR time_high > time_close) AS needs_timehigh_repair,
    (time_low  IS NULL OR time_low  < time_open OR time_low  > time_close) AS needs_timelow_repair,

    open, high, low, close, volume, market_cap,
    time_high,
    time_low
  FROM src_rows
),
repaired AS (
  SELECT
    id,
    "timestamp",
    bar_seq,

    name,
    source_file,
    load_ts,

    time_open,
    time_close,

    CASE
      WHEN needs_timehigh_repair THEN
        CASE WHEN close >= open THEN time_close ELSE time_open END
      ELSE time_high
    END AS time_high_fix,

    CASE
      WHEN needs_timelow_repair THEN
        CASE WHEN close <= open THEN time_close ELSE time_open END
      ELSE time_low
    END AS time_low_fix,

    CASE
      WHEN needs_timehigh_repair THEN GREATEST(open, close)
      ELSE high
    END AS high_1,

    CASE
      WHEN needs_timelow_repair THEN LEAST(open, close)
      ELSE low
    END AS low_1,

    open,
    close,
    volume,
    market_cap,

    needs_timehigh_repair AS repaired_timehigh,
    needs_timelow_repair  AS repaired_timelow
  FROM base
),
final AS (
  SELECT
    id,
    "timestamp",
    '1D'::text AS tf,
    bar_seq,

    time_open,
    time_close,

    time_high_fix,
    time_low_fix,

    open,
    close,
    volume,
    market_cap,

    GREATEST(high_1, open, close, low_1) AS high_fix,
    LEAST(low_1,  open, close, high_1)  AS low_fix,

    -- For 1D, these are always false (canonical bars, no partial snapshots).
    false::boolean AS is_partial_start,
    false::boolean AS is_partial_end,
    false::boolean AS is_missing_days,

    -- 1D fixed metadata
    1::integer AS tf_days,
    1::integer AS pos_in_bar,
    1::integer AS count_days,
    0::integer AS count_days_remaining,
    0::integer AS count_missing_days,
    0::integer AS count_missing_days_start,
    0::integer AS count_missing_days_end,
    0::integer AS count_missing_days_interior,

    repaired_timehigh,
    repaired_timelow,
    -- Detect high/low repairs from the CTE logic
    (GREATEST(high_1, open, close, low_1) <> high_1)::boolean AS repaired_high,
    (LEAST(low_1, open, close, high_1)  <> low_1)::boolean  AS repaired_low,

    name,
    load_ts,
    source_file
  FROM repaired
),
ins AS (
  INSERT INTO {dst} (
    id, "timestamp",
    tf, bar_seq,
    time_open, time_close, time_high, time_low,
    time_open_bar, time_close_bar,
    last_ts_half_open,
    open, high, low, close, volume, market_cap,
    is_partial_start, is_partial_end, is_missing_days,
    tf_days, pos_in_bar, count_days, count_days_remaining,
    count_missing_days, count_missing_days_start, count_missing_days_end, count_missing_days_interior,
    src_name, src_load_ts, src_file,
    repaired_timehigh, repaired_timelow, repaired_high, repaired_low
  )
  SELECT
    id, "timestamp",
    tf, bar_seq,
    time_open, time_close, time_high_fix, time_low_fix,
    time_open AS time_open_bar, time_close AS time_close_bar,
    "timestamp" + interval '1 millisecond' AS last_ts_half_open,
    open, high_fix, low_fix, close, volume, market_cap,
    is_partial_start, is_partial_end, is_missing_days,
    tf_days, pos_in_bar, count_days, count_days_remaining,
    count_missing_days, count_missing_days_start, count_missing_days_end, count_missing_days_interior,
    name, load_ts, source_file,
    repaired_timehigh, repaired_timelow, repaired_high, repaired_low
  FROM final
  WHERE
    id IS NOT NULL
    AND "timestamp" IS NOT NULL
    AND tf IS NOT NULL
    AND bar_seq IS NOT NULL
    AND time_open IS NOT NULL
    AND time_close IS NOT NULL
    AND open IS NOT NULL
    AND close IS NOT NULL
    AND volume IS NOT NULL
    AND market_cap IS NOT NULL
    AND time_high_fix IS NOT NULL
    AND time_low_fix IS NOT NULL
    AND high_fix IS NOT NULL
    AND low_fix IS NOT NULL
    AND time_open <= time_close
    AND time_open <= time_high_fix AND time_high_fix <= time_close
    AND time_open <= time_low_fix  AND time_low_fix  <= time_close
    AND high_fix >= low_fix
    AND high_fix >= GREATEST(open, close, low_fix)
    AND low_fix  <= LEAST(open, close, high_fix)
  ON CONFLICT (id, tf, bar_seq, "timestamp") DO UPDATE SET
    time_open = EXCLUDED.time_open,
    time_close = EXCLUDED.time_close,
    time_high = EXCLUDED.time_high,
    time_low = EXCLUDED.time_low,
    time_open_bar = EXCLUDED.time_open_bar,
    time_close_bar = EXCLUDED.time_close_bar,
    last_ts_half_open = EXCLUDED.last_ts_half_open,
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low  = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    market_cap = EXCLUDED.market_cap,
    is_partial_start = EXCLUDED.is_partial_start,
    is_partial_end   = EXCLUDED.is_partial_end,
    is_missing_days  = EXCLUDED.is_missing_days,
    tf_days = EXCLUDED.tf_days,
    pos_in_bar = EXCLUDED.pos_in_bar,
    count_days = EXCLUDED.count_days,
    count_days_remaining = EXCLUDED.count_days_remaining,
    count_missing_days = EXCLUDED.count_missing_days,
    count_missing_days_start = EXCLUDED.count_missing_days_start,
    count_missing_days_end = EXCLUDED.count_missing_days_end,
    count_missing_days_interior = EXCLUDED.count_missing_days_interior,
    src_name = EXCLUDED.src_name,
    src_load_ts = EXCLUDED.src_load_ts,
    src_file = EXCLUDED.src_file,
    repaired_timehigh = EXCLUDED.repaired_timehigh,
    repaired_timelow  = EXCLUDED.repaired_timelow,
    repaired_high = EXCLUDED.repaired_high,
    repaired_low = EXCLUDED.repaired_low
  RETURNING repaired_timehigh, repaired_timelow, "timestamp"
)
SELECT
  count(*)::int AS upserted,
  coalesce(sum((repaired_timehigh)::int), 0)::int AS repaired_timehigh,
  coalesce(sum((repaired_timelow)::int), 0)::int  AS repaired_timelow,
  max("timestamp") AS max_src_ts
FROM ins;
"""


# =============================================================================
# OneDayBarBuilder
# =============================================================================


class OneDayBarBuilder(BaseBarBuilder):
    """
    1D Bar Builder - builds daily OHLC bars from price_histories7.

    Simplest bar builder - one row per local calendar day per asset.
    Inherits shared infrastructure from BaseBarBuilder.
    Implements variant-specific: source query, bar building logic.

    Design:
    - Uses raw psycopg for SQL performance (large CTEs with complex aggregations)
    - BaseBarBuilder provides orchestration, logging, CLI, state management
    - This class provides 1D-specific query construction and execution
    - Backfill detection ensures historical data additions trigger rebuilds
    """

    # Table constants for this builder variant
    STATE_TABLE = "public.cmc_price_bars_1d_state"
    OUTPUT_TABLE = "public.cmc_price_bars_1d"
    SOURCE_TABLE = "public.cmc_price_histories7"

    def __init__(self, config: BarBuilderConfig, engine: Engine):
        """Initialize 1D bar builder with psycopg connection."""
        super().__init__(config, engine)
        # Create psycopg connection for raw SQL execution
        self.psycopg_conn = _connect(config.db_url)

    # =========================================================================
    # Abstract method implementations (required by BaseBarBuilder)
    # =========================================================================

    def get_state_table_name(self) -> str:
        """Return state table name for 1D builder."""
        return self.STATE_TABLE

    def get_output_table_name(self) -> str:
        """Return output bars table name for 1D builder."""
        return self.OUTPUT_TABLE

    def get_source_query(self, id_: int, start_ts: Optional[str] = None) -> str:
        """
        Return SQL query to load source data for one ID.

        Note: This builder uses psycopg CTEs directly, so this method
        is not used. Included for interface compliance.
        """
        # Not used - 1D builder executes CTEs directly via psycopg
        return f"SELECT * FROM {self.SOURCE_TABLE} WHERE id = {id_}"

    def ensure_state_table_exists(self) -> None:
        """
        Create 1D-specific state table if it doesn't exist.

        Schema is different from multi-TF builders:
        - Primary key is just 'id' (not 'id, tf')
        - Has 'last_src_ts' instead of 'last_time_close'
        - Includes daily_min_seen for backfill detection
        """
        state_table = self.get_state_table_name()
        self.logger.info(f"Ensuring 1D state table exists: {state_table}")

        # Handle fully-qualified table names
        if "." in state_table:
            schema, table = state_table.split(".", 1)
            fq_table = state_table
        else:
            schema = "public"
            table = state_table
            fq_table = f"{schema}.{table}"

        ddl = f"""
        CREATE TABLE IF NOT EXISTS {fq_table} (
            id INTEGER NOT NULL,
            tf TEXT NOT NULL DEFAULT '1D',
            last_src_ts TIMESTAMPTZ,
            daily_min_seen TIMESTAMPTZ,
            daily_max_seen TIMESTAMPTZ,
            last_bar_seq INTEGER,
            last_time_close TIMESTAMPTZ,
            last_run_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_upserted INTEGER NOT NULL DEFAULT 0,
            last_repaired_timehigh INTEGER NOT NULL DEFAULT 0,
            last_repaired_timelow INTEGER NOT NULL DEFAULT 0,
            last_rejected INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tf)
        );
        """

        try:
            from sqlalchemy import text

            with self.engine.begin() as conn:
                conn.execute(text(ddl))
            self.logger.info(f"State table ready: {state_table}")
        except Exception as e:
            self.logger.error(f"Failed to create 1D state table {state_table}: {e}")
            raise

        # Also ensure coverage table exists
        ensure_coverage_table(self.engine)

    def build_bars_for_id(
        self,
        id_: int,
        start_ts: Optional[str] = None,
    ) -> int:
        """
        Build 1D bars for one ID using SQL CTE pipeline.

        This method:
        1. Checks for backfill (historical data added before first processed date)
        2. Handles backfill if detected (delete bars + state, rebuild from scratch)
        3. Loads last processed timestamp from state (for incremental refresh)
        4. Executes SQL CTE to compute bars with OHLC repair
        5. Updates state table with new watermarks
        6. Returns count of rows upserted

        Args:
            id_: Cryptocurrency ID
            start_ts: Optional start timestamp (for incremental refresh, not used - state-based)

        Returns:
            Number of rows inserted/updated
        """
        conn = self.psycopg_conn
        src = self.SOURCE_TABLE
        dst = self.OUTPUT_TABLE
        state = self.STATE_TABLE

        # Ensure state table has daily_min_seen column
        _ensure_state_schema(conn, state)

        # Check for backfill and handle if detected
        state_dict = _get_state(conn, state, id_)
        if _check_for_backfill(conn, src, id_, state_dict):
            self.logger.info(f"ID={id_}: Backfill detected, triggering full rebuild")
            _handle_backfill(conn, dst, state, id_)
            state_dict = None  # Reset state after deletion

        # Load last processed timestamp for incremental refresh
        last_src_ts = _get_last_src_ts(conn, state, id_)

        # Build SQL parameters
        # Params order: (id, time_max, time_max, id, time_min, time_min, time_max, time_max, last_src_ts, last_src_ts, lookback_days)
        time_min = None  # No global time_min filter for 1D builder
        time_max = None  # No global time_max filter for 1D builder
        lookback_days = (
            3  # Reprocess 3 days back from last_src_ts (handles late revisions)
        )

        params: List[Any] = [
            id_,
            time_max,
            time_max,
            id_,
            time_min,
            time_min,
            time_max,
            time_max,
            last_src_ts,
            last_src_ts,
            lookback_days,
        ]

        # Execute bar building SQL
        ins_sql = _build_insert_bars_sql(dst=dst, src=src)
        row = _fetchone(conn, ins_sql, params)

        upserted = int(row[0]) if row and row[0] is not None else 0
        rep_hi = int(row[1]) if row and row[1] is not None else 0
        rep_lo = int(row[2]) if row and row[2] is not None else 0
        max_src_ts = row[3] if row else None

        # Update state if any rows were processed
        if max_src_ts is not None:
            # Query MIN timestamp and COUNT from source for coverage tracking
            stats_row = _fetchone(
                conn,
                f"SELECT MIN(timestamp), MAX(timestamp), COUNT(*)::bigint FROM {src} WHERE id = %s;",
                [id_],
            )
            daily_min_ts = (
                str(stats_row[0]) if stats_row and stats_row[0] is not None else None
            )
            daily_max_ts_cov = stats_row[1] if stats_row else None
            total_rows = int(stats_row[2]) if stats_row and stats_row[2] else 0

            _exec(
                conn,
                f"""
                INSERT INTO {state} (id, tf, last_src_ts, daily_min_seen, last_run_ts,
                                    last_upserted, last_repaired_timehigh, last_repaired_timelow, last_rejected)
                VALUES (%s, '1D', %s, %s, now(), %s, %s, %s, 0)
                ON CONFLICT (id, tf) DO UPDATE SET
                  last_src_ts = COALESCE(EXCLUDED.last_src_ts, {state}.last_src_ts),
                  daily_min_seen = LEAST(COALESCE({state}.daily_min_seen, EXCLUDED.daily_min_seen), COALESCE(EXCLUDED.daily_min_seen, {state}.daily_min_seen)),
                  last_run_ts = now(),
                  last_upserted = EXCLUDED.last_upserted,
                  last_repaired_timehigh = EXCLUDED.last_repaired_timehigh,
                  last_repaired_timelow  = EXCLUDED.last_repaired_timelow,
                  last_rejected = EXCLUDED.last_rejected;
                """,
                [id_, max_src_ts, daily_min_ts, upserted, rep_hi, rep_lo],
            )

            # Upsert asset_data_coverage (n_days = n_rows for 1D source data)
            if (
                total_rows > 0
                and daily_min_ts is not None
                and daily_max_ts_cov is not None
            ):
                try:
                    upsert_coverage(
                        self.engine,
                        id_=id_,
                        source_table=src,
                        granularity="1D",
                        n_rows=total_rows,
                        n_days=total_rows,  # 1D data: each row = 1 calendar day
                        first_ts=daily_min_ts,
                        last_ts=daily_max_ts_cov,
                    )
                except Exception as e:
                    self.logger.warning(f"ID={id_}: coverage upsert failed: {e}")

        self.logger.debug(
            f"ID={id_}: upserted={upserted}, repaired_hi={rep_hi}, repaired_lo={rep_lo}"
        )
        return upserted

    @classmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """
        Create argument parser for 1D bar builder CLI.

        Extends base parser with 1D-specific arguments.
        """
        parser = cls.create_base_argument_parser(
            description="Incremental build of canonical 1D bars table with state tracking.",
            default_daily_table="public.cmc_price_histories7",
            default_bars_table="public.cmc_price_bars_1d",
            default_state_table="public.cmc_price_bars_1d_state",
            include_tz=False,  # 1D builder doesn't need timezone parameter
        )

        # Add 1D-specific arguments
        parser.add_argument(
            "--keep-rejects",
            action="store_true",
            help="Log rejected rows to rejects table (not yet implemented for 1D)",
        )
        parser.add_argument(
            "--fail-on-rejects",
            action="store_true",
            help="Exit non-zero if any rejects were logged (not yet implemented for 1D)",
        )

        return parser

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "OneDayBarBuilder":
        """
        Factory method: Create 1D bar builder from CLI arguments.

        Args:
            args: Parsed CLI arguments

        Returns:
            OneDayBarBuilder instance configured from arguments
        """
        # Resolve database URL
        db_url = resolve_db_url(args.db_url)

        # Create engine for SQLAlchemy operations (state management)
        engine = get_engine(db_url)

        # Parse IDs
        ids_parsed = parse_ids(args.ids)
        if ids_parsed == "all":
            ids = load_all_ids(db_url, args.daily_table)
        else:
            ids = ids_parsed

        # Build configuration
        config = BarBuilderConfig(
            db_url=db_url,
            ids=ids,
            daily_table=args.daily_table,
            bars_table=args.bars_table,
            state_table=args.state_table,
            full_rebuild=args.full_rebuild,
            keep_rejects=getattr(args, "keep_rejects", False),
            rejects_table=f"{args.bars_table}_rejects",
            num_processes=getattr(args, "num_processes", 6),
            log_level="INFO",
            log_file=None,
            tz=None,  # 1D builder doesn't use timezone
        )

        return cls(config=config, engine=engine)


# =============================================================================
# CLI Entry Point
# =============================================================================


def main() -> None:
    """Entry point for 1D bar builder."""
    parser = OneDayBarBuilder.create_argument_parser()
    args = parser.parse_args()

    builder = OneDayBarBuilder.from_cli_args(args)
    builder.run()


if __name__ == "__main__":
    main()
