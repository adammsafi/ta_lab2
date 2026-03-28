"""
Cached query functions for Signal Browser page.

All functions use @st.cache_data and accept ``_engine`` (underscore-prefixed)
as the first argument so st.cache_data skips hashing the engine.

Signal data is queried with ttl=300 because signals update during daily refresh.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Canonical list of strategy types exposed in the Signal Browser.
# Matches signal_type values from dim_signals.
_STRATEGY_TYPES: list[str] = [
    "ema_crossover",
    "rsi_mean_revert",
    "atr_breakout",
]

# Map strategy_type to signal table name
_STRATEGY_TABLE_MAP: dict[str, str] = {
    "ema_crossover": "signals_ema_crossover",
    "rsi_mean_revert": "signals_rsi_mean_revert",
    "atr_breakout": "signals_atr_breakout",
}

# Common column list for UNION ALL queries (all three tables share this schema)
_SIGNAL_COLUMNS = """
    s.id,
    s.ts,
    s.signal_id,
    s.direction,
    s.position_state,
    s.entry_price,
    s.entry_ts,
    s.exit_price,
    s.exit_ts,
    s.pnl_pct,
    s.feature_snapshot,
    s.regime_key,
    s.created_at,
    da.symbol,
    ds.signal_type,
    ds.signal_name
"""


# ---------------------------------------------------------------------------
# Active signals (ttl=300)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def load_active_signals(
    _engine,
    strategy_type: str | None = None,
) -> pd.DataFrame:
    """Return all currently open signals across all signal tables.

    Optionally filter to a single strategy_type.

    Columns: id, ts, signal_id, direction, position_state, entry_price,
             entry_ts, exit_price, exit_ts, pnl_pct, created_at, symbol,
             signal_type, signal_name
    """
    # Build the UNION ALL across all three tables
    # Each sub-SELECT must have identical column lists
    union_parts = []
    for stype, tbl in _STRATEGY_TABLE_MAP.items():
        union_parts.append(
            f"""
            SELECT {_SIGNAL_COLUMNS}
            FROM public.{tbl} s
            JOIN public.dim_assets da ON da.id = s.id
            JOIN public.dim_signals ds ON ds.signal_id = s.signal_id
            WHERE s.position_state = 'open'
            """
        )

    union_sql = "\nUNION ALL\n".join(union_parts)
    full_sql = f"SELECT * FROM ({union_sql}) sub"

    if strategy_type is not None and strategy_type in _STRATEGY_TABLE_MAP:
        full_sql += " WHERE sub.signal_type = :strategy_type"
        full_sql += " ORDER BY sub.entry_ts DESC"
        sql = text(full_sql)
        with _engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={"strategy_type": strategy_type})
    else:
        full_sql += " ORDER BY sub.entry_ts DESC"
        sql = text(full_sql)
        with _engine.connect() as conn:
            df = pd.read_sql(sql, conn)

    if df.empty:
        return df

    for col in ("ts", "entry_ts", "exit_ts", "created_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    return df


# ---------------------------------------------------------------------------
# Signal history (ttl=300)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=300)
def load_signal_history(
    _engine,
    asset_id: int | None = None,
    strategy_type: str | None = None,
    days: int = 90,
) -> pd.DataFrame:
    """Return signal history (all states) for the past N days.

    Optionally filter by asset_id and/or strategy_type.

    CRITICAL: Uses NOW() - make_interval(days => :days) for PostgreSQL interval.

    Columns: id, ts, signal_id, direction, position_state, entry_price,
             entry_ts, exit_price, exit_ts, pnl_pct, created_at, symbol,
             signal_type, signal_name
    """
    union_parts = []
    for _stype, tbl in _STRATEGY_TABLE_MAP.items():
        union_parts.append(
            f"""
            SELECT {_SIGNAL_COLUMNS}
            FROM public.{tbl} s
            JOIN public.dim_assets da ON da.id = s.id
            JOIN public.dim_signals ds ON ds.signal_id = s.signal_id
            WHERE s.ts >= NOW() - make_interval(days => :days)
            """
        )

    union_sql = "\nUNION ALL\n".join(union_parts)
    full_sql = f"SELECT * FROM ({union_sql}) sub WHERE 1=1"

    params: dict = {"days": days}

    if asset_id is not None:
        full_sql += " AND sub.id = :asset_id"
        params["asset_id"] = asset_id

    if strategy_type is not None and strategy_type in _STRATEGY_TABLE_MAP:
        full_sql += " AND sub.signal_type = :strategy_type"
        params["strategy_type"] = strategy_type

    full_sql += " ORDER BY sub.ts DESC"

    sql = text(full_sql)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    if df.empty:
        return df

    for col in ("ts", "entry_ts", "exit_ts", "created_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    return df


# ---------------------------------------------------------------------------
# Strategy and dimension lookups (ttl=3600 -- rarely change)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=3600)
def load_signal_strategies(_engine) -> list[str]:
    """Return the canonical list of strategy types available in signal tables.

    Returns the hardcoded list of signal_type values from dim_signals.
    This avoids a DB round-trip for a value that never changes.
    """
    return list(_STRATEGY_TYPES)


@st.cache_data(ttl=3600)
def load_dim_signals(_engine) -> pd.DataFrame:
    """Return all rows from dim_signals.

    Columns: signal_id, signal_type, signal_name, params, is_active,
             description, created_at
    """
    sql = text(
        """
        SELECT
            signal_id,
            signal_type,
            signal_name,
            params,
            is_active,
            description,
            created_at
        FROM public.dim_signals
        ORDER BY signal_type, signal_name
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    if df.empty:
        return df

    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], utc=True)
    return df
