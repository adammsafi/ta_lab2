"""Cached query functions for Portfolio Allocation page.

All functions use @st.cache_data(ttl=N) and accept ``_engine`` (underscore-
prefixed) as the first argument so st.cache_data skips hashing the engine.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


@st.cache_data(ttl=300)
def load_available_optimizers(_engine) -> list[str]:
    """Return distinct optimizer names from portfolio_allocations.

    Returns empty list if the table has no rows.
    """
    sql = text(
        "SELECT DISTINCT optimizer FROM public.portfolio_allocations ORDER BY optimizer"
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    if df.empty:
        return []
    return df["optimizer"].tolist()


@st.cache_data(ttl=300)
def load_latest_allocations(_engine, optimizer: str = "hrp") -> pd.DataFrame:
    """Return the most recent allocation per asset for a given optimizer.

    Uses DISTINCT ON (asset_id) ordered by ts DESC to pick the latest row
    per asset.  Joins dim_assets (via cmc_da_info fallback) for ticker symbol.

    Columns: symbol, asset_id, ts, optimizer, weight, final_weight,
             regime_label, condition_number
    """
    sql = text(
        """
        SELECT
            COALESCE(ci.symbol, a.symbol) AS symbol,
            pa.asset_id,
            pa.ts,
            pa.optimizer,
            CAST(pa.weight AS FLOAT)        AS weight,
            CAST(pa.final_weight AS FLOAT)  AS final_weight,
            pa.regime_label,
            CAST(pa.condition_number AS FLOAT) AS condition_number
        FROM (
            SELECT DISTINCT ON (asset_id) *
            FROM public.portfolio_allocations
            WHERE optimizer = :optimizer
            ORDER BY asset_id, ts DESC
        ) pa
        JOIN public.dim_assets a ON a.id = pa.asset_id
        LEFT JOIN public.cmc_da_info ci ON ci.id = pa.asset_id
        ORDER BY pa.weight DESC
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"optimizer": optimizer})

    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


@st.cache_data(ttl=300)
def load_allocation_history(
    _engine, optimizer: str = "hrp", days: int = 30
) -> pd.DataFrame:
    """Return allocation weight history pivoted by symbol for area charts.

    Returns a DataFrame with DatetimeIndex (ts) and one column per asset symbol,
    values are raw weights (0-1 scale).  Returns empty DataFrame if no rows.
    """
    sql = text(
        """
        SELECT
            COALESCE(ci.symbol, a.symbol) AS symbol,
            pa.ts,
            CAST(pa.weight AS FLOAT) AS weight
        FROM public.portfolio_allocations pa
        JOIN public.dim_assets a ON a.id = pa.asset_id
        LEFT JOIN public.cmc_da_info ci ON ci.id = pa.asset_id
        WHERE pa.optimizer = :optimizer
          AND pa.ts >= NOW() - (:days * INTERVAL '1 day')
        ORDER BY pa.ts, COALESCE(ci.symbol, a.symbol)
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"optimizer": optimizer, "days": days})

    if df.empty:
        return pd.DataFrame()

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    pivoted = df.pivot_table(index="ts", columns="symbol", values="weight")
    pivoted = pivoted.sort_index()
    return pivoted
