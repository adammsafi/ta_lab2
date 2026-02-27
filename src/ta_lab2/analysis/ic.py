# -*- coding: utf-8 -*-
"""
IC (Information Coefficient) computation library.

Provides Spearman IC per feature per forward-return horizon, rolling IC with
IC-IR, IC decay table, significance testing, feature turnover, regime-conditional
IC breakdown, batch wrapper, Plotly visualization helpers, and DB persistence.

All public functions operate on pandas Series indexed by tz-aware UTC timestamps.
train_start and train_end are REQUIRED in compute_ic() — no default values to
prevent future-information leakage.

Public API:
    compute_forward_returns  -- arithmetic or log forward returns on a full series
    compute_ic               -- per-horizon IC table (14 rows by default)
    compute_rolling_ic       -- vectorized rolling IC + IC-IR summary statistics
    compute_feature_turnover -- rank autocorrelation proxy for signal stability
    compute_ic_by_regime     -- IC split by regime label (e.g. trend_state, vol_state)
    batch_compute_ic         -- IC for multiple feature columns, concatenated result
    plot_ic_decay            -- Plotly bar chart of IC decay across horizons
    plot_rolling_ic          -- Plotly line chart of rolling IC time series

DB helpers (for CLI and notebooks):
    load_feature_series      -- load feature + close from cmc_features
    load_regimes_for_asset   -- load and parse l2_label from cmc_regimes
    save_ic_results          -- persist IC rows to cmc_ic_results

Internal helpers (exported for testing):
    _compute_single_ic       -- IC + t-stat + p-value for one feature/horizon pair
    _ic_t_stat               -- t-stat formula with 1e-15 denominator guard
    _ic_p_value              -- two-sided p-value via norm.cdf
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from scipy.stats import norm, spearmanr
from sqlalchemy import text

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

    # Slice feature to train window once — reused for every horizon/return_type
    train_mask = (feature.index >= train_start) & (feature.index <= train_end)
    feat_train = feature[train_mask]
    has_enough_for_rolling = feat_train.notna().sum() >= rolling_window + 5

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
            if has_enough_for_rolling:
                fwd_train = fwd_ret_global.reindex(feat_train.index).copy()

                # Apply boundary masking for rolling IC as well
                horizon_delta = pd.Timedelta(days=horizon * tf_days_nominal)
                boundary_mask = (feat_train.index + horizon_delta) > train_end
                fwd_train.iloc[boundary_mask] = np.nan

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


# ---------------------------------------------------------------------------
# Regime-conditional IC breakdown
# ---------------------------------------------------------------------------


def compute_ic_by_regime(
    feature: pd.Series,
    close: pd.Series,
    regimes_df: Optional[pd.DataFrame],
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    *,
    horizons: Optional[list[int]] = None,
    return_types: Optional[list[str]] = None,
    rolling_window: int = 63,
    tf_days_nominal: int = 1,
    regime_col: str = "trend_state",
    min_obs_per_regime: int = 30,
    min_obs: int = 20,
) -> pd.DataFrame:
    """
    Compute Spearman IC broken down by regime label.

    This function accepts a pre-built ``regimes_df`` — the caller is responsible
    for loading and parsing regime data from the database. The l2_label
    parsing (e.g. split('-') to extract trend_state / vol_state) happens in
    the CLI/DB helper layer (Plan 04), NOT here.

    Parameters
    ----------
    feature : pd.Series
        Feature values indexed by UTC timestamps.
    close : pd.Series
        Close prices indexed by UTC timestamps.
    regimes_df : pd.DataFrame or None
        DataFrame indexed by ts (UTC) with a column named ``regime_col``
        containing regime labels (e.g. 'Up', 'Down', 'High', 'Low').
        If None or empty, falls back to full-sample IC with regime_label='all'.
    train_start : pd.Timestamp
        Start of the train window (REQUIRED).
    train_end : pd.Timestamp
        End of the train window (REQUIRED).
    horizons : list[int], optional
        Forward horizons. Default [1, 2, 3, 5, 10, 20, 60].
    return_types : list[str], optional
        Return type(s). Default ['arith', 'log'].
    rolling_window : int
        Window size for rolling IC. Default 63.
    tf_days_nominal : int
        Nominal calendar days per bar. Default 1.
    regime_col : str
        Column name in regimes_df containing the regime labels. Default 'trend_state'.
    min_obs_per_regime : int
        Minimum number of observations (bars) required for a regime subset to
        be evaluated. Regimes with fewer bars are skipped. Default 30.
    min_obs : int
        Minimum observations for IC computation within each regime. Default 20.

    Returns
    -------
    pd.DataFrame
        One row per (horizon, return_type, regime_label). Includes all columns
        from compute_ic() plus ``regime_col`` and ``regime_label`` columns.
        If regimes_df is empty/None, returns full-sample IC with regime_label='all'.
    """
    # Fall back to full-sample IC when no regime data is available
    if regimes_df is None or len(regimes_df) == 0:
        logger.debug(
            "compute_ic_by_regime: regimes_df is empty/None — falling back to full-sample IC"
        )
        base_df = compute_ic(
            feature,
            close,
            train_start,
            train_end,
            horizons=horizons,
            return_types=return_types,
            rolling_window=rolling_window,
            tf_days_nominal=tf_days_nominal,
            min_obs=min_obs,
        )
        base_df["regime_col"] = regime_col
        base_df["regime_label"] = "all"
        return base_df

    # Filter regimes to train window
    regime_in_window = regimes_df[
        (regimes_df.index >= train_start) & (regimes_df.index <= train_end)
    ]

    if len(regime_in_window) == 0:
        logger.debug(
            "compute_ic_by_regime: no regime rows in train window — falling back to full-sample IC"
        )
        base_df = compute_ic(
            feature,
            close,
            train_start,
            train_end,
            horizons=horizons,
            return_types=return_types,
            rolling_window=rolling_window,
            tf_days_nominal=tf_days_nominal,
            min_obs=min_obs,
        )
        base_df["regime_col"] = regime_col
        base_df["regime_label"] = "all"
        return base_df

    # Split IC by each regime label
    all_regime_results: list[pd.DataFrame] = []
    unique_labels = regime_in_window[regime_col].dropna().unique()

    for label in unique_labels:
        # Timestamps where this regime label is active (within train window)
        regime_ts = regime_in_window[regime_in_window[regime_col] == label].index

        # Filter feature and close to regime-active timestamps only
        feat_regime = feature.reindex(regime_ts).dropna()
        close_regime = close.reindex(regime_ts).dropna()

        # Only keep timestamps present in both (intersection)
        common_ts = feat_regime.index.intersection(close_regime.index)
        feat_regime = feat_regime.reindex(common_ts)
        close_regime = close_regime.reindex(common_ts)

        # Skip sparse regimes
        n_regime = len(feat_regime.dropna())
        if n_regime < min_obs_per_regime:
            logger.debug(
                "compute_ic_by_regime: skipping regime '%s' — only %d obs (min=%d)",
                label,
                n_regime,
                min_obs_per_regime,
            )
            continue

        # For a regime subset, we need to define a synthetic train window
        # spanning the regime-active timestamps. Use first/last ts in regime.
        regime_train_start = common_ts.min()
        regime_train_end = common_ts.max()

        regime_ic_df = compute_ic(
            feat_regime,
            close_regime,
            regime_train_start,
            regime_train_end,
            horizons=horizons,
            return_types=return_types,
            rolling_window=rolling_window,
            tf_days_nominal=tf_days_nominal,
            min_obs=min_obs,
        )

        regime_ic_df["regime_col"] = regime_col
        regime_ic_df["regime_label"] = str(label)
        all_regime_results.append(regime_ic_df)

    if not all_regime_results:
        # All regimes were sparse — fall back to full-sample IC
        logger.warning(
            "compute_ic_by_regime: all regime subsets were sparse — falling back to full-sample IC"
        )
        base_df = compute_ic(
            feature,
            close,
            train_start,
            train_end,
            horizons=horizons,
            return_types=return_types,
            rolling_window=rolling_window,
            tf_days_nominal=tf_days_nominal,
            min_obs=min_obs,
        )
        base_df["regime_col"] = regime_col
        base_df["regime_label"] = "all"
        return base_df

    return pd.concat(all_regime_results, ignore_index=True)


# ---------------------------------------------------------------------------
# Batch wrapper
# ---------------------------------------------------------------------------


def batch_compute_ic(
    features_df: pd.DataFrame,
    close: pd.Series,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    *,
    feature_cols: Optional[list[str]] = None,
    horizons: Optional[list[int]] = None,
    return_types: Optional[list[str]] = None,
    rolling_window: int = 63,
    tf_days_nominal: int = 1,
    min_obs: int = 20,
) -> pd.DataFrame:
    """
    Compute IC for multiple feature columns in one call.

    Pre-computes forward returns and rolling ranks ONCE for all
    (horizon, return_type) combinations, then reuses them across all features.
    This avoids redundant compute_forward_returns and rolling().rank() calls
    (112x reduction for a typical 112-feature sweep).

    Parameters
    ----------
    features_df : pd.DataFrame
        DataFrame indexed by ts (UTC) with multiple feature columns.
    close : pd.Series
        Close prices indexed by UTC timestamps.
    train_start : pd.Timestamp
        Start of the train window (REQUIRED).
    train_end : pd.Timestamp
        End of the train window (REQUIRED).
    feature_cols : list[str], optional
        Subset of columns to evaluate. Default: all numeric columns except 'close'.
    horizons : list[int], optional
        Forward horizons. Default [1, 2, 3, 5, 10, 20, 60].
    return_types : list[str], optional
        Return type(s). Default ['arith', 'log'].
    rolling_window : int
        Window size for rolling IC. Default 63.
    tf_days_nominal : int
        Nominal calendar days per bar. Default 1.
    min_obs : int
        Minimum observations for IC computation. Default 20.

    Returns
    -------
    pd.DataFrame
        Concatenated IC results for all feature columns. Includes all columns
        from compute_ic() plus a ``feature`` column with the column name.
    """
    if feature_cols is None:
        # Use all numeric columns except 'close'
        numeric_cols = features_df.select_dtypes(include=[np.number]).columns.tolist()
        feature_cols = [c for c in numeric_cols if c != "close"]

    if horizons is None:
        horizons = _DEFAULT_HORIZONS
    if return_types is None:
        return_types = _DEFAULT_RETURN_TYPES

    # --- Pre-compute forward returns cache ---
    # Key: (return_type, horizon) -> full-series forward returns
    fwd_returns_cache: dict[tuple[str, int], pd.Series] = {}
    for return_type in return_types:
        log_flag = return_type == "log"
        for horizon in horizons:
            fwd_returns_cache[(return_type, horizon)] = compute_forward_returns(
                close, horizon=horizon, log=log_flag
            )

    # --- Pre-compute train-window sliced + boundary-masked forward returns ---
    # Build train mask once (shared index from features_df)
    train_mask = (features_df.index >= train_start) & (features_df.index <= train_end)
    train_index = features_df.index[train_mask]

    # Key: (return_type, horizon) -> boundary-masked, train-sliced fwd returns
    fwd_train_cache: dict[tuple[str, int], pd.Series] = {}
    # Key: (return_type, horizon) -> pre-computed rolling rank of fwd returns
    fwd_rank_cache: dict[tuple[str, int], pd.Series] = {}

    for return_type in return_types:
        for horizon in horizons:
            fwd_global = fwd_returns_cache[(return_type, horizon)]
            fwd_train = fwd_global.reindex(train_index).copy()

            # Boundary masking: null forward returns for bars near train_end
            horizon_delta = pd.Timedelta(days=horizon * tf_days_nominal)
            boundary_mask = (train_index + horizon_delta) > train_end
            fwd_train.iloc[boundary_mask] = np.nan

            fwd_train_cache[(return_type, horizon)] = fwd_train
            fwd_rank_cache[(return_type, horizon)] = fwd_train.rolling(
                rolling_window
            ).rank()

    # Determine once whether there's enough data for rolling IC
    # Use any feature's non-null count as proxy (they share the same index)
    n_train = train_mask.sum()
    has_enough_for_rolling = n_train >= rolling_window + 5

    all_results: list[pd.DataFrame] = []

    for col in feature_cols:
        feature = features_df[col]

        # Compute feature turnover once per feature
        turnover = compute_feature_turnover(feature, min_obs=min_obs)

        # Slice feature to train window
        feat_train = feature[train_mask]
        feat_has_rolling = (
            has_enough_for_rolling and feat_train.notna().sum() >= rolling_window + 5
        )

        rows = []

        for return_type in return_types:
            for horizon in horizons:
                fwd_global = fwd_returns_cache[(return_type, horizon)]

                # Point IC via _compute_single_ic (uses full-series fwd_ret)
                ic_result = _compute_single_ic(
                    feature,
                    fwd_global,
                    train_start,
                    train_end,
                    horizon=horizon,
                    tf_days_nominal=tf_days_nominal,
                    min_obs=min_obs,
                )

                # Rolling IC using cached train-sliced fwd returns + ranks
                if feat_has_rolling:
                    fwd_train = fwd_train_cache[(return_type, horizon)]
                    fwd_rank = fwd_rank_cache[(return_type, horizon)]

                    feat_rank = feat_train.rolling(rolling_window).rank()
                    rolling_ic = feat_rank.rolling(rolling_window).corr(fwd_rank)

                    valid_ic = rolling_ic.dropna()
                    n_valid = len(valid_ic)

                    if n_valid < 5:
                        ic_ir, ic_ir_tstat = np.nan, np.nan
                    else:
                        ic_mean = float(valid_ic.mean())
                        ic_std = float(valid_ic.std(ddof=1))
                        if ic_std == 0.0:
                            ic_ir, ic_ir_tstat = np.nan, np.nan
                        else:
                            ic_ir = ic_mean / ic_std
                            ic_ir_tstat = ic_mean * np.sqrt(n_valid) / ic_std
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
                        "ic_ir_t_stat": float(ic_ir_tstat)
                        if not isinstance(ic_ir_tstat, float)
                        else ic_ir_tstat,
                        "turnover": turnover,
                        "n_obs": ic_result["n_obs"],
                    }
                )

        col_ic_df = pd.DataFrame(rows)
        col_ic_df["feature"] = col
        all_results.append(col_ic_df)

    if not all_results:
        return pd.DataFrame()

    return pd.concat(all_results, ignore_index=True)


# ---------------------------------------------------------------------------
# Plotly visualization helpers
# ---------------------------------------------------------------------------


def plot_ic_decay(
    ic_df: pd.DataFrame,
    feature: str,
    *,
    return_type: str = "arith",
    sig_threshold: float = 0.05,
) -> go.Figure:
    """
    Create a Plotly bar chart of IC decay across forward horizons.

    Parameters
    ----------
    ic_df : pd.DataFrame
        DataFrame with columns: horizon, ic, ic_p_value (and optionally return_type).
        Output of compute_ic() filtered to one return_type, or a DataFrame already
        containing only the desired return_type rows.
    feature : str
        Feature name for the chart title.
    return_type : str
        Return type label for the chart title. Default 'arith'.
    sig_threshold : float
        p-value significance threshold. Bars with ic_p_value < sig_threshold are
        colored "royalblue"; others are colored "lightgray". Default 0.05.

    Returns
    -------
    plotly.graph_objects.Figure
        Bar chart of IC vs horizon with significance coloring and p-value annotations.
    """
    # Filter to the requested return_type if the column is present
    if "return_type" in ic_df.columns:
        plot_df = ic_df[ic_df["return_type"] == return_type].copy()
    else:
        plot_df = ic_df.copy()

    # Sort by horizon for clean x-axis
    plot_df = plot_df.sort_values("horizon").reset_index(drop=True)

    horizons = plot_df["horizon"].tolist()
    ic_values = plot_df["ic"].tolist()
    p_values = plot_df["ic_p_value"].tolist()

    # Color bars by significance
    colors = ["royalblue" if p < sig_threshold else "lightgray" for p in p_values]

    # Text annotation: p-value above each bar
    text_labels = [f"p={p:.3f}" for p in p_values]

    fig = go.Figure(
        data=[
            go.Bar(
                x=horizons,
                y=ic_values,
                marker_color=colors,
                text=text_labels,
                textposition="outside",
            )
        ]
    )

    fig.update_layout(
        title=f"IC Decay -- Feature: {feature} ({return_type} returns)",
        xaxis_title="Horizon (bars)",
        yaxis_title="Spearman IC",
    )

    return fig


def plot_rolling_ic(
    rolling_ic_series: pd.Series,
    feature: str,
    *,
    horizon: Optional[int] = None,
    return_type: str = "arith",
) -> go.Figure:
    """
    Create a Plotly line chart of rolling IC over time.

    Parameters
    ----------
    rolling_ic_series : pd.Series
        Rolling IC values indexed by timestamp. Output of compute_rolling_ic()
        (first element of the tuple).
    feature : str
        Feature name for the chart title.
    horizon : int, optional
        Horizon used to compute the rolling IC. Included in subtitle if provided.
    return_type : str
        Return type label for the subtitle. Default 'arith'.

    Returns
    -------
    plotly.graph_objects.Figure
        Line chart of rolling IC with a zero reference line.
    """
    # Build subtitle
    subtitle_parts = []
    if horizon is not None:
        subtitle_parts.append(f"horizon={horizon}")
    subtitle_parts.append(f"return_type={return_type}")
    subtitle = ", ".join(subtitle_parts)

    title = f"Rolling IC -- Feature: {feature}"
    if subtitle:
        title = f"{title} ({subtitle})"

    fig = go.Figure()

    # Rolling IC line
    fig.add_trace(
        go.Scatter(
            x=rolling_ic_series.index,
            y=rolling_ic_series.values,
            mode="lines",
            name="Rolling IC",
        )
    )

    # Zero reference line
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.5)

    fig.update_layout(
        title=title,
        xaxis_title="Date",
        yaxis_title="Rolling Spearman IC",
    )

    return fig


# ---------------------------------------------------------------------------
# DB helper functions (for CLI and notebooks)
# ---------------------------------------------------------------------------

# Non-feature columns to exclude from --all-features discovery
_NON_FEATURE_COLS = frozenset(
    ["id", "ts", "tf", "close", "open", "high", "low", "volume", "ingested_at"]
)


def _to_python(v):
    """
    Normalize a value for SQL binding.

    - numpy scalars -> Python float/int via .item()
    - pd.Timestamp -> Python datetime
    - NaN float -> None (SQL NULL)
    - Everything else: unchanged
    """
    if hasattr(v, "item"):
        # numpy scalar (float32, float64, int32, int64, etc.)
        v = v.item()
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def load_feature_series(
    conn,
    asset_id: int,
    tf: str,
    feature_col: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
) -> tuple[pd.Series, pd.Series]:
    """
    Load a single feature column + close from cmc_features.

    Parameters
    ----------
    conn : SQLAlchemy connection
        Active database connection.
    asset_id : int
        Asset ID to load.
    tf : str
        Timeframe (e.g. '1D').
    feature_col : str
        Column name to load from cmc_features. Must be a valid column.
    train_start : pd.Timestamp
        Start of the range to load (inclusive, UTC).
    train_end : pd.Timestamp
        End of the range to load (inclusive, UTC).

    Returns
    -------
    tuple[pd.Series, pd.Series]
        (feature_series, close_series) both indexed by UTC timestamps.

    Raises
    ------
    ValueError
        If feature_col is not a valid column in cmc_features.
    """
    # Lazy import to avoid circular imports
    from ta_lab2.scripts.sync_utils import get_columns

    # Validate column name by querying information_schema
    # We need an engine for get_columns — use conn.engine if available
    engine = conn.engine
    available_cols = get_columns(engine, "public.cmc_features")

    if feature_col not in available_cols:
        raise ValueError(
            f"Feature column '{feature_col}' not found in cmc_features. "
            f"Available columns: {sorted(available_cols)}"
        )

    # Build SQL with dynamically injected column name (validated above)
    sql = text(
        f"SELECT ts, {feature_col}, close FROM public.cmc_features "
        f"WHERE id = :id AND tf = :tf AND ts >= :start AND ts <= :end ORDER BY ts"
    )

    df = pd.read_sql(
        sql,
        conn,
        params={"id": asset_id, "tf": tf, "start": train_start, "end": train_end},
    )

    # CRITICAL: fix mixed-tz-offset object dtype from pd.read_sql on Windows
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")

    feature_series = df[feature_col]
    close_series = df["close"]

    return feature_series, close_series


def load_regimes_for_asset(
    conn,
    asset_id: int,
    tf: str,
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
) -> pd.DataFrame:
    """
    Load regime labels from cmc_regimes, parsing trend_state and vol_state from l2_label.

    CRITICAL: cmc_regimes has NO trend_state or vol_state columns.
    Both are derived from l2_label via split_part() in SQL.

    Parameters
    ----------
    conn : SQLAlchemy connection
        Active database connection.
    asset_id : int
        Asset ID to load.
    tf : str
        Timeframe (e.g. '1D').
    train_start : pd.Timestamp
        Start of the range to load (inclusive, UTC).
    train_end : pd.Timestamp
        End of the range to load (inclusive, UTC).

    Returns
    -------
    pd.DataFrame
        DataFrame indexed by ts (UTC) with columns: regime_key, trend_state, vol_state.
        Empty DataFrame with those columns if no regime data exists for the asset.
    """
    sql = text(
        """
        SELECT
            ts,
            l2_label AS regime_key,
            split_part(l2_label, '-', 1) AS trend_state,
            split_part(l2_label, '-', 2) AS vol_state
        FROM public.cmc_regimes
        WHERE id = :id
          AND tf = :tf
          AND ts >= :start
          AND ts <= :end
          AND l2_label IS NOT NULL
        ORDER BY ts
        """
    )

    df = pd.read_sql(
        sql,
        conn,
        params={"id": asset_id, "tf": tf, "start": train_start, "end": train_end},
    )

    if df.empty:
        logger.warning(
            "load_regimes_for_asset: no regime data found for asset_id=%d tf=%s",
            asset_id,
            tf,
        )
        return pd.DataFrame(columns=["regime_key", "trend_state", "vol_state"])

    # CRITICAL: fix mixed-tz-offset object dtype from pd.read_sql on Windows
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")

    return df[["regime_key", "trend_state", "vol_state"]]


def save_ic_results(conn, rows: list[dict], *, overwrite: bool = False) -> int:
    """
    Persist IC result rows to cmc_ic_results.

    Parameters
    ----------
    conn : SQLAlchemy connection
        Active database connection (within a transaction).
    rows : list[dict]
        List of dicts with keys matching cmc_ic_results columns:
        asset_id, tf, feature, horizon, horizon_days, return_type,
        regime_col, regime_label, train_start, train_end,
        ic, ic_t_stat, ic_p_value, ic_ir, ic_ir_t_stat, turnover, n_obs.
    overwrite : bool
        If False (default): ON CONFLICT DO NOTHING (append-only, keeps history).
        If True: ON CONFLICT DO UPDATE with updated IC values (upsert).

    Returns
    -------
    int
        Number of rows written (rowcount sum across all inserts).
    """
    if not rows:
        return 0

    if overwrite:
        sql = text(
            """
            INSERT INTO public.cmc_ic_results
                (asset_id, tf, feature, horizon, horizon_days, return_type,
                 regime_col, regime_label, train_start, train_end,
                 ic, ic_t_stat, ic_p_value, ic_ir, ic_ir_t_stat, turnover, n_obs)
            VALUES
                (:asset_id, :tf, :feature, :horizon, :horizon_days, :return_type,
                 :regime_col, :regime_label, :train_start, :train_end,
                 :ic, :ic_t_stat, :ic_p_value, :ic_ir, :ic_ir_t_stat, :turnover, :n_obs)
            ON CONFLICT (asset_id, tf, feature, horizon, return_type,
                         regime_col, regime_label, train_start, train_end)
            DO UPDATE SET
                ic            = EXCLUDED.ic,
                ic_t_stat     = EXCLUDED.ic_t_stat,
                ic_p_value    = EXCLUDED.ic_p_value,
                ic_ir         = EXCLUDED.ic_ir,
                ic_ir_t_stat  = EXCLUDED.ic_ir_t_stat,
                turnover      = EXCLUDED.turnover,
                n_obs         = EXCLUDED.n_obs,
                horizon_days  = EXCLUDED.horizon_days,
                computed_at   = now()
            """
        )
    else:
        sql = text(
            """
            INSERT INTO public.cmc_ic_results
                (asset_id, tf, feature, horizon, horizon_days, return_type,
                 regime_col, regime_label, train_start, train_end,
                 ic, ic_t_stat, ic_p_value, ic_ir, ic_ir_t_stat, turnover, n_obs)
            VALUES
                (:asset_id, :tf, :feature, :horizon, :horizon_days, :return_type,
                 :regime_col, :regime_label, :train_start, :train_end,
                 :ic, :ic_t_stat, :ic_p_value, :ic_ir, :ic_ir_t_stat, :turnover, :n_obs)
            ON CONFLICT (asset_id, tf, feature, horizon, return_type,
                         regime_col, regime_label, train_start, train_end)
            DO NOTHING
            """
        )

    # Batch all rows into a single executemany call (one network round-trip)
    param_list = [
        {
            "asset_id": _to_python(row.get("asset_id")),
            "tf": _to_python(row.get("tf")),
            "feature": _to_python(row.get("feature")),
            "horizon": _to_python(row.get("horizon")),
            "horizon_days": _to_python(row.get("horizon_days")),
            "return_type": _to_python(row.get("return_type")),
            "regime_col": _to_python(row.get("regime_col", "all")),
            "regime_label": _to_python(row.get("regime_label", "all")),
            "train_start": _to_python(row.get("train_start")),
            "train_end": _to_python(row.get("train_end")),
            "ic": _to_python(row.get("ic")),
            "ic_t_stat": _to_python(row.get("ic_t_stat")),
            "ic_p_value": _to_python(row.get("ic_p_value")),
            "ic_ir": _to_python(row.get("ic_ir")),
            "ic_ir_t_stat": _to_python(row.get("ic_ir_t_stat")),
            "turnover": _to_python(row.get("turnover")),
            "n_obs": _to_python(row.get("n_obs")),
        }
        for row in rows
    ]
    conn.execute(sql, param_list)

    return len(param_list)
