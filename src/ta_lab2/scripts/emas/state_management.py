"""
Shared state table management for all EMA refresh scripts.

DEPRECATED: This module provides backward compatibility wrappers.
New code should use ema_state_manager.EMAStateManager instead.

Standardizes state table schema, creation, loading, and updating across:
- refresh_cmc_ema_multi_tf_from_bars.py
- refresh_cmc_ema_multi_tf_cal_from_bars.py
- refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py
- refresh_cmc_ema_multi_tf_v2.py

State table schema (unified across all EMA scripts):
- PRIMARY KEY: (id, tf, period)
- ALL scripts populate ALL fields:
  * daily_min_seen, daily_max_seen, last_bar_seq (from bars tables)
  * last_time_close, last_canonical_ts (from output tables)

All scripts read from pre-computed bar tables that contain bar_seq,
so all scripts populate all fields consistently.
"""

import warnings

from typing import Optional
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine


# =============================================================================
# Unified State Table Schema
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

    -- Bar sequence (only populated by multi_tf scripts, NULL for cal/anchor)
    last_bar_seq        INTEGER         NULL,

    -- Metadata
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, period)
);
"""


# =============================================================================
# State Table Functions
# =============================================================================

def ensure_ema_state_table(engine: Engine, schema: str, table: str) -> None:
    """
    Create unified EMA state table if it doesn't exist.

    DEPRECATED: Use EMAStateManager.ensure_state_table() instead.

    Args:
        engine: SQLAlchemy engine
        schema: Schema name (e.g., 'public')
        table: State table name (e.g., 'cmc_ema_multi_tf_state')
    """
    from ta_lab2.scripts.emas.ema_state_manager import EMAStateManager, EMAStateConfig

    config = EMAStateConfig(state_schema=schema, state_table=table)
    manager = EMAStateManager(engine, config)
    manager.ensure_state_table()


def load_ema_state(engine: Engine, schema: str, table: str) -> pd.DataFrame:
    """
    Load all state from unified EMA state table.

    DEPRECATED: Use EMAStateManager.load_state() instead.

    Returns DataFrame with columns:
    - id, tf, period
    - daily_min_seen, daily_max_seen, last_bar_seq, last_time_close
    - last_canonical_ts
    - updated_at

    Returns empty DataFrame if table doesn't exist or has no rows.
    """
    from ta_lab2.scripts.emas.ema_state_manager import EMAStateManager, EMAStateConfig

    config = EMAStateConfig(state_schema=schema, state_table=table)
    manager = EMAStateManager(engine, config)
    return manager.load_state()


def update_ema_state_from_output(
    engine: Engine,
    schema: str,
    state_table: str,
    output_table: str,
    *,
    use_canonical_ts: bool = False,
    ts_column: str = "canonical_ts",
    roll_filter: Optional[str] = None,
    bars_table: Optional[str] = None,
    bars_schema: Optional[str] = None,
    bars_partial_filter: Optional[str] = None,
) -> None:
    """
    Update state table from output table and optionally from bars table.

    DEPRECATED: Use EMAStateManager.update_state_from_output() instead.

    For multi_tf scripts (bars-based):
    - Updates: daily_min_seen, daily_max_seen, last_bar_seq, last_time_close

    For cal scripts (calendar-based with bar tables):
    - Updates: last_canonical_ts, last_time_close, daily_min_seen, daily_max_seen, last_bar_seq
    - Reads bar metadata from bars_table if provided

    Args:
        engine: SQLAlchemy engine
        schema: Schema name
        state_table: State table name
        output_table: Output EMA table name
        use_canonical_ts: If True, update from calendar-based timestamp column.
                         If False, update multi_tf fields from time_close, bar_seq, etc.
        ts_column: Name of timestamp column to use (default: "canonical_ts").
                   For cal scripts: "canonical_ts", for anchor scripts: "ts", etc.
        roll_filter: Optional WHERE clause for filtering canonical rows in output table.
                    For cal scripts: "roll = FALSE", for anchor scripts: "roll_bar = FALSE"
        bars_table: Optional bars table name to read bar_seq and time range from.
                   For cal: "cmc_price_bars_multi_tf_cal_us", for anchor: "cmc_price_bars_multi_tf_cal_anchor_us"
        bars_schema: Schema for bars table (default: same as schema)
        bars_partial_filter: Filter for canonical bars in bars table (default: "is_partial_end = FALSE")
    """
    from ta_lab2.scripts.emas.ema_state_manager import EMAStateManager, EMAStateConfig

    config = EMAStateConfig(
        state_schema=schema,
        state_table=state_table,
        ts_column=ts_column,
        roll_filter=roll_filter or "roll = FALSE",
        use_canonical_ts=use_canonical_ts,
        bars_table=bars_table,
        bars_schema=bars_schema or schema,
        bars_partial_filter=bars_partial_filter or "is_partial_end = FALSE",
    )
    manager = EMAStateManager(engine, config)
    manager.update_state_from_output(output_table=output_table, output_schema=schema)


def compute_dirty_window_start(
    state_df: pd.DataFrame,
    selected_ids: Optional[list[int]] = None,
    default_start: Optional[str] = None,
) -> Optional[pd.Timestamp]:
    """
    Compute dirty window start timestamp for incremental refresh.

    DEPRECATED: This function is kept for backward compatibility.
    New code should use EMAStateManager.compute_dirty_window_starts() instead.

    Uses whichever timestamp is available:
    - last_canonical_ts (for cal scripts)
    - last_time_close (for multi_tf scripts)

    Args:
        state_df: State DataFrame from load_ema_state()
        selected_ids: Optional list of IDs to filter on
        default_start: Default start if no state found

    Returns:
        Minimum timestamp across selected IDs, or None if no state
    """
    if state_df.empty:
        return pd.to_datetime(default_start) if default_start else None

    # Filter to selected IDs if provided
    if selected_ids:
        state_df = state_df[state_df["id"].isin(selected_ids)]

    if state_df.empty:
        return pd.to_datetime(default_start) if default_start else None

    # Use whichever timestamp column is populated
    if "last_canonical_ts" in state_df.columns:
        ts_col = "last_canonical_ts"
    elif "last_time_close" in state_df.columns:
        ts_col = "last_time_close"
    else:
        return pd.to_datetime(default_start) if default_start else None

    # Drop NULLs and find minimum
    ts_series = pd.to_datetime(state_df[ts_col], errors="coerce")
    ts_series = ts_series.dropna()

    if ts_series.empty:
        return pd.to_datetime(default_start) if default_start else None

    return ts_series.min()
