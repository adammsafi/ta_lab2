"""
Generalized 1D Bar Builder - handles CMC, TVC, and HL data sources.

Builds daily OHLC bars with:
- Source selection via --source cmc|tvc|hl|all
- Per-source config loaded from dim_data_sources (SQL CTE template, venue_id, etc.)
- Unified state table PK (id, venue_id, tf)
- Generalized backfill detection using ts_column from dim_data_sources
- Post-build sync to price_bars_multi_tf for TVC/HL sources

This is the BAR-01 / BAR-03 / BAR-04 implementation: one script for all
sources, config-driven extensibility (new source = new dim_data_sources row),
and backfill detection generalized to all sources.

Usage:
    # CMC (default, backwards compatible)
    python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source cmc --ids 1

    # TVC
    python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source tvc --ids all

    # Hyperliquid
    python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source hl --ids all

    # All sources
    python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source all --ids all

    # Full rebuild for one ID on all sources
    python -m ta_lab2.scripts.bars.refresh_price_bars_1d --source all --ids 1 --full-rebuild
"""

from __future__ import annotations

import argparse
import logging
from typing import Any, List, Optional

from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.base_bar_builder import BaseBarBuilder
from ta_lab2.scripts.bars.bar_builder_config import BarBuilderConfig
from ta_lab2.scripts.bars.common_snapshot_contract import (
    get_engine,
    parse_ids,
    resolve_db_url,
    ensure_coverage_table,
    upsert_coverage,
)
from ta_lab2.db.psycopg_helpers import connect, execute, fetchone, fetchall

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table constants (shared across all sources)
# ---------------------------------------------------------------------------

STATE_TABLE = "public.price_bars_1d_state"
OUTPUT_TABLE = "public.price_bars_1d"


# =============================================================================
# Pre-flight: fix CTE templates missing venue_id
# =============================================================================


def _add_venue_id_to_cmc_template(template_text: str) -> str:
    """Add venue_id to CMC CTE template INSERT column list and SELECT list.

    CMC INSERT ends with:
        src_name, src_load_ts, src_file,
        repaired_timehigh, repaired_timelow, repaired_high, repaired_low
      )
      SELECT
        ...
        name, load_ts, source_file,
        repaired_timehigh, repaired_timelow, repaired_high, repaired_low
      FROM final

    We insert venue_id after repaired_low in the INSERT column list,
    and 1::smallint AS venue_id after repaired_low in the SELECT.
    """
    # Fix INSERT column list: add venue_id after repaired_low (before closing paren)
    old_insert_tail = (
        "    repaired_timehigh, repaired_timelow, repaired_high, repaired_low\n  )"
    )
    new_insert_tail = (
        "    repaired_timehigh, repaired_timelow, repaired_high, repaired_low,\n"
        "    venue_id\n  )"
    )
    if old_insert_tail not in template_text:
        log.warning(
            "CMC template: expected INSERT tail not found -- skipping venue_id fix"
        )
        return template_text
    template_text = template_text.replace(old_insert_tail, new_insert_tail, 1)

    # Fix SELECT list: add 1::smallint AS venue_id after repaired_low in the SELECT
    # The SELECT ends with: repaired_timehigh, repaired_timelow, repaired_high, repaired_low\n  FROM final
    old_select_tail = "    repaired_timehigh, repaired_timelow, repaired_high, repaired_low\n  FROM final"
    new_select_tail = (
        "    repaired_timehigh, repaired_timelow, repaired_high, repaired_low,\n"
        "    1::smallint AS venue_id\n  FROM final"
    )
    if old_select_tail not in template_text:
        log.warning(
            "CMC template: expected SELECT tail not found -- skipping venue_id SELECT fix"
        )
        return template_text
    template_text = template_text.replace(old_select_tail, new_select_tail, 1)

    return template_text


def _add_venue_id_to_tvc_template(template_text: str) -> str:
    """Add venue_id to TVC CTE template INSERT column list and SELECT list.

    TVC INSERT ends with:
        ...
        repaired_timehigh, repaired_timelow, repaired_high, repaired_low,
        venue, venue_rank
      )
      SELECT
        ...
        repaired_timehigh, repaired_timelow, repaired_high, repaired_low,
        venue, venue_rank
      FROM final

    We insert venue_id after venue_rank in both the INSERT columns and SELECT.
    """
    # Fix INSERT column list
    old_insert_tail = (
        "    repaired_timehigh, repaired_timelow, repaired_high, repaired_low,\n"
        "    venue, venue_rank\n  )"
    )
    new_insert_tail = (
        "    repaired_timehigh, repaired_timelow, repaired_high, repaired_low,\n"
        "    venue, venue_rank, venue_id\n  )"
    )
    if old_insert_tail not in template_text:
        log.warning(
            "TVC template: expected INSERT tail not found -- skipping venue_id fix"
        )
        return template_text
    template_text = template_text.replace(old_insert_tail, new_insert_tail, 1)

    # Fix SELECT list: add 11::smallint AS venue_id after venue, venue_rank in SELECT
    # The SELECT portion before FROM final
    old_select_tail = (
        "    repaired_timehigh, repaired_timelow, repaired_high, repaired_low,\n"
        "    venue, venue_rank\n  FROM final"
    )
    new_select_tail = (
        "    repaired_timehigh, repaired_timelow, repaired_high, repaired_low,\n"
        "    venue, venue_rank,\n"
        "    11::smallint AS venue_id\n  FROM final"
    )
    if old_select_tail not in template_text:
        log.warning(
            "TVC template: expected SELECT tail not found -- skipping venue_id SELECT fix"
        )
        return template_text
    template_text = template_text.replace(old_select_tail, new_select_tail, 1)

    return template_text


def _preflight_fix_cte_templates(conn) -> None:
    """Fix CTE templates in dim_data_sources that are missing venue_id.

    This runs ONCE at startup (before the source loop). Uses Python string
    detection -- NOT SQL LIKE patterns -- to ensure idempotence. If the
    marker string is already present, the fix is skipped.

    CMC: inserts 1::smallint AS venue_id into final CTE SELECT + INSERT columns.
    TVC: inserts 11::smallint AS venue_id into final CTE SELECT + INSERT columns.
    HL:  already has 2::smallint AS venue_id -- no fix needed.
    """
    rows = fetchall(conn, "SELECT source_key, src_cte_template FROM dim_data_sources")

    for row in rows:
        source_key = row[0]
        template_text = row[1]

        if source_key == "cmc":
            if "1::smallint AS venue_id" not in template_text:
                fixed = _add_venue_id_to_cmc_template(template_text)
                execute(
                    conn,
                    "UPDATE dim_data_sources SET src_cte_template = %s WHERE source_key = %s",
                    [fixed, source_key],
                )
                log.info("Pre-flight: Fixed CMC CTE template -- added venue_id column")
            else:
                log.info("Pre-flight: CMC template already has venue_id -- skipping")

        elif source_key == "tvc":
            if "11::smallint AS venue_id" not in template_text:
                fixed = _add_venue_id_to_tvc_template(template_text)
                execute(
                    conn,
                    "UPDATE dim_data_sources SET src_cte_template = %s WHERE source_key = %s",
                    [fixed, source_key],
                )
                log.info("Pre-flight: Fixed TVC CTE template -- added venue_id column")
            else:
                log.info("Pre-flight: TVC template already has venue_id -- skipping")

        else:
            # HL already has venue_id; any future sources are expected to include it
            log.info(
                "Pre-flight: Template for %s already has venue_id -- skipping",
                source_key,
            )


# =============================================================================
# Source spec loading
# =============================================================================


def _load_source_spec(conn, source_key: str) -> dict:
    """Load per-source configuration from dim_data_sources.

    Args:
        conn: psycopg connection
        source_key: e.g. 'cmc', 'tvc', 'hl'

    Returns:
        dict with all columns from dim_data_sources

    Raises:
        ValueError if source_key not found
    """
    row = fetchone(
        conn,
        """
        SELECT
            source_key, source_name, source_table, venue_id, default_venue,
            ohlc_repair, has_market_cap, has_timehigh,
            id_loader_sql, src_cte_template, join_clause,
            id_filter_sql, ts_column, conflict_columns,
            src_name_label, description
        FROM dim_data_sources
        WHERE source_key = %s
        """,
        [source_key],
    )
    if not row:
        raise ValueError(
            f"Source '{source_key}' not found in dim_data_sources. "
            f"Valid keys: cmc, tvc, hl (or add a new row for new sources)."
        )
    return {
        "source_key": row[0],
        "source_name": row[1],
        "source_table": row[2],
        "venue_id": row[3],
        "default_venue": row[4],
        "ohlc_repair": row[5],
        "has_market_cap": row[6],
        "has_timehigh": row[7],
        "id_loader_sql": row[8],
        "src_cte_template": row[9],
        "join_clause": row[10],
        "id_filter_sql": row[11],
        "ts_column": row[12],
        "conflict_columns": row[13],
        "src_name_label": row[14],
        "description": row[15],
    }


def _resolve_sources(conn, source_arg: str) -> list[str]:
    """Resolve --source argument to list of source_keys.

    'all' loads all source_keys from dim_data_sources.
    Otherwise returns [source_arg].
    """
    if source_arg == "all":
        rows = fetchall(
            conn, "SELECT source_key FROM dim_data_sources ORDER BY source_key"
        )
        return [r[0] for r in rows]
    return [source_arg]


# =============================================================================
# State table migration
# =============================================================================


def _migrate_state_table_pk(conn, state_table: str, source_specs: list[dict]) -> None:
    """Migrate state table to (id, venue_id, tf) PK, handling overlapping IDs.

    CRITICAL: CMC and TVC share the state table with potentially overlapping
    IDs (same dim_assets.id can appear in both sources). A naive
    'backfill all NULL venue_id rows to X' would corrupt the other source's state.

    This function:
    1. Checks if venue_id column exists; adds it if not
    2. For non-CMC sources, creates new state rows for IDs that overlap with CMC
       (setting last_src_ts=NULL to trigger a full build for that source)
    3. Checks if PK includes venue_id; migrates if not
    4. Idempotent: no-op if already migrated

    Args:
        conn: psycopg connection
        state_table: Fully-qualified state table name
        source_specs: List of all source spec dicts for this run
    """
    table_name = state_table.split(".", 1)[-1] if "." in state_table else state_table
    schema_name = state_table.split(".", 1)[0] if "." in state_table else "public"

    # Step 1: Check if venue_id column exists
    venue_col_row = fetchone(
        conn,
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
          AND column_name = 'venue_id'
        """,
        [schema_name, table_name],
    )
    if not venue_col_row:
        log.info("State migration: adding venue_id column to %s", state_table)
        execute(
            conn,
            f"ALTER TABLE {state_table} ADD COLUMN venue_id SMALLINT NOT NULL DEFAULT 1",
        )
        log.info("State migration: venue_id column added (DEFAULT 1 = CMC)")

    # Step 2: For non-CMC sources, create new state rows for overlapping IDs
    # CMC rows get DEFAULT 1, which is already correct.
    # For TVC/HL, create new rows with NULL last_src_ts so they trigger full builds.
    for spec in source_specs:
        sk = spec["source_key"]
        vid = spec["venue_id"]

        if sk == "cmc":
            # CMC rows already have venue_id=1 from DEFAULT -- nothing to do
            continue

        src_table = spec["source_table"]
        join_clause = spec.get("join_clause")

        if join_clause:
            # HL: IDs come via dim_asset_identifiers
            insert_sql = f"""
                INSERT INTO {state_table}
                    (id, venue_id, tf, last_src_ts, daily_min_seen, last_run_ts, last_upserted,
                     last_repaired_timehigh, last_repaired_timelow, last_rejected)
                SELECT DISTINCT dai.id, {vid}::smallint, '1D', NULL, NULL, now(), 0, 0, 0, 0
                FROM dim_asset_identifiers dai
                JOIN hyperliquid.hl_candles c
                  ON dai.id_type = 'HL' AND dai.id_value::int = c.asset_id
                WHERE c.interval = '1d'
                ON CONFLICT (id, venue_id, tf) DO NOTHING
            """
        else:
            # TVC: IDs come directly from source table
            insert_sql = f"""
                INSERT INTO {state_table}
                    (id, venue_id, tf, last_src_ts, daily_min_seen, last_run_ts, last_upserted,
                     last_repaired_timehigh, last_repaired_timelow, last_rejected)
                SELECT DISTINCT id, {vid}::smallint, '1D', NULL, NULL, now(), 0, 0, 0, 0
                FROM {src_table}
                ON CONFLICT (id, venue_id, tf) DO NOTHING
            """

        log.info(
            "State migration: creating initial state rows for %s (venue_id=%d)", sk, vid
        )
        execute(conn, insert_sql)
        log.info("State migration: %s rows initialized (ON CONFLICT DO NOTHING)", sk)

    # Step 3: Check if PK includes venue_id
    pk_row = fetchone(
        conn,
        """
        SELECT array_agg(a.attname ORDER BY array_position(c.conkey, a.attnum))
        FROM pg_constraint c
        JOIN pg_attribute a
          ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        WHERE c.conrelid = %s::regclass
          AND c.contype = 'p'
        GROUP BY c.conname
        """,
        [state_table],
    )

    if pk_row:
        pk_cols = pk_row[0]
        if "venue_id" not in pk_cols:
            log.info("State migration: upgrading PK to include venue_id")
            # Get current PK constraint name
            pk_name_row = fetchone(
                conn,
                """
                SELECT c.conname
                FROM pg_constraint c
                WHERE c.conrelid = %s::regclass AND c.contype = 'p'
                """,
                [state_table],
            )
            if pk_name_row:
                pk_name = pk_name_row[0]
                execute(conn, f"ALTER TABLE {state_table} DROP CONSTRAINT {pk_name}")
            execute(
                conn,
                f"ALTER TABLE {state_table} ADD PRIMARY KEY (id, venue_id, tf)",
            )
            log.info("State migration: PK upgraded to (id, venue_id, tf)")
        else:
            log.info(
                "State migration: PK already includes venue_id -- no DDL change needed"
            )


# =============================================================================
# State table DDL
# =============================================================================


def _ensure_state_table_exists(engine: Engine, conn) -> None:
    """Create state table if it doesn't exist, with (id, venue_id, tf) PK.

    Also ensures asset_data_coverage table exists.
    """
    from sqlalchemy import text as sa_text

    ddl = f"""
    CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
        id INTEGER NOT NULL,
        venue_id SMALLINT NOT NULL DEFAULT 1,
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
        PRIMARY KEY (id, venue_id, tf)
    );
    """
    with engine.begin() as sa_conn:
        sa_conn.execute(sa_text(ddl))

    ensure_coverage_table(engine)
    log.info("State table ready: %s", STATE_TABLE)


# =============================================================================
# Backfill detection
# =============================================================================


def _get_state(conn, id_: int, venue_id: int) -> Optional[dict]:
    """Load full state for (id, venue_id) including daily_min_seen."""
    row = fetchone(
        conn,
        f"SELECT last_src_ts, daily_min_seen FROM {STATE_TABLE} "
        f"WHERE id = %s AND venue_id = %s AND tf = '1D';",
        [id_, venue_id],
    )
    if not row:
        return None
    return {
        "last_src_ts": str(row[0]) if row[0] is not None else None,
        "daily_min_seen": str(row[1]) if row[1] is not None else None,
    }


def _get_last_src_ts(conn, id_: int, venue_id: int) -> Optional[str]:
    """Get last processed timestamp for incremental refresh."""
    row = fetchone(
        conn,
        f"SELECT last_src_ts FROM {STATE_TABLE} "
        f"WHERE id = %s AND venue_id = %s AND tf = '1D';",
        [id_, venue_id],
    )
    if not row or row[0] is None:
        return None
    return str(row[0])


def _check_for_backfill_generic(
    conn, id_: int, spec: dict, state_dict: Optional[dict]
) -> bool:
    """Check if historical data was backfilled before first processed date.

    Returns True if backfill detected (rebuild required).

    For HL source (has join_clause), uses explicit JOIN through
    dim_asset_identifiers since hl_candles has no direct 'id' column.
    For CMC/TVC, queries the source table directly.
    """
    if state_dict is None or state_dict.get("daily_min_seen") is None:
        return False  # No state = first run, not a backfill

    ts_col = spec["ts_column"]
    src = spec["source_table"]
    join_clause = spec.get("join_clause")

    if join_clause:
        # HL path: JOIN through dim_asset_identifiers
        sql = f"""
            SELECT MIN(c.{ts_col})
            FROM {src} c
            JOIN dim_asset_identifiers dai
              ON dai.id_type = 'HL' AND dai.id_value::int = c.asset_id
            WHERE dai.id = %s AND c.interval = '1d'
        """
    else:
        # CMC/TVC path: direct id column
        sql = f"""
            SELECT MIN({ts_col})
            FROM {src}
            WHERE id = %s
        """

    row = fetchone(conn, sql, [id_])
    if row and row[0] is not None:
        src_min_ts = str(row[0])
        daily_min_seen = state_dict["daily_min_seen"]
        if src_min_ts < daily_min_seen:
            return True
    return False


def _handle_backfill(conn, id_: int, venue_id: int) -> None:
    """Delete bars and state for this ID/venue for full rebuild."""
    execute(
        conn,
        f"DELETE FROM {OUTPUT_TABLE} WHERE id = %s AND venue_id = %s AND tf = '1D';",
        [id_, venue_id],
    )
    execute(
        conn,
        f"DELETE FROM {STATE_TABLE} WHERE id = %s AND venue_id = %s AND tf = '1D';",
        [id_, venue_id],
    )


# =============================================================================
# ID loading
# =============================================================================


def _load_ids_for_source(conn, spec: dict) -> list[int]:
    """Load all asset IDs for a source using id_loader_sql from dim_data_sources."""
    sql = spec["id_loader_sql"]
    if not sql:
        raise ValueError(
            f"No id_loader_sql configured for source '{spec['source_key']}'"
        )
    rows = fetchall(conn, sql)
    return [r[0] for r in rows]


# =============================================================================
# Post-build sync
# =============================================================================


def _sync_1d_to_multi_tf(db_url: str, src_name_label: str) -> None:
    """Copy source 1D bars to price_bars_multi_tf for downstream pipeline.

    Uses ON CONFLICT (id, tf, bar_seq, venue_id, timestamp) which is the
    live post-migration PK for price_bars_multi_tf.
    """
    log.info("Syncing %s 1D bars to price_bars_multi_tf...", src_name_label)
    conn = connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO public.price_bars_multi_tf
            SELECT * FROM public.price_bars_1d
            WHERE src_name = %s
            ON CONFLICT (id, tf, bar_seq, venue_id, "timestamp") DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low  = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                market_cap = EXCLUDED.market_cap,
                src_name = EXCLUDED.src_name,
                src_load_ts = EXCLUDED.src_load_ts,
                src_file = EXCLUDED.src_file,
                venue_rank = EXCLUDED.venue_rank
            """,
            [src_name_label],
        )
        conn.commit()
        log.info("Synced %s 1D bars to price_bars_multi_tf", src_name_label)
        cur.close()
    except Exception as e:
        log.warning("Failed to sync %s 1D bars to multi_tf: %s", src_name_label, e)
        conn.rollback()
    finally:
        conn.close()


# =============================================================================
# GenericOneDayBarBuilder
# =============================================================================


class GenericOneDayBarBuilder(BaseBarBuilder):
    """
    Generalized 1D Bar Builder -- handles CMC, TVC, and HL data sources.

    Source-specific behavior (SQL CTE, venue_id, OHLC repair, ID mapping) is
    loaded from dim_data_sources at construction time. Adding a new data source
    requires only a new row in dim_data_sources -- no code changes.

    Inherits shared infrastructure from BaseBarBuilder.
    Implements variant-specific: source loading, bar building logic.

    Design:
    - Uses raw psycopg for SQL performance (large CTEs with complex aggregations)
    - BaseBarBuilder provides orchestration, logging, CLI, state management
    - This class provides source-spec-driven query construction and execution
    - Backfill detection generalized to all sources via ts_column from spec
    """

    def __init__(self, config: BarBuilderConfig, engine: Engine, source_spec: dict):
        """Initialize generalized 1D bar builder.

        Args:
            config: BarBuilderConfig dataclass
            engine: SQLAlchemy engine
            source_spec: Dict loaded from dim_data_sources for this source
        """
        super().__init__(config, engine)
        self.source_spec = source_spec
        self.psycopg_conn = connect(config.db_url)

    # =========================================================================
    # Abstract method implementations (required by BaseBarBuilder)
    # =========================================================================

    def get_state_table_name(self) -> str:
        return STATE_TABLE

    def get_output_table_name(self) -> str:
        return OUTPUT_TABLE

    def get_source_query(self, id_: int, start_ts: Optional[str] = None) -> str:
        """Not used -- 1D builder executes CTEs directly via psycopg."""
        src = self.source_spec["source_table"]
        return f"SELECT * FROM {src} WHERE id = {id_}"

    def ensure_state_table_exists(self) -> None:
        """Create 1D-specific state table with (id, venue_id, tf) PK."""
        _ensure_state_table_exists(self.engine, self.psycopg_conn)

    def build_bars_for_id(
        self,
        id_: int,
        start_ts: Optional[str] = None,
    ) -> int:
        """Build 1D bars for one ID using SQL CTE pipeline from dim_data_sources.

        Steps:
        1. Check for backfill (historical data added before first processed date)
        2. Handle backfill if detected (delete bars + state, rebuild from scratch)
        3. Load last processed timestamp from state (for incremental refresh)
        4. Execute SQL CTE template from dim_data_sources
        5. Update state table with new watermarks
        6. Return count of rows upserted

        Args:
            id_: Asset ID (dim_assets.id)
            start_ts: Not used (state-based incremental)

        Returns:
            Number of rows inserted/updated
        """
        conn = self.psycopg_conn
        spec = self.source_spec
        venue_id = spec["venue_id"]
        dst = OUTPUT_TABLE

        # Full rebuild: delete existing bars and state for this ID/venue
        if self.config.full_rebuild:
            execute(
                conn,
                f"DELETE FROM {dst} WHERE id = %s AND venue_id = %s AND tf = '1D';",
                [id_, venue_id],
            )
            execute(
                conn,
                f"DELETE FROM {STATE_TABLE} WHERE id = %s AND venue_id = %s AND tf = '1D';",
                [id_, venue_id],
            )

        # Check for backfill and handle if detected
        state_dict = _get_state(conn, id_, venue_id)
        if _check_for_backfill_generic(conn, id_, spec, state_dict):
            self.logger.info("ID=%d: Backfill detected, triggering full rebuild", id_)
            _handle_backfill(conn, id_, venue_id)
            state_dict = None  # Reset state after deletion

        # Load last processed timestamp for incremental refresh
        last_src_ts = _get_last_src_ts(conn, id_, venue_id)

        # Build SQL from CTE template
        src_table = spec["source_table"]
        template = spec["src_cte_template"]

        # HL template uses only {dst} (no {src}); CMC/TVC use both {dst} and {src}
        if "{src}" in template:
            ins_sql = template.format(dst=dst, src=src_table)
        else:
            ins_sql = template.format(dst=dst)

        # Build params based on ohlc_repair flag
        time_max = None
        time_min = None
        lookback_days = (
            3  # Reprocess 3 days back from last_src_ts (handles late revisions)
        )

        if spec["ohlc_repair"]:
            # CMC: 11 params
            # ranked_all: id, time_max, time_max
            # src_rows: id, time_min, time_min, time_max, time_max, last_src_ts, last_src_ts, lookback_days
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
        else:
            # TVC/HL: 6 params
            # src_filtered: id
            # ranked: id, last_src_ts, last_src_ts, time_max, time_max
            params = [
                id_,
                id_,
                last_src_ts,
                last_src_ts,
                time_max,
                time_max,
            ]
        row = fetchone(conn, ins_sql, params)

        upserted = int(row[0]) if row and row[0] is not None else 0
        if spec["ohlc_repair"]:
            rep_hi = int(row[1]) if row and row[1] is not None else 0
            rep_lo = int(row[2]) if row and row[2] is not None else 0
            max_src_ts = row[3] if row else None
        else:
            rep_hi = 0
            rep_lo = 0
            max_src_ts = row[1] if row else None

        # Update state if any rows were processed
        if max_src_ts is not None:
            # Query MIN/MAX timestamp and COUNT from source for coverage tracking
            if spec.get("join_clause"):
                # HL: use JOIN through dim_asset_identifiers
                ts_col = spec["ts_column"]
                stats_row = fetchone(
                    conn,
                    f"""
                    SELECT MIN(c.{ts_col}), MAX(c.{ts_col}), COUNT(*)::bigint
                    FROM {src_table} c
                    JOIN dim_asset_identifiers dai
                      ON dai.id_type = 'HL' AND dai.id_value::int = c.asset_id
                    WHERE dai.id = %s AND c.interval = '1d';
                    """,
                    [id_],
                )
            else:
                # CMC/TVC: direct id column
                ts_col = spec["ts_column"]
                stats_row = fetchone(
                    conn,
                    f"SELECT MIN({ts_col}), MAX({ts_col}), COUNT(*)::bigint "
                    f"FROM {src_table} WHERE id = %s;",
                    [id_],
                )

            daily_min_ts = (
                str(stats_row[0]) if stats_row and stats_row[0] is not None else None
            )
            daily_max_ts_cov = stats_row[1] if stats_row else None
            total_rows = int(stats_row[2]) if stats_row and stats_row[2] else 0

            execute(
                conn,
                f"""
                INSERT INTO {STATE_TABLE}
                    (id, venue_id, tf, last_src_ts, daily_min_seen, last_run_ts,
                     last_upserted, last_repaired_timehigh, last_repaired_timelow, last_rejected)
                VALUES (%s, %s, '1D', %s, %s, now(), %s, %s, %s, 0)
                ON CONFLICT (id, venue_id, tf) DO UPDATE SET
                  last_src_ts = COALESCE(EXCLUDED.last_src_ts, {STATE_TABLE}.last_src_ts),
                  daily_min_seen = LEAST(
                    COALESCE({STATE_TABLE}.daily_min_seen, EXCLUDED.daily_min_seen),
                    COALESCE(EXCLUDED.daily_min_seen, {STATE_TABLE}.daily_min_seen)
                  ),
                  last_run_ts = now(),
                  last_upserted = EXCLUDED.last_upserted,
                  last_repaired_timehigh = EXCLUDED.last_repaired_timehigh,
                  last_repaired_timelow  = EXCLUDED.last_repaired_timelow,
                  last_rejected = EXCLUDED.last_rejected;
                """,
                [id_, venue_id, max_src_ts, daily_min_ts, upserted, rep_hi, rep_lo],
            )

            # Upsert asset_data_coverage
            if (
                total_rows > 0
                and daily_min_ts is not None
                and daily_max_ts_cov is not None
            ):
                try:
                    upsert_coverage(
                        self.engine,
                        id_=id_,
                        source_table=src_table,
                        granularity="1D",
                        n_rows=total_rows,
                        n_days=total_rows,  # 1D data: each row = 1 calendar day
                        first_ts=daily_min_ts,
                        last_ts=daily_max_ts_cov,
                    )
                except Exception as e:
                    self.logger.warning("ID=%d: coverage upsert failed: %s", id_, e)

        self.logger.debug(
            "ID=%d: upserted=%d, repaired_hi=%d, repaired_lo=%d",
            id_,
            upserted,
            rep_hi,
            rep_lo,
        )
        return upserted

    @classmethod
    def create_argument_parser(cls) -> argparse.ArgumentParser:
        """Create argument parser for generalized 1D bar builder CLI."""
        parser = cls.create_base_argument_parser(
            description=(
                "Generalized 1D bar builder. Handles CMC, TVC, and HL data sources "
                "via --source flag. Config loaded from dim_data_sources."
            ),
            default_daily_table="public.cmc_price_histories7",
            default_bars_table="public.price_bars_1d",
            default_state_table="public.price_bars_1d_state",
            include_tz=False,
        )

        parser.add_argument(
            "--source",
            type=str,
            choices=["cmc", "tvc", "hl", "all"],
            default="cmc",
            help=(
                "Data source to build bars for. "
                "'cmc' = CoinMarketCap (default), "
                "'tvc' = TradingView, "
                "'hl' = Hyperliquid, "
                "'all' = all sources in dim_data_sources."
            ),
        )
        parser.add_argument(
            "--keep-rejects",
            action="store_true",
            help="Log rejected rows to rejects table",
        )
        parser.add_argument(
            "--fail-on-rejects",
            action="store_true",
            help="Exit non-zero if any rejects were logged",
        )

        return parser

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "GenericOneDayBarBuilder":
        """Not used directly -- main() builds each source separately."""
        raise NotImplementedError(
            "Use main() to instantiate GenericOneDayBarBuilder for each source. "
            "from_cli_args() is not supported for multi-source builds."
        )


# =============================================================================
# CLI Entry Point
# =============================================================================


def main() -> None:
    """Entry point for generalized 1D bar builder."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = GenericOneDayBarBuilder.create_argument_parser()
    args = parser.parse_args()

    db_url = resolve_db_url(args.db_url)
    engine = get_engine(db_url)
    conn = connect(db_url)

    # Pre-flight: fix CTE templates missing venue_id (idempotent, Python string check)
    _preflight_fix_cte_templates(conn)

    # Resolve source list
    source_keys = _resolve_sources(conn, args.source)
    log.info("Sources to process: %s", source_keys)

    # Load all source specs (needed for state migration)
    all_specs = [_load_source_spec(conn, sk) for sk in source_keys]

    # Migrate state table PK once (handles overlapping IDs across sources)
    _migrate_state_table_pk(conn, STATE_TABLE, all_specs)

    for spec in all_specs:
        sk = spec["source_key"]
        log.info("=== Building source: %s ===", sk)

        # Resolve IDs for this source
        ids_parsed = parse_ids(args.ids)
        if ids_parsed == "all":
            ids = _load_ids_for_source(conn, spec)
            log.info("Loaded %d IDs for source %s", len(ids), sk)
        else:
            ids = ids_parsed

        if not ids:
            log.warning("No IDs found for source %s -- skipping", sk)
            continue

        config = BarBuilderConfig(
            db_url=db_url,
            ids=ids,
            daily_table=spec["source_table"],
            bars_table=OUTPUT_TABLE,
            state_table=STATE_TABLE,
            full_rebuild=args.full_rebuild,
            keep_rejects=getattr(args, "keep_rejects", False),
            rejects_table="public.price_bars_1d_rejects",
            num_processes=getattr(args, "num_processes", 6),
            log_level="INFO",
            log_file=None,
            tz=None,
        )

        builder = GenericOneDayBarBuilder(
            config=config, engine=engine, source_spec=spec
        )
        builder.run()

        # Sync 1D to multi_tf for non-CMC sources (TVC, HL)
        if sk != "cmc":
            _sync_1d_to_multi_tf(db_url, spec["src_name_label"])

    conn.close()


if __name__ == "__main__":
    main()
