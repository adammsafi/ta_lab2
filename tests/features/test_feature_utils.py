"""
Unit tests for feature_utils module.

Tests null handling, normalization, and data quality validation utilities.
"""

import numpy as np
import pandas as pd
import pytest

from ta_lab2.features.feature_utils import (
    apply_null_strategy,
    add_zscore,
    validate_min_data_points,
    flag_outliers,
)


# =============================================================================
# Null Strategy Tests
# =============================================================================

class TestApplyNullStrategy:
    """Tests for apply_null_strategy function."""

    def test_apply_null_strategy_skip(self):
        """Test that 'skip' strategy returns series unchanged."""
        s = pd.Series([1.0, np.nan, 3.0, np.nan, 5.0])
        result = apply_null_strategy(s, 'skip')

        pd.testing.assert_series_equal(result, s)
        assert result.isna().sum() == 2

    def test_apply_null_strategy_forward_fill(self):
        """Test that 'forward_fill' strategy fills NULLs forward then backward."""
        s = pd.Series([1.0, np.nan, 3.0, np.nan, 5.0])
        result = apply_null_strategy(s, 'forward_fill')

        expected = pd.Series([1.0, 1.0, 3.0, 3.0, 5.0])
        pd.testing.assert_series_equal(result, expected)

    def test_apply_null_strategy_forward_fill_with_limit(self):
        """Test that 'forward_fill' respects limit parameter."""
        s = pd.Series([1.0, np.nan, np.nan, np.nan, 5.0])
        result = apply_null_strategy(s, 'forward_fill', limit=1)

        # Should only fill 1 consecutive null per gap
        # ffill with limit=1 then bfill with limit=1
        # After ffill: [1.0, 1.0, nan, nan, 5.0]
        # After bfill: [1.0, 1.0, nan, 5.0, 5.0]
        expected = pd.Series([1.0, 1.0, np.nan, 5.0, 5.0])
        pd.testing.assert_series_equal(result, expected)

    def test_apply_null_strategy_forward_fill_leading_nulls(self):
        """Test that 'forward_fill' handles leading NULLs with bfill."""
        s = pd.Series([np.nan, np.nan, 3.0, 4.0, 5.0])
        result = apply_null_strategy(s, 'forward_fill')

        # Should bfill leading nulls
        expected = pd.Series([3.0, 3.0, 3.0, 4.0, 5.0])
        pd.testing.assert_series_equal(result, expected)

    def test_apply_null_strategy_interpolate(self):
        """Test that 'interpolate' strategy performs linear interpolation."""
        s = pd.Series([1.0, np.nan, 3.0, np.nan, 5.0])
        result = apply_null_strategy(s, 'interpolate')

        expected = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        pd.testing.assert_series_equal(result, expected)

    def test_apply_null_strategy_interpolate_with_limit(self):
        """Test that 'interpolate' respects limit parameter."""
        s = pd.Series([1.0, np.nan, np.nan, np.nan, 5.0])
        result = apply_null_strategy(s, 'interpolate', limit=1)

        # Should only interpolate 1 consecutive null
        assert result.isna().sum() > 0

    def test_apply_null_strategy_invalid(self):
        """Test that invalid strategy raises ValueError."""
        s = pd.Series([1.0, np.nan, 3.0])

        with pytest.raises(ValueError, match="Invalid strategy"):
            apply_null_strategy(s, 'invalid_strategy')

    def test_apply_null_strategy_all_nulls(self):
        """Test handling series with all NULLs."""
        s = pd.Series([np.nan, np.nan, np.nan])

        # Skip should return as-is
        result_skip = apply_null_strategy(s, 'skip')
        assert result_skip.isna().all()

        # Interpolate should return all NULLs
        result_interp = apply_null_strategy(s, 'interpolate')
        assert result_interp.isna().all()


# =============================================================================
# Z-Score Normalization Tests
# =============================================================================

class TestAddZscore:
    """Tests for add_zscore function."""

    def test_add_zscore_basic(self):
        """Test basic z-score calculation."""
        df = pd.DataFrame({
            'price': [100, 102, 101, 103, 105, 104, 106, 108, 107, 109]
        })

        result = add_zscore(df, 'price', window=3)

        assert 'price_zscore' in result.columns
        # First window-1 rows should be NaN
        assert result['price_zscore'].iloc[:2].isna().all()
        # Rest should have values
        assert result['price_zscore'].iloc[2:].notna().any()

    def test_add_zscore_custom_window(self):
        """Test that custom window parameter is respected."""
        df = pd.DataFrame({
            'price': [100 + i for i in range(20)]
        })

        result = add_zscore(df, 'price', window=5)

        # First 4 rows should be NaN (window-1)
        assert result['price_zscore'].iloc[:4].isna().all()
        # Row 5 onwards should have values
        assert result['price_zscore'].iloc[4:].notna().any()

    def test_add_zscore_custom_output_col(self):
        """Test that custom output column name is used."""
        df = pd.DataFrame({'price': [100, 102, 104, 106, 108]})

        result = add_zscore(df, 'price', window=3, out_col='price_z3')

        assert 'price_z3' in result.columns
        assert 'price_zscore' not in result.columns

    def test_add_zscore_column_not_found(self):
        """Test that KeyError is raised for missing column."""
        df = pd.DataFrame({'price': [100, 102, 104]})

        with pytest.raises(KeyError, match="Column 'missing'"):
            add_zscore(df, 'missing', window=3)

    def test_add_zscore_zero_std(self):
        """Test handling of constant values (std = 0)."""
        df = pd.DataFrame({'price': [100, 100, 100, 100, 100]})

        result = add_zscore(df, 'price', window=3)

        # Should be NaN when std = 0
        assert result['price_zscore'].iloc[2:].isna().all()

    def test_add_zscore_calculation_correctness(self):
        """Test that z-score calculation is mathematically correct."""
        # Create data with known mean and std
        data = [10, 12, 14, 16, 18]
        df = pd.DataFrame({'price': data})

        result = add_zscore(df, 'price', window=3)

        # For index 2: values [10, 12, 14], mean=12, std=2
        # z-score for 14 = (14-12)/2 = 1.0
        assert abs(result['price_zscore'].iloc[2] - 1.0) < 0.001


# =============================================================================
# Data Quality Validation Tests
# =============================================================================

class TestValidateMinDataPoints:
    """Tests for validate_min_data_points function."""

    def test_validate_min_data_points_valid(self):
        """Test validation passes when enough data points."""
        s = pd.Series([1, 2, np.nan, 4, 5])

        is_valid, count = validate_min_data_points(s, min_required=3, feature_name='test')

        assert is_valid == True
        assert count == 4

    def test_validate_min_data_points_invalid(self):
        """Test validation fails when insufficient data points."""
        s = pd.Series([1, 2, np.nan, 4, 5])

        is_valid, count = validate_min_data_points(s, min_required=5, feature_name='test')

        assert is_valid == False
        assert count == 4

    def test_validate_min_data_points_exact(self):
        """Test validation with exact required count."""
        s = pd.Series([1, 2, 3, np.nan])

        is_valid, count = validate_min_data_points(s, min_required=3, feature_name='test')

        assert is_valid == True
        assert count == 3

    def test_validate_min_data_points_empty(self):
        """Test validation with empty series."""
        s = pd.Series([np.nan, np.nan, np.nan])

        is_valid, count = validate_min_data_points(s, min_required=1, feature_name='test')

        assert is_valid == False
        assert count == 0


# =============================================================================
# Outlier Detection Tests
# =============================================================================

class TestFlagOutliers:
    """Tests for flag_outliers function."""

    def test_flag_outliers_zscore(self):
        """Test z-score outlier detection."""
        # Data with clear outlier
        s = pd.Series([1, 2, 3, 100, 4, 5, 6])

        outliers = flag_outliers(s, n_sigma=2.0, method='zscore')

        assert outliers.dtype == bool
        assert outliers[3] == True  # 100 is outlier
        assert outliers[0] == False  # 1 is not outlier

    def test_flag_outliers_zscore_no_outliers(self):
        """Test z-score when no outliers present."""
        s = pd.Series([1, 2, 3, 4, 5, 6, 7])

        outliers = flag_outliers(s, n_sigma=4.0, method='zscore')

        # With high threshold, normal distribution has no outliers
        assert not outliers.any()

    def test_flag_outliers_iqr(self):
        """Test IQR outlier detection."""
        # Create data with outlier beyond IQR range
        s = pd.Series([1, 2, 3, 4, 5, 6, 100])

        outliers = flag_outliers(s, n_sigma=1.5, method='iqr')

        assert outliers.dtype == bool
        assert outliers[6] == True  # 100 is outlier

    def test_flag_outliers_iqr_no_outliers(self):
        """Test IQR when no outliers present."""
        s = pd.Series([1, 2, 3, 4, 5, 6, 7])

        outliers = flag_outliers(s, n_sigma=1.5, method='iqr')

        # Normal sequential data should have no outliers
        assert not outliers.any()

    def test_flag_outliers_invalid_method(self):
        """Test that invalid method raises ValueError."""
        s = pd.Series([1, 2, 3, 4, 5])

        with pytest.raises(ValueError, match="Invalid method"):
            flag_outliers(s, method='invalid')

    def test_flag_outliers_constant_series_zscore(self):
        """Test z-score with constant values (std = 0)."""
        s = pd.Series([5, 5, 5, 5, 5])

        outliers = flag_outliers(s, n_sigma=2.0, method='zscore')

        # No variation = no outliers
        assert not outliers.any()

    def test_flag_outliers_constant_series_iqr(self):
        """Test IQR with constant values (IQR = 0)."""
        s = pd.Series([5, 5, 5, 5, 5])

        outliers = flag_outliers(s, n_sigma=1.5, method='iqr')

        # No variation = no outliers
        assert not outliers.any()

    def test_flag_outliers_multiple_outliers(self):
        """Test detection of multiple outliers using IQR method."""
        # IQR is more robust to extreme values than z-score
        s = pd.Series([10, 11, 12, 13, 14, 15, 16, 100, 200])

        outliers = flag_outliers(s, n_sigma=1.5, method='iqr')

        # Should flag both extreme values (100 and 200)
        assert outliers[7] == True  # 100
        assert outliers[8] == True  # 200
        assert outliers.sum() >= 2

    def test_flag_outliers_preserves_index(self):
        """Test that result preserves original series index."""
        s = pd.Series([10, 11, 12, 100], index=['a', 'b', 'c', 'd'])

        outliers = flag_outliers(s, n_sigma=1.5, method='iqr')

        assert outliers.index.tolist() == ['a', 'b', 'c', 'd']
        assert outliers['d'] == True  # Outlier at index 'd' (value 100)
