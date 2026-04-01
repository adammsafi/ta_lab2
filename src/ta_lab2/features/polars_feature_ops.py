"""
Shared polars utility functions for feature computation migration.

Provides helpers that wrap pandas/polars interop for the per-asset groupby
loops common across feature sub-phases (cycle_stats, rolling_extremes, etc.).

When polars is available (HAVE_POLARS=True), sorting is delegated to polars
for faster performance; the actual per-group computation remains in pandas
since it calls numba kernels operating on numpy arrays.

When polars is not available, all operations fall back to pure pandas.

Usage:
    from ta_lab2.features.polars_feature_ops import (
        HAVE_POLARS,
        polars_sorted_groupby,
        normalize_timestamps_for_polars,
        restore_timestamps_from_polars,
    )
"""

from __future__ import annotations

from typing import Callable

import pandas as pd

# ---------------------------------------------------------------------------
# Polars availability check
# ---------------------------------------------------------------------------

try:
    import polars as pl

    HAVE_POLARS = True
except ImportError:  # pragma: no cover
    pl = None  # type: ignore[assignment]
    HAVE_POLARS = False


# ---------------------------------------------------------------------------
# Timestamp normalization helpers
# ---------------------------------------------------------------------------


def normalize_timestamps_for_polars(
    df: pd.DataFrame,
    ts_col: str = "ts",
) -> pd.DataFrame:
    """
    Strip UTC timezone from timestamp column before polars conversion.

    Polars cannot represent tz-aware pandas datetimes directly; this strips
    the timezone so the column converts cleanly. Call
    restore_timestamps_from_polars() after round-tripping through polars.

    Args:
        df: DataFrame potentially containing a tz-aware datetime column.
        ts_col: Name of the timestamp column to normalize.

    Returns:
        Modified copy of df with ts_col timezone stripped (tz-naive UTC).
    """
    df = df.copy()
    if ts_col in df.columns:
        col = df[ts_col]
        if hasattr(col.dtype, "tz") and col.dtype.tz is not None:
            df[ts_col] = col.dt.tz_localize(None)
    return df


def restore_timestamps_from_polars(
    df: pd.DataFrame,
    ts_col: str = "ts",
) -> pd.DataFrame:
    """
    Restore UTC timezone on timestamp column after converting back from polars.

    Args:
        df: DataFrame with tz-naive timestamp column.
        ts_col: Name of the timestamp column to restore.

    Returns:
        Modified copy of df with ts_col re-localized to UTC.
    """
    df = df.copy()
    if ts_col in df.columns:
        col = df[ts_col]
        if hasattr(col.dtype, "tz") and col.dtype.tz is not None:
            # Already tz-aware — no-op
            pass
        else:
            df[ts_col] = pd.to_datetime(col, utc=True)
    return df


# ---------------------------------------------------------------------------
# pandas_to_polars / polars_to_pandas
# ---------------------------------------------------------------------------


def pandas_to_polars_df(
    df: pd.DataFrame,
    ts_col: str = "ts",
) -> "pl.DataFrame":  # type: ignore[name-defined]
    """
    Convert a pandas DataFrame to polars, stripping tz from ts_col.

    Args:
        df: Source pandas DataFrame.
        ts_col: Timestamp column name whose tz will be stripped.

    Returns:
        polars DataFrame.

    Raises:
        ImportError: If polars is not installed.
    """
    if not HAVE_POLARS:
        raise ImportError("polars is not installed")
    df_clean = normalize_timestamps_for_polars(df, ts_col)
    return pl.from_pandas(df_clean)


def polars_to_pandas_df(
    pl_df: "pl.DataFrame",  # type: ignore[name-defined]
    ts_col: str = "ts",
) -> pd.DataFrame:
    """
    Convert a polars DataFrame back to pandas, restoring UTC on ts_col.

    Args:
        pl_df: Source polars DataFrame.
        ts_col: Timestamp column name to restore UTC on.

    Returns:
        pandas DataFrame with ts_col re-localized to UTC.
    """
    df = pl_df.to_pandas()
    return restore_timestamps_from_polars(df, ts_col)


# ---------------------------------------------------------------------------
# Core utility: polars_sorted_groupby
# ---------------------------------------------------------------------------


def polars_sorted_groupby(
    df: pd.DataFrame,
    group_cols: list[str],
    sort_col: str,
    apply_fn: Callable[[pd.DataFrame], pd.DataFrame],
    ts_col: str = "ts",
) -> pd.DataFrame:
    """
    Sort with polars then apply a per-group function using pandas groupby.

    The primary benefit over a pure-pandas groupby is that polars sorts the
    full DataFrame once (including correct ordering of the sort_col within
    each group) before handing it back to the pandas groupby.  This
    eliminates the Python-level sort inside the per-group apply_fn.

    Falls back to pure pandas when polars is not available.

    Args:
        df: Input DataFrame, potentially with tz-aware timestamp columns.
        group_cols: Columns to group by (e.g. ["id", "venue_id"]).
        sort_col: Column to sort by within each group (e.g. "ts").
        apply_fn: Callable that accepts a single-group DataFrame (copy) and
                  returns a DataFrame with computed columns appended.
        ts_col: Timestamp column whose timezone needs stripping before
                polars conversion and restoring afterwards.

    Returns:
        Concatenated results of apply_fn across all groups.
    """
    if HAVE_POLARS:
        # Sort with polars — faster for large DataFrames
        df_clean = normalize_timestamps_for_polars(df, ts_col)
        pl_df = pl.from_pandas(df_clean)
        pl_sorted = pl_df.sort(group_cols + [sort_col])
        df_sorted = pl_sorted.to_pandas()
        df_sorted = restore_timestamps_from_polars(df_sorted, ts_col)
    else:
        # Pure pandas fallback
        df_sorted = df.sort_values(group_cols + [sort_col])

    results = []
    for _, df_group in df_sorted.groupby(group_cols, sort=False):
        df_group = df_group.copy()
        result = apply_fn(df_group)
        if result is not None and not result.empty:
            results.append(result)

    if not results:
        return pd.DataFrame()

    return pd.concat(results, ignore_index=True)
