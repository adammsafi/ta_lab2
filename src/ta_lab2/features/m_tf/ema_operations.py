"""
EMA Operations - Pure utility functions for EMA computations.

This module extracts common EMA computation patterns from all feature modules:
- ema_multi_timeframe.py
- ema_multi_tf_cal.py
- ema_multi_tf_cal_anchor.py
- ema_multi_tf_v2.py

Analogous to polars_bar_operations.py for bar builders.

All functions are pure (no side effects) and optimized for performance.
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# =============================================================================
# Alpha Calculation
# =============================================================================


def calculate_alpha_from_period(period: int) -> float:
    """
    Calculate EMA alpha from period using standard formula.

    Alpha = 2 / (period + 1)

    Args:
        period: EMA period (e.g., 9, 21, 50)

    Returns:
        Alpha value between 0 and 1

    Examples:
        >>> calculate_alpha_from_period(9)
        0.2
        >>> calculate_alpha_from_period(21)
        0.09090909090909091
    """
    if period <= 0:
        raise ValueError(f"period must be positive, got {period}")
    return 2.0 / (period + 1.0)


def calculate_alpha_from_horizon(horizon_days: int) -> float:
    """
    Calculate EMA alpha from horizon in days.

    This is the same as calculate_alpha_from_period() but with clearer semantics
    for daily-space EMAs (used by v2).

    Alpha = 2 / (horizon_days + 1)

    Args:
        horizon_days: Smoothing horizon in days (e.g., for 7D/period=10, horizon=70 days)

    Returns:
        Alpha value between 0 and 1

    Examples:
        >>> calculate_alpha_from_horizon(70)
        0.028169014084507043
    """
    if horizon_days <= 0:
        raise ValueError(f"horizon_days must be positive, got {horizon_days}")
    return 2.0 / (horizon_days + 1.0)


# =============================================================================
# Derivative Computation
# =============================================================================


def compute_first_derivative(
    ema_series: pd.Series,
    *,
    name: Optional[str] = None,
) -> pd.Series:
    """
    Compute first derivative (d1) of EMA series.

    d1[i] = ema[i] - ema[i-1]

    First value is NaN (no previous value to diff against).

    Args:
        ema_series: EMA values
        name: Optional name for output series

    Returns:
        First derivative series
    """
    result = ema_series.diff()
    if name:
        result = result.rename(name)
    return result


def compute_second_derivative(
    ema_series: pd.Series,
    *,
    name: Optional[str] = None,
) -> pd.Series:
    """
    Compute second derivative (d2) of EMA series.

    d2[i] = d1[i] - d1[i-1] = (ema[i] - ema[i-1]) - (ema[i-1] - ema[i-2])

    First two values are NaN.

    Args:
        ema_series: EMA values
        name: Optional name for output series

    Returns:
        Second derivative series
    """
    d1 = ema_series.diff()
    result = d1.diff()
    if name:
        result = result.rename(name)
    return result


def compute_derivatives(
    ema_series: pd.Series,
    *,
    d1_name: Optional[str] = None,
    d2_name: Optional[str] = None,
) -> tuple[pd.Series, pd.Series]:
    """
    Compute both first and second derivatives efficiently.

    More efficient than calling compute_first_derivative and compute_second_derivative
    separately since we only compute diff() once for d1.

    Args:
        ema_series: EMA values
        d1_name: Optional name for d1 series
        d2_name: Optional name for d2 series

    Returns:
        Tuple of (d1, d2) series
    """
    d1 = ema_series.diff()
    d2 = d1.diff()

    if d1_name:
        d1 = d1.rename(d1_name)
    if d2_name:
        d2 = d2.rename(d2_name)

    return d1, d2


def compute_rolling_derivatives_continuous(
    ema_series: pd.Series,
    *,
    d1_roll_name: Optional[str] = None,
    d2_roll_name: Optional[str] = None,
) -> tuple[pd.Series, pd.Series]:
    """
    Compute rolling derivatives across ALL rows (continuous series).

    This is the same as regular derivatives - included for API consistency
    with compute_rolling_derivatives_canonical().

    d1_roll[i] = ema[i] - ema[i-1]  (for all i)
    d2_roll[i] = d1_roll[i] - d1_roll[i-1]  (for all i)

    Args:
        ema_series: EMA values
        d1_roll_name: Optional name for d1_roll series
        d2_roll_name: Optional name for d2_roll series

    Returns:
        Tuple of (d1_roll, d2_roll) series
    """
    return compute_derivatives(ema_series, d1_name=d1_roll_name, d2_name=d2_roll_name)


def compute_rolling_derivatives_canonical(
    ema_series: pd.Series,
    is_canonical: pd.Series,
    *,
    d1_name: Optional[str] = None,
    d2_name: Optional[str] = None,
) -> tuple[pd.Series, pd.Series]:
    """
    Compute derivatives ONLY across canonical rows (roll=FALSE).

    Non-canonical rows get NaN for derivatives.

    This is used by cal/cal_anchor scripts where derivatives are only
    meaningful across canonical endpoints.

    Args:
        ema_series: EMA values
        is_canonical: Boolean series where True = canonical row (roll=FALSE)
        d1_name: Optional name for d1 series
        d2_name: Optional name for d2 series

    Returns:
        Tuple of (d1, d2) series with NaN on non-canonical rows
    """
    # Create series of canonical EMA values only
    canonical_ema = ema_series.where(is_canonical)

    # Compute derivatives (will be NaN where canonical_ema is NaN)
    d1 = canonical_ema.diff()
    d2 = d1.diff()

    if d1_name:
        d1 = d1.rename(d1_name)
    if d2_name:
        d2 = d2.rename(d2_name)

    return d1, d2


# =============================================================================
# Period Filtering
# =============================================================================


def filter_ema_periods_by_obs_count(
    periods: list[int],
    n_obs: int,
    *,
    min_obs_multiplier: float = 3.0,
    logger_name: Optional[str] = None,
) -> list[int]:
    """
    Filter EMA periods to only those with sufficient observations.

    Rule: period must have at least (min_obs_multiplier * period) observations.
    Default: 3x period (e.g., period=100 needs 300 observations).

    Args:
        periods: List of EMA periods to filter
        n_obs: Number of observations available
        min_obs_multiplier: Minimum observations = period * multiplier
        logger_name: Optional logger name for warnings

    Returns:
        Filtered list of periods that have sufficient observations

    Examples:
        >>> filter_ema_periods_by_obs_count([9, 21, 50, 100, 200], 250)
        [9, 21, 50]  # 100 needs 300, 200 needs 600
    """
    if not periods:
        return []

    log = logging.getLogger(logger_name) if logger_name else logger

    valid_periods = []
    dropped_periods = []

    for period in periods:
        min_required = int(period * min_obs_multiplier)
        if n_obs >= min_required:
            valid_periods.append(period)
        else:
            dropped_periods.append(period)

    if dropped_periods and log:
        log.warning(
            f"Dropped {len(dropped_periods)} periods due to insufficient observations "
            f"(n_obs={n_obs}, multiplier={min_obs_multiplier}): {dropped_periods}"
        )

    return valid_periods


# =============================================================================
# EMA Computation with Horizon
# =============================================================================


def compute_ema_from_horizon(
    prices: pd.Series,
    *,
    horizon_days: int,
    min_periods: Optional[int] = None,
    name: Optional[str] = None,
) -> pd.Series:
    """
    Compute EMA using horizon-based alpha calculation.

    This is a convenience wrapper around compute_ema() that calculates
    alpha from horizon_days automatically.

    Alpha = 2 / (horizon_days + 1)

    Args:
        prices: Price series
        horizon_days: Smoothing horizon in days
        min_periods: Minimum observations before computing EMA (default: horizon_days)
        name: Optional name for output series

    Returns:
        EMA series

    Examples:
        >>> # 7D timeframe, period=10 -> horizon = 7*10 = 70 days
        >>> compute_ema_from_horizon(prices, horizon_days=70)
    """
    from ta_lab2.features.ema import compute_ema

    alpha = calculate_alpha_from_horizon(horizon_days)
    period = horizon_days  # For min_periods calculation

    return compute_ema(
        prices,
        period=period,
        min_periods=min_periods or period,
        name=name,
    )


# =============================================================================
# Vectorized Operations
# =============================================================================


def add_ema_columns_vectorized(
    df: pd.DataFrame,
    price_col: str,
    periods: list[int],
    *,
    group_col: Optional[str] = None,
    ema_prefix: str = "ema_",
) -> pd.DataFrame:
    """
    Add multiple EMA columns to DataFrame efficiently.

    If group_col is provided, computes EMAs separately per group.

    Args:
        df: Input DataFrame
        price_col: Column name containing prices
        periods: List of EMA periods to compute
        group_col: Optional column to group by (e.g., 'id', 'tf')
        ema_prefix: Prefix for output column names

    Returns:
        DataFrame with added EMA columns: ema_9, ema_21, etc.
    """
    from ta_lab2.features.ema import compute_ema

    result = df.copy()

    if group_col:
        # Compute EMAs per group
        for period in periods:
            col_name = f"{ema_prefix}{period}"
            result[col_name] = result.groupby(group_col)[price_col].transform(
                lambda s: compute_ema(s, period=period)
            )
    else:
        # Compute EMAs on full series
        for period in periods:
            col_name = f"{ema_prefix}{period}"
            result[col_name] = compute_ema(result[price_col], period=period)

    return result


def add_derivative_columns_vectorized(
    df: pd.DataFrame,
    ema_col: str,
    *,
    group_col: Optional[str] = None,
    d1_col: str = "d1",
    d2_col: str = "d2",
) -> pd.DataFrame:
    """
    Add first and second derivative columns to DataFrame.

    If group_col is provided, computes derivatives separately per group.

    Args:
        df: Input DataFrame
        ema_col: Column name containing EMA values
        group_col: Optional column to group by
        d1_col: Output column name for first derivative
        d2_col: Output column name for second derivative

    Returns:
        DataFrame with added derivative columns
    """
    result = df.copy()

    if group_col:
        # Compute derivatives per group
        result[d1_col] = result.groupby(group_col)[ema_col].transform(
            lambda s: compute_first_derivative(s)
        )
        result[d2_col] = result.groupby(group_col)[ema_col].transform(
            lambda s: compute_second_derivative(s)
        )
    else:
        # Compute derivatives on full series
        result[d1_col] = compute_first_derivative(result[ema_col])
        result[d2_col] = compute_second_derivative(result[ema_col])

    return result
