"""
Cached query functions for Executor Status page.

All functions use @st.cache_data(ttl=N) and accept ``_engine`` (underscore-
prefixed) as the first argument so st.cache_data skips hashing the engine.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


@st.cache_data(ttl=120)
def load_executor_run_log(_engine, limit: int = 50) -> pd.DataFrame:
    """Return the most recent executor run log entries.

    Columns: run_id, started_at, finished_at, config_ids, dry_run,
             replay_historical, status, signals_read, orders_generated,
             fills_processed, skipped_no_delta, error_message

    Parameters
    ----------
    limit : int
        Maximum number of rows to return. Default 50.
    """
    sql = text(
        """
        SELECT
            run_id,
            started_at,
            finished_at,
            config_ids,
            dry_run,
            replay_historical,
            status,
            signals_read,
            orders_generated,
            fills_processed,
            skipped_no_delta,
            error_message
        FROM public.executor_run_log
        ORDER BY started_at DESC
        LIMIT :limit
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"limit": limit})

    if df.empty:
        return df

    df["started_at"] = pd.to_datetime(df["started_at"], utc=True)
    df["finished_at"] = pd.to_datetime(df["finished_at"], utc=True)
    return df


@st.cache_data(ttl=300)
def load_executor_config(_engine) -> pd.DataFrame:
    """Return all executor configs with their operational parameters.

    Columns: config_id, config_name, signal_type, signal_id, is_active,
             exchange, environment, sizing_mode, position_fraction,
             max_position_fraction, fill_price_mode, slippage_mode,
             slippage_base_bps, cadence_hours
    """
    sql = text(
        """
        SELECT
            config_id,
            config_name,
            signal_type,
            signal_id,
            is_active,
            exchange,
            environment,
            sizing_mode,
            position_fraction,
            max_position_fraction,
            fill_price_mode,
            slippage_mode,
            slippage_base_bps,
            cadence_hours
        FROM public.dim_executor_config
        ORDER BY config_id
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    return df
