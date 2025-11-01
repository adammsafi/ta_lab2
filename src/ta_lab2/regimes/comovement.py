# ta_lab2/regimes/comovement.py
from __future__ import annotations
from typing import Optional, Dict, Iterable
import numpy as np
import pandas as pd


def _ensure_sorted(df: pd.DataFrame, on: str) -> pd.DataFrame:
    if on not in df.columns:
        raise KeyError(f"Column '{on}' not found in DataFrame.")
    if not df[on].is_monotonic_increasing:
        return df.sort_values(on).reset_index(drop=True)
    return df


def build_alignment_frame(
    low_df: pd.DataFrame,
    high_df: pd.DataFrame,
    *,
    on: str = "date",
    low_cols: Optional[Iterable[str]] = None,
    high_cols: Optional[Iterable[str]] = None,
    suffix_low: str = "",
    suffix_high: str = "_w",
    direction: str = "backward",
) -> pd.DataFrame:
    """
    Merge-asof align low timeframe rows with the most recent high timeframe row.

    low_df:  typically daily/enriched data
    high_df: typically weekly/monthly enriched data
    on:      timestamp column present in both dataframes (tz-aware OK)
    direction: 'backward' means use the last high-row <= low-row timestamp
    """
    low_cols = list(low_cols or [])
    high_cols = list(high_cols or [])

    a = _ensure_sorted(low_df[[on] + low_cols].copy(), on)
    b = _ensure_sorted(high_df[[on] + high_cols].copy(), on)

    # apply suffixes (keep the 'on' column name intact)
    if suffix_low:
        a = a.rename(columns={c: f"{c}{suffix_low}" for c in low_cols})
    if suffix_high:
        b = b.rename(columns={c: f"{c}{suffix_high}" for c in high_cols})

    out = pd.merge_asof(a, b, on=on, direction=direction)
    return out


def sign_agreement(
    df: pd.DataFrame,
    col_a: str,
    col_b: str,
    *,
    out_col: str = "agree",
) -> tuple[pd.DataFrame, float]:
    """
    Mark True where signs of two series match (strictly > 0).
    Returns the modified df and the agreement rate.
    """
    s = (np.sign(df[col_a]) * np.sign(df[col_b])) > 0
    df[out_col] = s
    return df, float(np.nanmean(s.astype(float)))


def rolling_agreement(
    df: pd.DataFrame,
    col_a: str,
    col_b: str,
    *,
    window: int = 63,
    out_col: Optional[str] = None,
    min_periods: Optional[int] = None,
) -> pd.DataFrame:
    """
    Rolling share of days where signs match over a window.
    """
    if out_col is None:
        out_col = f"agree_{window}"
    if min_periods is None:
        min_periods = max(5, window // 3)

    agree = (np.sign(df[col_a]) * np.sign(df[col_b])) > 0
    df[out_col] = agree.rolling(window, min_periods=min_periods).mean()
    return df


# ---- optional extras (nice to have) -----------------------------------------

def forward_return_split(
    df: pd.DataFrame,
    agree_col: str,
    fwd_ret_col: str,
) -> pd.DataFrame:
    """
    Compare forward returns when agree==True vs False.
    """
    sub = df[[agree_col, fwd_ret_col]].dropna()
    return (sub
            .groupby(agree_col)[fwd_ret_col]
            .agg(count="count", mean="mean", median="median", std="std")
            .reset_index()
            .rename(columns={agree_col: "agree"}))


def lead_lag_max_corr(
    df: pd.DataFrame,
    col_a: str,
    col_b: str,
    lags: range = range(-10, 11),
) -> Dict[str, object]:
    """
    Find lag that maximizes Pearson correlation between two columns.
    Positive lag means col_b is shifted *forward* (col_b leads col_a).
    """
    corrs = {}
    x = df[col_a].astype(float)
    y = df[col_b].astype(float)
    for k in lags:
        if k == 0:
            corrs[k] = x.corr(y)
        elif k > 0:
            corrs[k] = x.iloc[k:].reset_index(drop=True).corr(y.iloc[:-k].reset_index(drop=True))
        else:  # k < 0
            kk = -k
            corrs[k] = x.iloc[:-kk].reset_index(drop=True).corr(y.iloc[kk:].reset_index(drop=True))
    s = pd.Series(corrs).dropna()
    best_lag = int(s.abs().idxmax()) if not s.empty else 0
    return {"best_lag": best_lag, "best_corr": float(s.loc[best_lag]) if not s.empty else np.nan, "corr_by_lag": s}
