# src/ta_lab2/regimes/comovement.py
"""
Comovement utilities (no-loss merged module)

Preserves original helpers:
- _ensure_sorted, build_alignment_frame
- sign_agreement, rolling_agreement
- forward_return_split
- lead_lag_max_corr

Adds:
- compute_ema_comovement_stats: correlation + sign-agreement across EMA columns
- compute_ema_comovement_hierarchy: derives an ordered “hierarchy” from EMA corr
"""

from __future__ import annotations
from typing import Optional, Dict, Iterable, Sequence, Iterable as _Iterable
import itertools
import numpy as np
import pandas as pd


# ---------------------------------------------------------------------
# Original utilities (PRESERVED)
# ---------------------------------------------------------------------
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
    low_cols: Optional[_Iterable[str]] = None,
    high_cols: Optional[_Iterable[str]] = None,
    suffix_low: str = "",
    suffix_high: str = "_w",
    direction: str = "backward",
) -> pd.DataFrame:
    """
    Merge-asof align low timeframe rows with the most recent high timeframe row.
    """
    low_cols = list(low_cols or [])
    high_cols = list(high_cols or [])

    a = _ensure_sorted(low_df[[on] + low_cols].copy(), on)
    b = _ensure_sorted(high_df[[on] + high_cols].copy(), on)

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
    """Mark True where signs of two series match (strictly > 0)."""
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
    """Rolling share of days where signs match over a window."""
    if out_col is None:
        out_col = f"agree_{window}"
    if min_periods is None:
        min_periods = max(5, window // 3)

    agree = (np.sign(df[col_a]) * np.sign(df[col_b])) > 0
    df[out_col] = agree.rolling(window, min_periods=min_periods).mean()
    return df


def forward_return_split(df: pd.DataFrame, agree_col: str, fwd_ret_col: str) -> pd.DataFrame:
    """Compare forward returns when agree==True vs False."""
    sub = df[[agree_col, fwd_ret_col]].dropna()
    return (
        sub.groupby(agree_col)[fwd_ret_col]
        .agg(count="count", mean="mean", median="median", std="std")
        .reset_index()
        .rename(columns={agree_col: "agree"})
    )


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


# ---------------------------------------------------------------------
# New EMA comovement stats (ADDED)
# ---------------------------------------------------------------------
def _find_ema_columns(df: pd.DataFrame, token: str = "_ema_") -> list[str]:
    """Auto-detect EMA columns by substring token (default: '_ema_')."""
    cols = [c for c in df.columns if token in c]
    def _tail_int(name: str) -> int:
        try:
            return int(name.split("_")[-1])
        except Exception:
            return 10**9
    return sorted(cols, key=_tail_int)


def _pairwise(cols: Sequence[str]) -> Iterable[tuple[str, str]]:
    return itertools.combinations(cols, 2)


def compute_ema_comovement_stats(
    df: pd.DataFrame,
    *,
    ema_cols: Sequence[str] | None = None,
    method: str = "spearman",      # "pearson" | "spearman"
    agree_on_sign_of_diff: bool = True,
    diff_window: int = 1,
) -> Dict[str, pd.DataFrame]:
    """
    Compute co-movement stats among EMA series.

    Returns dict:
      - 'corr':  correlation matrix over EMA levels
      - 'agree': pairwise agreement of sign(dEMA) over `diff_window`
      - 'meta':  one-row metadata (n_ema, method, diff_window)
    """
    if ema_cols is None:
        ema_cols = _find_ema_columns(df)

    ema_cols = [c for c in ema_cols if c in df.columns]
    if len(ema_cols) < 2:
        return {
            "corr": pd.DataFrame(index=ema_cols, columns=ema_cols, dtype=float),
            "agree": pd.DataFrame(columns=["a", "b", "agree_rate"], dtype=float),
            "meta": pd.DataFrame([{"n_ema": len(ema_cols)}]),
        }

    corr = df[ema_cols].corr(method=method)

    if agree_on_sign_of_diff:
        diffs = df[ema_cols].diff(diff_window)
        signs = np.sign(diffs)
        rows = []
        for a, b in _pairwise(list(ema_cols)):
            s_a, s_b = signs[a], signs[b]
            valid = s_a.notna() & s_b.notna()
            agree = float((s_a[valid] == s_b[valid]).mean()) if valid.any() else np.nan
            rows.append({"a": a, "b": b, "agree_rate": agree})
        agree_df = pd.DataFrame(rows)
    else:
        agree_df = pd.DataFrame(columns=["a", "b", "agree_rate"], dtype=float)

    meta = pd.DataFrame([{"n_ema": len(ema_cols), "method": method, "diff_window": diff_window}])
    return {"corr": corr, "agree": agree_df, "meta": meta}


def compute_ema_comovement_hierarchy(
    df: pd.DataFrame,
    *,
    ema_cols: Sequence[str] | None = None,
    method: str = "spearman",
) -> Dict[str, object]:
    """
    Build a simple ordering (“hierarchy”) of EMA columns from the correlation matrix.

    - If scipy is not available (default), we derive an order by sorting columns
      on mean absolute correlation (highest first). This is lightweight and
      dependency-free.
    - Returns dictionary with:
        * 'corr'   : correlation matrix among EMA columns
        * 'order'  : list of column names sorted by mean |corr|
        * 'scores' : DataFrame with per-column mean_abs_corr used for ordering
    """
    if ema_cols is None:
        ema_cols = _find_ema_columns(df)
    ema_cols = [c for c in ema_cols if c in df.columns]

    corr = df[ema_cols].corr(method=method) if len(ema_cols) >= 2 else pd.DataFrame(index=ema_cols, columns=ema_cols)
    if corr.empty:
        return {"corr": corr, "order": ema_cols, "scores": pd.DataFrame({"col": ema_cols, "mean_abs_corr": []})}

    # Mean absolute correlation per EMA column (ignore self-corr on the diagonal)
    abs_corr = corr.abs()
    np.fill_diagonal(abs_corr.values, np.nan)
    scores = abs_corr.mean(skipna=True).rename("mean_abs_corr").to_frame()
    order = list(scores.sort_values("mean_abs_corr", ascending=False).index)

    return {"corr": corr, "order": order, "scores": scores.reset_index().rename(columns={"index": "col"})}


__all__ = [
    # original
    "_ensure_sorted",
    "build_alignment_frame",
    "sign_agreement",
    "rolling_agreement",
    "forward_return_split",
    "lead_lag_max_corr",
    # added
    "compute_ema_comovement_stats",
    "compute_ema_comovement_hierarchy",
]
