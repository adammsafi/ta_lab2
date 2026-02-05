"""
Test suite for multi-TF bar derivation from 1D bars.

Validates that --from-1d derivation produces identical bars to direct computation.
This is critical for migration: derivation must be bit-for-bit identical
(within floating point tolerance) to existing logic.
"""

import pytest
import pandas as pd
import polars as pl

from ta_lab2.scripts.bars.derive_multi_tf_from_1d import (
    aggregate_daily_to_timeframe,
    validate_derivation_consistency,
)


class TestAggregationOHLCVMath:
    """
    Unit tests for OHLCV aggregation rules:
    - Open = first day's open
    - High = max of all days' highs
    - Low = min of all days' lows
    - Close = last day's close
    - Volume = sum of all days' volumes
    """

    def test_aggregation_basic_2d(self):
        """Test 2D aggregation with simple data."""
        # Create sample daily bars
        df_daily = pl.DataFrame(
            {
                "id": [1, 1, 1, 1],
                "timestamp": pd.date_range("2024-01-01", periods=4, freq="D"),
                "tf": ["1D", "1D", "1D", "1D"],
                "bar_seq": [1, 2, 3, 4],
                "time_open": pd.date_range("2024-01-01", periods=4, freq="D"),
                "time_high": pd.date_range("2024-01-01 12:00", periods=4, freq="D"),
                "time_low": pd.date_range("2024-01-01 10:00", periods=4, freq="D"),
                "open": [100.0, 105.0, 110.0, 108.0],
                "high": [102.0, 107.0, 112.0, 111.0],
                "low": [99.0, 104.0, 109.0, 107.0],
                "close": [101.0, 106.0, 111.0, 110.0],
                "volume": [1000.0, 1100.0, 1200.0, 1150.0],
                "market_cap": [1e9, 1.01e9, 1.02e9, 1.03e9],
                "is_partial_start": [False, False, False, False],
                "is_partial_end": [False, False, False, False],
                "is_missing_days": [False, False, False, False],
                "count_days": [1, 1, 1, 1],
                "count_missing_days": [0, 0, 0, 0],
            }
        )

        # Aggregate to 2D
        df_2d = aggregate_daily_to_timeframe(df_daily, "2D")

        # Should have 2 bars (days 1-2, days 3-4)
        assert len(df_2d) == 2

        # First bar (days 1-2)
        bar1 = df_2d[0]
        assert bar1["open"] == 100.0  # First day's open
        assert bar1["high"] == 107.0  # Max of 102, 107
        assert bar1["low"] == 99.0  # Min of 99, 104
        assert bar1["close"] == 106.0  # Last day's close
        assert bar1["volume"] == 2100.0  # 1000 + 1100

        # Second bar (days 3-4)
        bar2 = df_2d[1]
        assert bar2["open"] == 110.0  # First day's open
        assert bar2["high"] == 112.0  # Max of 112, 111
        assert bar2["low"] == 107.0  # Min of 109, 107
        assert bar2["close"] == 110.0  # Last day's close
        assert bar2["volume"] == 2350.0  # 1200 + 1150

    def test_aggregation_with_nan_values(self):
        """Test OHLCV aggregation handles NaN values correctly."""
        # TODO: Implement test with NaN values in OHLCV
        pytest.skip("Pending implementation")

    def test_aggregation_single_day_bar(self):
        """Test that single-day bars work correctly."""
        # TODO: Test edge case where bar has only 1 day
        pytest.skip("Pending implementation")


class TestAggregationQualityFlagPropagation:
    """
    Test that quality flags propagate correctly:
    - If any source day has is_missing_days=TRUE, bar has is_missing_days=TRUE
    - If first day has is_partial_start=TRUE, bar has is_partial_start=TRUE
    - If last day has is_partial_end=TRUE, bar has is_partial_end=TRUE
    """

    def test_missing_days_flag_propagation(self):
        """Test is_missing_days flag propagates with OR logic."""
        # TODO: Create daily bars where some have is_missing_days=TRUE
        # Verify aggregated bar has is_missing_days=TRUE
        pytest.skip("Pending implementation")

    def test_partial_start_propagation(self):
        """Test is_partial_start propagates from first day."""
        # TODO: Create daily bars where first has is_partial_start=TRUE
        # Verify aggregated bar has is_partial_start=TRUE
        pytest.skip("Pending implementation")

    def test_partial_end_propagation(self):
        """Test is_partial_end propagates from last day."""
        # TODO: Create daily bars where last has is_partial_end=TRUE
        # Verify aggregated bar has is_partial_end=TRUE
        pytest.skip("Pending implementation")


class TestTimeHighLowDeterminism:
    """
    Test that time_high and time_low are deterministic:
    - Choose earliest timestamp among ties
    - Same as existing compute_time_high_low behavior
    """

    def test_time_high_earliest_among_ties(self):
        """Test time_high selects earliest timestamp when multiple days tie for high."""
        # TODO: Create daily bars where 2+ days have same high value
        # Verify time_high is from the EARLIEST day
        pytest.skip("Pending implementation")

    def test_time_low_earliest_among_ties(self):
        """Test time_low selects earliest timestamp when multiple days tie for low."""
        # TODO: Create daily bars where 2+ days have same low value
        # Verify time_low is from the EARLIEST day
        pytest.skip("Pending implementation")

    def test_extrema_timestamps_with_single_extreme(self):
        """Test time_high/time_low when only one day has the extreme."""
        # TODO: Test case where one day clearly has the high/low
        pytest.skip("Pending implementation")


class TestDerivationConsistency:
    """
    Integration test: Validate that --from-1d derivation produces identical bars
    to direct computation from price_histories7.
    """

    @pytest.mark.skip(reason="Requires database connection")
    def test_derivation_matches_direct_computation_integration(self):
        """
        Integration test with real database.

        This would run the builder in both modes for a test ID and compare results.
        """
        # TODO: When database is available:
        # 1. Run: python refresh_cmc_price_bars_multi_tf.py --ids 1 --from-1d --validate-derivation
        # 2. Check logs for "Derivation consistent for id=1"
        # 3. Query both derived and direct bars, compare row-by-row
        pass

    def test_validation_function_detects_discrepancies(self):
        """Test that validate_derivation_consistency correctly identifies mismatches."""
        # Create two Polars DataFrames with known differences
        df_derived = pl.DataFrame(
            {
                "id": [1, 1],
                "tf": ["2D", "2D"],
                "bar_seq": [1, 2],
                "time_close": pd.date_range("2024-01-02", periods=2, freq="2D"),
                "open": [100.0, 110.0],
                "high": [105.0, 115.0],
                "low": [99.0, 109.0],
                "close": [104.0, 114.0],
                "volume": [2000.0, 2200.0],
            }
        )

        # Direct has slightly different values
        df_direct = pl.DataFrame(
            {
                "id": [1, 1],
                "tf": ["2D", "2D"],
                "bar_seq": [1, 2],
                "time_close": pd.date_range("2024-01-02", periods=2, freq="2D"),
                "open": [100.0, 110.0],
                "high": [105.0, 116.0],  # Different!
                "low": [99.0, 109.0],
                "close": [104.0, 114.0],
                "volume": [2000.0, 2200.0],
            }
        )

        is_consistent, discrepancies = validate_derivation_consistency(
            df_derived=df_derived,
            df_direct=df_direct,
        )

        assert not is_consistent
        assert len(discrepancies) > 0
        assert any("high" in d for d in discrepancies)

    def test_validation_function_accepts_identical_data(self):
        """Test that identical data passes validation."""
        df = pl.DataFrame(
            {
                "id": [1, 1],
                "tf": ["2D", "2D"],
                "bar_seq": [1, 2],
                "time_close": pd.date_range("2024-01-02", periods=2, freq="2D"),
                "open": [100.0, 110.0],
                "high": [105.0, 115.0],
                "low": [99.0, 109.0],
                "close": [104.0, 114.0],
                "volume": [2000.0, 2200.0],
            }
        )

        is_consistent, discrepancies = validate_derivation_consistency(
            df_derived=df.clone(),
            df_direct=df.clone(),
        )

        assert is_consistent
        assert len(discrepancies) == 0


# Manual validation command (not automated test)
#
# To validate derivation with real data:
#
# python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf.py \
#     --ids 1 --from-1d --validate-derivation
#
# Expected output: "Derivation consistent for id=1" (or warning if discrepancies)
