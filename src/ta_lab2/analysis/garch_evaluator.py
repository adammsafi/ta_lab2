"""
GARCH forecast evaluation framework (Phase 81, GARCH-03).

Provides accuracy metrics for comparing GARCH conditional volatility forecasts
against a realized volatility proxy, plus a rolling out-of-sample evaluation
harness.

Exports:
    compute_realized_vol_proxy  - 5-day rolling std as realized vol proxy
    rmse_loss                   - Root Mean Squared Error loss
    qlike_loss                  - Quasi-Likelihood loss (Patton 2011)
    mincer_zarnowitz_r2         - OLS calibration R-squared (MZ regression)
    combined_score              - Weighted RMSE + QLIKE composite metric
    rolling_oos_evaluate        - Expanding-window OOS evaluation for one model
    evaluate_all_models         - Run OOS evaluation for all four GARCH variants

Implementation notes:
- QLIKE clips both sigma^2 and realized^2 to 1e-16 to avoid log(0)/div-by-zero
- Forecast alignment: h=1 forecast from fitting through bar t is evaluated
  against realized vol at bar t+1 (no look-ahead bias)
- garch_engine is imported lazily so this module is usable without arch installed
- statsmodels.api is imported lazily for the same reason

Reference:
    Patton, A.J. (2011). Volatility forecast comparison using imperfect volatility
    proxies. Journal of Econometrics, 160(1), 246-256.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports (optional dependencies)
# ---------------------------------------------------------------------------

try:
    import statsmodels.api as sm  # type: ignore[import]
except ImportError:  # pragma: no cover
    sm = None  # type: ignore[assignment]

# garch_engine imported lazily inside functions to avoid circular import issues
# and to allow this module to be imported without arch installed.


# ---------------------------------------------------------------------------
# Realized volatility proxy
# ---------------------------------------------------------------------------


def compute_realized_vol_proxy(returns: pd.Series, window: int = 5) -> pd.Series:
    """Compute a realized volatility proxy using a rolling standard deviation.

    Uses a 5-day rolling std of returns (daily scale). Single-day squared
    returns are too noisy and Parkinson/Garman-Klass estimators are used as
    *comparison targets*, not as the evaluation benchmark.

    Parameters
    ----------
    returns:
        Daily returns expressed as decimals (e.g. 0.03 = 3%).
        Must have a DatetimeIndex or integer index aligned with forecast series.
    window:
        Rolling window in bars (default 5 = 1 trading week).

    Returns
    -------
    pd.Series
        Realized volatility proxy aligned to the input index. First ``window-1``
        values will be NaN (insufficient data for the rolling window).
    """
    return returns.rolling(window=window, min_periods=window).std()


# ---------------------------------------------------------------------------
# Loss metrics (scalar)
# ---------------------------------------------------------------------------


def rmse_loss(sigma_forecast: np.ndarray, realized_vol: np.ndarray) -> float:
    """Compute Root Mean Squared Error between forecasted and realized vol.

    Parameters
    ----------
    sigma_forecast:
        Predicted conditional volatility (decimal scale, e.g. 0.03 = 3%).
    realized_vol:
        Realized volatility proxy (same scale as sigma_forecast).

    Returns
    -------
    float
        RMSE: sqrt(mean((sigma_forecast - realized_vol)^2)).
        Both inputs are clipped to min 1e-8 before computation.
    """
    f = np.clip(np.asarray(sigma_forecast, dtype=float), 1e-8, None)
    r = np.clip(np.asarray(realized_vol, dtype=float), 1e-8, None)
    return float(np.sqrt(np.mean((f - r) ** 2)))


def qlike_loss(sigma_forecast: np.ndarray, realized_vol: np.ndarray) -> float:
    """Compute Quasi-Likelihood (QLIKE) loss.

    QLIKE = mean(log(sigma^2) + realized^2 / sigma^2) per Patton (2011).

    QLIKE penalises under-prediction of volatility more severely than RMSE,
    which makes it particularly relevant for risk management applications.

    Parameters
    ----------
    sigma_forecast:
        Predicted conditional volatility (decimal scale).
    realized_vol:
        Realized volatility proxy (same scale).

    Returns
    -------
    float
        Mean QLIKE loss. Lower is better. Both sigma^2 and realized^2 are
        clipped to 1e-16 before computation to avoid log(0) and division-by-zero.
    """
    f = np.asarray(sigma_forecast, dtype=float)
    r = np.asarray(realized_vol, dtype=float)
    # Clip variances (squared vols) to avoid log(0) and div-by-zero
    sigma2 = np.clip(f**2, 1e-16, None)
    real2 = np.clip(r**2, 1e-16, None)
    return float(np.mean(np.log(sigma2) + real2 / sigma2))


def mincer_zarnowitz_r2(sigma_forecast: np.ndarray, realized_vol: np.ndarray) -> float:
    """Compute the Mincer-Zarnowitz R-squared (forecast calibration quality).

    Runs the OLS regression:
        realized_vol = alpha + beta * sigma_forecast + epsilon

    A perfect forecast has alpha=0, beta=1, and R2=1.0. R2 measures how much
    of the variation in realized vol is explained by the forecasts.

    Parameters
    ----------
    sigma_forecast:
        Predicted conditional volatility (decimal scale).
    realized_vol:
        Realized volatility proxy (same scale).

    Returns
    -------
    float
        OLS R-squared. Returns NaN if statsmodels is unavailable or if
        there are fewer than 3 observations.
    """
    if sm is None:  # pragma: no cover
        logger.warning("statsmodels not available -- returning NaN for MZ R2")
        return float("nan")

    f = np.asarray(sigma_forecast, dtype=float)
    r = np.asarray(realized_vol, dtype=float)

    if len(f) < 3:
        return float("nan")

    X = sm.add_constant(f)
    try:
        result = sm.OLS(r, X).fit()
        return float(result.rsquared)
    except Exception as exc:  # pragma: no cover
        logger.warning("MZ regression failed: %s", exc)
        return float("nan")


def combined_score(rmse: float, qlike: float, rmse_weight: float = 0.5) -> float:
    """Compute a weighted combination of RMSE and QLIKE.

    Parameters
    ----------
    rmse:
        RMSE loss value.
    qlike:
        QLIKE loss value.
    rmse_weight:
        Weight on RMSE in [0, 1] (default 0.5 = equal weight).
        QLIKE weight = 1 - rmse_weight.

    Returns
    -------
    float
        Combined score. Lower is better.
    """
    return rmse_weight * rmse + (1.0 - rmse_weight) * qlike


# ---------------------------------------------------------------------------
# Rolling OOS evaluation
# ---------------------------------------------------------------------------


def rolling_oos_evaluate(
    returns: pd.Series,
    model_type: str,
    train_window: int = 252,
    eval_window: int = 63,
    step: int = 21,
) -> pd.DataFrame:
    """Run an expanding-window out-of-sample evaluation for one GARCH model.

    For each evaluation step:
    1. Fit GARCH on returns[:train_end] using ``fit_single_variant``
    2. Extract the h=1 conditional volatility forecast
    3. Evaluate against the realized vol proxy at bar train_end+1 (t+1)

    After all steps, cumulative RMSE and QLIKE are computed over the full
    OOS forecast series.

    Parameters
    ----------
    returns:
        Daily returns as a pd.Series (decimal scale). Must have at least
        ``train_window + eval_window`` observations.
    model_type:
        One of: 'garch_1_1', 'gjr_garch_1_1', 'egarch_1_1', 'figarch_1_d_1'.
    train_window:
        Minimum number of bars in the initial training set (default 252).
    eval_window:
        Minimum number of OOS forecast steps to accumulate before computing
        aggregate metrics (default 63 = 1 quarter).
    step:
        Bars between successive OOS evaluations (default 21 = 1 month).
        Smaller step = more evaluation points but higher runtime.

    Returns
    -------
    pd.DataFrame
        Columns: [date, model_type, forecast_vol, realized_vol,
                  rmse_cumulative, qlike_cumulative].
        Each row is one OOS forecast step. Failed steps are skipped with a
        logged warning. Returns empty DataFrame if fewer than train_window+1
        observations.
    """
    # Lazy import to allow module to be used without arch
    try:
        from ta_lab2.analysis.garch_engine import fit_single_variant
    except ImportError:  # pragma: no cover
        logger.error("arch library not installed -- rolling_oos_evaluate requires it")
        return pd.DataFrame(
            columns=[
                "date",
                "model_type",
                "forecast_vol",
                "realized_vol",
                "rmse_cumulative",
                "qlike_cumulative",
            ]
        )

    n = len(returns)
    if n < train_window + 1:
        logger.warning(
            "rolling_oos_evaluate: only %d observations; need at least %d for model %s",
            n,
            train_window + 1,
            model_type,
        )
        return pd.DataFrame(
            columns=[
                "date",
                "model_type",
                "forecast_vol",
                "realized_vol",
                "rmse_cumulative",
                "qlike_cumulative",
            ]
        )

    # Precompute realized vol proxy on the full series
    realized_proxy = compute_realized_vol_proxy(returns, window=5)

    rows: list[dict[str, Any]] = []
    returns_values = returns.values
    returns_index = returns.index

    # Generate evaluation points: start at train_window, step by `step`
    # We evaluate at position t and the realized vol at t+1
    eval_starts = range(train_window, n - 1, step)

    for t in eval_starts:
        # t+1 is the "future" bar we predict; realized vol at t+1
        realized_idx = t + 1
        if realized_idx >= n:
            break

        realized_at_t1 = realized_proxy.iloc[realized_idx]
        if np.isnan(realized_at_t1):
            # Not enough history for rolling std proxy -- skip
            continue

        # Fit on returns[0:t] (bars 0 through t-1 inclusive)
        train_returns = returns_values[:t]
        result = fit_single_variant(train_returns, model_type)

        if not result.converged or result.h1_vol is None:
            logger.debug(
                "rolling_oos_evaluate: fit failed at t=%d for %s: %s",
                t,
                model_type,
                result.error_msg,
            )
            continue

        rows.append(
            {
                "date": returns_index[realized_idx],
                "model_type": model_type,
                "forecast_vol": result.h1_vol,
                "realized_vol": float(realized_at_t1),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
                "model_type",
                "forecast_vol",
                "realized_vol",
                "rmse_cumulative",
                "qlike_cumulative",
            ]
        )

    df = pd.DataFrame(rows)

    # Compute cumulative RMSE and QLIKE at each OOS step
    forecasts = df["forecast_vol"].values
    realized = df["realized_vol"].values

    rmse_cum = np.array(
        [rmse_loss(forecasts[: i + 1], realized[: i + 1]) for i in range(len(df))]
    )
    qlike_cum = np.array(
        [qlike_loss(forecasts[: i + 1], realized[: i + 1]) for i in range(len(df))]
    )

    df["rmse_cumulative"] = rmse_cum
    df["qlike_cumulative"] = qlike_cum

    return df


def evaluate_all_models(
    returns: pd.Series,
    train_window: int = 252,
    eval_window: int = 63,
) -> dict[str, dict[str, Any]]:
    """Run rolling OOS evaluation for all four GARCH model types.

    Parameters
    ----------
    returns:
        Daily returns as a pd.Series (decimal scale).
    train_window:
        Initial training window in bars (default 252 = 1 year).
    eval_window:
        Minimum OOS eval window in bars (default 63 = 1 quarter).
        Used as the step size (21) to generate evaluation points.

    Returns
    -------
    dict[str, dict]
        Keys are model_type strings. Each inner dict contains:
        - ``rmse``: final OOS RMSE
        - ``qlike``: final OOS QLIKE
        - ``mz_r2``: Mincer-Zarnowitz R-squared
        - ``combined``: combined_score(rmse, qlike)
        - ``n_forecasts``: number of OOS forecast points
        - ``oos_df``: the full rolling OOS DataFrame from rolling_oos_evaluate
    """
    from ta_lab2.analysis.garch_engine import MODEL_SPECS  # noqa: PLC0415

    results: dict[str, dict[str, Any]] = {}

    for model_type in MODEL_SPECS:
        logger.info("evaluate_all_models: evaluating %s", model_type)
        oos_df = rolling_oos_evaluate(
            returns,
            model_type=model_type,
            train_window=train_window,
            eval_window=eval_window,
            step=21,
        )

        if oos_df.empty:
            results[model_type] = {
                "rmse": float("nan"),
                "qlike": float("nan"),
                "mz_r2": float("nan"),
                "combined": float("nan"),
                "n_forecasts": 0,
                "oos_df": oos_df,
            }
            continue

        f = oos_df["forecast_vol"].values
        r = oos_df["realized_vol"].values
        rmse = rmse_loss(f, r)
        qlike = qlike_loss(f, r)
        mz_r2 = mincer_zarnowitz_r2(f, r)

        results[model_type] = {
            "rmse": rmse,
            "qlike": qlike,
            "mz_r2": mz_r2,
            "combined": combined_score(rmse, qlike),
            "n_forecasts": len(oos_df),
            "oos_df": oos_df,
        }

    return results
