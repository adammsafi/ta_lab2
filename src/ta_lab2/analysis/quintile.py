# -*- coding: utf-8 -*-
"""
Quintile group returns engine for factor monotonicity testing.

Cross-sectional quintile analysis ranks all assets by a factor column into 5
equal-weight buckets at each timestamp, then tracks cumulative forward returns
per bucket. Monotonic Q1 < Q2 < Q3 < Q4 < Q5 return ordering is the
gold-standard test for factor predictive power.

Public API:
    compute_quintile_returns  -- rank assets into quintiles, compute cumulative fwd returns
    build_quintile_returns_chart  -- Plotly figure with 5 colored lines (Q1-Q5)

Usage:
    from ta_lab2.analysis.quintile import compute_quintile_returns, build_quintile_returns_chart

    cumulative, spread = compute_quintile_returns(df, factor_col='rsi_14', forward_horizon=1)
    fig = build_quintile_returns_chart(cumulative, factor_col='rsi_14', horizon=1, long_short_spread=spread)
    fig.write_html('reports/quintile/rsi_14_1D_h1.html')
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go

logger = logging.getLogger(__name__)

# Quintile label order (1=worst factor score, 5=best)
_QUINTILE_LABELS: list[int] = [1, 2, 3, 4, 5]

# Colors per quintile: Q1=red, Q2=orange, Q3=green, Q4=blue, Q5=purple
_QUINTILE_COLORS: dict[int, str] = {
    1: "red",
    2: "orange",
    3: "green",
    4: "blue",
    5: "purple",
}


def compute_quintile_returns(
    features_df: pd.DataFrame,
    factor_col: str,
    forward_horizon: int = 1,
    close_col: str = "close",
    min_assets_per_ts: int = 5,
) -> tuple[pd.DataFrame, pd.Series]:
    """
    Cross-sectional quintile return engine.

    At each timestamp, ranks ALL assets by ``factor_col`` into 5 equal-weight
    quintiles (Q1=bottom 20%, Q5=top 20%). Forward returns per quintile are
    averaged and cumulated over time.

    CRITICAL: This is cross-sectional ranking across all assets at each
    timestamp, NOT a single-asset time-series ranking.

    Parameters
    ----------
    features_df : pd.DataFrame
        DataFrame with columns including ``ts``, ``id``, ``tf`` (optional),
        ``factor_col``, and ``close_col``. Must contain multiple assets.
    factor_col : str
        Column name to rank on (e.g. 'rsi_14', 'ret_arith').
    forward_horizon : int
        Number of bars forward to compute returns. Default 1.
    close_col : str
        Close price column name. Default 'close'.
    min_assets_per_ts : int
        Minimum number of assets with non-null factor values required
        for a timestamp to be included. Default 5.

    Returns
    -------
    tuple[pd.DataFrame, pd.Series]
        - cumulative_df: DataFrame indexed by ts, columns 1..5 (quintile labels).
          Each value is the cumulative return for that quintile bucket
          (starts at 1.0 for the first timestamp included).
        - long_short_spread: Series indexed by ts = cumulative_df[5] - cumulative_df[1].
          Positive spread = Q5 outperforms Q1 (factor is predictive in expected direction).

    Notes
    -----
    Timestamps with fewer than ``min_assets_per_ts`` non-null factor observations
    are dropped before quintile assignment. The last ``forward_horizon`` timestamps
    will have NaN forward returns and are excluded from cumulative return computation.
    """
    if factor_col not in features_df.columns:
        raise ValueError(
            f"Factor column '{factor_col}' not found in features_df. "
            f"Available columns: {sorted(features_df.columns.tolist())}"
        )
    if close_col not in features_df.columns:
        raise ValueError(
            f"Close column '{close_col}' not found in features_df. "
            f"Available columns: {sorted(features_df.columns.tolist())}"
        )
    if "ts" not in features_df.columns:
        raise ValueError("features_df must contain a 'ts' column")
    if "id" not in features_df.columns:
        raise ValueError("features_df must contain an 'id' column")

    df = features_df.copy()

    # Ensure ts is UTC-aware datetime
    if not pd.api.types.is_datetime64_any_dtype(df["ts"]):
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    elif df["ts"].dt.tz is None:
        df["ts"] = df["ts"].dt.tz_localize("UTC")

    # Sort by (ts, id) for deterministic ordering
    df = df.sort_values(["ts", "id"]).reset_index(drop=True)

    # --- Step 1: Compute forward returns per asset ---
    # Sort by (id, ts) for correct per-asset shifting
    df = df.sort_values(["id", "ts"]).reset_index(drop=True)
    df["fwd_ret"] = df.groupby("id")[close_col].transform(
        lambda x: x.shift(-forward_horizon) / x - 1.0
    )

    # Return to (ts, id) ordering for cross-sectional operations
    df = df.sort_values(["ts", "id"]).reset_index(drop=True)

    # --- Step 2: Cross-sectional quintile assignment at each timestamp ---
    # Filter to rows where factor is non-null for ranking
    df_valid = df.dropna(subset=[factor_col]).copy()

    # Count distinct assets per timestamp with valid factor values
    ts_counts = df_valid.groupby("ts")["id"].nunique()
    valid_ts = ts_counts[ts_counts >= min_assets_per_ts].index

    if len(valid_ts) == 0:
        logger.warning(
            "compute_quintile_returns: no timestamps have >= %d assets with non-null '%s' values",
            min_assets_per_ts,
            factor_col,
        )
        empty_df = pd.DataFrame(columns=_QUINTILE_LABELS)
        empty_spread = pd.Series(dtype=float, name="long_short_spread")
        return empty_df, empty_spread

    df_valid = df_valid[df_valid["ts"].isin(valid_ts)].copy()

    logger.debug(
        "compute_quintile_returns: %d valid timestamps (>= %d assets), factor='%s'",
        len(valid_ts),
        min_assets_per_ts,
        factor_col,
    )

    # Cross-sectional quintile ranking using pd.qcut on rank (handles ties via 'first')
    def _assign_quintile(x: pd.Series) -> pd.Series:
        """Assign quintile labels 1-5 within a cross-section of assets."""
        n = x.notna().sum()
        if n < min_assets_per_ts:
            return pd.Series(np.nan, index=x.index)
        try:
            ranked = x.rank(method="first")
            return pd.qcut(ranked, 5, labels=_QUINTILE_LABELS).astype(float)
        except Exception as e:
            logger.debug("_assign_quintile failed for ts group: %s", e)
            return pd.Series(np.nan, index=x.index)

    df_valid["quintile"] = df_valid.groupby("ts")[factor_col].transform(
        _assign_quintile
    )

    # Drop rows where quintile assignment failed (edge cases)
    df_valid = df_valid.dropna(subset=["quintile", "fwd_ret"])

    if df_valid.empty:
        logger.warning(
            "compute_quintile_returns: no valid quintile+fwd_ret rows after filtering"
        )
        empty_df = pd.DataFrame(columns=_QUINTILE_LABELS)
        empty_spread = pd.Series(dtype=float, name="long_short_spread")
        return empty_df, empty_spread

    df_valid["quintile"] = df_valid["quintile"].astype(int)

    # --- Step 3: Average forward return per (ts, quintile) ---
    quintile_returns = (
        df_valid.groupby(["ts", "quintile"])["fwd_ret"].mean().unstack("quintile")
    )

    # Ensure all 5 quintile columns are present (fill missing with NaN)
    for q in _QUINTILE_LABELS:
        if q not in quintile_returns.columns:
            quintile_returns[q] = np.nan
    quintile_returns = quintile_returns[_QUINTILE_LABELS]

    # --- Step 4: Cumulative returns per quintile ---
    # Drop timestamps where ANY quintile has NaN forward returns
    quintile_returns_clean = quintile_returns.dropna()

    if quintile_returns_clean.empty:
        logger.warning(
            "compute_quintile_returns: quintile_returns_clean is empty after dropna()"
        )
        empty_df = pd.DataFrame(columns=_QUINTILE_LABELS)
        empty_spread = pd.Series(dtype=float, name="long_short_spread")
        return empty_df, empty_spread

    cumulative_df = (1.0 + quintile_returns_clean).cumprod()

    logger.info(
        "compute_quintile_returns: %d timestamps, cumulative returns: %s",
        len(cumulative_df),
        {
            q: f"{cumulative_df[q].iloc[-1]:.4f}"
            for q in _QUINTILE_LABELS
            if q in cumulative_df.columns
        },
    )

    # --- Step 5: Long-short spread (Q5 - Q1) ---
    long_short_spread = cumulative_df[5] - cumulative_df[1]
    long_short_spread.name = "long_short_spread"

    return cumulative_df, long_short_spread


def build_quintile_returns_chart(
    quintile_cum_returns: pd.DataFrame,
    factor_col: str,
    horizon: int,
    long_short_spread: Optional[pd.Series] = None,
) -> go.Figure:
    """
    Build a Plotly figure showing cumulative returns per quintile over time.

    Creates a line chart with 5 colored lines (Q1-Q5) and an optional
    dashed black line for the Q5-Q1 long-short spread.

    Parameters
    ----------
    quintile_cum_returns : pd.DataFrame
        Cumulative returns DataFrame with columns 1..5 (quintile labels),
        indexed by ts. Output from compute_quintile_returns()[0].
    factor_col : str
        Factor column name (used in chart title).
    horizon : int
        Forward return horizon in bars (used in chart title).
    long_short_spread : pd.Series, optional
        Q5-Q1 spread series indexed by ts. If provided, adds a dashed
        black line. Output from compute_quintile_returns()[1].

    Returns
    -------
    plotly.graph_objects.Figure
        Interactive Plotly figure with quintile return lines.
    """
    fig = go.Figure()

    # Q1-Q5 lines
    quintile_names = {
        1: "Q1 (Bottom 20%)",
        2: "Q2",
        3: "Q3",
        4: "Q4",
        5: "Q5 (Top 20%)",
    }

    for q in _QUINTILE_LABELS:
        if q not in quintile_cum_returns.columns:
            logger.debug(
                "build_quintile_returns_chart: quintile %d missing — skipping", q
            )
            continue

        series = quintile_cum_returns[q]
        fig.add_trace(
            go.Scatter(
                x=series.index,
                y=series.values,
                mode="lines",
                name=quintile_names.get(q, f"Q{q}"),
                line=dict(color=_QUINTILE_COLORS[q], width=2),
            )
        )

    # Optional: Q5-Q1 long-short spread
    if long_short_spread is not None and not long_short_spread.empty:
        fig.add_trace(
            go.Scatter(
                x=long_short_spread.index,
                y=long_short_spread.values,
                mode="lines",
                name="Q5-Q1 Spread",
                line=dict(color="black", width=2, dash="dash"),
            )
        )

    # Zero reference line
    fig.add_hline(y=1.0, line_dash="dot", line_color="gray", opacity=0.4)

    fig.update_layout(
        title=f"Quintile Returns: {factor_col} (horizon={horizon}d)",
        xaxis_title="Date",
        yaxis_title="Cumulative Return (1.0 = starting value)",
        legend=dict(orientation="v", x=1.02, y=1.0),
        hovermode="x unified",
    )

    return fig
