"""
Cached query functions for Feature Experiments page.

All functions use @st.cache_data and accept ``_engine`` (underscore-prefixed)
as the first argument so st.cache_data skips hashing the engine.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import text


@st.cache_data(ttl=300)
def load_experiment_results(_engine, feature_name: str | None = None) -> pd.DataFrame:
    """Return experiment rows from feature_experiments.

    If feature_name is None, load all rows. Otherwise filter by feature_name.

    Columns: feature_name, asset_id, tf, horizon, return_type, ic,
             ic_p_value, ic_p_value_bh, ic_ir, n_obs, wall_clock_seconds,
             train_start, train_end, computed_at
    """
    if feature_name is None:
        sql = text(
            """
            SELECT
                feature_name,
                asset_id,
                tf,
                horizon,
                return_type,
                ic,
                ic_p_value,
                ic_p_value_bh,
                ic_ir,
                n_obs,
                wall_clock_seconds,
                train_start,
                train_end,
                computed_at
            FROM public.feature_experiments
            ORDER BY feature_name, asset_id, horizon
            """
        )
        with _engine.connect() as conn:
            df = pd.read_sql(sql, conn)
    else:
        sql = text(
            """
            SELECT
                feature_name,
                asset_id,
                tf,
                horizon,
                return_type,
                ic,
                ic_p_value,
                ic_p_value_bh,
                ic_ir,
                n_obs,
                wall_clock_seconds,
                train_start,
                train_end,
                computed_at
            FROM public.feature_experiments
            WHERE feature_name = :feature_name
            ORDER BY feature_name, asset_id, horizon
            """
        )
        with _engine.connect() as conn:
            df = pd.read_sql(sql, conn, params={"feature_name": feature_name})

    if df.empty:
        return df

    for col in ("train_start", "train_end", "computed_at"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], utc=True)
    return df


@st.cache_data(ttl=300)
def load_experiment_feature_names(_engine) -> list[str]:
    """Return DISTINCT feature_name from feature_experiments ORDER BY feature_name."""
    sql = text(
        """
        SELECT DISTINCT feature_name
        FROM public.feature_experiments
        ORDER BY feature_name
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)
    if df.empty:
        return []
    return df["feature_name"].tolist()


@st.cache_data(ttl=300)
def load_experiment_summary(_engine) -> pd.DataFrame:
    """Aggregate experiment summary per feature_name.

    Columns: feature_name, n_experiments, n_significant, mean_abs_ic, latest_run.
    Ordered by n_significant DESC, mean_abs_ic DESC.
    """
    sql = text(
        """
        SELECT
            feature_name,
            COUNT(*) AS n_experiments,
            COUNT(*) FILTER (WHERE ic_p_value_bh < 0.05) AS n_significant,
            AVG(ABS(ic)) AS mean_abs_ic,
            MAX(computed_at) AS latest_run
        FROM public.feature_experiments
        GROUP BY feature_name
        ORDER BY n_significant DESC, mean_abs_ic DESC
        """
    )
    with _engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    if df.empty:
        return df

    if "latest_run" in df.columns:
        df["latest_run"] = pd.to_datetime(df["latest_run"], utc=True)
    return df
