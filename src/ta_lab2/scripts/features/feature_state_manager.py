"""
Feature State Manager - State management for feature pipeline refresh scripts.

This module provides state tracking for feature calculations (returns, volatility,
technical indicators) extending the EMA state management pattern with feature_type
and feature_name dimensions.

Unified State Schema (PRIMARY KEY: id, feature_type, feature_name):
- id: Asset identifier
- feature_type: 'returns', 'vol', 'ta'
- feature_name: 'b2t_pct', 'parkinson_20', 'rsi_14'
- daily_min_seen, daily_max_seen: Timestamp range from source bars
- last_ts: Latest feature timestamp
- row_count: Number of feature rows
- updated_at: Last update timestamp

Usage:
    from ta_lab2.scripts.features import FeatureStateManager, FeatureStateConfig

    config = FeatureStateConfig(
        state_schema="public",
        state_table="cmc_feature_state",
        feature_type="returns",
        ts_column="ts",
    )

    manager = FeatureStateManager(engine, config)
    manager.ensure_state_table()

    state_df = manager.load_state(ids=[1, 52], feature_names=["b2t_pct"])

    manager.update_state_from_output(
        output_table="cmc_returns_daily",
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
class FeatureStateConfig:
    """
    Configuration for feature state management.

    Attributes:
        state_schema: Schema containing state table (default: "public")
        state_table: State table name (default: "cmc_feature_state")
        feature_type: Feature category - 'returns', 'vol', 'ta' (default: "returns")
        ts_column: Timestamp column name in output table (default: "ts")
        id_column: ID column name in output table (default: "id")
    """
    state_schema: str = "public"
    state_table: str = "cmc_feature_state"
    feature_type: str = "returns"  # 'returns', 'vol', 'ta'
    ts_column: str = "ts"
    id_column: str = "id"


# =============================================================================
# State Manager Class
# =============================================================================

UNIFIED_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS {schema}.{table} (
    -- Primary key
    id                  INTEGER         NOT NULL,
    feature_type        TEXT            NOT NULL,
    feature_name        TEXT            NOT NULL,

    -- Timestamp range (populated from feature output)
    daily_min_seen      TIMESTAMPTZ     NULL,
    daily_max_seen      TIMESTAMPTZ     NULL,
    last_ts             TIMESTAMPTZ     NULL,

    -- Row count tracking
    row_count           INTEGER         NULL,

    -- Metadata
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id, feature_type, feature_name)
);
"""


class FeatureStateManager:
    """
    Manages state tables for incremental feature refreshes.

    Responsibilities:
    - Ensure state table exists with unified schema
    - Load existing state for incremental computation
    - Update state after feature computation from output tables
    - Compute dirty windows for backfill detection
    - Query dim_features for null handling strategies

    Thread-safety: Not thread-safe. Create separate instances per thread.
    """

    def __init__(self, engine: Engine, config: FeatureStateConfig):
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
        Create unified feature state table if it doesn't exist.

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
        feature_type: Optional[str] = None,
        feature_names: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        """
        Load state from state table with optional filters.

        Args:
            ids: Optional list of IDs to filter
            feature_type: Optional feature type to filter ('returns', 'vol', 'ta')
            feature_names: Optional list of feature names to filter

        Returns:
            DataFrame with columns: id, feature_type, feature_name, daily_min_seen,
            daily_max_seen, last_ts, row_count, updated_at

            Returns empty DataFrame if table doesn't exist or no rows match filters.
        """
        # Build WHERE clauses
        where_clauses = []
        params = {}

        if ids is not None:
            where_clauses.append("id = ANY(:ids)")
            params["ids"] = ids

        if feature_type is not None:
            where_clauses.append("feature_type = :feature_type")
            params["feature_type"] = feature_type

        if feature_names is not None:
            where_clauses.append("feature_name = ANY(:feature_names)")
            params["feature_names"] = feature_names

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        sql_text = f"""
            SELECT
                id, feature_type, feature_name,
                daily_min_seen, daily_max_seen, last_ts,
                row_count,
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
                return pd.DataFrame(columns=[
                    "id", "feature_type", "feature_name",
                    "daily_min_seen", "daily_max_seen", "last_ts",
                    "row_count",
                    "updated_at"
                ])

    def update_state_from_output(
        self,
        output_table: str,
        output_schema: str = "public",
        feature_name: Optional[str] = None,
    ) -> int:
        """
        Update state table from feature output table.

        Uses configuration to determine:
        - Which timestamp column to use (config.ts_column)
        - Which ID column to use (config.id_column)
        - Feature type from config (config.feature_type)

        Args:
            output_table: Name of feature output table
            output_schema: Schema containing output table (default: "public")
            feature_name: Feature name for this output (if None, derived from table)

        Returns:
            Number of state rows upserted

        Raises:
            sqlalchemy.exc.SQLAlchemyError: On database errors
        """
        # Derive feature_name from table if not provided
        if feature_name is None:
            # Extract from table name (e.g., 'cmc_returns_daily' -> 'returns_daily')
            feature_name = output_table.replace("cmc_", "").replace(f"_{self.config.feature_type}_", "_")

        ts_col = self.config.ts_column
        id_col = self.config.id_column
        feature_type = self.config.feature_type
        state_table_fq = f"{self.config.state_schema}.{self.config.state_table}"

        sql = f"""
        INSERT INTO {state_table_fq} (
            id, feature_type, feature_name,
            daily_min_seen, daily_max_seen, last_ts,
            row_count,
            updated_at
        )
        SELECT
            {id_col} as id,
            '{feature_type}' as feature_type,
            '{feature_name}' as feature_name,
            MIN({ts_col}) as daily_min_seen,
            MAX({ts_col}) as daily_max_seen,
            MAX({ts_col}) as last_ts,
            COUNT(*) as row_count,
            now() as updated_at
        FROM {output_schema}.{output_table}
        WHERE {ts_col} IS NOT NULL
        GROUP BY {id_col}
        ON CONFLICT (id, feature_type, feature_name) DO UPDATE SET
            daily_min_seen = EXCLUDED.daily_min_seen,
            daily_max_seen = EXCLUDED.daily_max_seen,
            last_ts = EXCLUDED.last_ts,
            row_count = EXCLUDED.row_count,
            updated_at = EXCLUDED.updated_at
        """

        with self.engine.begin() as conn:
            result = conn.execute(text(sql))
            return result.rowcount

    def compute_dirty_window_starts(
        self,
        ids: list[int],
        feature_type: Optional[str] = None,
        default_start: str = "2010-01-01",
    ) -> dict[int, pd.Timestamp]:
        """
        Compute incremental start timestamp per ID based on existing state.

        Uses last_ts from state to determine where to resume feature calculation.

        Args:
            ids: List of IDs to compute dirty windows for
            feature_type: Optional feature type filter
            default_start: Default start if no state found for an ID

        Returns:
            Dictionary mapping ID → start timestamp
            IDs with no state will map to default_start
        """
        if feature_type is None:
            feature_type = self.config.feature_type

        state_df = self.load_state(ids=ids, feature_type=feature_type)
        default_ts = pd.to_datetime(default_start, utc=True)

        result = {}
        for id_ in ids:
            id_state = state_df[state_df["id"] == id_]

            if id_state.empty:
                result[id_] = default_ts
                continue

            # Get minimum last_ts for this ID across all feature_names
            ts_series = pd.to_datetime(id_state["last_ts"], errors="coerce")
            ts_series = ts_series.dropna()

            if ts_series.empty:
                result[id_] = default_ts
            else:
                result[id_] = ts_series.min()

        return result

    def get_null_strategy(self, feature_name: str) -> str:
        """
        Query dim_features for null handling strategy.

        Args:
            feature_name: Feature name to look up

        Returns:
            Null strategy: 'skip', 'forward_fill', or 'interpolate'
            Returns 'skip' as default if feature not found

        Raises:
            sqlalchemy.exc.SQLAlchemyError: On database errors
        """
        sql = text("""
            SELECT null_strategy
            FROM public.dim_features
            WHERE feature_type = :feature_type
        """)

        with self.engine.connect() as conn:
            result = conn.execute(sql, {"feature_type": feature_name})
            row = result.fetchone()

            if row is None:
                # Default to 'skip' if not found
                return 'skip'

            return row[0]

    def __repr__(self) -> str:
        return (
            f"FeatureStateManager("
            f"state_table={self.config.state_schema}.{self.config.state_table}, "
            f"feature_type={self.config.feature_type})"
        )
