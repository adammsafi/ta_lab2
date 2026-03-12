"""
Cached query functions for Risk & Controls page.

All functions use @st.cache_data(ttl=N) and accept ``_engine`` (underscore-
prefixed) as the first argument so st.cache_data skips hashing the engine.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


@st.cache_data(ttl=60)
def load_risk_state(_engine) -> dict:
    """Return the single dim_risk_state row as a dict.

    Keys: trading_state, halted_at, halted_reason, halted_by, drift_paused,
          drift_paused_at, drift_paused_reason, drift_auto_escalate_after_days,
          day_open_portfolio_value, last_day_open_date, cb_consecutive_losses,
          cb_breaker_tripped_at, updated_at

    Returns empty dict if no row found.
    """
    sql = text(
        """
        SELECT
            trading_state,
            halted_at,
            halted_reason,
            halted_by,
            drift_paused,
            drift_paused_at,
            drift_paused_reason,
            drift_auto_escalate_after_days,
            day_open_portfolio_value,
            last_day_open_date,
            cb_consecutive_losses,
            cb_breaker_tripped_at,
            updated_at
        FROM public.dim_risk_state
        WHERE state_id = 1
        """
    )
    with _engine.connect() as conn:
        row = conn.execute(sql).fetchone()

    if row is None:
        return {}
    return dict(row._mapping)


@st.cache_data(ttl=300)
def load_risk_limits(_engine) -> dict:
    """Return the portfolio-wide dim_risk_limits row as a dict.

    Keys: max_position_pct, max_portfolio_pct, daily_loss_pct_threshold,
          cb_consecutive_losses_n, cb_cooldown_hours,
          drift_tracking_error_threshold_5d, drift_tracking_error_threshold_30d

    Returns empty dict if no row found.
    """
    sql = text(
        """
        SELECT
            max_position_pct,
            max_portfolio_pct,
            daily_loss_pct_threshold,
            cb_consecutive_losses_n,
            cb_cooldown_hours,
            drift_tracking_error_threshold_5d,
            drift_tracking_error_threshold_30d
        FROM public.dim_risk_limits
        WHERE asset_id IS NULL
          AND strategy_id IS NULL
        LIMIT 1
        """
    )
    with _engine.connect() as conn:
        row = conn.execute(sql).fetchone()

    if row is None:
        return {}
    return dict(row._mapping)


@st.cache_data(ttl=120)
def load_risk_events(
    _engine,
    days: int = 30,
    event_type: str | None = None,
) -> pd.DataFrame:
    """Return recent risk events from risk_events.

    Columns: event_id, event_ts, event_type, trigger_source, reason, operator,
             asset_id, strategy_id, metadata

    Parameters
    ----------
    days : int
        Number of days of history to return. Default 30.
    event_type : str | None
        Optional filter on event_type column. Default None (all types).
    """
    base_sql = """
        SELECT
            event_id,
            event_ts,
            event_type,
            trigger_source,
            reason,
            operator,
            asset_id,
            strategy_id,
            metadata
        FROM public.risk_events
        WHERE event_ts >= NOW() - INTERVAL :interval
    """
    params: dict = {"interval": f"{days} days"}

    if event_type is not None:
        base_sql += " AND event_type = :event_type"
        params["event_type"] = event_type

    base_sql += " ORDER BY event_ts DESC LIMIT 200"

    with _engine.connect() as conn:
        df = pd.read_sql(text(base_sql), conn, params=params)

    if df.empty:
        return df

    df["event_ts"] = pd.to_datetime(df["event_ts"], utc=True)
    return df
