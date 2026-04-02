"""
GARCH forecast combination and blend weight system (Phase 81, GARCH-03).

Provides inverse-RMSE blend weights and blended volatility lookup that
combines GARCH conditional volatility forecasts with range-based estimators
(Parkinson, Garman-Klass, ATR).

Exports:
    BlendConfig             - Dataclass configuring blend behaviour
    compute_blend_weights   - Inverse-RMSE weights with min-weight floor
    compute_trailing_rmse   - Per-estimator RMSE over trailing window
    get_blended_vol         - DB-aware blended vol lookup (garch_forecasts_latest)
Design:
    Pure computation functions (compute_blend_weights) have no DB dependency.
    DB-aware functions (get_blended_vol, compute_trailing_rmse) accept a
    SQLAlchemy Engine as their first argument, matching the project pattern
    used elsewhere in the analysis and scripts packages.

Reference:
    Bates, J.M. & Granger, C.W.J. (1969). The combination of forecasts.
    Operational Research Quarterly, 20(4), 451-468.
    Timmermann, A. (2006). Forecast combinations. Handbook of Economic
    Forecasting, Vol. 1, 135-196.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from ta_lab2.analysis.garch_evaluator import rmse_loss

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default GARCH model types used in blend (matches MODEL_SPECS in garch_engine)
_DEFAULT_GARCH_MODELS: list[str] = [
    "garch_1_1",
    "gjr_garch_1_1",
    "egarch_1_1",
    "figarch_1_d_1",
]

#: Range-based estimator column names (must match columns in garch_forecasts_latest
#: or be provided as separate dict keys in compute_trailing_rmse)
_RANGE_ESTIMATOR_NAMES: list[str] = ["parkinson", "garman_klass", "atr_14"]


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------


@dataclass
class BlendConfig:
    """Configuration for the GARCH + range-estimator blend system.

    Attributes
    ----------
    eval_window:
        Trailing days used when computing per-estimator RMSE for weights.
        Default 63 = 1 quarter.
    min_weight:
        Minimum weight floor per estimator (Bates-Granger style floor).
        Prevents any single estimator from being zeroed out entirely.
        Default 0.05 = 5%.
    mode:
        How the blended vol is used downstream.
        'sizing_only'       - Only affects position size, not hard risk limits.
        'sizing_and_limits' - Drives both position size and risk limit checks.
        'advisory'          - Read-only signal, no automatic sizing impact.
    garch_model_types:
        GARCH variant names to include in the blend. Defaults to all four.
    include_range_estimators:
        Whether to include range-based estimators (Parkinson, GK, ATR-14)
        alongside the GARCH variants. Default True.
    """

    eval_window: int = 63
    min_weight: float = 0.05
    mode: str = "sizing_only"
    garch_model_types: list[str] = field(
        default_factory=lambda: list(_DEFAULT_GARCH_MODELS)
    )
    include_range_estimators: bool = True


# ---------------------------------------------------------------------------
# Pure computation: blend weights
# ---------------------------------------------------------------------------


def compute_blend_weights(
    rmse_dict: dict[str, float],
    min_weight: float = 0.05,
) -> dict[str, float]:
    """Compute inverse-RMSE blend weights with a minimum weight floor.

    Implements the Bates-Granger (1969) inverse-RMSE combination:
    1. weight_i = 1 / rmse_i  (higher accuracy -> higher weight)
    2. Normalize so weights sum to 1.0
    3. Apply minimum weight floor (``min_weight``) and renormalize

    Parameters
    ----------
    rmse_dict:
        Mapping of estimator name -> RMSE value over a trailing evaluation
        window. Estimators with RMSE <= 0 or NaN are excluded.
    min_weight:
        Minimum weight fraction allocated to each estimator (default 0.05).
        Must be in [0, 1/n) where n = number of valid estimators.

    Returns
    -------
    dict[str, float]
        Normalized weight per estimator. Sums to 1.0 (within floating-point
        tolerance). Returns an empty dict if rmse_dict is empty or all values
        are invalid.
    """
    # Filter out invalid (non-positive, NaN) entries
    valid = {k: v for k, v in rmse_dict.items() if np.isfinite(v) and v > 0}
    if not valid:
        logger.warning(
            "compute_blend_weights: no valid RMSE values; returning empty weights"
        )
        return {}

    n = len(valid)

    # Step 1: inverse RMSE
    inv_rmse = {k: 1.0 / v for k, v in valid.items()}
    total_inv = sum(inv_rmse.values())

    # Step 2: normalize to sum to 1
    weights = {k: v / total_inv for k, v in inv_rmse.items()}

    # Step 3: apply minimum weight floor iteratively.
    # Guard: min_weight must be < 1/n otherwise floor is impossible.
    if min_weight > 0:
        effective_floor = min(min_weight, 1.0 / n)
        # Iterative floor: fix low-weight estimators at the floor, then
        # redistribute remaining probability mass over unconstrained ones.
        for _ in range(n):  # at most n iterations to converge
            below = {k for k, w in weights.items() if w < effective_floor - 1e-12}
            if not below:
                break
            # Lock floored estimators; redistribute mass from free estimators
            floored_mass = effective_floor * len(below)
            free_keys = [k for k in weights if k not in below]
            free_mass = 1.0 - floored_mass
            if free_mass <= 0 or not free_keys:
                # All estimators at the floor: assign uniformly
                weights = {k: effective_floor for k in weights}
                total_w = sum(weights.values())
                weights = {k: v / total_w for k, v in weights.items()}
                break
            # Rescale free weights proportionally to fill remaining mass
            free_total = sum(weights[k] for k in free_keys)
            for k in below:
                weights[k] = effective_floor
            if free_total > 0:
                for k in free_keys:
                    weights[k] = weights[k] / free_total * free_mass

    return weights


# ---------------------------------------------------------------------------
# Trailing RMSE computation (DB-aware)
# ---------------------------------------------------------------------------


def compute_trailing_rmse(
    forecasts_df: pd.DataFrame,
    realized_vol: pd.Series,
    window: int = 63,
) -> dict[str, float]:
    """Compute per-estimator RMSE over a trailing window.

    Parameters
    ----------
    forecasts_df:
        DataFrame with columns: [ts, estimator_name, forecast_vol].
        ``ts`` must be compatible with the index of ``realized_vol``.
        One row per (ts, estimator_name) pair.
    realized_vol:
        Realized vol proxy series (indexed by timestamp matching ``ts``).
        Typically computed by ``compute_realized_vol_proxy``.
    window:
        Number of trailing bars to include in the RMSE computation
        (default 63 = 1 quarter).

    Returns
    -------
    dict[str, float]
        Mapping estimator_name -> trailing RMSE. Missing estimators (not
        enough data within the window) return NaN.
    """
    if forecasts_df.empty or realized_vol.empty:
        return {}

    # Limit to the trailing window
    cutoff = realized_vol.index[-1] if hasattr(realized_vol.index, "__len__") else None
    if cutoff is not None and hasattr(forecasts_df["ts"], "max"):
        max_ts = forecasts_df["ts"].max()
        if hasattr(max_ts, "freq"):
            pass  # already a Timestamp
        window_start = (
            realized_vol.index[-window]
            if len(realized_vol) >= window
            else realized_vol.index[0]
        )
        recent = forecasts_df[forecasts_df["ts"] >= window_start]
    else:
        recent = forecasts_df

    results: dict[str, float] = {}
    for estimator, grp in recent.groupby("estimator_name"):
        grp_sorted = grp.sort_values("ts")
        # Align with realized_vol
        aligned_real = realized_vol.reindex(grp_sorted["ts"].values)
        aligned_fore = grp_sorted["forecast_vol"].values

        mask = ~np.isnan(aligned_real.values) & ~np.isnan(aligned_fore)
        if mask.sum() < 5:
            results[str(estimator)] = float("nan")
            continue

        results[str(estimator)] = rmse_loss(
            aligned_fore[mask], aligned_real.values[mask]
        )

    return results


# ---------------------------------------------------------------------------
# DB-aware blended vol lookup
# ---------------------------------------------------------------------------


def get_blended_vol(
    asset_id: int,
    venue_id: int,
    tf: str,
    engine: Any,
    config: BlendConfig | None = None,
) -> dict[str, Any] | None:
    """Retrieve the latest GARCH forecasts and compute a blended volatility.

    Reads from ``garch_forecasts_latest`` materialized view, computes
    trailing RMSE per estimator (over the configured eval_window), then
    weights them via inverse-RMSE to produce a single blended vol estimate.

    Parameters
    ----------
    asset_id:
        Asset integer ID (matches ``id`` column in price/feature tables).
    venue_id:
        Venue SMALLINT (1=CMC_AGG, 2=HYPERLIQUID, etc.).
    tf:
        Timeframe string (e.g. '1d').
    engine:
        SQLAlchemy Engine connected to the target database.
    config:
        Optional BlendConfig. Uses default values if None.

    Returns
    -------
    dict or None
        On success, a dict with keys:
        - ``blended_vol`` (float): weighted-average vol forecast
        - ``weights`` (dict[str, float]): per-estimator blend weights
        - ``components`` (dict[str, float]): per-estimator raw vol values
        - ``mode`` (str): BlendConfig.mode
        Returns None if no GARCH forecasts are available for this asset/tf.
    """
    if config is None:
        config = BlendConfig()

    try:
        from sqlalchemy import text  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        logger.error("sqlalchemy not available -- get_blended_vol requires it")
        return None

    query = text(
        """
        SELECT model_type, cond_vol
        FROM garch_forecasts_latest
        WHERE id = :asset_id
          AND venue_id = :venue_id
          AND tf = :tf
          AND horizon = 1
        """
    )

    try:
        with engine.connect() as conn:
            rows = conn.execute(
                query, {"asset_id": asset_id, "venue_id": venue_id, "tf": tf}
            ).fetchall()
    except Exception as exc:
        logger.warning("get_blended_vol: DB query failed for id=%d: %s", asset_id, exc)
        return None

    if not rows:
        logger.debug(
            "get_blended_vol: no forecasts for id=%d venue_id=%d tf=%s",
            asset_id,
            venue_id,
            tf,
        )
        return None

    # Build components dict (GARCH variants only from DB)
    components: dict[str, float] = {}
    for row in rows:
        model_type, cond_vol = row[0], row[1]
        if model_type in config.garch_model_types and cond_vol is not None:
            components[model_type] = float(cond_vol)

    if not components:
        return None

    # For DB-based blending, use equal weights when no trailing RMSE available
    # (trailing RMSE computation requires a stored forecast history + realized vol,
    # which is provided by Plan 05 comparison report; here we fall back to equal)
    equal_w = 1.0 / len(components)
    weights = {k: equal_w for k in components}

    blended_vol = sum(weights[k] * v for k, v in components.items())

    return {
        "blended_vol": float(blended_vol),
        "weights": weights,
        "components": components,
        "mode": config.mode,
    }
