"""
Signal State Manager - State management for signal position lifecycle tracking.

This module provides state tracking for signal positions (open, closed) extending
the feature state management pattern from Phase 7 with signal-specific dimensions.

State Schema (PRIMARY KEY: id, signal_type, signal_id):
- id: Asset identifier
- signal_type: 'ema_crossover', 'rsi_mean_revert', 'atr_breakout'
- signal_id: Reference to dim_signals configuration
- last_entry_ts: Most recent entry signal timestamp
- last_exit_ts: Most recent exit signal timestamp
- open_position_count: Number of currently open positions
- updated_at: Last update timestamp

Usage:
    from ta_lab2.scripts.signals import SignalStateManager, SignalStateConfig

    config = SignalStateConfig(
        state_schema="public",
        state_table="cmc_signal_state",
        signal_type="ema_crossover",
    )

    manager = SignalStateManager(engine, config)
    manager.ensure_state_table()

    # Load open positions for incremental signal generation
    open_positions = manager.load_open_positions(ids=[1, 52], signal_id=1)

    # Update state after generating signals
    manager.update_state_after_generation(
        signal_table="cmc_signals_ema_crossover",
        signal_id=1
    )
"""

from dataclasses import dataclass
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


# =============================================================================
# Configuration
# =============================================================================


@dataclass(frozen=True)
class SignalStateConfig:
    """
    Configuration for signal state management.

    Attributes:
        signal_type: Signal category - 'ema_crossover', 'rsi_mean_revert', 'atr_breakout' (required)
        state_schema: Schema containing state table (default: "public")
        state_table: State table name (default: "cmc_signal_state")
        ts_column: Timestamp column name in signal table (default: "ts")
        id_column: ID column name in signal table (default: "id")
    """

    signal_type: str  # Required: 'ema_crossover', 'rsi_mean_revert', 'atr_breakout'
    state_schema: str = "public"
    state_table: str = "cmc_signal_state"
    ts_column: str = "ts"
    id_column: str = "id"


# =============================================================================
# State Manager Class
# =============================================================================

STATE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS {schema}.{table} (
    -- Primary key
    id                      INTEGER         NOT NULL,
    signal_type             TEXT            NOT NULL,
    signal_id               INTEGER         NOT NULL,

    -- Position tracking
    last_entry_ts           TIMESTAMPTZ     NULL,
    last_exit_ts            TIMESTAMPTZ     NULL,
    open_position_count     INTEGER         DEFAULT 0,

    -- Metadata
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id, signal_type, signal_id)
);
"""


class SignalStateManager:
    """
    Manages state tables for stateful signal position lifecycle tracking.

    Responsibilities:
    - Ensure state table exists with correct schema
    - Load open positions for incremental signal generation
    - Update state after signal generation from signal tables
    - Compute dirty windows for incremental processing
    - Query dim_signals for active signal configurations

    Thread-safety: Not thread-safe. Create separate instances per thread.
    """

    def __init__(self, engine: Engine, config: SignalStateConfig):
        """
        Initialize signal state manager.

        Args:
            engine: SQLAlchemy engine for database operations
            config: Signal state management configuration
        """
        self.engine = engine
        self.config = config

    def ensure_state_table(self) -> None:
        """
        Create signal state table if it doesn't exist.

        This is idempotent - safe to call multiple times.
        """
        sql = STATE_TABLE_SCHEMA.format(
            schema=self.config.state_schema,
            table=self.config.state_table,
        )
        with self.engine.begin() as conn:
            conn.execute(text(sql))

    def load_open_positions(
        self,
        ids: list[int],
        signal_id: int,
    ) -> pd.DataFrame:
        """
        Load open positions for specified assets and signal.

        Queries the signal table (not state table) for position_state='open'
        to get full signal context including entry prices and feature snapshots.

        Args:
            ids: List of asset IDs to query
            signal_id: Signal ID from dim_signals

        Returns:
            DataFrame with columns: id, signal_id, ts, entry_ts, entry_price,
            direction, feature_snapshot, etc.

            Returns empty DataFrame if no open positions found.
        """
        # Determine signal table name from signal_type
        signal_table = f"cmc_signals_{self.config.signal_type}"

        sql_text = f"""
            SELECT
                id, signal_id, ts, direction, position_state,
                entry_ts, entry_price, feature_snapshot,
                signal_version, feature_version_hash, params_hash
            FROM public.{signal_table}
            WHERE id = ANY(:ids)
                AND signal_id = :signal_id
                AND position_state = 'open'
            ORDER BY id, ts
        """

        sql = text(sql_text)

        with self.engine.connect() as conn:
            try:
                return pd.read_sql(
                    sql, conn, params={"ids": ids, "signal_id": signal_id}
                )
            except Exception:
                # Table doesn't exist yet or is empty
                return pd.DataFrame(
                    columns=[
                        "id",
                        "signal_id",
                        "ts",
                        "direction",
                        "position_state",
                        "entry_ts",
                        "entry_price",
                        "feature_snapshot",
                        "signal_version",
                        "feature_version_hash",
                        "params_hash",
                    ]
                )

    def update_state_after_generation(
        self,
        signal_table: str,
        signal_id: int,
    ) -> int:
        """
        Update state table from signal table aggregates.

        Computes last_entry_ts, last_exit_ts, and open_position_count from
        signal table and upserts into state table.

        Args:
            signal_table: Name of signal table (e.g., 'cmc_signals_ema_crossover')
            signal_id: Signal ID from dim_signals

        Returns:
            Number of state rows upserted

        Raises:
            sqlalchemy.exc.SQLAlchemyError: On database errors
        """
        signal_type = self.config.signal_type
        state_table_fq = f"{self.config.state_schema}.{self.config.state_table}"

        sql = f"""
        INSERT INTO {state_table_fq} (
            id, signal_type, signal_id,
            last_entry_ts, last_exit_ts, open_position_count,
            updated_at
        )
        SELECT
            id,
            '{signal_type}' as signal_type,
            signal_id,
            MAX(CASE WHEN entry_ts IS NOT NULL THEN ts END) as last_entry_ts,
            MAX(CASE WHEN exit_ts IS NOT NULL THEN ts END) as last_exit_ts,
            SUM(CASE WHEN position_state = 'open' THEN 1 ELSE 0 END)::INTEGER as open_position_count,
            now() as updated_at
        FROM public.{signal_table}
        WHERE signal_id = :signal_id
        GROUP BY id, signal_id
        ON CONFLICT (id, signal_type, signal_id) DO UPDATE SET
            last_entry_ts = EXCLUDED.last_entry_ts,
            last_exit_ts = EXCLUDED.last_exit_ts,
            open_position_count = EXCLUDED.open_position_count,
            updated_at = EXCLUDED.updated_at
        """

        with self.engine.begin() as conn:
            result = conn.execute(text(sql), {"signal_id": signal_id})
            return result.rowcount

    def get_dirty_window_start(
        self,
        ids: list[int],
        signal_id: int,
    ) -> dict[int, pd.Timestamp]:
        """
        Compute incremental start timestamp per ID based on existing state.

        Uses last_entry_ts from state to determine where to resume signal generation.

        Args:
            ids: List of IDs to compute dirty windows for
            signal_id: Signal ID from dim_signals

        Returns:
            Dictionary mapping ID → start timestamp
            IDs with no state will map to None (indicating full history needed)
        """
        sql_text = f"""
            SELECT id, last_entry_ts
            FROM {self.config.state_schema}.{self.config.state_table}
            WHERE id = ANY(:ids)
                AND signal_type = :signal_type
                AND signal_id = :signal_id
        """

        sql = text(sql_text)

        with self.engine.connect() as conn:
            try:
                state_df = pd.read_sql(
                    sql,
                    conn,
                    params={
                        "ids": ids,
                        "signal_type": self.config.signal_type,
                        "signal_id": signal_id,
                    },
                )
            except Exception:
                # Table doesn't exist yet
                return {id_: None for id_ in ids}

        # If state_df is empty, return None for all IDs
        if state_df.empty:
            return {id_: None for id_ in ids}

        result = {}
        for id_ in ids:
            id_state = state_df[state_df["id"] == id_]

            if id_state.empty or pd.isna(id_state["last_entry_ts"].iloc[0]):
                result[id_] = None
            else:
                result[id_] = pd.to_datetime(
                    id_state["last_entry_ts"].iloc[0], utc=True
                )

        return result

    def __repr__(self) -> str:
        return (
            f"SignalStateManager("
            f"state_table={self.config.state_schema}.{self.config.state_table}, "
            f"signal_type={self.config.signal_type})"
        )
