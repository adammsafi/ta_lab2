"""
Cached query functions for Research Explorer page.

All functions use @st.cache_data and accept ``_engine`` (underscore-prefixed)
as the first argument so st.cache_data skips hashing the engine.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


@st.cache_data(ttl=3600)
def load_asset_list(_engine) -> pd.DataFrame:
    """Return all assets ordered by symbol.

    Joins cmc_da_info for proper ticker symbols (dim_assets.symbol stores CMC
    IDs like '1' for Bitcoin).  Falls back to dim_assets.symbol for non-CMC
    assets (e.g. AAPL, HYPE).

    Columns: id, symbol
    """
    sql = text(
        """
        SELECT da.id,
               COALESCE(ci.symbol, da.symbol) AS symbol
        FROM public.dim_assets da
        LEFT JOIN public.cmc_da_info ci ON ci.id = da.id
        ORDER BY COALESCE(ci.symbol, da.symbol)
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    return df


@st.cache_data(ttl=3600)
def load_tf_list(_engine) -> list[str]:
    """Return all timeframe strings ordered by tf_days_nominal.

    CRITICAL: uses tf_days_nominal (NOT tf_days) for ordering.
    """
    sql = text("SELECT tf FROM public.dim_timeframe ORDER BY tf_days_nominal")
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    if df.empty:
        return []
    return df["tf"].tolist()


@st.cache_data(ttl=300)
def load_ic_results(_engine, asset_id: int, tf: str) -> pd.DataFrame:
    """Return IC results for a given asset and timeframe.

    Columns: feature, horizon, return_type, regime_col, regime_label,
             ic, ic_p_value, ic_t_stat, ic_ir, turnover, n_obs, computed_at
    """
    sql = text(
        """
        SELECT
            feature,
            horizon,
            return_type,
            regime_col,
            regime_label,
            ic,
            ic_p_value,
            ic_t_stat,
            ic_ir,
            turnover,
            n_obs,
            computed_at
        FROM public.ic_results
        WHERE asset_id = :id
          AND tf = :tf
        ORDER BY feature, horizon, return_type
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf})

    if df.empty:
        return df

    if "computed_at" in df.columns:
        df["computed_at"] = pd.to_datetime(df["computed_at"], utc=True)
    return df


@st.cache_data(ttl=600)
def load_feature_names(_engine, asset_id: int, tf: str) -> list[str]:
    """Return distinct feature names for a given asset and timeframe."""
    sql = text(
        """
        SELECT DISTINCT feature
        FROM public.ic_results
        WHERE asset_id = :id
          AND tf = :tf
        ORDER BY feature
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf})
    if df.empty:
        return []
    return df["feature"].tolist()


@st.cache_data(ttl=300)
def load_feature_close_series(
    _engine, asset_id: int, tf: str, feature_col: str
) -> tuple[pd.Series, pd.Series] | None:
    """Load a feature column and close price as paired Series for rolling IC.

    Parameters
    ----------
    _engine :
        SQLAlchemy engine (underscore-prefixed so st.cache_data skips hashing it).
    asset_id : int
        Asset ID to query.
    tf : str
        Timeframe string (e.g. '1D').
    feature_col : str
        Column name from features to load (e.g. 'rsi_14').

    Returns
    -------
    tuple[pd.Series, pd.Series] | None
        (feature_series, close_series) both indexed by UTC timestamp, or None
        if the feature column is invalid or not found.
    """
    if not all(c.isalnum() or c == "_" for c in feature_col) or len(feature_col) == 0:
        return None
    sql = text(
        f"SELECT ts, {feature_col}, close FROM public.features "
        f"WHERE id = :id AND tf = :tf ORDER BY ts"
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf})
    if df.empty or feature_col not in df.columns:
        return None
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    return df[feature_col].dropna(), df["close"].dropna()


@st.cache_data(ttl=300)
def load_regimes(_engine, asset_id: int, tf: str) -> pd.DataFrame:
    """Return regime rows for a given asset and timeframe.

    Columns: ts, l2_label, trend_state, vol_state

    CRITICAL: trend_state and vol_state are derived from l2_label via
    split_part -- regimes has NO such columns natively.
    """
    sql = text(
        """
        SELECT
            ts,
            l2_label,
            split_part(l2_label, '-', 1) AS trend_state,
            split_part(l2_label, '-', 2) AS vol_state
        FROM public.regimes
        WHERE id = :id
          AND tf = :tf
        ORDER BY ts
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf})

    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


@st.cache_data(ttl=300)
def load_close_prices(_engine, asset_id: int, tf: str) -> pd.Series:
    """Return close prices as a Series indexed by UTC timestamp.

    Returns: pd.Series[float] with DatetimeIndex (UTC)
    """
    sql = text(
        """
        SELECT ts, close
        FROM public.features
        WHERE id = :id
          AND tf = :tf
        ORDER BY ts
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf})

    if df.empty:
        return pd.Series(dtype=float, name="close")

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    return df["close"]


@st.cache_data(ttl=300)
def load_ohlcv_features(_engine, asset_id: int, tf: str) -> pd.DataFrame:
    """Return OHLCV + RSI-14 data for candlestick chart rendering.

    Columns: ts (UTC datetime), open, high, low, close, volume, rsi_14

    The rsi_14 column enables the RSI subplot in build_candlestick_chart.
    Returns an empty DataFrame if no rows are found.
    """
    sql = text(
        """
        SELECT ts, open, high, low, close, volume, rsi_14
        FROM public.features
        WHERE id = :id
          AND tf = :tf
        ORDER BY ts
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"id": asset_id, "tf": tf})

    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


@st.cache_data(ttl=300)
def load_ema_overlays(
    _engine,
    asset_id: int,
    tf: str,
    periods: list[int] | None = None,
) -> pd.DataFrame:
    """Return EMA values for chart overlay rendering.

    Columns: ts (UTC datetime), period (int), ema_value (float)

    Each unique period gets its own overlay line in build_candlestick_chart.
    If periods is None, all available periods are returned.
    Returns an empty DataFrame if no rows are found.

    CRITICAL: ema_multi_tf_u uses alignment_source='multi_tf' as the
    canonical source. The EMA value column is `ema` -- aliased here as
    ema_value to match build_candlestick_chart's expected column name.
    """
    base_sql = (
        "SELECT ts, period, ema AS ema_value"
        " FROM public.ema_multi_tf_u"
        " WHERE id = :id"
        "   AND tf = :tf"
        "   AND alignment_source = 'multi_tf'"
    )
    params: dict = {"id": asset_id, "tf": tf}

    if periods:
        base_sql += " AND period = ANY(:periods)"
        params["periods"] = periods

    base_sql += " ORDER BY period, ts"

    sql = text(base_sql)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
