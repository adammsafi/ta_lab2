"""
Core GARCH fitting and forecasting engine (Phase 81, GARCH-01).

Provides:
- fit_single_variant: fit one GARCH variant to a returns series
- fit_all_variants: fit all four GARCH variants in one call
- generate_forecasts: produce h1/h5 conditional volatility forecasts
- compute_ljung_box_pvalue: residual autocorrelation diagnostic
- GARCHResult: dataclass with fit metrics and forecasts
- MODEL_SPECS: dict mapping model_type strings to arch_model kwargs

Model types:
  garch_1_1       - Standard GARCH(1,1), analytic multi-step forecasts
  gjr_garch_1_1   - GJR-GARCH(1,1), leverage asymmetry, analytic forecasts
  egarch_1_1      - EGARCH(1,1), simulation-based multi-step forecasts
  figarch_1_d_1   - FIGARCH(1,d,1), long memory, simulation forecasts, 200-obs gate

Implementation notes:
- Returns are scaled by 100 before fitting (convergence aid for daily crypto returns)
- Student's t distribution used for all variants (fat tails in crypto)
- rescale=True as additional convergence aid (arch library built-in)
- Variances and conditional_volatility are unscaled back to decimal space (divide by 10000)
- FIGARCH requires 200 observations minimum (DEFAULT_MIN_OBS is 126 for other models)

This module has no DB dependencies -- pure computation only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# Lazy import so the module is importable even without arch installed.
# (Matches project pattern in vol_sizer.py with vectorbt.)
try:
    from arch import arch_model as _arch_model  # type: ignore[import]
except ImportError:  # pragma: no cover
    _arch_model = None  # type: ignore[assignment]

try:
    from statsmodels.stats.diagnostic import acorr_ljungbox  # type: ignore[import]
except ImportError:  # pragma: no cover
    acorr_ljungbox = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Minimum observations required for FIGARCH (long-memory model needs more history).
#: Research recommends 200-250; 200 is used to maximise asset coverage while
#: maintaining convergence reliability.
FIGARCH_MIN_OBS: int = 200

#: Minimum observations for standard GARCH variants (~6 months of daily bars).
DEFAULT_MIN_OBS: int = 126

#: arch_model keyword arguments for each supported model type.
MODEL_SPECS: dict[str, dict[str, Any]] = {
    "garch_1_1": {"vol": "GARCH", "p": 1, "o": 0, "q": 1},
    "gjr_garch_1_1": {"vol": "GARCH", "p": 1, "o": 1, "q": 1},
    "egarch_1_1": {"vol": "EGARCH", "p": 1, "o": 1, "q": 1},
    "figarch_1_d_1": {"vol": "FIGARCH", "p": 1, "q": 1},
}

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class GARCHResult:
    """Container for a single GARCH variant fit and forecast results.

    Fields are populated by fit_single_variant and generate_forecasts.
    None values indicate the model did not converge or forecasting failed.
    """

    model_type: str
    converged: bool
    n_obs: int
    convergence_flag: int | None = None
    aic: float | None = None
    bic: float | None = None
    loglikelihood: float | None = None
    ljung_box_pvalue: float | None = None
    # Forecast outputs (populated by generate_forecasts)
    h1_vol: float | None = None
    h5_vol: float | None = None
    # In-sample conditional volatility series (unscaled, decimal)
    conditional_volatility: np.ndarray | None = field(default=None, repr=False)
    error_msg: str | None = None


# ---------------------------------------------------------------------------
# Ljung-Box helper
# ---------------------------------------------------------------------------


def compute_ljung_box_pvalue(std_resid: np.ndarray, lags: int = 10) -> float:
    """Compute the minimum Ljung-Box p-value across ``lags`` lags.

    Parameters
    ----------
    std_resid:
        Standardised residuals from a fitted GARCH model.
    lags:
        Number of lags to test (default 10).

    Returns
    -------
    float
        Minimum p-value across all tested lags. Low values (<0.05) indicate
        residual autocorrelation, suggesting the model is mis-specified.
    """
    if acorr_ljungbox is None:  # pragma: no cover
        logger.warning("statsmodels not available -- skipping Ljung-Box test")
        return float("nan")

    lb = acorr_ljungbox(std_resid, lags=lags, return_df=True)
    return float(lb["lb_pvalue"].min())


# ---------------------------------------------------------------------------
# Forecast helper
# ---------------------------------------------------------------------------


def generate_forecasts(
    fit_result: Any, model_type: str, horizon: int = 5
) -> dict[str, Any]:
    """Generate h1 and h5 conditional volatility forecasts from a fitted model.

    Parameters
    ----------
    fit_result:
        A fitted arch model result object (``arch.univariate.base.ARCHModelResult``).
    model_type:
        One of the keys in MODEL_SPECS.
    horizon:
        Maximum forecast horizon (default 5 days).

    Returns
    -------
    dict with keys:
        h1_vol   - 1-step-ahead conditional vol (decimal, e.g. 0.03 = 3%)
        h5_vol   - 5-step-ahead conditional vol (decimal)
        method_h5 - 'analytic' or 'simulation'
        error    - error message string if forecasting failed, else None
    """
    analytic_models = {"garch_1_1", "gjr_garch_1_1"}

    try:
        if model_type in analytic_models or horizon <= 1:
            method = "analytic"
            forecasts = fit_result.forecast(
                horizon=horizon, method="analytic", reindex=False
            )
        else:
            # EGARCH and FIGARCH: simulation-based for multi-step (analytic not supported)
            method = "simulation"
            forecasts = fit_result.forecast(
                horizon=horizon,
                method="simulation",
                simulations=500,
                reindex=False,
            )

        # forecasts.variance is a DataFrame with shape (1, horizon)
        # Values are in (100 * decimal)^2 scale because we scaled returns * 100
        var_df = forecasts.variance
        h1_var_scaled = float(var_df.iloc[-1, 0])
        h5_var_scaled = float(var_df.iloc[-1, -1])

        # Unscale: divide by 100^2 = 10000, then sqrt to get vol in decimal
        h1_vol = float(np.sqrt(h1_var_scaled / 10_000))
        h5_vol = float(np.sqrt(h5_var_scaled / 10_000))

        return {"h1_vol": h1_vol, "h5_vol": h5_vol, "method_h5": method, "error": None}

    except Exception as exc:  # pragma: no cover
        logger.warning("GARCH forecast failed for %s: %s", model_type, exc)
        return {"h1_vol": None, "h5_vol": None, "method_h5": None, "error": str(exc)}


# ---------------------------------------------------------------------------
# Single-variant fitter
# ---------------------------------------------------------------------------


def fit_single_variant(returns_decimal: np.ndarray, model_type: str) -> GARCHResult:
    """Fit one GARCH variant to a returns array.

    Parameters
    ----------
    returns_decimal:
        Daily returns expressed as decimals (e.g. 0.03 for 3%).
        Must be a 1-D numpy array.
    model_type:
        One of: 'garch_1_1', 'gjr_garch_1_1', 'egarch_1_1', 'figarch_1_d_1'.

    Returns
    -------
    GARCHResult
        If fitting fails or the model does not converge, ``converged`` is False
        and ``error_msg`` contains the reason. Forecasts (h1_vol, h5_vol) are
        populated for converged models.
    """
    if _arch_model is None:
        return GARCHResult(
            model_type=model_type,
            converged=False,
            n_obs=len(returns_decimal),
            error_msg="arch library not installed; run: pip install 'arch>=8.0.0'",
        )

    n_obs = len(returns_decimal)

    # FIGARCH gate: requires more data than standard GARCH
    min_req = FIGARCH_MIN_OBS if model_type == "figarch_1_d_1" else DEFAULT_MIN_OBS
    if n_obs < min_req:
        return GARCHResult(
            model_type=model_type,
            converged=False,
            n_obs=n_obs,
            error_msg=(
                f"Insufficient data: {n_obs} obs < {min_req} required for {model_type}"
            ),
        )

    if model_type not in MODEL_SPECS:
        return GARCHResult(
            model_type=model_type,
            converged=False,
            n_obs=n_obs,
            error_msg=f"Unknown model_type '{model_type}'; choose from {list(MODEL_SPECS)}",
        )

    # Scale returns by 100 to aid numerical convergence (GARCH convergence anti-pattern #1)
    returns_scaled = returns_decimal * 100.0
    spec = MODEL_SPECS[model_type]

    try:
        model = _arch_model(
            returns_scaled,
            mean="Zero",
            dist="StudentsT",
            rescale=True,
            **spec,
        )
        fit = model.fit(
            disp="off",
            show_warning=False,
            options={"maxiter": 500, "ftol": 1e-9},
        )

        convergence_flag = int(fit.optimization_result.get("status", 1))
        converged = convergence_flag == 0

        if not converged:
            logger.debug(
                "GARCH %s did not converge (flag=%d): %s",
                model_type,
                convergence_flag,
                fit.optimization_result.get("message", ""),
            )

        # Ljung-Box on standardised residuals
        try:
            std_resid = fit.std_resid
            lb_pvalue = compute_ljung_box_pvalue(std_resid)
        except Exception as lb_exc:  # pragma: no cover
            logger.debug("Ljung-Box failed for %s: %s", model_type, lb_exc)
            lb_pvalue = None

        # Unscale conditional volatility (was fitted on 100x returns, so vol is 100x)
        try:
            cond_vol_scaled = fit.conditional_volatility.values
            cond_vol = cond_vol_scaled / 100.0
        except Exception:  # pragma: no cover
            cond_vol = None

        result = GARCHResult(
            model_type=model_type,
            converged=converged,
            n_obs=n_obs,
            convergence_flag=convergence_flag,
            aic=float(fit.aic),
            bic=float(fit.bic),
            loglikelihood=float(fit.loglikelihood),
            ljung_box_pvalue=float(lb_pvalue) if lb_pvalue is not None else None,
            conditional_volatility=cond_vol,
            error_msg=None if converged else fit.optimization_result.get("message"),
        )

        if converged:
            forecast_out = generate_forecasts(fit, model_type, horizon=5)
            result.h1_vol = forecast_out["h1_vol"]
            result.h5_vol = forecast_out["h5_vol"]

        return result

    except Exception as exc:
        logger.warning("GARCH fit failed for %s: %s", model_type, exc)
        return GARCHResult(
            model_type=model_type,
            converged=False,
            n_obs=n_obs,
            error_msg=str(exc),
        )


# ---------------------------------------------------------------------------
# Batch fitter (all variants)
# ---------------------------------------------------------------------------


def fit_all_variants(
    returns_decimal: np.ndarray,
    min_obs: int = DEFAULT_MIN_OBS,
) -> dict[str, GARCHResult]:
    """Fit all four GARCH variants to the same returns array.

    Parameters
    ----------
    returns_decimal:
        Daily returns in decimal form (e.g. 0.03 = 3%). Must be 1-D numpy array.
    min_obs:
        Minimum observations required. Used for non-FIGARCH models.
        FIGARCH always uses FIGARCH_MIN_OBS regardless of this parameter.

    Returns
    -------
    dict mapping model_type (str) -> GARCHResult.
    All four model types are always present in the returned dict; models with
    insufficient data or convergence failure have converged=False.

    Notes
    -----
    For converged models, h1_vol and h5_vol are merged into the GARCHResult.
    """
    n = len(returns_decimal)

    if n < min_obs:
        logger.warning(
            "fit_all_variants: only %d observations (need %d); all variants skipped",
            n,
            min_obs,
        )
        return {
            mt: GARCHResult(
                model_type=mt,
                converged=False,
                n_obs=n,
                error_msg=f"Insufficient data: {n} obs < {min_obs} required",
            )
            for mt in MODEL_SPECS
        }

    results: dict[str, GARCHResult] = {}
    for model_type in MODEL_SPECS:
        logger.debug("Fitting %s on %d observations", model_type, n)
        results[model_type] = fit_single_variant(returns_decimal, model_type)

    n_converged = sum(1 for r in results.values() if r.converged)
    logger.info(
        "fit_all_variants: %d/%d variants converged on %d obs",
        n_converged,
        len(MODEL_SPECS),
        n,
    )

    return results
