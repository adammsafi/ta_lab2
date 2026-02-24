"""
Probabilistic Sharpe Ratio (PSR), Deflated Sharpe Ratio (DSR), and Minimum
Track Record Length (MinTRL) formulas.

Reference: Bailey & Lopez de Prado, "The Sharpe Ratio Efficient Frontier"
           SSRN 1821643 (2012).

Critical convention: All kurtosis calculations use Pearson kurtosis
(fisher=False in scipy), NOT the default Fisher/excess kurtosis.
For a normal distribution: Pearson kurtosis = 3, Fisher kurtosis = 0.
Using Fisher kurtosis in the PSR variance formula produces incorrect results
because the formula expects gamma_4 ≈ 3 for normal data.

Exports:
    compute_psr       - Probabilistic Sharpe Ratio
    expected_max_sr   - Expected maximum SR across N trials
    compute_dsr       - Deflated Sharpe Ratio
    min_trl           - Minimum Track Record Length
"""

from __future__ import annotations

import math
import warnings
from typing import Sequence

import numpy as np
from scipy.stats import kurtosis, norm, skew


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _to_array(returns: Sequence[float] | np.ndarray) -> np.ndarray:
    """Convert any array-like to a 1-D float64 numpy array."""
    return np.asarray(returns, dtype=np.float64).ravel()


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def compute_psr(
    returns: Sequence[float] | np.ndarray,
    sr_star: float = 0.0,
) -> float:
    """
    Probabilistic Sharpe Ratio.

    Probability that the true (population) Sharpe ratio exceeds the benchmark
    sr_star, given the observed returns series.

    The formula accounts for non-normality of returns via skewness (gamma_3)
    and Pearson kurtosis (gamma_4, fisher=False).  For normal returns
    gamma_3=0, gamma_4=3 so the variance simplifies to (1+SR^2/2)/(n-1).

    Args:
        returns:  Per-bar returns (not annualised).  Accepts np.ndarray,
                  pd.Series, or plain list.
        sr_star:  Benchmark Sharpe ratio in the SAME per-bar units as the
                  observed returns.  Default 0.0.

    Returns:
        float in [0, 1]: probability that the true SR exceeds sr_star.
        Returns NaN when n < 30 (insufficient data guard).

    Warns:
        UserWarning when n < 30 (returns NaN).
        UserWarning when n < 100 (estimate may be unreliable).

    Zero-std guard (std == 0.0, i.e. constant returns):
        SR is undefined; we treat it as zero and compare with sr_star:
        - sr_star == 0.0 → return 0.5  (z = 0, CDF = 0.5)
        - sr_star > 0.0  → return 0.0  (SR = 0 cannot beat positive benchmark)
        - sr_star < 0.0  → return 1.0  (SR = 0 always beats negative benchmark)
    """
    arr = _to_array(returns)
    n = len(arr)

    # ── Sample size guards ─────────────────────────────────────────────────
    if n < 30:
        warnings.warn(
            f"PSR: n={n} < 30.  Estimate is unreliable — returning NaN.",
            UserWarning,
            stacklevel=2,
        )
        return float("nan")

    if n < 100:
        warnings.warn(
            f"PSR: n={n} < 100.  Estimate may be unreliable.",
            UserWarning,
            stacklevel=2,
        )

    # ── Zero-std guard ─────────────────────────────────────────────────────
    std = float(np.std(arr, ddof=1))
    if std == 0.0:
        if sr_star == 0.0:
            return 0.5
        elif sr_star > 0.0:
            return 0.0
        else:
            return 1.0

    # ── Core PSR formula ──────────────────────────────────────────────────
    sr_hat = float(np.mean(arr)) / std
    gamma_3 = float(skew(arr))
    gamma_4 = float(kurtosis(arr, fisher=False))  # Pearson kurtosis (3 for normal)

    var_sr = (1.0 - gamma_3 * sr_hat + (gamma_4 - 1.0) / 4.0 * sr_hat**2) / (n - 1)

    if var_sr <= 0.0:
        warnings.warn(
            f"PSR: var_sr={var_sr:.6g} <= 0.  Returning NaN.",
            UserWarning,
            stacklevel=2,
        )
        return float("nan")

    z = (sr_hat - sr_star) / math.sqrt(var_sr)
    return float(norm.cdf(z))


def expected_max_sr(
    sr_estimates: Sequence[float],
    expected_mean: float = 0.0,
) -> float:
    """
    Expected maximum Sharpe ratio across N independent trials.

    Uses the Bailey & Lopez de Prado (2012) approximation based on the
    expected maximum of a normal distribution.

    Args:
        sr_estimates:   List of observed Sharpe ratios from N trials.
        expected_mean:  Expected mean of the Sharpe ratio distribution.
                        Default 0.0 (assume mean-zero distribution of SRs).

    Returns:
        float: expected maximum SR across the N trials.
    """
    sr_arr = np.asarray(sr_estimates, dtype=np.float64)
    n = len(sr_arr)

    if n == 0:
        return float("nan")

    if n == 1:
        # With one trial the expected maximum is just that estimate
        # (formula degenerates: ppf(1-1/1) = ppf(0) = -inf)
        return float(sr_arr[0])

    euler_gamma = 0.5772156649015329
    e = math.e

    # Std of SR estimates relative to the expected mean
    std_sr = float(np.std(sr_arr - expected_mean, ddof=1))

    if std_sr == 0.0:
        return float(np.mean(sr_arr))

    # E[max] = mean + std * ((1-γ)*Φ^{-1}(1-1/N) + γ*Φ^{-1}(1-1/(N·e)))
    term1 = (1.0 - euler_gamma) * norm.ppf(1.0 - 1.0 / n)
    term2 = euler_gamma * norm.ppf(1.0 - 1.0 / (n * e))
    e_max = expected_mean + std_sr * (term1 + term2)
    return float(e_max)


def compute_dsr(
    best_trial_returns: Sequence[float] | np.ndarray,
    sr_estimates: Sequence[float] | None = None,
    n_trials: int | None = None,
    sr_star_override: float | None = None,
) -> float:
    """
    Deflated Sharpe Ratio.

    Adjusts the PSR for selection bias across multiple strategy trials by
    setting the benchmark equal to the expected maximum SR across all trials.

    Two modes:
    - Exact mode (sr_estimates provided): uses the observed distribution of
      SR estimates across trials to compute expected_max_sr.
    - Approximate mode (n_trials provided): Bailey approximation assuming
      SRs are drawn from N(0, 1).

    Args:
        best_trial_returns:  Returns series of the best-performing trial.
        sr_estimates:        List of SR values from all N trials (exact mode).
        n_trials:            Number of independent trials tested (approx mode).
        sr_star_override:    If provided, bypass the computed benchmark and
                             use this value directly as sr_star.

    Returns:
        float in [0, 1]: DSR value.

    Raises:
        ValueError: if neither sr_estimates nor n_trials is provided.
    """
    if sr_star_override is not None:
        benchmark = sr_star_override
    elif sr_estimates is not None:
        benchmark = expected_max_sr(sr_estimates)
    elif n_trials is not None:
        # Bailey approximation: assume SR ~ N(0,1) across n_trials
        # E[max_SR] using expected_max_sr with synthetic draws from N(0,1)
        rng = np.random.default_rng(42)
        synthetic = rng.standard_normal(n_trials).tolist()
        benchmark = expected_max_sr(synthetic)
    else:
        raise ValueError(
            "compute_dsr requires either sr_estimates (list of SR values) "
            "or n_trials (int). Neither was provided."
        )

    return compute_psr(best_trial_returns, sr_star=benchmark)


def min_trl(
    returns: Sequence[float] | np.ndarray,
    sr_star: float = 0.0,
    target_psr: float = 0.95,
    freq_per_year: int = 365,
) -> dict:
    """
    Minimum Track Record Length.

    Computes the minimum number of observations (bars) and approximate
    calendar days required so that the PSR exceeds target_psr at the
    observed moments.

    Args:
        returns:        Per-bar returns series.
        sr_star:        Benchmark Sharpe ratio (per-bar units).  Default 0.0.
        target_psr:     Desired PSR threshold (probability).  Default 0.95.
        freq_per_year:  Trading bars per year (e.g. 365 for daily crypto,
                        252 for equities).  Used to convert n_obs to days.

    Returns:
        dict with keys:
            n_obs          – minimum observations required (float; inf if
                             sr_hat <= sr_star)
            calendar_days  – approximate calendar days (int or inf)
            sr_hat         – observed per-bar Sharpe ratio
            target_psr     – echoed back for convenience
    """
    arr = _to_array(returns)
    std = float(np.std(arr, ddof=1))
    sr_hat = float(np.mean(arr)) / std if std > 0.0 else 0.0

    result_inf: dict = {
        "n_obs": float("inf"),
        "calendar_days": float("inf"),
        "sr_hat": sr_hat,
        "target_psr": target_psr,
    }

    # Cannot beat benchmark → TRL is infinite
    if sr_hat <= sr_star:
        return result_inf

    gamma_3 = float(skew(arr))
    gamma_4 = float(kurtosis(arr, fisher=False))  # Pearson kurtosis

    # Variance factor (numerator of var_sr before dividing by n-1)
    v_factor = 1.0 - gamma_3 * sr_hat + (gamma_4 - 1.0) / 4.0 * sr_hat**2

    if v_factor <= 0.0:
        # Degenerate case; fall back to standard normal approximation
        v_factor = 1.0 + sr_hat**2 / 2.0

    z_threshold = float(norm.ppf(target_psr))

    # Solve: z = (sr_hat - sr_star) / sqrt(v_factor / (n-1)) >= z_threshold
    # → n-1 >= (z_threshold * sqrt(v_factor) / (sr_hat - sr_star))^2
    # → n_obs = (z_threshold * sqrt(v_factor) / (sr_hat - sr_star))^2 + 1
    n_obs = (z_threshold * math.sqrt(v_factor) / (sr_hat - sr_star)) ** 2 + 1.0

    if not math.isfinite(n_obs) or n_obs <= 0:
        return result_inf

    calendar_days = round(math.ceil(n_obs) / freq_per_year * 365)

    return {
        "n_obs": n_obs,
        "calendar_days": calendar_days,
        "sr_hat": sr_hat,
        "target_psr": target_psr,
    }
