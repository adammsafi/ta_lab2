# -*- coding: utf-8 -*-
"""
Feature diagnostics:
- correlation & redundancy checks
- simple predictive value checks vs. future returns
- (optional) sklearn logistic regression feature weights (if available)
"""
from __future__ import annotations
import warnings
from typing import Iterable, List, Tuple, Dict
import numpy as np
import pandas as pd

try:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    SKLEARN = True
except Exception:  # keep optional
    SKLEARN = False

def corr_matrix(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Pearson correlation among selected feature columns."""
    cols = [c for c in columns if c in df.columns]
    return df[cols].corr()

def redundancy_report(df: pd.DataFrame, columns: Iterable[str], thresh: float = 0.9) -> pd.DataFrame:
    """
    Flag highly correlated pairs (> thresh).
    Useful to prune features before modeling.
    """
    cm = corr_matrix(df, columns).abs()
    pairs = []
    for i, c1 in enumerate(cm.columns):
        for j, c2 in enumerate(cm.columns):
            if j <= i: continue
            if cm.loc[c1, c2] >= thresh:
                pairs.append({"f1": c1, "f2": c2, "abs_corr": cm.loc[c1, c2]})
    return pd.DataFrame(pairs).sort_values("abs_corr", ascending=False)

def future_return(close: pd.Series, horizon: int = 1, log: bool = False) -> pd.Series:
    """Compute forward return over N bars (target)."""
    if log:
        return np.log(close.shift(-horizon)) - np.log(close)
    return close.shift(-horizon) / close - 1.0

def binarize_target(y: pd.Series, threshold: float = 0.0) -> pd.Series:
    """Label up/down based on threshold (e.g., future return > 0)."""
    return (y > threshold).astype(int)

def quick_logit_feature_weights(
    df: pd.DataFrame,
    feature_cols: List[str],
    close_col: str = "close",
    horizon: int = 1,
    log_ret: bool = False,
) -> pd.DataFrame:
    """
    If sklearn is available: fit a simple logit predicting (fwd_return > 0).
    Returns standardized coefficient magnitudes as a rough importance proxy.
    """
    if not SKLEARN:
        warnings.warn("scikit-learn not available; skipping logistic regression.")
        return pd.DataFrame(columns=["feature", "coef"])

    cols = [c for c in feature_cols if c in df.columns]
    y = binarize_target(future_return(df[close_col], horizon, log=log_ret)).dropna()
    X = df.loc[y.index, cols].fillna(method="ffill").fillna(0.0)

    pipe = Pipeline([
        ("scaler", StandardScaler(with_mean=True, with_std=True)),
        ("logit", LogisticRegression(max_iter=1000))
    ])
    pipe.fit(X, y)

    coefs = pipe.named_steps["logit"].coef_.ravel()
    out = pd.DataFrame({"feature": cols, "coef": coefs})
    out["abs_coef"] = out["coef"].abs()
    return out.sort_values("abs_coef", ascending=False, kind="mergesort")

def feature_target_correlations(
    df: pd.DataFrame,
    feature_cols: List[str],
    close_col: str = "close",
    horizon: int = 1,
    log_ret: bool = False,
) -> pd.DataFrame:
    """
    Rank features by absolute correlation with forward returns.
    Quick sanity check before heavier modeling.
    """
    y = future_return(df[close_col], horizon, log=log_ret)
    rows = []
    for f in feature_cols:
        if f not in df.columns: continue
        s = df[f]
        c = pd.concat([s, y], axis=1).dropna()
        if len(c) < 10: continue
        corr = c.iloc[:, 0].corr(c.iloc[:, 1])
        rows.append({"feature": f, "corr_to_fwd": corr, "abs_corr": abs(corr), "n": len(c)})
    return pd.DataFrame(rows).sort_values("abs_corr", ascending=False, kind="mergesort")
