"""
EMA State Manager - Object-oriented state management for EMA refresh scripts.

This module provides a clean OOP interface for managing state tables used by
EMA refresh scripts. It encapsulates the functional state_management.py module
with better encapsulation, error handling, and testability.

Unified State Schema (PRIMARY KEY: id, tf, period):
- id, tf, period: Identifiers
- daily_min_seen, daily_max_seen: Timestamp range from source bars
- last_bar_seq: Maximum bar sequence from source bars
- last_time_close, last_canonical_ts: Latest EMA timestamps
- updated_at: Last update timestamp

Usage:
    from ta_lab2.scripts.emas.ema_state_manager import EMAStateManager, EMAStateConfig

    config = EMAStateConfig(
        state_schema="public",
        state_table="cmc_ema_multi_tf_state",
        ts_column="ts",
        roll_filter="roll = FALSE",
    )

    manager = EMAStateManager(engine, config)
    manager.ensure_state_table()

    state_df = manager.load_state(ids=[1, 52], periods=[9, 10])

    manager.update_state_from_output(
        output_table="cmc_ema_multi_tf",
        output_schema="public",
    )
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


# =============================================================================
# Configuration
# =============================================================================


@dataclass(frozen=True)
class EMAStateConfig:
    """
    Configuration for EMA state management.

    Attributes:
        state_schema: Schema containing state table (default: "public")
        state_table: State table name (default: "cmc_ema_state")
        ts_column: Timestamp column name in output table (default: "ts")
        roll_filter: WHERE clause for canonical rows (default: "roll = FALSE")
        use_canonical_ts: Whether to use canonical timestamp logic (default: False)
        bars_table: Optional bars table for metadata (default: None)
        bars_schema: Schema for bars table (default: "public")
        bars_partial_filter: Filter for canonical bars (default: "is_partial_end = FALSE")
    """

    state_schema: str = "public"
    state_table: str = "cmc_ema_state"
    ts_column: str = "ts"
    roll_filter: str = "roll = FALSE"
    use_canonical_ts: bool = False
    bars_table: Optional[str] = None
    bars_schema: str = "public"
    bars_partial_filter: str = "is_partial_end = FALSE"


# =============================================================================
# State Manager Class
# =============================================================================

UNIFIED_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS {schema}.{table} (
    -- Primary key
    id                  INTEGER         NOT NULL,
    tf                  TEXT            NOT NULL,
    period              INTEGER         NOT NULL,

    -- Timestamp range (populated by all scripts)
    daily_min_seen      TIMESTAMPTZ     NULL,
    daily_max_seen      TIMESTAMPTZ     NULL,
    last_time_close     TIMESTAMPTZ     NULL,
    last_canonical_ts   TIMESTAMPTZ     NULL,

    -- Bar sequence (populated from bars tables)
    last_bar_seq        INTEGER         NULL,

    -- Metadata
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, period)
);
"""


class EMAStateManager:
    """
    Manages state tables for incremental EMA refreshes.

    Responsibilities:
    - Ensure state table exists with unified schema
    - Load existing state for incremental computation
    - Update state after EMA computation from output and bars tables
    - Compute dirty windows for backfill detection

    Thread-safety: Not thread-safe. Create separate instances per thread.
    """

    def __init__(self, engine: Engine, config: EMAStateConfig):
        """
        Initialize state manager.

        Args:
            engine: SQLAlchemy engine for database operations
            config: State management configuration
        """
        self.engine = engine
        self.config = config

    def ensure_state_table(self) -> None:
        """
        Create unified EMA state table if it doesn't exist.

        This is idempotent - safe to call multiple times.
        """
        sql = UNIFIED_STATE_SCHEMA.format(
            schema=self.config.state_schema,
            table=self.config.state_table,
        )
        with self.engine.begin() as conn:
            conn.execute(text(sql))

    def load_state(
        self,
        *,
        ids: Optional[list[int]] = None,
        tfs: Optional[list[str]] = None,
        periods: Optional[list[int]] = None,
    ) -> pd.DataFrame:
        """
        Load state from state table with optional filters.

        Args:
            ids: Optional list of IDs to filter
            tfs: Optional list of timeframes to filter
            periods: Optional list of periods to filter

        Returns:
            DataFrame with columns: id, tf, period, daily_min_seen, daily_max_seen,
            last_bar_seq, last_time_close, last_canonical_ts, updated_at

            Returns empty DataFrame if table doesn't exist or no rows match filters.
        """
        # Build WHERE clauses
        where_clauses = []
        params = {}

        if ids is not None:
            where_clauses.append("id = ANY(:ids)")
            params["ids"] = ids

        if tfs is not None:
            where_clauses.append("tf = ANY(:tfs)")
            params["tfs"] = tfs

        if periods is not None:
            where_clauses.append("period = ANY(:periods)")
            params["periods"] = periods

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        sql_text = f"""
            SELECT
                id, tf, period,
                daily_min_seen, daily_max_seen, last_bar_seq, last_time_close,
                last_canonical_ts,
                updated_at
            FROM {self.config.state_schema}.{self.config.state_table}
            {where_sql}
        """

        sql = text(sql_text)

        with self.engine.connect() as conn:
            try:
                return pd.read_sql(sql, conn, params=params)
            except Exception:
                # Table doesn't exist yet or is empty
                return pd.DataFrame(
                    columns=[
                        "id",
                        "tf",
                        "period",
                        "daily_min_seen",
                        "daily_max_seen",
                        "last_bar_seq",
                        "last_time_close",
                        "last_canonical_ts",
                        "updated_at",
                    ]
                )

    def update_state_from_output(
        self,
        output_table: str,
        output_schema: str = "public",
    ) -> int:
        """
        Update state table from EMA output table and optionally bars table.

        Uses configuration to determine:
        - Which timestamp column to use (config.ts_column)
        - Whether to use canonical timestamp logic (config.use_canonical_ts)
        - Whether to pull metadata from bars table (config.bars_table)
        - How to filter canonical rows (config.roll_filter)

        Args:
            output_table: Name of EMA output table
            output_schema: Schema containing output table (default: "public")

        Returns:
            Number of state rows upserted

        Raises:
            sqlalchemy.exc.SQLAlchemyError: On database errors
        """
        if self.config.use_canonical_ts:
            return self._update_canonical_ts_mode(output_table, output_schema)
        else:
            return self._update_multi_tf_mode(output_table, output_schema)

    def _update_canonical_ts_mode(self, output_table: str, output_schema: str) -> int:
        """Update state using canonical timestamp logic (for cal/anchor scripts)."""
        ts_col = self.config.ts_column
        roll_filter = self.config.roll_filter
        where_clause = (
            f"WHERE {roll_filter}" if roll_filter else f"WHERE {ts_col} IS NOT NULL"
        )

        bars_table = self.config.bars_table
        bars_schema = self.config.bars_schema
        bars_partial_filter = self.config.bars_partial_filter

        state_table_fq = f"{self.config.state_schema}.{self.config.state_table}"

        if bars_table:
            # Read bar metadata from bars table
            sql = f"""
            WITH canonical_ts AS (
                -- Canonical closes (for last_canonical_ts and last_time_close)
                SELECT
                    id,
                    tf,
                    period,
                    MAX({ts_col}) as last_canonical_ts
                FROM {output_schema}.{output_table}
                {where_clause}
                GROUP BY id, tf, period
            ),
            bar_metadata AS (
                -- Bar metadata (daily range and bar_seq) per (id, tf)
                SELECT
                    id,
                    tf,
                    MIN(time_open) as daily_min_seen,
                    MAX("timestamp") as daily_max_seen,
                    MAX(CASE WHEN {bars_partial_filter} THEN bar_seq END) as last_bar_seq
                FROM {bars_schema}.{bars_table}
                GROUP BY id, tf
            ),
            periods_for_id_tf AS (
                -- Get all periods for each (id, tf) from output table
                SELECT DISTINCT id, tf, period
                FROM {output_schema}.{output_table}
            )
            INSERT INTO {state_table_fq} (
                id, tf, period,
                last_canonical_ts,
                last_time_close,
                daily_min_seen,
                daily_max_seen,
                last_bar_seq,
                updated_at
            )
            SELECT
                p.id,
                p.tf,
                p.period,
                c.last_canonical_ts,
                c.last_canonical_ts as last_time_close,
                b.daily_min_seen,
                b.daily_max_seen,
                b.last_bar_seq,
                now() as updated_at
            FROM periods_for_id_tf p
            JOIN canonical_ts c ON p.id = c.id AND p.tf = c.tf AND p.period = c.period
            JOIN bar_metadata b ON p.id = b.id AND p.tf = b.tf
            ON CONFLICT (id, tf, period) DO UPDATE SET
                last_canonical_ts = EXCLUDED.last_canonical_ts,
                last_time_close = EXCLUDED.last_time_close,
                daily_min_seen = EXCLUDED.daily_min_seen,
                daily_max_seen = EXCLUDED.daily_max_seen,
                last_bar_seq = EXCLUDED.last_bar_seq,
                updated_at = EXCLUDED.updated_at
            """
        else:
            # No bars table - use timestamp range from output table
            sql = f"""
            WITH canonical_ts AS (
                -- Canonical closes (for last_canonical_ts and last_time_close)
                SELECT
                    id,
                    tf,
                    period,
                    MAX({ts_col}) as last_canonical_ts
                FROM {output_schema}.{output_table}
                {where_clause}
                GROUP BY id, tf, period
            ),
            daily_range AS (
                -- Full timestamp range (for daily_min_seen and daily_max_seen)
                SELECT
                    id,
                    tf,
                    period,
                    MIN({ts_col}) as daily_min_seen,
                    MAX({ts_col}) as daily_max_seen
                FROM {output_schema}.{output_table}
                WHERE {ts_col} IS NOT NULL
                GROUP BY id, tf, period
            )
            INSERT INTO {state_table_fq} (
                id, tf, period,
                last_canonical_ts,
                last_time_close,
                daily_min_seen,
                daily_max_seen,
                updated_at
            )
            SELECT
                c.id,
                c.tf,
                c.period,
                c.last_canonical_ts,
                c.last_canonical_ts as last_time_close,
                d.daily_min_seen,
                d.daily_max_seen,
                now() as updated_at
            FROM canonical_ts c
            JOIN daily_range d ON c.id = d.id AND c.tf = d.tf AND c.period = d.period
            ON CONFLICT (id, tf, period) DO UPDATE SET
                last_canonical_ts = EXCLUDED.last_canonical_ts,
                last_time_close = EXCLUDED.last_time_close,
                daily_min_seen = EXCLUDED.daily_min_seen,
                daily_max_seen = EXCLUDED.daily_max_seen,
                updated_at = EXCLUDED.updated_at
            """

        with self.engine.begin() as conn:
            result = conn.execute(text(sql))
            return result.rowcount

    def _update_multi_tf_mode(self, output_table: str, output_schema: str) -> int:
        """Update state using multi-tf logic (for multi_tf scripts)."""
        state_table_fq = f"{self.config.state_schema}.{self.config.state_table}"
        ts_col = self.config.ts_column

        sql = f"""
        INSERT INTO {state_table_fq} (id, tf, period, last_time_close, last_bar_seq, updated_at)
        SELECT
            id,
            tf,
            period,
            MAX({ts_col}) as last_time_close,
            MAX(bar_seq) as last_bar_seq,
            now() as updated_at
        FROM {output_schema}.{output_table}
        WHERE {ts_col} IS NOT NULL
        GROUP BY id, tf, period
        ON CONFLICT (id, tf, period) DO UPDATE SET
            last_time_close = EXCLUDED.last_time_close,
            last_bar_seq = EXCLUDED.last_bar_seq,
            updated_at = EXCLUDED.updated_at
        """

        with self.engine.begin() as conn:
            result = conn.execute(text(sql))
            return result.rowcount

    def compute_dirty_window_starts(
        self,
        ids: list[int],
        default_start: str = "2010-01-01",
    ) -> dict[int, pd.Timestamp]:
        """
        Compute incremental start timestamp per ID based on existing state.

        Uses whichever timestamp is available (last_canonical_ts or last_time_close).

        Args:
            ids: List of IDs to compute dirty windows for
            default_start: Default start if no state found for an ID

        Returns:
            Dictionary mapping ID → start timestamp
            IDs with no state will map to default_start
        """
        state_df = self.load_state(ids=ids)
        default_ts = pd.to_datetime(default_start, utc=True)

        result = {}
        for id_ in ids:
            id_state = state_df[state_df["id"] == id_]

            if id_state.empty:
                result[id_] = default_ts
                continue

            # Use whichever timestamp column is populated
            if "last_canonical_ts" in id_state.columns:
                ts_col = "last_canonical_ts"
            elif "last_time_close" in id_state.columns:
                ts_col = "last_time_close"
            else:
                result[id_] = default_ts
                continue

            # Get minimum timestamp for this ID across all (tf, period) combinations
            ts_series = pd.to_datetime(id_state[ts_col], errors="coerce")
            ts_series = ts_series.dropna()

            if ts_series.empty:
                result[id_] = default_ts
            else:
                result[id_] = ts_series.min()

        return result

    def __repr__(self) -> str:
        return (
            f"EMAStateManager("
            f"state_table={self.config.state_schema}.{self.config.state_table}, "
            f"ts_column={self.config.ts_column})"
        )
