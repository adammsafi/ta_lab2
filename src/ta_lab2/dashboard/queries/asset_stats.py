"""
Cached query functions for Asset Statistics & Correlation page.

All functions use @st.cache_data(ttl=300) and accept ``_engine`` (underscore-
prefixed) as the first argument so st.cache_data skips hashing the engine.

DB objects queried:
  - cmc_asset_stats       : wide-format rolling stats per (id, ts, tf)
  - cmc_corr_latest       : materialized view, latest correlation per (id_a, id_b, tf, window)
  - dim_assets            : id -> symbol mapping

NOTE: The ``window`` column is a PostgreSQL reserved word.  All raw SQL that
references it must use double-quotes: "window".
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


@st.cache_data(ttl=3600)
def load_asset_symbols(_engine) -> dict[int, str]:
    """Return mapping of asset id -> symbol from dim_assets.

    Long TTL (1 hour) because the asset list changes rarely.
    """
    sql = text("SELECT id, symbol FROM public.dim_assets ORDER BY symbol")
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    if df.empty:
        return {}
    return dict(zip(df["id"], df["symbol"]))


@st.cache_data(ttl=300)
def load_asset_stats_latest(_engine, tf: str = "1D") -> pd.DataFrame:
    """Return the most recent stats row per asset for the given timeframe.

    Uses DISTINCT ON (id) ordered by ts DESC to fetch the latest bar's rolling
    stats for every asset.  Joins dim_assets for symbol name.

    Columns: symbol, id, ts, <all 32 window stat columns>, max_dd_from_ath,
             rf_rate, ingested_at
    """
    sql = text(
        """
        SELECT
            a.symbol,
            s.id,
            s.ts,
            s.mean_ret_30,   s.std_ret_30,   s.sharpe_raw_30,   s.sharpe_ann_30,
            s.skew_30,       s.kurt_fisher_30, s.kurt_pearson_30, s.max_dd_window_30,
            s.mean_ret_60,   s.std_ret_60,   s.sharpe_raw_60,   s.sharpe_ann_60,
            s.skew_60,       s.kurt_fisher_60, s.kurt_pearson_60, s.max_dd_window_60,
            s.mean_ret_90,   s.std_ret_90,   s.sharpe_raw_90,   s.sharpe_ann_90,
            s.skew_90,       s.kurt_fisher_90, s.kurt_pearson_90, s.max_dd_window_90,
            s.mean_ret_252,  s.std_ret_252,  s.sharpe_raw_252,  s.sharpe_ann_252,
            s.skew_252,      s.kurt_fisher_252, s.kurt_pearson_252, s.max_dd_window_252,
            s.max_dd_from_ath,
            s.rf_rate,
            s.ingested_at
        FROM (
            SELECT DISTINCT ON (id) *
            FROM public.cmc_asset_stats
            WHERE tf = :tf
            ORDER BY id, ts DESC
        ) s
        JOIN public.dim_assets a ON a.id = s.id
        ORDER BY a.symbol
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"tf": tf})

    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["ingested_at"] = pd.to_datetime(df["ingested_at"], utc=True)
    return df


@st.cache_data(ttl=300)
def load_corr_latest(_engine, tf: str = "1D", window: int = 90) -> pd.DataFrame:
    """Return latest correlation values per asset pair from the materialized view.

    Queries ``cmc_corr_latest`` (DISTINCT ON per pair/window, already materialized).
    Joins dim_assets twice for both asset symbols.

    Parameters
    ----------
    tf : str
        Timeframe string, e.g. ``"1D"``.
    window : int
        Rolling window size (30, 60, 90, or 252).

    Columns: symbol_a, symbol_b, id_a, id_b, ts, tf, window, pearson_r,
             pearson_p, spearman_r, spearman_p, n_obs
    """
    sql = text(
        """
        SELECT
            a.symbol  AS symbol_a,
            b.symbol  AS symbol_b,
            c.id_a,
            c.id_b,
            c.ts,
            c.tf,
            c."window",
            c.pearson_r,
            c.pearson_p,
            c.spearman_r,
            c.spearman_p,
            c.n_obs
        FROM public.cmc_corr_latest c
        JOIN public.dim_assets a ON a.id = c.id_a
        JOIN public.dim_assets b ON b.id = c.id_b
        WHERE c.tf = :tf
          AND c."window" = :window
        ORDER BY a.symbol, b.symbol
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"tf": tf, "window": window})

    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


@st.cache_data(ttl=300)
def load_asset_stats_timeseries(_engine, asset_id: int, tf: str = "1D") -> pd.DataFrame:
    """Return full time series of rolling stats for a single asset.

    Returns all columns from cmc_asset_stats for the given (id, tf) combination,
    sorted by ts ascending and indexed by ts.

    Columns (index=ts): id, tf, <all 32 window stat columns>, max_dd_from_ath,
                        rf_rate, ingested_at
    """
    sql = text(
        """
        SELECT *
        FROM public.cmc_asset_stats
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
    df = df.set_index("ts")
    return df
