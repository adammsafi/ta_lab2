"""
Cached query functions for AMA/EMA Inspector page.

All functions use @st.cache_data and accept ``_engine`` (underscore-prefixed)
as the first argument so st.cache_data skips hashing the engine.

CRITICAL notes:
- ama_multi_tf_u is 170M rows -- always filter by indicator, asset, tf, and days_back
- er is NULL for DEMA, HMA, TEMA -- only KAMA computes efficiency ratio
- ema_multi_tf_u has NO d1/d2 columns -- only ama_multi_tf_u has d1, d2, d1_roll, d2_roll
- dim_ama_params has 18 rows: DEMA x5 + HMA x5 + KAMA x3 + TEMA x5
- ema_multi_tf_u column is `ema` (NOT `ema_value`)
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


@st.cache_data(ttl=3600)
def load_ama_params_catalogue(_engine) -> pd.DataFrame:
    """Return all AMA indicator/param combos for UI selector.

    TTL=3600 (dimension data, rarely changes). 18 rows total.

    Columns: indicator, params_hash, label, params_json
    """
    sql = text(
        """
        SELECT indicator, params_hash, label, params_json
        FROM public.dim_ama_params
        ORDER BY indicator, label
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    return df


@st.cache_data(ttl=300)
def load_ama_curves(
    _engine,
    asset_id: int,
    tf: str = "1D",
    indicator: str = "KAMA",
    days_back: int = 365,
) -> pd.DataFrame:
    """Return AMA curves with human-readable labels from dim_ama_params.

    Always filters by indicator, alignment_source='multi_tf', and roll=false.
    The er column is NULL for DEMA/HMA/TEMA -- only KAMA computes efficiency ratio.

    Columns: ts (UTC datetime), label, indicator, ama, d1, d2, d1_roll, d2_roll, er, roll
    """
    sql = text(
        """
        SELECT a.ts, p.label, a.indicator, a.ama, a.d1, a.d2,
               a.d1_roll, a.d2_roll, a.er, a.roll
        FROM public.ama_multi_tf_u a
        JOIN public.dim_ama_params p
          ON p.params_hash = a.params_hash AND p.indicator = a.indicator
        WHERE a.id = :id
          AND a.tf = :tf
          AND a.indicator = :indicator
          AND a.alignment_source = 'multi_tf'
          AND a.roll = false
          AND a.ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY a.ts, p.label
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={
                "id": asset_id,
                "tf": tf,
                "indicator": indicator,
                "days_back": days_back,
            },
        )

    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


@st.cache_data(ttl=300)
def load_ema_for_comparison(
    _engine,
    asset_id: int,
    tf: str = "1D",
    periods: list[int] | None = None,
    days_back: int = 365,
) -> pd.DataFrame:
    """Return fixed EMA values for AMA vs EMA comparison.

    alignment_source='multi_tf' is canonical. EMA column is `ema` (NOT `ema_value`).

    Columns: ts (UTC datetime), period (int), ema (float)

    Default periods: [9, 21, 50, 200].
    """
    if periods is None:
        periods = [9, 21, 50, 200]

    sql = text(
        """
        SELECT ts, period, ema
        FROM public.ema_multi_tf_u
        WHERE id = :id
          AND tf = :tf
          AND alignment_source = 'multi_tf'
          AND period = ANY(:periods)
          AND ts >= NOW() - (:days_back || ' days')::interval
        ORDER BY period, ts
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(
            sql,
            conn,
            params={
                "id": asset_id,
                "tf": tf,
                "periods": periods,
                "days_back": days_back,
            },
        )

    if df.empty:
        return df

    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df
