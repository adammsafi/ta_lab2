"""
Cached query functions for Hyperliquid Perps page.

All functions use @st.cache_data and accept ``_engine`` (underscore-prefixed)
as the first argument so st.cache_data skips hashing the engine.

CRITICAL:
- All SQL uses ``hyperliquid.`` schema prefix (cross-schema queries).
- ``hyperliquid.hl_assets.asset_id`` is NOT the same as ``public.dim_assets.id``.
- OI time series uses ``hl_open_interest`` (82K rows), NOT ``hl_oi_snapshots`` (3 timestamps).
- Candles use ``interval='1d'`` only -- hourly data is sparse (3 days only).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


@st.cache_data(ttl=3600)
def load_hl_perp_list(_engine) -> pd.DataFrame:
    """Return all Hyperliquid perp assets ordered by symbol.

    TTL=3600 -- dimension data, rarely changes.

    Columns: asset_id, symbol
    """
    sql = text("""
        SELECT asset_id, symbol
        FROM hyperliquid.hl_assets
        WHERE asset_type = 'perp'
        ORDER BY symbol
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    return df


@st.cache_data(ttl=900)
def load_hl_top_perps(_engine, limit: int = 15) -> pd.DataFrame:
    """Return top Hyperliquid perps by 24h notional volume.

    Columns: asset_id, symbol, day_ntl_vlm, funding, open_interest, mark_px,
             oracle_px, premium, max_leverage
    """
    sql = text("""
        SELECT asset_id, symbol, day_ntl_vlm, funding, open_interest, mark_px,
               oracle_px, premium, max_leverage
        FROM hyperliquid.hl_assets
        WHERE asset_type = 'perp'
          AND day_ntl_vlm IS NOT NULL
        ORDER BY day_ntl_vlm DESC NULLS LAST
        LIMIT :limit
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"limit": limit})
    return df


@st.cache_data(ttl=900)
def load_hl_funding_history(
    _engine, asset_ids: list[int], days_back: int = 30
) -> pd.DataFrame:
    """Return funding rate time series for selected Hyperliquid perp assets.

    Funding is 8-hourly (~3 rows/day). 30 days ≈ 90 rows per asset.

    Columns: asset_id, symbol, ts (UTC), funding_rate, premium
    """
    sql = text("""
        SELECT f.asset_id, a.symbol, f.ts, f.funding_rate, f.premium
        FROM hyperliquid.hl_funding_rates f
        JOIN hyperliquid.hl_assets a ON a.asset_id = f.asset_id
        WHERE f.asset_id = ANY(:asset_ids)
          AND f.ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY f.asset_id, f.ts
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(
            sql, conn, params={"asset_ids": asset_ids, "days_back": days_back}
        )
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


@st.cache_data(ttl=900)
def load_hl_funding_heatmap(
    _engine, days_back: int = 30, top_n: int = 20
) -> pd.DataFrame:
    """Return daily average funding rate per asset for heatmap pivot.

    Returns top-N perps by volume ranked by day_ntl_vlm. Pivot in the page:
    rows=symbol, columns=date, values=avg_funding_rate.

    Columns: asset_id, symbol, date, avg_funding_rate
    """
    sql = text("""
        SELECT f.asset_id, a.symbol,
               DATE(f.ts AT TIME ZONE 'UTC') AS date,
               AVG(f.funding_rate) AS avg_funding_rate
        FROM hyperliquid.hl_funding_rates f
        JOIN hyperliquid.hl_assets a ON a.asset_id = f.asset_id
        WHERE f.ts >= NOW() - (:days_back || ' days')::interval
          AND a.asset_type = 'perp'
          AND a.day_ntl_vlm IS NOT NULL
          AND a.asset_id = ANY(
              SELECT asset_id FROM hyperliquid.hl_assets
              WHERE asset_type = 'perp'
              ORDER BY day_ntl_vlm DESC NULLS LAST
              LIMIT :top_n
          )
        GROUP BY f.asset_id, a.symbol, DATE(f.ts AT TIME ZONE 'UTC')
        ORDER BY MAX(a.day_ntl_vlm) DESC, date
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"days_back": days_back, "top_n": top_n})
    return df


@st.cache_data(ttl=900)
def load_hl_candles(_engine, asset_id: int, days_back: int = 90) -> pd.DataFrame:
    """Return daily OHLCV candles for one Hyperliquid perp asset.

    IMPORTANT: Only uses interval='1d'. Hourly data covers only ~3 days
    for most assets and is too sparse for a meaningful chart.

    Columns: asset_id, symbol, ts (UTC), open, high, low, close, volume, open_oi
    """
    sql = text("""
        SELECT c.asset_id, a.symbol, c.ts, c.open, c.high, c.low, c.close,
               c.volume, c.open_oi
        FROM hyperliquid.hl_candles c
        JOIN hyperliquid.hl_assets a ON a.asset_id = c.asset_id
        WHERE c.asset_id = :asset_id
          AND c.interval = '1d'
          AND c.ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY c.ts
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(
            sql, conn, params={"asset_id": asset_id, "days_back": days_back}
        )
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


@st.cache_data(ttl=900)
def load_hl_oi_timeseries(_engine, asset_id: int, days_back: int = 90) -> pd.DataFrame:
    """Return daily OI time series for one Hyperliquid perp asset.

    Uses ``hl_open_interest`` (82K rows, Coinalyze source) -- NOT
    ``hl_oi_snapshots`` which has only 3 point-in-time timestamps.

    Columns: asset_id, symbol, ts (UTC), oi_open, oi_high, oi_low, oi_close
    """
    sql = text("""
        SELECT oi.asset_id, a.symbol, oi.ts,
               oi.open AS oi_open, oi.high AS oi_high,
               oi.low AS oi_low, oi.close AS oi_close
        FROM hyperliquid.hl_open_interest oi
        JOIN hyperliquid.hl_assets a ON a.asset_id = oi.asset_id
        WHERE oi.asset_id = :asset_id
          AND oi.ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY oi.ts
    """)
    with _engine.connect() as conn:
        df = pd.read_sql(
            sql, conn, params={"asset_id": asset_id, "days_back": days_back}
        )
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
