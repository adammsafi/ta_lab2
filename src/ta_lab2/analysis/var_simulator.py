"""
VaR (Value at Risk) simulation library.

Pure computation module -- no DB, no CLI, no pandas, no vectorbt.
Used by the loss limits CLI in Plan 02.

Methods implemented:
    historical_var         - Empirical percentile method
    parametric_var_normal  - Gaussian parametric method
    cornish_fisher_var     - Cornish-Fisher expansion (Favre & Galeano 2002)
    historical_cvar        - Expected Shortfall (mean of tail losses)
    garch_var              - GARCH conditional VaR with Student's t (Phase 81)

All functions return negative floats representing losses
(e.g. -0.05 means a 5% loss at the specified confidence level).

Reference:
    Favre, L. & Galeano, J.A. (2002). Mean-Modified Value-at-Risk Optimization
    with Hedge Funds. Journal of Alternative Investments, 5(2), 21-25.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.stats import kurtosis as scipy_kurtosis
from scipy.stats import norm
from scipy.stats import skew as scipy_skew
from scipy.stats import t as student_t

logger = logging.getLogger(__name__)

# Cornish-Fisher reliability threshold: excess kurtosis above this value
# may produce non-monotonic quantile transformations.
_CF_KURTOSIS_WARN_THRESHOLD = 8.0

# Maximum daily loss cap (sanity ceiling): 15%
_MAX_DAILY_CAP = 0.15

# Supported var_to_daily_cap method names
_VALID_METHODS = frozenset(
    {"historical_95", "historical_99", "cf_95", "cf_99", "garch_95", "garch_99"}
)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class VaRResult:
    """Container for a full VaR suite computed for one (strategy, asset) pair."""

    strategy: str
    asset_id: int
    confidence: float
    historical_var: float
    parametric_var_normal: float
    cornish_fisher_var: float
    historical_cvar: float
    n_observations: int
    skewness: float
    excess_kurtosis: float
    cf_reliable: bool  # False when abs(excess_kurtosis) > _CF_KURTOSIS_WARN_THRESHOLD
    garch_var_value: float | None = (
        None  # GARCH conditional VaR (None if not available)
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _to_array(returns: Sequence[float] | np.ndarray) -> np.ndarray:
    """Convert any array-like to a 1-D float64 numpy array."""
    return np.asarray(returns, dtype=np.float64).ravel()


# ---------------------------------------------------------------------------
# Core VaR functions
# ---------------------------------------------------------------------------


def historical_var(
    returns: Sequence[float] | np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Empirical (historical simulation) VaR at the given confidence level.

    Uses the (1 - confidence) percentile of the returns distribution.

    Args:
        returns:    1-D array of period returns (arithmetic, e.g. 0.01 = +1%).
        confidence: Confidence level, e.g. 0.95 for 95% VaR.

    Returns:
        Negative float representing the loss quantile.
        E.g. -0.05 means 95% VaR is 5% loss.
    """
    arr = _to_array(returns)
    return float(np.percentile(arr, (1.0 - confidence) * 100.0))


def parametric_var_normal(
    returns: Sequence[float] | np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Gaussian (normal) parametric VaR.

    Assumes returns are normally distributed: VaR = mu + z * sigma
    where z = norm.ppf(1 - confidence).

    Args:
        returns:    1-D array of period returns.
        confidence: Confidence level.

    Returns:
        Negative float (loss) when mu is small relative to the tail.
    """
    arr = _to_array(returns)
    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=1))
    z = float(norm.ppf(1.0 - confidence))
    return mu + z * sigma


def cornish_fisher_var(
    returns: Sequence[float] | np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Cornish-Fisher modified VaR.

    Adjusts the Gaussian z-score using higher moments (skewness and excess
    kurtosis) per the Cornish-Fisher expansion:

        z_cf = z + (z^2 - 1)*s/6 + (z^3 - 3z)*k/24 - (2z^3 - 5z)*s^2/36

    where s = skewness, k = excess kurtosis (Fisher), z = norm.ppf(1-confidence).

    Falls back to the historical VaR and logs a WARNING when
    abs(excess_kurtosis) > 8, as the CF expansion may become non-monotonic.

    Args:
        returns:    1-D array of period returns.
        confidence: Confidence level.

    Returns:
        Negative float representing the modified loss quantile.
    """
    arr = _to_array(returns)
    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=1))
    s = float(scipy_skew(arr))
    # fisher=True gives excess kurtosis (normal = 0)
    k = float(scipy_kurtosis(arr, fisher=True))

    if abs(k) > _CF_KURTOSIS_WARN_THRESHOLD:
        logger.warning(
            "cornish_fisher_var: excess kurtosis %.2f > %.0f -- "
            "CF expansion may be non-monotonic; falling back to historical VaR.",
            k,
            _CF_KURTOSIS_WARN_THRESHOLD,
        )
        return historical_var(arr, confidence)

    z = float(norm.ppf(1.0 - confidence))
    z_cf = (
        z
        + (z**2 - 1.0) * s / 6.0
        + (z**3 - 3.0 * z) * k / 24.0
        - (2.0 * z**3 - 5.0 * z) * s**2 / 36.0
    )
    return mu + z_cf * sigma


def historical_cvar(
    returns: Sequence[float] | np.ndarray,
    confidence: float = 0.95,
) -> float:
    """Historical CVaR (Conditional VaR / Expected Shortfall).

    Computes the mean of all returns that are at or below the historical VaR
    threshold (the tail mean).

    Args:
        returns:    1-D array of period returns.
        confidence: Confidence level, matching the VaR confidence.

    Returns:
        Negative float (mean tail loss). Returns VaR itself when no
        observations fall below the threshold (edge case with very few rows).
    """
    arr = _to_array(returns)
    var = historical_var(arr, confidence)
    tail = arr[arr <= var]
    if len(tail) == 0:
        # Edge case: no observations in tail (can happen with tiny datasets)
        return var
    return float(np.mean(tail))


def garch_var(
    sigma_forecast: float,
    confidence: float = 0.95,
    mu: float = 0.0,
    dist: str = "studentst",
    df: float = 6.0,
) -> float:
    """GARCH conditional VaR.

    Uses the GARCH-forecasted conditional volatility to compute VaR via
    the distribution quantile: ``VaR = mu + sigma * q_alpha``.

    The default distribution is Student's t (``dist="studentst"``), which
    better captures the fat tails typical of crypto returns.

    Args:
        sigma_forecast: Daily conditional vol from GARCH (decimal, e.g. 0.03 = 3%).
        confidence:     Confidence level (default 0.95 for 95% VaR).
        mu:             Expected daily return (default 0 for conservative estimate).
        dist:           Distribution -- ``"normal"`` or ``"studentst"`` (default).
        df:             Degrees of freedom for Student's t (default 6.0, typical
                        for crypto).  Ignored when ``dist="normal"``.

    Returns:
        Negative float representing the loss quantile, consistent with the
        existing VaR functions in this module.

    Raises:
        ValueError: If sigma_forecast <= 0, confidence not in (0, 1), or
                    dist is not one of ``"normal"`` / ``"studentst"``.
    """
    if sigma_forecast <= 0:
        raise ValueError(f"garch_var: sigma_forecast must be > 0, got {sigma_forecast}")
    if not (0.0 < confidence < 1.0):
        raise ValueError(f"garch_var: confidence must be in (0, 1), got {confidence}")

    alpha = 1.0 - confidence

    if dist == "normal":
        q = float(norm.ppf(alpha))
    elif dist == "studentst":
        # Student's t quantile, then scale by sqrt((df-2)/df) to match
        # unit-variance convention (so sigma_forecast maps directly to vol).
        raw_q = float(student_t.ppf(alpha, df=df))
        # Student's t with df dof has variance df/(df-2). Scale the
        # quantile so that the resulting VaR corresponds to sigma_forecast
        # being the *standard deviation*, not the t-scale parameter.
        scale_factor = np.sqrt((df - 2.0) / df) if df > 2 else 1.0
        q = raw_q * scale_factor
    else:
        raise ValueError(
            f"garch_var: dist must be 'normal' or 'studentst', got {dist!r}"
        )

    return float(mu + q * sigma_forecast)


# ---------------------------------------------------------------------------
# Suite function
# ---------------------------------------------------------------------------


def compute_var_suite(
    returns: Sequence[float] | np.ndarray,
    strategy: str,
    asset_id: int,
    confidence: float = 0.95,
    garch_sigma: float | None = None,
    garch_dist: str = "studentst",
    garch_df: float = 6.0,
) -> VaRResult:
    """Compute the full VaR suite for a given returns series.

    Calls historical_var, parametric_var_normal, cornish_fisher_var, and
    historical_cvar in one shot and returns a VaRResult dataclass.

    When *garch_sigma* is provided, also computes GARCH conditional VaR
    via :func:`garch_var` and stores it in
    :attr:`VaRResult.garch_var_value`.

    Args:
        returns:      1-D array of period returns.
        strategy:     Human-readable strategy name (e.g. "ema_trend_17_77").
        asset_id:     Integer asset ID from dim_assets.
        confidence:   Confidence level (default 0.95).
        garch_sigma:  Optional GARCH conditional volatility forecast (decimal).
                      When provided, ``garch_var_value`` is populated.
        garch_dist:   Distribution for GARCH-VaR -- ``"normal"`` or
                      ``"studentst"`` (default).
        garch_df:     Student's t degrees of freedom (default 6.0).

    Returns:
        VaRResult populated with all VaR metrics and distribution stats.
        ``garch_var_value`` is None when ``garch_sigma`` is not provided.
    """
    arr = _to_array(returns)
    s = float(scipy_skew(arr))
    k = float(scipy_kurtosis(arr, fisher=True))  # excess kurtosis
    cf_reliable = abs(k) <= _CF_KURTOSIS_WARN_THRESHOLD

    garch_var_value: float | None = None
    if garch_sigma is not None and garch_sigma > 0:
        mu_hat = float(np.mean(arr))
        garch_var_value = garch_var(
            garch_sigma,
            confidence=confidence,
            mu=mu_hat,
            dist=garch_dist,
            df=garch_df,
        )

    return VaRResult(
        strategy=strategy,
        asset_id=asset_id,
        confidence=confidence,
        historical_var=historical_var(arr, confidence),
        parametric_var_normal=parametric_var_normal(arr, confidence),
        cornish_fisher_var=cornish_fisher_var(arr, confidence),
        historical_cvar=historical_cvar(arr, confidence),
        n_observations=len(arr),
        skewness=s,
        excess_kurtosis=k,
        cf_reliable=cf_reliable,
        garch_var_value=garch_var_value,
    )


# ---------------------------------------------------------------------------
# Cap translation
# ---------------------------------------------------------------------------


def var_to_daily_cap(
    var_results: list[VaRResult],
    method: str = "historical_95",
) -> float:
    """Translate a list of VaRResult objects into a single daily loss cap.

    Takes the median absolute VaR value across all strategies, then caps at
    _MAX_DAILY_CAP (15%) as a sanity ceiling.

    Args:
        var_results: List of VaRResult instances (one per strategy/asset).
        method:      Which VaR field to use. One of:
                     "historical_95" | "historical_99" | "cf_95" | "cf_99" |
                     "garch_95" | "garch_99"
                     Note: "_99" variants require that var_results were computed
                     with confidence=0.99. "garch_*" variants require that
                     garch_sigma was provided to compute_var_suite.

    Returns:
        Positive float: daily loss cap as a fraction (e.g. 0.05 = 5%).

    Raises:
        ValueError: If method is not one of the supported options or
                    var_results is empty.
    """
    if not var_results:
        raise ValueError("var_to_daily_cap: var_results must not be empty")
    if method not in _VALID_METHODS:
        raise ValueError(
            f"var_to_daily_cap: unsupported method '{method}'. "
            f"Choose from: {sorted(_VALID_METHODS)}"
        )

    if method.startswith("historical"):
        values = [abs(r.historical_var) for r in var_results]
    elif method.startswith("garch"):
        values = [
            abs(r.garch_var_value) for r in var_results if r.garch_var_value is not None
        ]
        if not values:
            raise ValueError(
                f"var_to_daily_cap: method is '{method}' but no results have "
                "garch_var_value populated. Provide garch_sigma to compute_var_suite."
            )
    else:  # cf_*
        values = [abs(r.cornish_fisher_var) for r in var_results]

    cap = float(np.median(values))

    if cap > _MAX_DAILY_CAP:
        logger.warning(
            "var_to_daily_cap: computed cap %.4f exceeds maximum %.2f -- "
            "capping at %.2f.",
            cap,
            _MAX_DAILY_CAP,
            _MAX_DAILY_CAP,
        )
        cap = _MAX_DAILY_CAP

    return cap
