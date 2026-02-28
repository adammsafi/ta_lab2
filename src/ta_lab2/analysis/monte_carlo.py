# -*- coding: utf-8 -*-
"""
Monte Carlo trade/return resampling for Sharpe ratio confidence intervals.

Bootstraps trade PnL (or daily returns) by sampling with replacement to produce
a distribution of Sharpe ratios. The 2.5th and 97.5th percentiles of this
distribution form the 95% confidence interval for Sharpe.

This answers: "Is the observed Sharpe ratio robust, or could it be luck?"
A narrow CI (lo near hi) indicates consistency; a wide CI indicates high
path-dependence.

Public API:
    monte_carlo_trades   -- resample trade PnL to get 95% Sharpe CI
    monte_carlo_returns  -- resample daily returns to get 95% Sharpe CI

Usage:
    from ta_lab2.analysis.monte_carlo import monte_carlo_trades, monte_carlo_returns

    result = monte_carlo_trades(trades_df, n_samples=1000, seed=42)
    print(result['mc_sharpe_lo'], result['mc_sharpe_hi'])
"""

from __future__ import annotations

import logging
import math
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Annualization constant: sqrt(365) for calendar-day Sharpe
_ANNUALIZATION_FACTOR: float = math.sqrt(365)

# Minimum trades required before we attempt Monte Carlo (guard against noise)
_MIN_TRADES: int = 10

# Minimum returns observations required for monte_carlo_returns()
_MIN_RETURNS: int = 30


def monte_carlo_trades(
    trades_df: pd.DataFrame,
    n_samples: int = 1000,
    seed: int = 42,
) -> dict:
    """
    Monte Carlo Sharpe ratio confidence interval via trade PnL resampling.

    Resamples trade PnL (with replacement) N times, computing the annualized
    Sharpe for each bootstrap sample. Returns the 2.5th/97.5th percentiles as
    a 95% CI, plus the median.

    Annualized Sharpe = mean(pnl_decimal) / std(pnl_decimal, ddof=1) * sqrt(365).

    Parameters
    ----------
    trades_df : pd.DataFrame
        DataFrame containing a ``pnl_pct`` column with per-trade PnL in
        percentage points (e.g. 2.5 for +2.5%). NaN values are dropped before
        resampling.
    n_samples : int
        Number of bootstrap resamples. Default 1000.
    seed : int
        Random seed for ``numpy.random.default_rng`` reproducibility. Default 42.

    Returns
    -------
    dict
        Keys:
        - mc_sharpe_lo   : float or None — 2.5th percentile of bootstrap Sharpe distribution
        - mc_sharpe_hi   : float or None — 97.5th percentile of bootstrap Sharpe distribution
        - mc_sharpe_median: float or None — median of bootstrap Sharpe distribution
        - mc_n_samples   : int — number of bootstrap samples with non-zero std
        - n_trades       : int — number of closed trades used in resampling

        All float values are None when fewer than 10 trades are available.

    Notes
    -----
    - pnl_pct is divided by 100 internally to convert to decimal returns.
    - Bootstrap sample size equals n_trades (same size as original, with replacement).
    - Samples where std == 0 are skipped (e.g. all-same PnL resamples).
    - Uses numpy.random.default_rng(seed) for reproducibility.
    """
    if "pnl_pct" not in trades_df.columns:
        logger.warning(
            "monte_carlo_trades: 'pnl_pct' column not found in trades_df — returning None CI"
        )
        return _none_result(n_samples=n_samples, n_trades=0)

    # Drop NaN, convert percentage to decimal
    pnl_arr = trades_df["pnl_pct"].dropna().values / 100.0
    n_trades = len(pnl_arr)

    if n_trades < _MIN_TRADES:
        logger.info(
            "monte_carlo_trades: only %d trades (min=%d) — returning None CI",
            n_trades,
            _MIN_TRADES,
        )
        return _none_result(n_samples=n_samples, n_trades=n_trades)

    sharpe_arr = _bootstrap_sharpe(pnl_arr, n_trades, n_samples, seed)

    if len(sharpe_arr) == 0:
        logger.warning(
            "monte_carlo_trades: all bootstrap samples had zero std — returning None CI"
        )
        return _none_result(n_samples=n_samples, n_trades=n_trades)

    lo, hi = np.percentile(sharpe_arr, [2.5, 97.5])
    median = float(np.median(sharpe_arr))

    logger.debug(
        "monte_carlo_trades: n_trades=%d mc_sharpe_lo=%.4f mc_sharpe_hi=%.4f median=%.4f "
        "n_valid_samples=%d",
        n_trades,
        lo,
        hi,
        median,
        len(sharpe_arr),
    )

    return {
        "mc_sharpe_lo": float(lo),
        "mc_sharpe_hi": float(hi),
        "mc_sharpe_median": median,
        "mc_n_samples": len(sharpe_arr),
        "n_trades": n_trades,
    }


def monte_carlo_returns(
    returns_series: pd.Series,
    n_samples: int = 1000,
    seed: int = 42,
) -> dict:
    """
    Monte Carlo Sharpe ratio confidence interval via daily return resampling.

    Same bootstrap logic as ``monte_carlo_trades`` but operates on a pd.Series
    of daily returns (already in decimal form, e.g. 0.025 for +2.5%).

    Parameters
    ----------
    returns_series : pd.Series
        Daily return values in decimal form. NaN values are dropped before
        resampling.
    n_samples : int
        Number of bootstrap resamples. Default 1000.
    seed : int
        Random seed for reproducibility. Default 42.

    Returns
    -------
    dict
        Same keys as monte_carlo_trades():
        mc_sharpe_lo, mc_sharpe_hi, mc_sharpe_median, mc_n_samples, n_trades.

        All float values are None when fewer than 30 observations are available.

    Notes
    -----
    - Returns are treated as calendar-day returns; annualization uses sqrt(365).
    - Sample size equals n_obs (same size as original, with replacement).
    - Uses numpy.random.default_rng(seed) for reproducibility.
    """
    returns_arr = returns_series.dropna().values
    n_obs = len(returns_arr)

    if n_obs < _MIN_RETURNS:
        logger.info(
            "monte_carlo_returns: only %d observations (min=%d) — returning None CI",
            n_obs,
            _MIN_RETURNS,
        )
        return _none_result(n_samples=n_samples, n_trades=n_obs)

    sharpe_arr = _bootstrap_sharpe(returns_arr, n_obs, n_samples, seed)

    if len(sharpe_arr) == 0:
        logger.warning(
            "monte_carlo_returns: all bootstrap samples had zero std — returning None CI"
        )
        return _none_result(n_samples=n_samples, n_trades=n_obs)

    lo, hi = np.percentile(sharpe_arr, [2.5, 97.5])
    median = float(np.median(sharpe_arr))

    logger.debug(
        "monte_carlo_returns: n_obs=%d mc_sharpe_lo=%.4f mc_sharpe_hi=%.4f median=%.4f "
        "n_valid_samples=%d",
        n_obs,
        lo,
        hi,
        median,
        len(sharpe_arr),
    )

    return {
        "mc_sharpe_lo": float(lo),
        "mc_sharpe_hi": float(hi),
        "mc_sharpe_median": median,
        "mc_n_samples": len(sharpe_arr),
        "n_trades": n_obs,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _bootstrap_sharpe(
    values: np.ndarray,
    sample_size: int,
    n_samples: int,
    seed: int,
) -> np.ndarray:
    """
    Bootstrap Sharpe ratio distribution via resampling with replacement.

    Parameters
    ----------
    values : np.ndarray
        1-D array of return values (decimal, NOT percentage).
    sample_size : int
        Number of elements in each bootstrap sample (equals len(values)).
    n_samples : int
        Number of bootstrap iterations.
    seed : int
        Seed for numpy.random.default_rng.

    Returns
    -------
    np.ndarray
        Array of annualized Sharpe ratios (one per valid sample).
        Samples where std == 0 are excluded (empty array if all zero-std).
    """
    rng = np.random.default_rng(seed)
    sharpe_list: list[float] = []

    for _ in range(n_samples):
        sample = rng.choice(values, size=sample_size, replace=True)
        std = sample.std(ddof=1)
        if std == 0:
            continue
        sharpe = sample.mean() / std * _ANNUALIZATION_FACTOR
        sharpe_list.append(float(sharpe))

    return np.array(sharpe_list)


def _none_result(n_samples: int, n_trades: int) -> dict:
    """
    Return a result dict with all CI values set to None.

    Used when insufficient data prevents meaningful Monte Carlo estimation.

    Parameters
    ----------
    n_samples : int
        Requested number of bootstrap samples (stored for reference).
    n_trades : int
        Actual number of trades/observations available.

    Returns
    -------
    dict
        mc_sharpe_lo=None, mc_sharpe_hi=None, mc_sharpe_median=None,
        mc_n_samples=n_samples, n_trades=n_trades.
    """
    return {
        "mc_sharpe_lo": None,
        "mc_sharpe_hi": None,
        "mc_sharpe_median": None,
        "mc_n_samples": n_samples,
        "n_trades": n_trades,
    }
