"""
Cached query functions for Drift Monitor page.

All functions use @st.cache_data(ttl=300) and accept ``_engine`` (underscore-
prefixed) as the first argument so st.cache_data skips hashing the engine.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


@st.cache_data(ttl=300)
def load_drift_timeseries(_engine, config_id: int, days: int = 30) -> pd.DataFrame:
    """Return daily drift metrics for a specific executor config over N days.

    Columns: metric_date, tracking_error_5d, tracking_error_30d,
             paper_cumulative_pnl, replay_pit_cumulative_pnl,
             threshold_breach, drift_pct_of_threshold

    Parameters
    ----------
    config_id : int
        Executor config ID to filter on.
    days : int
        Number of calendar days of history to return. Default 30.
    """
    sql = text(
        """
        SELECT
            metric_date,
            tracking_error_5d,
            tracking_error_30d,
            paper_cumulative_pnl,
            replay_pit_cumulative_pnl,
            threshold_breach,
            drift_pct_of_threshold
        FROM public.cmc_drift_metrics
        WHERE config_id = :config_id
          AND metric_date >= CURRENT_DATE - :days
        ORDER BY metric_date ASC
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"config_id": config_id, "days": days})

    if df.empty:
        return df

    df["metric_date"] = pd.to_datetime(df["metric_date"])
    return df


@st.cache_data(ttl=300)
def load_drift_summary(_engine) -> pd.DataFrame:
    """Return the v_drift_summary materialized view with one row per config/asset.

    Columns: config_id, asset_id, signal_type, days_monitored, breach_count,
             avg_tracking_error_5d, max_tracking_error_5d, avg_tracking_error_30d,
             max_tracking_error_30d, avg_absolute_pnl_diff, avg_sharpe_divergence,
             last_metric_date, current_tracking_error_5d
    """
    sql = text(
        """
        SELECT
            config_id,
            asset_id,
            signal_type,
            days_monitored,
            breach_count,
            avg_tracking_error_5d,
            max_tracking_error_5d,
            avg_tracking_error_30d,
            max_tracking_error_30d,
            avg_absolute_pnl_diff,
            avg_sharpe_divergence,
            last_metric_date,
            current_tracking_error_5d
        FROM public.v_drift_summary
        ORDER BY config_id, asset_id
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    return df


@st.cache_data(ttl=300)
def load_executor_configs(_engine) -> pd.DataFrame:
    """Return active executor configs for use in config selector widgets.

    Columns: config_id, config_name, signal_type, is_active
    """
    sql = text(
        """
        SELECT
            config_id,
            config_name,
            signal_type,
            is_active
        FROM public.dim_executor_config
        WHERE is_active = TRUE
        ORDER BY config_id
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    return df
