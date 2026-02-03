# -*- coding: utf-8 -*-
"""
Unit tests for polars_bar_operations.py

Tests the extracted Polars utilities for bar construction.
"""

import pytest
import pandas as pd
import numpy as np
import polars as pl

from ta_lab2.scripts.bars.polars_bar_operations import (
    apply_ohlcv_cumulative_aggregations,
    compute_extrema_timestamps_with_new_extreme_detection,
    compute_day_time_open,
    compute_missing_days_gaps,
    normalize_timestamps_for_polars,
    compact_output_types,
    restore_utc_timezone,
    apply_standard_polars_pipeline,
)


def test_ohlcv_aggregations():
    """Test cumulative OHLCV operations."""
    # Create test data: 2 bars, 3 days each
    df = pd.DataFrame(
        {
            "bar_seq": [1, 1, 1, 2, 2],
            "ts": pd.date_range("2020-01-01", periods=5, tz="UTC").tz_localize(None),
            "open": [100, 101, 102, 103, 104],
            "high": [105, 110, 108, 115, 112],
            "low": [95, 98, 96, 100, 99],
            "close": [102, 103, 104, 105, 106],
            "volume": [1000, 1500, 1200, 1100, 1300],
            "market_cap": [1e9, 1.1e9, 1.2e9, 1.3e9, 1.4e9],
        }
    )

    pl_df = pl.from_pandas(df)
    result = apply_ohlcv_cumulative_aggregations(pl_df)
    out = result.to_pandas()

    # Bar 1 assertions
    assert out.loc[0, "open_bar"] == 100  # first
    assert out.loc[0, "high_bar"] == 105  # first row max
    assert out.loc[1, "high_bar"] == 110  # cumulative max
    assert out.loc[2, "high_bar"] == 110  # stays at max
    assert out.loc[2, "low_bar"] == 95  # cumulative min
    assert out.loc[2, "vol_bar"] == 3700  # cumulative sum

    # Bar 2 assertions (reset)
    assert out.loc[3, "open_bar"] == 103  # new bar, first open
    assert out.loc[3, "high_bar"] == 115  # new bar's first high
    assert out.loc[4, "vol_bar"] == 2400  # new bar cumsum


def test_extrema_timestamps_new_extreme_reset():
    """Test that extrema timestamps reset correctly on new extremes."""
    df = pd.DataFrame(
        {
            "bar_seq": [1, 1, 1, 1],
            "ts": pd.date_range(
                "2020-01-01", periods=4, freq="D", tz="UTC"
            ).tz_localize(None),
            "high": [100, 110, 105, 120],  # new high on days 2 and 4
            "low": [90, 85, 87, 80],  # new low on days 2 and 4
            "timehigh": pd.date_range(
                "2020-01-01 14:00", periods=4, freq="D", tz="UTC"
            ).tz_localize(None),
            "timelow": pd.date_range(
                "2020-01-01 10:00", periods=4, freq="D", tz="UTC"
            ).tz_localize(None),
            "high_bar": [100, 110, 110, 120],  # cumulative (pre-computed)
            "low_bar": [90, 85, 85, 80],
        }
    )

    pl_df = pl.from_pandas(df)
    result = compute_extrema_timestamps_with_new_extreme_detection(pl_df)
    out = result.to_pandas()

    # Day 1: first extreme
    assert pd.to_datetime(out.loc[0, "time_high"]) == pd.to_datetime(
        df.loc[0, "timehigh"]
    )

    # Day 2: new high, should reset to day 2's timehigh
    assert pd.to_datetime(out.loc[1, "time_high"]) == pd.to_datetime(
        df.loc[1, "timehigh"]
    )

    # Day 3: no new high, should preserve day 2's timehigh
    assert pd.to_datetime(out.loc[2, "time_high"]) == pd.to_datetime(
        df.loc[1, "timehigh"]
    )

    # Day 4: new high again, should reset to day 4's timehigh
    assert pd.to_datetime(out.loc[3, "time_high"]) == pd.to_datetime(
        df.loc[3, "timehigh"]
    )


def test_day_time_open_calculation():
    """Test day_time_open edge cases."""
    df = pd.DataFrame(
        {
            "ts": pd.to_datetime(
                [
                    "2020-01-01 00:00:00",
                    "2020-01-02 00:00:00",
                    "2020-01-03 00:00:00",
                ],
                utc=True,
            ).tz_localize(None),
        }
    )

    pl_df = pl.from_pandas(df)
    result = compute_day_time_open(pl_df)
    out = result.to_pandas()

    # First row: ts - 1 day + 1ms
    expected_first = pd.Timestamp("2019-12-31 00:00:00.001")
    assert abs((out.loc[0, "day_time_open"] - expected_first).total_seconds()) < 0.01

    # Second row: prev ts + 1ms
    expected_second = pd.Timestamp("2020-01-01 00:00:00.001")
    assert abs((out.loc[1, "day_time_open"] - expected_second).total_seconds()) < 0.01

    # Third row: prev ts + 1ms
    expected_third = pd.Timestamp("2020-01-02 00:00:00.001")
    assert abs((out.loc[2, "day_time_open"] - expected_third).total_seconds()) < 0.01


def test_missing_days_gaps():
    """Test missing days gap calculation."""
    # 3-day gap between day 2 and day 3
    df = pd.DataFrame(
        {
            "bar_seq": [1, 1, 1],
            "ts": pd.to_datetime(
                [
                    "2020-01-01",
                    "2020-01-02",
                    "2020-01-06",  # 3-day gap
                ],
                utc=True,
            ).tz_localize(None),
        }
    )

    pl_df = pl.from_pandas(df)
    result = compute_missing_days_gaps(pl_df)
    out = result.to_pandas()

    assert out.loc[0, "missing_incr"] == 0  # first row
    assert out.loc[1, "missing_incr"] == 0  # consecutive
    assert out.loc[2, "missing_incr"] == 3  # (6-2-1) = 3 missing days

    assert out.loc[0, "count_missing_days"] == 0
    assert out.loc[1, "count_missing_days"] == 0
    assert out.loc[2, "count_missing_days"] == 3


def test_normalize_timestamps_for_polars():
    """Test timestamp normalization."""
    df = pd.DataFrame(
        {
            "ts": pd.date_range("2020-01-01", periods=3, tz="US/Eastern"),
            "timehigh": pd.date_range("2020-01-01 14:00", periods=3, tz="US/Eastern"),
            "timelow": pd.date_range("2020-01-01 10:00", periods=3, tz="US/Eastern"),
        }
    )

    result = normalize_timestamps_for_polars(df)

    # All should be tz-naive after normalization
    assert result["ts"].dt.tz is None
    assert result["timehigh"].dt.tz is None
    assert result["timelow"].dt.tz is None

    # Should be valid timestamps
    assert pd.api.types.is_datetime64_any_dtype(result["ts"])


def test_compact_output_types():
    """Test type compaction reduces memory."""
    df = pd.DataFrame(
        {
            "bar_seq": pd.Series([1, 2, 3], dtype="int64"),
            "is_partial_end": pd.Series([True, False, True], dtype="object"),
            "count_days": pd.Series([5, 7, 10], dtype="int64"),
        }
    )

    compacted = compact_output_types(df)

    assert compacted["bar_seq"].dtype == np.int32
    assert compacted["is_partial_end"].dtype == bool
    assert compacted["count_days"].dtype == np.int32


def test_restore_utc_timezone():
    """Test UTC timezone restoration."""
    df = pd.DataFrame(
        {
            "time_close": pd.date_range("2020-01-01", periods=3).tz_localize(None),
            "time_open": pd.date_range("2020-01-01", periods=3).tz_localize(None),
        }
    )

    result = restore_utc_timezone(df)

    # Should have UTC timezone
    assert result["time_close"].dt.tz is not None
    assert str(result["time_close"].dt.tz) == "UTC"
    assert str(result["time_open"].dt.tz) == "UTC"


def test_standard_pipeline_integration():
    """Test the full standard pipeline."""
    # Create realistic test data
    df = pd.DataFrame(
        {
            "bar_seq": [1, 1, 1, 2, 2],
            "ts": pd.date_range("2020-01-01", periods=5, tz="UTC").tz_localize(None),
            "timehigh": pd.date_range(
                "2020-01-01 14:00", periods=5, tz="UTC"
            ).tz_localize(None),
            "timelow": pd.date_range(
                "2020-01-01 10:00", periods=5, tz="UTC"
            ).tz_localize(None),
            "open": [100, 101, 102, 103, 104],
            "high": [105, 110, 108, 115, 112],
            "low": [95, 98, 96, 100, 99],
            "close": [102, 103, 104, 105, 106],
            "volume": [1000, 1500, 1200, 1100, 1300],
            "market_cap": [1e9, 1.1e9, 1.2e9, 1.3e9, 1.4e9],
        }
    )

    pl_df = pl.from_pandas(df)
    result = apply_standard_polars_pipeline(pl_df, include_missing_days=True)
    out = result.to_pandas()

    # Verify all expected columns exist
    assert "day_time_open" in out.columns
    assert "open_bar" in out.columns
    assert "high_bar" in out.columns
    assert "low_bar" in out.columns
    assert "time_high" in out.columns
    assert "time_low" in out.columns
    assert "count_missing_days" in out.columns

    # Spot check some values
    assert out.loc[0, "open_bar"] == 100
    assert out.loc[2, "high_bar"] == 110  # Bar 1 cumulative max
    assert out.loc[3, "open_bar"] == 103  # Bar 2 first open


def test_empty_dataframe_handling():
    """Test that utilities handle empty DataFrames gracefully."""
    empty_df = pd.DataFrame()

    # Should not raise errors
    result = compact_output_types(empty_df)
    assert result.empty

    result = restore_utc_timezone(empty_df)
    assert result.empty


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
