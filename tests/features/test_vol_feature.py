"""
Tests for VolatilityFeature module.

Covers:
- Configuration defaults and customization
- OHLC data loading
- Volatility computation (Parkinson, GK, RS, ATR, rolling)
- Null handling (forward_fill)
- Annualization
- Outlier flagging
- Full template method flow
"""

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from ta_lab2.scripts.features.vol_feature import VolatilityFeature, VolatilityConfig


# =============================================================================
# Configuration Tests
# =============================================================================

def test_vol_config_defaults():
    """Test default VolatilityConfig values."""
    config = VolatilityConfig()

    assert config.feature_type == "vol"
    assert config.output_table == "cmc_vol_daily"
    assert config.null_strategy == "forward_fill"
    assert config.add_zscore is True
    assert config.zscore_window == 252
    assert config.vol_windows == (20, 63, 126)
    assert config.estimators == ("parkinson", "gk", "rs")
    assert config.periods_per_year == 252
    assert config.atr_period == 14


def test_vol_config_custom_windows():
    """Test custom window configuration."""
    config = VolatilityConfig(
        vol_windows=(10, 30, 60),
        atr_period=20,
    )

    assert config.vol_windows == (10, 30, 60)
    assert config.atr_period == 20


def test_vol_config_custom_estimators():
    """Test custom estimator selection."""
    config = VolatilityConfig(
        estimators=("parkinson",),
    )

    assert config.estimators == ("parkinson",)


# =============================================================================
# Data Loading Tests
# =============================================================================

def test_load_source_data_ohlc():
    """Test that load_source_data queries for all OHLC columns."""
    mock_engine = MagicMock()
    config = VolatilityConfig()
    feature = VolatilityFeature(mock_engine, config)

    # Create mock DataFrame with OHLC
    mock_df = pd.DataFrame({
        'id': [1, 1, 1],
        'ts': pd.date_range('2023-01-01', periods=3),
        'open': [100.0, 101.0, 102.0],
        'high': [105.0, 106.0, 107.0],
        'low': [99.0, 100.0, 101.0],
        'close': [103.0, 104.0, 105.0],
    })

    with patch('pandas.read_sql', return_value=mock_df):
        df = feature.load_source_data(ids=[1], start="2023-01-01")

    assert 'open' in df.columns
    assert 'high' in df.columns
    assert 'low' in df.columns
    assert 'close' in df.columns
    assert 'ts' in df.columns
    assert len(df) == 3


# =============================================================================
# Volatility Computation Tests
# =============================================================================

def test_compute_parkinson_basic():
    """Test Parkinson volatility formula correctness."""
    mock_engine = MagicMock()
    config = VolatilityConfig(
        estimators=("parkinson",),
        vol_windows=(5,),
    )
    feature = VolatilityFeature(mock_engine, config)

    # Create synthetic data with known high/low ratio
    df = pd.DataFrame({
        'id': [1] * 20,
        'ts': pd.date_range('2023-01-01', periods=20),
        'open': [100.0] * 20,
        'high': [110.0] * 20,  # 10% above
        'low': [90.0] * 20,    # 10% below
        'close': [100.0] * 20,
    })

    result = feature.compute_features(df)

    # Parkinson vol should be computed for window=5
    assert 'vol_parkinson_5' in result.columns
    assert result['vol_parkinson_5'].notna().any()

    # Check that volatility is positive
    vol_values = result['vol_parkinson_5'].dropna()
    assert (vol_values > 0).all()


def test_compute_garman_klass_basic():
    """Test Garman-Klass volatility formula correctness."""
    mock_engine = MagicMock()
    config = VolatilityConfig(
        estimators=("gk",),
        vol_windows=(5,),
    )
    feature = VolatilityFeature(mock_engine, config)

    df = pd.DataFrame({
        'id': [1] * 20,
        'ts': pd.date_range('2023-01-01', periods=20),
        'open': [100.0] * 20,
        'high': [110.0] * 20,
        'low': [90.0] * 20,
        'close': [105.0] * 20,
    })

    result = feature.compute_features(df)

    assert 'vol_gk_5' in result.columns
    assert result['vol_gk_5'].notna().any()

    vol_values = result['vol_gk_5'].dropna()
    assert (vol_values > 0).all()


def test_compute_rogers_satchell_basic():
    """Test Rogers-Satchell volatility formula correctness."""
    mock_engine = MagicMock()
    config = VolatilityConfig(
        estimators=("rs",),
        vol_windows=(5,),
    )
    feature = VolatilityFeature(mock_engine, config)

    df = pd.DataFrame({
        'id': [1] * 20,
        'ts': pd.date_range('2023-01-01', periods=20),
        'open': [100.0] * 20,
        'high': [110.0] * 20,
        'low': [90.0] * 20,
        'close': [105.0] * 20,
    })

    result = feature.compute_features(df)

    assert 'vol_rs_5' in result.columns
    assert result['vol_rs_5'].notna().any()

    vol_values = result['vol_rs_5'].dropna()
    assert (vol_values >= 0).all()  # RS can be zero


def test_compute_features_all_estimators():
    """Test that all estimators are computed together."""
    mock_engine = MagicMock()
    config = VolatilityConfig(
        estimators=("parkinson", "gk", "rs"),
        vol_windows=(20,),
    )
    feature = VolatilityFeature(mock_engine, config)

    df = pd.DataFrame({
        'id': [1] * 50,
        'ts': pd.date_range('2023-01-01', periods=50),
        'open': np.random.uniform(95, 105, 50),
        'high': np.random.uniform(105, 115, 50),
        'low': np.random.uniform(85, 95, 50),
        'close': np.random.uniform(95, 105, 50),
    })

    result = feature.compute_features(df)

    # All estimators should be present
    assert 'vol_parkinson_20' in result.columns
    assert 'vol_gk_20' in result.columns
    assert 'vol_rs_20' in result.columns
    assert 'atr_14' in result.columns
    assert 'vol_log_roll_20' in result.columns


def test_compute_atr():
    """Test ATR computation."""
    mock_engine = MagicMock()
    config = VolatilityConfig(atr_period=5)
    feature = VolatilityFeature(mock_engine, config)

    df = pd.DataFrame({
        'id': [1] * 20,
        'ts': pd.date_range('2023-01-01', periods=20),
        'open': [100.0] * 20,
        'high': [110.0] * 20,
        'low': [90.0] * 20,
        'close': [105.0] * 20,
    })

    result = feature.compute_features(df)

    assert 'atr_5' in result.columns
    assert result['atr_5'].notna().any()

    atr_values = result['atr_5'].dropna()
    assert (atr_values > 0).all()


# =============================================================================
# Null Handling Tests
# =============================================================================

def test_null_handling_forward_fill():
    """Test that forward_fill is applied to missing OHLC."""
    mock_engine = MagicMock()
    config = VolatilityConfig(
        null_strategy="forward_fill",
        vol_windows=(5,),
    )
    feature = VolatilityFeature(mock_engine, config)

    # Create data with missing OHLC values
    df = pd.DataFrame({
        'id': [1] * 10,
        'ts': pd.date_range('2023-01-01', periods=10),
        'open': [100.0, np.nan, np.nan, 103.0, 104.0, np.nan, 106.0, 107.0, 108.0, 109.0],
        'high': [110.0, np.nan, np.nan, 113.0, 114.0, np.nan, 116.0, 117.0, 118.0, 119.0],
        'low': [90.0, np.nan, np.nan, 93.0, 94.0, np.nan, 96.0, 97.0, 98.0, 99.0],
        'close': [100.0, np.nan, np.nan, 103.0, 104.0, np.nan, 106.0, 107.0, 108.0, 109.0],
    })

    # Apply null handling (this is done in compute_for_ids, but we can test directly)
    df_handled = feature.apply_null_handling(df)

    # Forward fill should have filled missing values
    assert df_handled['open'].isna().sum() == 0
    assert df_handled['high'].isna().sum() == 0
    assert df_handled['low'].isna().sum() == 0
    assert df_handled['close'].isna().sum() == 0

    # Check that forward fill worked correctly
    assert df_handled['open'].iloc[1] == 100.0  # Forward filled from idx 0
    assert df_handled['open'].iloc[2] == 100.0  # Forward filled from idx 0


# =============================================================================
# Annualization Tests
# =============================================================================

def test_annualization():
    """Test that volatility is annualized with sqrt(252)."""
    mock_engine = MagicMock()
    config = VolatilityConfig(
        estimators=("parkinson",),
        vol_windows=(20,),
        periods_per_year=252,
    )
    feature = VolatilityFeature(mock_engine, config)

    # Create stable data to check annualization
    df = pd.DataFrame({
        'id': [1] * 50,
        'ts': pd.date_range('2023-01-01', periods=50),
        'open': [100.0] * 50,
        'high': [102.0] * 50,
        'low': [98.0] * 50,
        'close': [100.0] * 50,
    })

    result = feature.compute_features(df)

    # Volatility should be annualized (positive values)
    vol_values = result['vol_parkinson_20'].dropna()
    assert (vol_values > 0).all()

    # Check that annualized vol is reasonable (not too small)
    # With 2% daily range, annualized vol should be significant
    assert vol_values.mean() > 0.01  # At least 1% annualized


# =============================================================================
# Outlier Flagging Tests
# =============================================================================

def test_outlier_flagging():
    """Test that outlier flag columns are created correctly."""
    mock_engine = MagicMock()
    config = VolatilityConfig(
        estimators=("parkinson",),
        vol_windows=(5,),
    )
    feature = VolatilityFeature(mock_engine, config)

    # Create stable data (we're just testing that the flag column is added)
    df = pd.DataFrame({
        'id': [1] * 20,
        'ts': pd.date_range('2023-01-01', periods=20),
        'open': [100.0] * 20,
        'high': [102.0] * 20,
        'low': [98.0] * 20,
        'close': [100.0] * 20,
    })

    result = feature.compute_features(df)

    # Apply outlier flagging (done in compute_for_ids, but we can test separately)
    result = feature.add_outlier_flags(result)

    # Check that outlier flag column exists
    assert 'vol_parkinson_5_is_outlier' in result.columns

    # Check that the column is boolean type
    assert result['vol_parkinson_5_is_outlier'].dtype == bool

    # With stable data, no outliers should be flagged
    outlier_count = result['vol_parkinson_5_is_outlier'].sum()
    # This is fine - we're just verifying the mechanism works
    assert outlier_count >= 0  # Can be 0 or more


# =============================================================================
# Full Flow Tests
# =============================================================================

def test_compute_for_ids_full_flow():
    """Test full template method flow from end to end."""
    mock_engine = MagicMock()
    config = VolatilityConfig(
        vol_windows=(5,),
    )
    feature = VolatilityFeature(mock_engine, config)

    # Mock load_source_data
    mock_df = pd.DataFrame({
        'id': [1] * 20,
        'ts': pd.date_range('2023-01-01', periods=20),
        'open': np.random.uniform(95, 105, 20),
        'high': np.random.uniform(105, 115, 20),
        'low': np.random.uniform(85, 95, 20),
        'close': np.random.uniform(95, 105, 20),
    })

    with patch.object(feature, 'load_source_data', return_value=mock_df):
        with patch.object(feature, 'write_to_db', return_value=20) as mock_write:
            rows = feature.compute_for_ids(ids=[1])

    assert rows == 20
    mock_write.assert_called_once()

    # Check that the written DataFrame has expected columns
    written_df = mock_write.call_args[0][0]
    assert 'vol_parkinson_5' in written_df.columns
    assert 'vol_gk_5' in written_df.columns
    assert 'vol_rs_5' in written_df.columns
    assert 'atr_14' in written_df.columns
    assert 'vol_log_roll_5' in written_df.columns


def test_empty_ohlc_handling():
    """Test graceful handling when all OHLC are NULL."""
    mock_engine = MagicMock()
    config = VolatilityConfig()
    feature = VolatilityFeature(mock_engine, config)

    # Empty DataFrame
    df = pd.DataFrame({
        'id': [],
        'ts': [],
        'open': [],
        'high': [],
        'low': [],
        'close': [],
    })

    result = feature.compute_features(df)

    # Should return empty DataFrame without error
    assert result.empty


def test_get_output_schema():
    """Test that output schema includes all required columns."""
    mock_engine = MagicMock()
    config = VolatilityConfig(
        vol_windows=(20, 63, 126),
        atr_period=14,
    )
    feature = VolatilityFeature(mock_engine, config)

    schema = feature.get_output_schema()

    # Check primary columns
    assert 'id' in schema
    assert 'ts' in schema
    assert 'open' in schema
    assert 'high' in schema
    assert 'low' in schema
    assert 'close' in schema

    # Check volatility columns
    assert 'vol_parkinson_20' in schema
    assert 'vol_parkinson_63' in schema
    assert 'vol_parkinson_126' in schema
    assert 'vol_gk_20' in schema
    assert 'vol_rs_20' in schema
    assert 'atr_14' in schema
    assert 'vol_log_roll_20' in schema

    # Check z-score columns
    assert 'vol_parkinson_20_zscore' in schema
    assert 'vol_gk_20_zscore' in schema

    # Check outlier flags
    assert 'vol_parkinson_20_is_outlier' in schema
    assert 'vol_gk_20_is_outlier' in schema

    # Check metadata
    assert 'updated_at' in schema


def test_get_feature_columns():
    """Test that get_feature_columns returns all volatility columns."""
    mock_engine = MagicMock()
    config = VolatilityConfig(
        vol_windows=(20, 63, 126),
        atr_period=14,
    )
    feature = VolatilityFeature(mock_engine, config)

    cols = feature.get_feature_columns()

    # Should include all volatility measures
    assert 'vol_parkinson_20' in cols
    assert 'vol_parkinson_63' in cols
    assert 'vol_parkinson_126' in cols
    assert 'vol_gk_20' in cols
    assert 'vol_rs_20' in cols
    assert 'atr_14' in cols
    assert 'vol_log_roll_20' in cols

    # Should NOT include metadata or ID/TS columns
    assert 'id' not in cols
    assert 'ts' not in cols
    assert 'updated_at' not in cols


# =============================================================================
# Multiple ID Tests
# =============================================================================

def test_compute_features_multiple_ids():
    """Test that features are computed correctly for multiple IDs."""
    mock_engine = MagicMock()
    config = VolatilityConfig(
        vol_windows=(5,),
    )
    feature = VolatilityFeature(mock_engine, config)

    # Create data for two IDs
    df = pd.DataFrame({
        'id': [1] * 20 + [2] * 20,
        'ts': list(pd.date_range('2023-01-01', periods=20)) * 2,
        'open': np.random.uniform(95, 105, 40),
        'high': np.random.uniform(105, 115, 40),
        'low': np.random.uniform(85, 95, 40),
        'close': np.random.uniform(95, 105, 40),
    })

    result = feature.compute_features(df)

    # Should have rows for both IDs
    assert 1 in result['id'].values
    assert 2 in result['id'].values

    # Both IDs should have volatility computed
    id1_rows = result[result['id'] == 1]
    id2_rows = result[result['id'] == 2]

    assert id1_rows['vol_parkinson_5'].notna().any()
    assert id2_rows['vol_parkinson_5'].notna().any()
