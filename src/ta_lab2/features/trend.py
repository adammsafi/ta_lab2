# src/ta_lab2/features/trend.py
"""
Trend labeling utilities

Provides slope-based or flat-zone trend classification on arbitrary numeric series.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def compute_trend_labels(
    df: pd.DataFrame,
    price_col: str = "close",
    window: int = 21,
    mode: str = "flat_zone",
    flat_thresh: float = 0.0,
    label_col: str | None = None,
) -> pd.DataFrame:
    """
    Compute trend labels for a given price series.

    Parameters
    ----------
    df : pd.DataFrame
        Input DataFrame containing at least one price column.
    price_col : str, default "close"
        Column used to compute rolling slope / trend.
    window : int, default 21
        Rolling lookback window for slope calculation.
    mode : str, default "flat_zone"
        Labeling strategy: "binary", "three_state", or "flat_zone".
    flat_thresh : float, default 0.0
        Flat-zone threshold (absolute slope). If 0, uses 20th percentile of |slope|.
    label_col : str or None
        If given, output labels are stored under this name.
        If None, uses f"trend_{mode}_{window}".

    Returns
    -------
    df : pd.DataFrame
        Original DataFrame with an added label column.
    """
    s = df[price_col].astype(float)
    if len(s) < window:
        df[label_col or f"trend_{mode}_{window}"] = np.nan
        return df

    # Rolling slope via linear regression on index vs price
    x = np.arange(window)
    denom = (x - x.mean()).var() * window
    cov = s.rolling(window).apply(lambda v: np.dot(v - v.mean(), x - x.mean()) / denom, raw=False)
    slope = cov * window  # approximate slope per index unit
    df[f"{price_col}_slope_{window}"] = slope

    # Determine threshold if flat_zone and threshold=0
    if mode == "flat_zone" and flat_thresh == 0:
        flat_thresh = np.nanpercentile(np.abs(slope.dropna()), 20) or 0.0

    if mode == "binary":
        label = np.where(slope > 0, 1, -1)
    elif mode == "three_state":
        pct = np.nanpercentile(np.abs(slope.dropna()), [33, 67])
        lo, hi = pct[0], pct[1]
        label = np.where(
            slope.abs() < lo, 0,
            np.where(slope > 0, 1, -1)
        )
    elif mode == "flat_zone":
        label = np.where(np.abs(slope) < flat_thresh, 0, np.sign(slope))
    else:
        raise ValueError(f"Unknown mode '{mode}'")

    df[label_col or f"trend_{mode}_{window}"] = label.astype("Int8")
    return df
