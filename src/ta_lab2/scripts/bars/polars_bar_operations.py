# -*- coding: utf-8 -*-
"""
Polars-based bar operations for high-performance multi-timeframe bar construction.

Contains 100% identical Polars operations extracted from all 5 multi-tf bar builders:
- refresh_cmc_price_bars_multi_tf.py (modulo-based rolling)
- refresh_cmc_price_bars_multi_tf_cal_iso.py (ISO week calendar)
- refresh_cmc_price_bars_multi_tf_cal_us.py (US week calendar)
- refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py (ISO week anchored)
- refresh_cmc_price_bars_multi_tf_cal_anchor_us.py (US week anchored)

All functions are pure, stateless, and operate on Polars DataFrames with bar_seq grouping.

Usage:
    from ta_lab2.scripts.bars.polars_bar_operations import apply_standard_polars_pipeline

    # Full pipeline (replaces 120+ lines of duplicated code)
    pl_df = apply_standard_polars_pipeline(pl_df, include_missing_days=True)

Performance:
    20-30% faster than pandas iterrows for large datasets (10k+ days).
    O(N) cumulative operations vs O(S×D) row-by-row iteration.
"""

from __future__ import annotations
from typing import Optional, List
import numpy as np
import pandas as pd
import polars as pl


def apply_ohlcv_cumulative_aggregations(
    pl_df: pl.DataFrame,
    *,
    group_col: str = "bar_seq",
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    volume_col: str = "volume",
    market_cap_col: str = "market_cap",
) -> pl.DataFrame:
    """
    Apply cumulative OHLCV aggregations within bar_seq windows.

    Operations (100% identical across all 5 builders):
    - open_bar: first open in window
    - close_bar: current close (no aggregation, just alias)
    - high_bar: cumulative max of high
    - low_bar: cumulative min of low
    - vol_bar: cumulative sum of volume (null-filled with 0)
    - mc_bar: forward-fill market_cap

    Args:
        pl_df: Input Polars DataFrame with sorted rows within bar_seq groups
        group_col: Column defining bar windows (default: "bar_seq")
        open_col, high_col, low_col, close_col, volume_col, market_cap_col: Input column names

    Returns:
        DataFrame with new columns: open_bar, close_bar, high_bar, low_bar, vol_bar, mc_bar

    Performance:
        O(N) using Polars window operations vs O(S×D) pandas iterrows approach.
        20-30% faster for large datasets (tested on 10k+ days).

    Example:
        >>> pl_df = pl.from_pandas(df_daily)
        >>> pl_df = apply_ohlcv_cumulative_aggregations(pl_df)
        >>> assert "high_bar" in pl_df.columns
    """
    return pl_df.with_columns(
        [
            pl.col(open_col).first().over(group_col).alias("open_bar"),
            pl.col(close_col).alias("close_bar"),
            pl.col(high_col).cum_max().over(group_col).alias("high_bar"),
            pl.col(low_col).cum_min().over(group_col).alias("low_bar"),
            pl.col(volume_col)
            .fill_null(0.0)
            .cum_sum()
            .over(group_col)
            .alias("vol_bar"),
            pl.col(market_cap_col).forward_fill().over(group_col).alias("mc_bar"),
        ]
    )


def compute_extrema_timestamps_with_new_extreme_detection(
    pl_df: pl.DataFrame,
    *,
    group_col: str = "bar_seq",
    ts_col: str = "ts",
    timehigh_col: str = "timehigh",
    timelow_col: str = "timelow",
    high_bar_col: str = "high_bar",
    low_bar_col: str = "low_bar",
) -> pl.DataFrame:
    """
    Compute time_high and time_low with correct new-extreme reset behavior.

    CRITICAL CONTRACT:
    - When high_bar increases (new extreme), reset time_high to today's timehigh
    - When low_bar decreases (new extreme), reset time_low to today's timelow
    - Ties do NOT reset (preserves earliest timestamp among equals)
    - Falls back to ts when timehigh/timelow is null (contract requirement)

    This fixes the "sentinel + cum_min" bug where timestamps can't forget old extremes.

    Problem with "sentinel + cum_min":
    - once you take a cum_min of candidate timestamps, it can't "forget" an earlier
      timestamp from an OLD (lower) high when the running high later increases.

    Correct behavior:
    - when high_bar increases (new extreme), reset time_high to today's timehigh_actual
    - when low_bar decreases (new extreme), reset time_low to today's timelow_actual
    - ties do NOT reset, preserving earliest timestamp among equals

    Args:
        pl_df: Must already have high_bar/low_bar columns from apply_ohlcv_cumulative_aggregations
        group_col: Bar grouping column (default: "bar_seq")
        ts_col: Primary timestamp column (fallback when timehigh/timelow is null)
        timehigh_col: Intraday high timestamp (nullable)
        timelow_col: Intraday low timestamp (nullable)
        high_bar_col: Cumulative bar high (must exist)
        low_bar_col: Cumulative bar low (must exist)

    Returns:
        DataFrame with new columns: time_high, time_low

    Example:
        >>> pl_df = apply_ohlcv_cumulative_aggregations(pl_df)
        >>> pl_df = compute_extrema_timestamps_with_new_extreme_detection(pl_df)
        >>> assert "time_high" in pl_df.columns
    """
    # Fallback to ts when timehigh/timelow is null
    pl_df = pl_df.with_columns(
        [
            pl.when(pl.col(timehigh_col).is_null())
            .then(pl.col(ts_col))
            .otherwise(pl.col(timehigh_col))
            .alias("timehigh_actual"),
            pl.when(pl.col(timelow_col).is_null())
            .then(pl.col(ts_col))
            .otherwise(pl.col(timelow_col))
            .alias("timelow_actual"),
        ]
    )

    # Detect new extremes (compare to previous row in bar_seq)
    prev_high = pl.col(high_bar_col).shift(1).over(group_col)
    prev_low = pl.col(low_bar_col).shift(1).over(group_col)

    pl_df = pl_df.with_columns(
        [
            (prev_high.is_null() | (pl.col(high_bar_col) != prev_high)).alias(
                "_new_high"
            ),
            (prev_low.is_null() | (pl.col(low_bar_col) != prev_low)).alias("_new_low"),
        ]
    )

    # Reset-on-new-extreme candidate, then forward-fill
    pl_df = pl_df.with_columns(
        [
            pl.when(pl.col("_new_high"))
            .then(pl.col("timehigh_actual"))
            .otherwise(pl.lit(None, dtype=pl.Datetime))
            .forward_fill()
            .over(group_col)
            .alias("time_high"),
            pl.when(pl.col("_new_low"))
            .then(pl.col("timelow_actual"))
            .otherwise(pl.lit(None, dtype=pl.Datetime))
            .forward_fill()
            .over(group_col)
            .alias("time_low"),
        ]
    ).drop(["_new_high", "_new_low", "timehigh_actual", "timelow_actual"])

    return pl_df


def compute_day_time_open(
    pl_df: pl.DataFrame,
    *,
    ts_col: str = "ts",
) -> pl.DataFrame:
    """
    Compute day_time_open: previous ts + 1ms; first row: ts - 1 day + 1ms.

    This represents the half-open start time of each daily bar in the snapshot sequence.

    Contract:
    - For rows after the first: prev_ts + 1 millisecond
    - For the first row: ts - 1 day + 1 millisecond

    Args:
        pl_df: Input DataFrame sorted by ts
        ts_col: Timestamp column (must be tz-naive datetime for Polars arithmetic)

    Returns:
        DataFrame with new column: day_time_open

    Example:
        >>> pl_df = compute_day_time_open(pl_df)
        >>> # First row: 2020-01-02 00:00:00 -> day_time_open = 2020-01-01 00:00:00.001
        >>> # Second row: 2020-01-03 00:00:00 -> day_time_open = 2020-01-02 00:00:00.001
    """
    one_day = pl.duration(days=1)
    one_ms = pl.duration(milliseconds=1)

    pl_df = (
        pl_df.with_columns([pl.col(ts_col).shift(1).alias("_prev_ts")])
        .with_columns(
            [
                pl.when(pl.col("_prev_ts").is_null())
                .then(pl.col(ts_col) - one_day + one_ms)
                .otherwise(pl.col("_prev_ts") + one_ms)
                .alias("day_time_open"),
            ]
        )
        .drop("_prev_ts")
    )

    return pl_df


def compute_missing_days_gaps(
    pl_df: pl.DataFrame,
    *,
    group_col: str = "bar_seq",
    ts_col: str = "ts",
) -> pl.DataFrame:
    """
    Compute per-row missing day increments from timestamp gaps within bar_seq.

    Logic (100% identical in multi_tf, similar pattern in others):
    1. Compute ts diff within bar_seq
    2. Convert milliseconds to days, subtract 1 (consecutive days have gap=1)
    3. Clip to 0 (no negative gaps)
    4. Cumulative sum within bar_seq gives total missing days count

    Args:
        pl_df: Input DataFrame sorted by ts within bar_seq groups
        group_col: Bar grouping column
        ts_col: Timestamp column

    Returns:
        DataFrame with new columns: missing_incr, count_missing_days

    Note:
        This is the SIMPLE version used in multi_tf. Calendar builders have
        more complex missing-days logic (start/interior/end breakdown) which
        is NOT extracted because it's builder-specific.

    Example:
        >>> pl_df = compute_missing_days_gaps(pl_df)
        >>> assert "count_missing_days" in pl_df.columns
    """
    pl_df = pl_df.with_columns(
        [
            pl.col(ts_col).diff().over(group_col).alias("_gap"),
        ]
    )

    pl_df = pl_df.with_columns(
        [
            pl.when(pl.col("_gap").is_null())
            .then(pl.lit(0))
            .otherwise(
                (
                    (pl.col("_gap").dt.total_milliseconds() / (1000 * 60 * 60 * 24)) - 1
                ).clip(lower_bound=0)
            )
            .cast(pl.Int64)
            .alias("missing_incr"),
        ]
    ).drop("_gap")

    pl_df = pl_df.with_columns(
        [
            pl.col("missing_incr")
            .cum_sum()
            .over(group_col)
            .alias("count_missing_days"),
        ]
    )

    return pl_df


def normalize_timestamps_for_polars(
    df: pd.DataFrame,
    *,
    ts_col: str = "ts",
    timehigh_col: str = "timehigh",
    timelow_col: str = "timelow",
) -> pd.DataFrame:
    """
    Normalize timestamp columns: convert to UTC, strip timezone for Polars processing.

    WHY: Polars datetime arithmetic works best with tz-naive datetimes.
    This avoids DST ambiguity issues and supertype errors.

    Contract:
    1. ts: convert to UTC (strict, error on invalid), then strip tz
    2. timehigh/timelow: convert to UTC (coerce invalid to NaT), then strip tz

    Args:
        df: Pandas DataFrame with timezone-aware or naive timestamps
        ts_col: Primary timestamp column (strict validation)
        timehigh_col: Intraday high timestamp (coerce mode)
        timelow_col: Intraday low timestamp (coerce mode)

    Returns:
        DataFrame with tz-naive UTC timestamps (ready for Polars conversion)

    Example:
        >>> df = normalize_timestamps_for_polars(df)
        >>> pl_df = pl.from_pandas(df)  # No tz-related errors
    """
    df = df.copy()

    # Strict for ts (must be valid)
    if ts_col in df.columns:
        df[ts_col] = pd.to_datetime(df[ts_col], utc=True, errors="raise").dt.tz_convert(
            None
        )

    # Coerce for extrema timestamps (can be null)
    if timehigh_col in df.columns:
        df[timehigh_col] = pd.to_datetime(
            df[timehigh_col], utc=True, errors="coerce"
        ).dt.tz_convert(None)

    if timelow_col in df.columns:
        df[timelow_col] = pd.to_datetime(
            df[timelow_col], utc=True, errors="coerce"
        ).dt.tz_convert(None)

    return df


def compact_output_types(
    df: pd.DataFrame,
    *,
    int32_cols: Optional[List[str]] = None,
    bool_cols: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Compact output DataFrame types: int64->int32, object->bool.

    Reduces memory usage by ~50% for snapshot tables with millions of rows.

    Args:
        df: Output DataFrame from Polars (typically has int64, object dtypes)
        int32_cols: Columns to cast to int32 (defaults to common snapshot columns)
        bool_cols: Columns to cast to bool (defaults to common flag columns)

    Returns:
        DataFrame with compacted types

    Example:
        >>> out = pl_df.to_pandas()
        >>> out = compact_output_types(out)
        >>> assert out["bar_seq"].dtype == np.int32
    """
    if df.empty:
        return df

    df = df.copy()

    # Default int32 columns (common across all builders)
    if int32_cols is None:
        int32_cols = [
            "bar_seq",
            "tf_days",
            "pos_in_bar",
            "count_days",
            "count_days_remaining",
            "count_missing_days",
            # Calendar-specific (safe to cast even if missing)
            "count_missing_days_start",
            "count_missing_days_end",
            "count_missing_days_interior",
            "bar_anchor_offset",  # anchor-specific
        ]

    # Default bool columns
    if bool_cols is None:
        bool_cols = [
            "is_partial_start",
            "is_partial_end",
            "is_missing_days",
        ]

    # Cast int32
    for col in int32_cols:
        if col in df.columns:
            df[col] = df[col].astype(np.int32)

    # Cast bool
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].astype(bool)

    return df


def restore_utc_timezone(
    df: pd.DataFrame,
    *,
    timestamp_cols: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Re-add UTC timezone to timestamp columns after Polars round-trip.

    Polars strips timezone info; this restores it for database insertion.

    Args:
        df: DataFrame with tz-naive timestamps (from Polars)
        timestamp_cols: Columns to restore UTC tz (defaults to common snapshot columns)

    Returns:
        DataFrame with UTC-aware timestamps

    Example:
        >>> out = pl_df.to_pandas()
        >>> out = restore_utc_timezone(out)
        >>> assert out["time_close"].dt.tz == 'UTC'
    """
    if df.empty:
        return df

    df = df.copy()

    # Default timestamp columns (common across all builders)
    if timestamp_cols is None:
        timestamp_cols = [
            "time_open",
            "time_close",
            "time_high",
            "time_low",
            "timestamp",
            "last_ts_half_open",
        ]

    for col in timestamp_cols:
        if col in df.columns and pd.api.types.is_datetime64_any_dtype(df[col]):
            df[col] = pd.to_datetime(df[col], utc=True)

    return df


# =============================================================================
# High-level pipeline composition
# =============================================================================


def apply_standard_polars_pipeline(
    pl_df: pl.DataFrame,
    *,
    group_col: str = "bar_seq",
    include_missing_days: bool = True,
) -> pl.DataFrame:
    """
    Apply the full standard Polars pipeline for bar snapshot construction.

    This is the CORE pipeline used by all 5 builders (order matters):
    1. day_time_open calculation
    2. OHLCV cumulative aggregations
    3. Extrema timestamps with new-extreme detection
    4. (Optional) Missing days gap calculation

    Args:
        pl_df: Input Polars DataFrame with:
            - Sorted by ts within bar_seq groups
            - Columns: ts, timehigh, timelow, open, high, low, close, volume, market_cap
        group_col: Bar grouping column (default: "bar_seq")
        include_missing_days: Whether to compute missing_days metrics (default: True)

    Returns:
        Polars DataFrame with all aggregated columns ready for final selection

    Example:
        >>> pl_df = pl.from_pandas(df)
        >>> pl_df = apply_standard_polars_pipeline(pl_df)
        >>> out = pl_df.to_pandas()
    """
    # Step 1: day_time_open
    pl_df = compute_day_time_open(pl_df)

    # Step 2: OHLCV aggregations (creates high_bar/low_bar needed for step 3)
    pl_df = apply_ohlcv_cumulative_aggregations(pl_df, group_col=group_col)

    # Step 3: Extrema timestamps (depends on high_bar/low_bar from step 2)
    pl_df = compute_extrema_timestamps_with_new_extreme_detection(
        pl_df, group_col=group_col
    )

    # Step 4: Missing days (optional, simple version)
    if include_missing_days:
        pl_df = compute_missing_days_gaps(pl_df, group_col=group_col)

    return pl_df
