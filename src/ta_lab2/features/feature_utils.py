"""
Feature utility functions for null handling and normalization.

This module provides reusable utilities for feature computation modules:
- Null handling strategies (skip, forward_fill, interpolate)
- Feature normalization (z-score)
- Data quality validation (minimum data points, outlier detection)

Used by BaseFeature and concrete feature implementations (returns, volatility, TA).
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


__all__ = [
    "apply_null_strategy",
    "add_zscore",
    "validate_min_data_points",
    "flag_outliers",
]


# =============================================================================
# Null Handling
# =============================================================================

def apply_null_strategy(
    series: pd.Series,
    strategy: str,
    *,
    limit: Optional[int] = None,
) -> pd.Series:
    """
    Apply null handling strategy to a series.

    Args:
        series: Input series with potential NULLs
        strategy: One of 'skip', 'forward_fill', 'interpolate'
        limit: Max consecutive NULLs to fill (None = unlimited)

    Returns:
        Series with nulls handled according to strategy

    Raises:
        ValueError: If strategy is not one of the allowed values

    Strategies:
        - 'skip': Return series as-is (calculations skip NULLs naturally)
        - 'forward_fill': ffill() then bfill() for leading NULLs
        - 'interpolate': Linear interpolation with limit

    Examples:
        >>> s = pd.Series([1.0, np.nan, 3.0, np.nan, 5.0])
        >>> apply_null_strategy(s, 'skip')
        0    1.0
        1    NaN
        2    3.0
        3    NaN
        4    5.0
        dtype: float64

        >>> apply_null_strategy(s, 'forward_fill')
        0    1.0
        1    1.0
        2    3.0
        3    3.0
        4    5.0
        dtype: float64

        >>> apply_null_strategy(s, 'interpolate')
        0    1.0
        1    2.0
        2    3.0
        3    4.0
        4    5.0
        dtype: float64
    """
    if strategy not in ('skip', 'forward_fill', 'interpolate'):
        raise ValueError(
            f"Invalid strategy '{strategy}'. "
            "Must be one of: 'skip', 'forward_fill', 'interpolate'"
        )

    if strategy == 'skip':
        return series

    if strategy == 'forward_fill':
        # Forward fill, then backward fill for leading NULLs
        result = series.ffill(limit=limit)
        result = result.bfill(limit=limit)
        return result

    if strategy == 'interpolate':
        # Linear interpolation
        return series.interpolate(method='linear', limit=limit)

    # Should never reach here due to validation above
    return series


# =============================================================================
# Normalization
# =============================================================================

def add_zscore(
    df: pd.DataFrame,
    col: str,
    *,
    window: int = 252,
    out_col: Optional[str] = None,
) -> pd.DataFrame:
    """
    Add rolling z-score column.

    z = (x - rolling_mean) / rolling_std

    Args:
        df: DataFrame with feature column
        col: Column name to normalize
        window: Rolling window for mean/std (default 252 = 1 year of trading days)
        out_col: Output column name (default: {col}_zscore)

    Returns:
        DataFrame with added z-score column (modifies in-place)

    Raises:
        KeyError: If col not found in DataFrame

    Examples:
        >>> df = pd.DataFrame({'price': [100, 102, 101, 103, 105, 104, 106]})
        >>> add_zscore(df, 'price', window=3)
        >>> 'price_zscore' in df.columns
        True

        >>> # Custom output column
        >>> add_zscore(df, 'price', window=5, out_col='price_z5')
        >>> 'price_z5' in df.columns
        True
    """
    if col not in df.columns:
        raise KeyError(f"Column '{col}' not found in DataFrame")

    # Determine output column name
    if out_col is None:
        out_col = f"{col}_zscore"

    # Calculate rolling mean and std
    rolling_mean = df[col].rolling(window=window, min_periods=window).mean()
    rolling_std = df[col].rolling(window=window, min_periods=window).std()

    # Z-score = (x - mean) / std
    # Handle division by zero (std = 0)
    df[out_col] = np.where(
        rolling_std > 0,
        (df[col] - rolling_mean) / rolling_std,
        np.nan,
    )

    return df


# =============================================================================
# Data Quality Validation
# =============================================================================

def validate_min_data_points(
    series: pd.Series,
    min_required: int,
    feature_name: str,
) -> tuple[bool, int]:
    """
    Validate series has minimum required data points.

    Args:
        series: Input series to validate
        min_required: Minimum number of non-null data points required
        feature_name: Name of feature (for error messages/logging)

    Returns:
        Tuple of (is_valid, actual_count)
        - is_valid: True if series has enough data points
        - actual_count: Actual number of non-null data points

    Examples:
        >>> s = pd.Series([1, 2, np.nan, 4, 5])
        >>> validate_min_data_points(s, min_required=3, feature_name='test')
        (True, 4)

        >>> validate_min_data_points(s, min_required=5, feature_name='test')
        (False, 4)
    """
    actual_count = series.notna().sum()
    is_valid = actual_count >= min_required

    return (is_valid, actual_count)


def flag_outliers(
    series: pd.Series,
    *,
    n_sigma: float = 4.0,
    method: str = 'zscore',
) -> pd.Series:
    """
    Return boolean series marking outliers.

    Per CONTEXT.md: Flag but keep - mark as outlier, preserve original value.
    This function does NOT modify the original data, only identifies outliers.

    Args:
        series: Input series
        n_sigma: Number of std devs for outlier threshold (default 4.0)
        method: 'zscore' or 'iqr'
            - 'zscore': |z-score| > n_sigma
            - 'iqr': x < Q1 - n_sigma*IQR or x > Q3 + n_sigma*IQR

    Returns:
        Boolean series (True = outlier, False = normal)

    Raises:
        ValueError: If method is not 'zscore' or 'iqr'

    Examples:
        >>> s = pd.Series([1, 2, 3, 100, 4, 5])  # 100 is outlier
        >>> outliers = flag_outliers(s, n_sigma=2.0, method='zscore')
        >>> outliers[3]  # True for the 100
        True

        >>> # IQR method
        >>> outliers_iqr = flag_outliers(s, n_sigma=1.5, method='iqr')
        >>> outliers_iqr[3]
        True
    """
    if method not in ('zscore', 'iqr'):
        raise ValueError(f"Invalid method '{method}'. Must be 'zscore' or 'iqr'")

    if method == 'zscore':
        # Z-score method: |z| > n_sigma
        mean = series.mean()
        std = series.std()

        if std == 0:
            # No variation - nothing is an outlier
            return pd.Series(False, index=series.index)

        z_scores = np.abs((series - mean) / std)
        return z_scores > n_sigma

    if method == 'iqr':
        # IQR method: x < Q1 - n_sigma*IQR or x > Q3 + n_sigma*IQR
        q1 = series.quantile(0.25)
        q3 = series.quantile(0.75)
        iqr = q3 - q1

        if iqr == 0:
            # No variation - nothing is an outlier
            return pd.Series(False, index=series.index)

        lower_bound = q1 - n_sigma * iqr
        upper_bound = q3 + n_sigma * iqr

        return (series < lower_bound) | (series > upper_bound)

    # Should never reach here due to validation above
    return pd.Series(False, index=series.index)
