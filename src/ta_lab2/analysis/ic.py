# -*- coding: utf-8 -*-
"""
IC (Information Coefficient) computation library.

Provides Spearman IC per feature per forward-return horizon, rolling IC with
IC-IR, IC decay table, significance testing, and feature turnover.

All public functions operate on pandas Series indexed by tz-aware UTC timestamps.
train_start and train_end are REQUIRED in compute_ic() — no default values to
prevent future-information leakage.

Public API:
    compute_forward_returns  -- arithmetic or log forward returns on a full series
    compute_ic               -- per-horizon IC table (14 rows by default)
    compute_rolling_ic       -- vectorized rolling IC + IC-IR summary statistics
    compute_feature_turnover -- rank autocorrelation proxy for signal stability

Internal helpers (exported for testing):
    _compute_single_ic       -- IC + t-stat + p-value for one feature/horizon pair
    _ic_t_stat               -- t-stat formula with 1e-15 denominator guard
    _ic_p_value              -- two-sided p-value via norm.cdf
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import norm, spearmanr

logger = logging.getLogger(__name__)

_DEFAULT_HORIZONS: list[int] = [1, 2, 3, 5, 10, 20, 60]
_DEFAULT_RETURN_TYPES: list[str] = ["arith", "log"]


# ---------------------------------------------------------------------------
# Public helpers (also exported for test-level assertions)
# ---------------------------------------------------------------------------


def _ic_t_stat(ic: float, n: int) -> float:
    """
    IC t-statistic: t = IC * sqrt(n-2) / sqrt(max(1 - IC^2, 1e-15)).

    The 1e-15 floor prevents division-by-zero when |IC| = 1.0.

    Parameters
    ----------
    ic : float
        Spearman IC value (in [-1, 1]).
    n : int
        Number of observations used to compute IC.

    Returns
    -------
    float
        t-statistic.
    """
    denom = max(1.0 - ic**2, 1e-15)
    return float(ic * np.sqrt(n - 2) / np.sqrt(denom))


def _ic_p_value(t_stat: float) -> float:
    """
    Two-sided p-value: p = 2 * (1 - norm.cdf(|t_stat|)).

    Parameters
    ----------
    t_stat : float

    Returns
    -------
    float
        Two-sided p-value.
    """
    return float(2.0 * (1.0 - norm.cdf(abs(t_stat))))


# ---------------------------------------------------------------------------
# Core computation functions
# ---------------------------------------------------------------------------


def compute_forward_returns(
    close: pd.Series,
    horizon: int,
    log: bool = False,
) -> pd.Series:
    """
    Compute forward returns on the COMPLETE close series.

    Forward returns are always computed on the full series before any train-window
    slicing. The caller then slices to train_start..train_end and applies boundary
    masking. Never compute forward returns on a pre-sliced window — the resulting
    NaN at the tail would be an artefact of slicing, not of explicit look-ahead
    prevention.

    Parameters
    ----------
    close : pd.Series
        Close prices indexed by UTC timestamps.
    horizon : int
        Forward horizon in bars (e.g. 1, 5, 20).
    log : bool
        If True, compute log returns. Default False (arithmetic).

    Returns
    -------
    pd.Series
        Same index as close. Last ``horizon`` bars are NaN.
    """
    if log:
        return np.log(close.shift(-horizon)) - np.log(close)
    return close.shift(-horizon) / close - 1.0


def _compute_single_ic(
    feature: pd.Series,
    fwd_ret: pd.Series,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    horizon: int,
    tf_days_nominal: int,
    min_obs: int = 20,
) -> dict:
    """
    Compute Spearman IC for one feature/horizon pair within a train window.

    BOUNDARY MASKING (look-ahead bias prevention):
    Bars where ``bar_ts + timedelta(days=horizon * tf_days_nominal) > train_end``
    have their forward returns nulled out. Without this, the last ``horizon`` bars
    in the training window use close prices from after train_end.

    Parameters
    ----------
    feature : pd.Series
        Feature values indexed by UTC timestamps (full series or pre-sliced).
    fwd_ret : pd.Series
        Forward returns indexed by UTC timestamps (must have been computed on the
        full close series, NOT on a train-window slice).
    train_start : pd.Timestamp
        Start of the evaluation window (inclusive).
    train_end : pd.Timestamp
        End of the evaluation window (inclusive). Boundary bars are nulled.
    horizon : int
        Forward return horizon in bars.
    tf_days_nominal : int
        Nominal calendar days per bar (1 for 1D, 7 for 1W, 30 for 1M, etc.).
    min_obs : int
        Minimum valid observations required to compute IC. Returns NaN dict if
        fewer observations remain after boundary masking and dropna().

    Returns
    -------
    dict
        Keys: ic, t_stat, p_value, n_obs.  All float/int (NaN when insufficient data).
    """
    # Filter feature to train window
    mask = (feature.index >= train_start) & (feature.index <= train_end)
    feat_train = feature[mask]

    # Align forward returns to the FEATURE index (not a boolean mask).
    # This handles the case where fwd_ret has a different (broader) index length
    # than feat_train — reindex by label ensures correct alignment.
    fwd_train = fwd_ret.reindex(feat_train.index).copy()

    # Boundary masking: null forward returns for bars near train_end
    # bar_ts + timedelta(horizon * tf_days_nominal days) > train_end => look-ahead
    horizon_delta = pd.Timedelta(days=horizon * tf_days_nominal)
    # DatetimeIndex arithmetic returns a numpy bool array directly — no .to_numpy() needed
    boundary_mask = (feat_train.index + horizon_delta) > train_end
    fwd_train.iloc[boundary_mask] = np.nan

    # Align and drop NaN from either series
    valid = pd.concat([feat_train, fwd_train], axis=1).dropna()
    n = len(valid)

    if n < min_obs:
        return {"ic": np.nan, "t_stat": np.nan, "p_value": np.nan, "n_obs": n}

    # Guard: constant feature or constant returns -> IC is undefined
    if valid.iloc[:, 0].std() == 0 or valid.iloc[:, 1].std() == 0:
        logger.debug(
            "Constant feature or returns for horizon=%d — returning NaN IC", horizon
        )
        return {"ic": np.nan, "t_stat": np.nan, "p_value": np.nan, "n_obs": n}

    result = spearmanr(valid.iloc[:, 0].values, valid.iloc[:, 1].values)
    ic = float(result.statistic)

    t_stat = _ic_t_stat(ic, n)
    p_value = _ic_p_value(t_stat)

    return {"ic": ic, "t_stat": t_stat, "p_value": p_value, "n_obs": n}


def compute_rolling_ic(
    feature: pd.Series,
    fwd_ret: pd.Series,
    window: int = 63,
) -> tuple[pd.Series, float, float]:
    """
    Vectorized rolling Spearman IC using rank-then-correlate pattern.

    This is ~30x faster than per-window ``spearmanr()`` calls for typical series
    lengths (5000+ bars). The approach uses pandas ``rolling().rank()`` for within-
    window ranking, then ``rolling().corr()`` on the rank series — mathematically
    equivalent to Spearman correlation within each window.

    Parameters
    ----------
    feature : pd.Series
        Feature values (train-window slice, UTC indexed).
    fwd_ret : pd.Series
        Forward returns (train-window slice, same index as feature).
        Should already have boundary bars nulled out.
    window : int
        Rolling window size in bars. Default 63 (approximately 1 quarter for 1D).

    Returns
    -------
    tuple[pd.Series, float, float]
        - rolling_ic_series : rolling IC values. NaN for the first window-1 bars.
        - ic_ir : IC Information Ratio = mean(rolling_ic) / std(rolling_ic).
          NaN if fewer than 5 valid rolling IC values.
        - ic_ir_tstat : t-statistic for IC-IR != 0 = mean * sqrt(n) / std.
          NaN if fewer than 5 valid rolling IC values.
    """
    # Vectorized: rank within rolling window = Spearman rank basis
    feat_rank = feature.rolling(window).rank()
    fwd_rank = fwd_ret.rolling(window).rank()

    # Rolling Pearson correlation of ranks = rolling Spearman IC
    rolling_ic = feat_rank.rolling(window).corr(fwd_rank)

    valid_ic = rolling_ic.dropna()
    n = len(valid_ic)

    if n < 5:
        return rolling_ic, np.nan, np.nan

    ic_mean = float(valid_ic.mean())
    ic_std = float(valid_ic.std(ddof=1))

    if ic_std == 0.0:
        return rolling_ic, np.nan, np.nan

    ic_ir = ic_mean / ic_std
    ic_ir_tstat = ic_mean * np.sqrt(n) / ic_std  # equivalent to ttest_1samp t-stat

    return rolling_ic, float(ic_ir), float(ic_ir_tstat)


def compute_feature_turnover(
    feature: pd.Series,
    min_obs: int = 20,
) -> float:
    """
    Feature turnover = 1 - rank_autocorrelation(lag=1).

    High rank autocorrelation (stable ranks day-to-day) -> low turnover.
    Low rank autocorrelation (ranks jump around) -> high turnover.

    Interpretation:
    - turnover ~ 0  : perfectly stable ranks (e.g. monotone cumulative signal)
    - turnover ~ 1  : random rank permutation each bar
    - turnover > 1  : negatively autocorrelated (rank reversal)

    Parameters
    ----------
    feature : pd.Series
        Feature values. NaN values are dropped before computation.
    min_obs : int
        Minimum observations required. Returns NaN if fewer available.

    Returns
    -------
    float
        Turnover in [approximately] 0..2 range.  NaN if insufficient data.
    """
    feature_clean = feature.dropna()
    if len(feature_clean) < min_obs:
        return float(np.nan)

    ranks = feature_clean.rank()
    result = spearmanr(ranks.iloc[:-1].values, ranks.iloc[1:].values)
    return float(1.0 - result.statistic)


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------


def compute_ic(
    feature: pd.Series,
    close: pd.Series,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    *,
    horizons: Optional[list[int]] = None,
    return_types: Optional[list[str]] = None,
    rolling_window: int = 63,
    tf_days_nominal: int = 1,
    min_obs: int = 20,
) -> pd.DataFrame:
    """
    Compute Spearman IC for a single feature across forward-return horizons.

    REQUIRED parameters: train_start and train_end have NO default value.
    Omitting either raises TypeError immediately (Python's natural behavior for
    missing required arguments). This is by design — IC without a bounded
    evaluation window is meaningless and risks future-information leakage.

    For each (horizon, return_type) combination:
    1. Compute forward returns on the FULL close series.
    2. Slice to [train_start, train_end] and apply boundary masking.
    3. Compute Spearman IC + t-stat + p-value.
    4. Compute rolling IC time series and IC-IR summary.
    5. Compute feature turnover once per feature (same for all rows).

    Parameters
    ----------
    feature : pd.Series
        Feature values indexed by UTC timestamps.
    close : pd.Series
        Close prices indexed by UTC timestamps. Must have same or broader index
        than feature.
    train_start : pd.Timestamp
        Start of the train window (REQUIRED, no default).
    train_end : pd.Timestamp
        End of the train window (REQUIRED, no default).
    horizons : list[int], optional
        Bar-based forward horizons. Default [1, 2, 3, 5, 10, 20, 60].
    return_types : list[str], optional
        Return type(s) to compute. Default ['arith', 'log'].
        'arith' = arithmetic (close[t+h]/close[t] - 1).
        'log'   = log return (log(close[t+h]) - log(close[t])).
    rolling_window : int
        Window size for rolling IC. Default 63.
    tf_days_nominal : int
        Nominal calendar days per bar for boundary masking. Default 1 (daily).
    min_obs : int
        Minimum observations for IC computation. Default 20.

    Returns
    -------
    pd.DataFrame
        One row per (horizon, return_type). Columns:
        horizon, return_type, ic, ic_t_stat, ic_p_value,
        ic_ir, ic_ir_t_stat, turnover, n_obs
        IC decay table: sort by horizon to read IC decay across horizons.
    """
    if horizons is None:
        horizons = _DEFAULT_HORIZONS
    if return_types is None:
        return_types = _DEFAULT_RETURN_TYPES

    # Compute feature turnover once per feature (shared across all horizon/return_type rows)
    turnover = compute_feature_turnover(feature, min_obs=min_obs)

    rows = []

    for return_type in return_types:
        log_flag = return_type == "log"

        for horizon in horizons:
            # Step 1: Compute forward returns on the FULL close series
            fwd_ret_global = compute_forward_returns(
                close, horizon=horizon, log=log_flag
            )

            # Step 2: Point IC + significance
            ic_result = _compute_single_ic(
                feature,
                fwd_ret_global,
                train_start,
                train_end,
                horizon=horizon,
                tf_days_nominal=tf_days_nominal,
                min_obs=min_obs,
            )

            # Step 3: Rolling IC + IC-IR
            # Slice feature and forward returns to train window for rolling IC
            mask = (feature.index >= train_start) & (feature.index <= train_end)
            feat_train = feature[mask]

            fwd_train = fwd_ret_global.reindex(feat_train.index).copy()

            # Apply boundary masking for rolling IC as well
            horizon_delta = pd.Timedelta(days=horizon * tf_days_nominal)
            boundary_mask = (feat_train.index + horizon_delta) > train_end
            fwd_train.iloc[boundary_mask] = np.nan

            if feat_train.notna().sum() >= rolling_window + 5:
                _, ic_ir, ic_ir_tstat = compute_rolling_ic(
                    feat_train, fwd_train, window=rolling_window
                )
            else:
                ic_ir, ic_ir_tstat = np.nan, np.nan

            rows.append(
                {
                    "horizon": horizon,
                    "return_type": return_type,
                    "ic": ic_result["ic"],
                    "ic_t_stat": ic_result["t_stat"],
                    "ic_p_value": ic_result["p_value"],
                    "ic_ir": ic_ir,
                    "ic_ir_t_stat": ic_ir_tstat,
                    "turnover": turnover,
                    "n_obs": ic_result["n_obs"],
                }
            )

    return pd.DataFrame(rows)
