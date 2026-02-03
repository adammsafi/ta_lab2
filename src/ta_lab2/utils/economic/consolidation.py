"""Time series consolidation utilities.

Extracted from fedtools2.utils.consolidation and cleaned up with:
- Full type hints
- Comprehensive docstrings
- Removed S#/V# comment style
- Improved variable names

Original source: .archive/external-packages/2026-02-03/fedtools2/src/fedtools2/utils/consolidation.py
"""
from __future__ import annotations

from functools import reduce
from typing import Optional

import pandas as pd


def _prepare_dataframe(df: pd.DataFrame, name: str) -> pd.DataFrame:
    """Prepare a DataFrame for time series merging.

    Normalizes the first column to 'date', converts to DatetimeIndex,
    prefixes all data columns with the series name, and adds a coverage flag.

    Args:
        df: Input DataFrame with date in first column
        name: Series name for column prefixing

    Returns:
        DataFrame with DatetimeIndex and prefixed columns
    """
    df = df.copy()

    # Normalize first column to 'date'
    df.rename(columns={df.columns[0]: "date"}, inplace=True)

    # Convert to sorted DatetimeIndex
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    # Prefix data columns and add coverage flag
    df.columns = [f"{name}_{col}" for col in df.columns]
    df[f"has_{name}"] = True

    return df


def combine_timeframes(
    dfs: list[pd.DataFrame],
    names: list[str],
    persist: bool = True,
    limit: Optional[int] = None,
) -> pd.DataFrame:
    """Merge multiple time series DataFrames with coverage tracking.

    Performs an outer join on all DataFrames by date, prefixes columns
    with series names to avoid collisions, and tracks which series have
    data at each date via has_{name} boolean columns.

    Args:
        dfs: List of DataFrames to merge (each with date in first column)
        names: List of names for each DataFrame (used for column prefixes)
        persist: If True, forward-fill missing values after merge
        limit: Maximum number of consecutive NaN values to forward-fill

    Returns:
        Merged DataFrame with:
        - DatetimeIndex
        - Columns prefixed with series names: {name}_{original_col}
        - Coverage flags: has_{name} (True where series has data)

    Raises:
        AssertionError: If dfs and names have different lengths

    Example:
        >>> df1 = pd.DataFrame({"date": ["2024-01-01"], "value": [100]})
        >>> df2 = pd.DataFrame({"date": ["2024-01-01", "2024-01-02"], "value": [200, 201]})
        >>> merged = combine_timeframes([df1, df2], ["series1", "series2"])
        >>> merged.columns.tolist()
        ['series1_value', 'has_series1', 'series2_value', 'has_series2']
    """
    assert len(dfs) == len(names), "dfs and names must have the same length"

    # Prepare all DataFrames
    prepared = [_prepare_dataframe(df, name) for df, name in zip(dfs, names)]

    # Outer join all on date index
    merged = reduce(lambda left, right: left.join(right, how="outer"), prepared)

    # Fill coverage flags to False where missing
    for name in names:
        merged[f"has_{name}"] = merged[f"has_{name}"].fillna(False)

    # Forward-fill values if requested
    if persist:
        value_cols = [col for col in merged.columns if not col.startswith("has_")]
        merged[value_cols] = merged[value_cols].ffill(limit=limit)

    return merged


def missing_ranges(mask: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Detect contiguous ranges where a boolean mask is True.

    Useful for finding gaps in time series data by passing a mask
    like `series.isna()` or `~has_data`.

    Args:
        mask: Boolean Series with DatetimeIndex

    Returns:
        List of (start, end) timestamp tuples for each contiguous True range

    Example:
        >>> dates = pd.date_range("2024-01-01", periods=5)
        >>> mask = pd.Series([False, True, True, False, True], index=dates)
        >>> gaps = missing_ranges(mask)
        >>> len(gaps)
        2
        >>> gaps[0]  # First gap: Jan 2-3
        (Timestamp('2024-01-02'), Timestamp('2024-01-03'))
    """
    if mask.empty:
        return []

    # Normalize to pandas nullable boolean
    boolean_mask = mask.astype("boolean").fillna(False)

    # Detect transitions: False->True (start) and True->False (end)
    starts = (~boolean_mask.shift(1, fill_value=False)) & boolean_mask
    ends = boolean_mask & (~boolean_mask.shift(-1, fill_value=False))

    # Pair into intervals
    return list(zip(boolean_mask.index[starts], boolean_mask.index[ends]))
