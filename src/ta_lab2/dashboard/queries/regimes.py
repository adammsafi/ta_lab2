"""
Cached query functions for Regime Heatmap page.

All functions use @st.cache_data and accept ``_engine`` (underscore-prefixed)
as the first argument so st.cache_data skips hashing the engine.

IMPORTANT: The ``regimes`` table has NO ``trend_state`` column.
Trend state is derived via ``split_part(l2_label, '-', 1)`` in SQL.

NOTE: ``regime_comovement`` contains per-asset EMA indicator comovement data
(21 rows: 7 assets x 3 EMA pairs).  It is NOT cross-asset correlation.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


@st.cache_data(ttl=900)
def load_regime_all_assets(
    _engine,
    tf: str = "1D",
    days_back: int = 365,
) -> pd.DataFrame:
    """Return regime states for all assets for the cross-asset heatmap.

    CRITICAL: trend_state is derived via split_part(l2_label, '-', 1).
    The regimes table has NO trend_state column.

    Columns: id, symbol, ts, trend_state, vol_state, regime_key
    """
    sql = text(
        """
        SELECT r.id,
               COALESCE(ci.symbol, da.symbol) AS symbol,
               r.ts,
               split_part(r.l2_label, '-', 1) AS trend_state,
               split_part(r.l2_label, '-', 2) AS vol_state,
               r.regime_key
        FROM public.regimes r
        JOIN public.dim_assets da ON da.id = r.id
        LEFT JOIN public.cmc_da_info ci ON ci.id = r.id
        WHERE r.tf = :tf
          AND r.ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY r.id, r.ts
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"tf": tf, "days_back": days_back})
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


@st.cache_data(ttl=900)
def load_regime_stats_summary(
    _engine,
    tf: str = "1D",
) -> pd.DataFrame:
    """Return per-asset regime stats summary.

    NOTE: avg_ret_1d is NULL for all rows in current data.
    Still included in output but should not be relied upon.

    Columns: id, symbol, regime_key, n_bars, pct_of_history, avg_ret_1d
    """
    sql = text(
        """
        SELECT rs.id,
               COALESCE(ci.symbol, da.symbol) AS symbol,
               rs.regime_key,
               rs.n_bars,
               rs.pct_of_history,
               rs.avg_ret_1d
        FROM public.regime_stats rs
        JOIN public.dim_assets da ON da.id = rs.id
        LEFT JOIN public.cmc_da_info ci ON ci.id = rs.id
        WHERE rs.tf = :tf
        ORDER BY rs.id, rs.n_bars DESC
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"tf": tf})
    return df


@st.cache_data(ttl=900)
def load_regime_flips_recent(
    _engine,
    tf: str = "1D",
    limit: int = 50,
) -> pd.DataFrame:
    """Return most recent regime flips across all assets.

    Columns: id, symbol, ts, old_regime, new_regime, duration_bars
    """
    sql = text(
        """
        SELECT rf.id,
               COALESCE(ci.symbol, da.symbol) AS symbol,
               rf.ts,
               rf.old_regime,
               rf.new_regime,
               rf.duration_bars
        FROM public.regime_flips rf
        JOIN public.dim_assets da ON da.id = rf.id
        LEFT JOIN public.cmc_da_info ci ON ci.id = rf.id
        WHERE rf.tf = :tf
        ORDER BY rf.ts DESC
        LIMIT :limit
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"tf": tf, "limit": limit})
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


@st.cache_data(ttl=900)
def load_regime_comovement(
    _engine,
    tf: str = "1D",
) -> pd.DataFrame:
    """Return per-asset EMA comovement data.

    WARNING: Only 21 rows (7 assets x 3 EMA pairs).
    This is NOT cross-asset correlation.  It tracks how EMAs within a
    single asset co-move.

    Columns: id, symbol, ema_a, ema_b, correlation, sign_agree_rate,
             best_lead_lag, n_obs
    """
    sql = text(
        """
        SELECT rc.id,
               COALESCE(ci.symbol, da.symbol) AS symbol,
               rc.ema_a,
               rc.ema_b,
               rc.correlation,
               rc.sign_agree_rate,
               rc.best_lead_lag,
               rc.n_obs
        FROM public.regime_comovement rc
        JOIN public.dim_assets da ON da.id = rc.id
        LEFT JOIN public.cmc_da_info ci ON ci.id = rc.id
        WHERE rc.tf = :tf
        ORDER BY rc.id, rc.ema_a, rc.ema_b
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"tf": tf})
    return df
