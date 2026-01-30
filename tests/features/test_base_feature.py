"""
Unit tests for BaseFeature abstract class.

Tests configuration, template method pattern, and helper methods.
Uses unittest.mock throughout - no database required.
"""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, Mock, patch, call

from ta_lab2.scripts.features.base_feature import BaseFeature, FeatureConfig


# =============================================================================
# Configuration Tests
# =============================================================================

class TestFeatureConfig:
    """Tests for FeatureConfig dataclass."""

    def test_feature_config_defaults(self):
        """Test that default values are correct."""
        config = FeatureConfig(feature_type='returns')

        assert config.feature_type == 'returns'
        assert config.output_schema == 'public'
        assert config.output_table == ''
        assert config.null_strategy == 'skip'
        assert config.add_zscore is True
        assert config.zscore_window == 252

    def test_feature_config_custom(self):
        """Test that custom values are preserved."""
        config = FeatureConfig(
            feature_type='vol',
            output_schema='features',
            output_table='cmc_vol_daily',
            null_strategy='forward_fill',
            add_zscore=False,
            zscore_window=63,
        )

        assert config.feature_type == 'vol'
        assert config.output_schema == 'features'
        assert config.output_table == 'cmc_vol_daily'
        assert config.null_strategy == 'forward_fill'
        assert config.add_zscore is False
        assert config.zscore_window == 63

    def test_feature_config_frozen(self):
        """Test that FeatureConfig is immutable (frozen=True)."""
        config = FeatureConfig(feature_type='returns')

        with pytest.raises(AttributeError):
            config.feature_type = 'vol'


# =============================================================================
# BaseFeature Tests
# =============================================================================

class TestBaseFeature:
    """Tests for BaseFeature abstract class."""

    def test_base_feature_is_abstract(self):
        """Test that BaseFeature cannot be instantiated directly."""
        engine = MagicMock()
        config = FeatureConfig(feature_type='returns')

        # Should raise TypeError because abstract methods not implemented
        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseFeature(engine, config)

    def test_concrete_feature_computes(self):
        """Test that a concrete subclass can be instantiated and used."""
        # Create concrete implementation
        class ConcreteFeature(BaseFeature):
            def load_source_data(self, ids, start=None, end=None):
                return pd.DataFrame({
                    'id': [1, 1, 1],
                    'ts': pd.date_range('2024-01-01', periods=3),
                    'close': [100.0, 102.0, 101.0],
                })

            def compute_features(self, df_source):
                df = df_source.copy()
                df['return_1d'] = df['close'].pct_change()
                return df

            def get_output_schema(self):
                return {
                    'id': 'INTEGER',
                    'ts': 'TIMESTAMPTZ',
                    'return_1d': 'DOUBLE PRECISION',
                }

            def get_feature_columns(self):
                return ['return_1d']

        engine = MagicMock()
        config = FeatureConfig(
            feature_type='returns',
            output_table='test_returns',
            add_zscore=False,  # Disable for simpler test
        )

        feature = ConcreteFeature(engine, config)

        # Should be able to call methods
        assert feature.config.feature_type == 'returns'
        assert feature.get_feature_columns() == ['return_1d']


# =============================================================================
# Template Method Flow Tests
# =============================================================================

class TestComputeForIdsFlow:
    """Tests for compute_for_ids template method flow."""

    def create_mock_feature(self, config=None):
        """Helper to create mock feature with all methods."""
        if config is None:
            config = FeatureConfig(
                feature_type='test',
                output_table='test_table',
                add_zscore=False,
            )

        class MockFeature(BaseFeature):
            def load_source_data(self, ids, start=None, end=None):
                return pd.DataFrame({
                    'id': [1, 1],
                    'ts': pd.date_range('2024-01-01', periods=2),
                    'close': [100.0, 102.0],
                })

            def compute_features(self, df_source):
                df = df_source.copy()
                df['feature'] = df['close'] * 2
                return df

            def get_output_schema(self):
                return {
                    'id': 'INTEGER',
                    'ts': 'TIMESTAMPTZ',
                    'feature': 'DOUBLE PRECISION',
                }

            def get_feature_columns(self):
                return ['feature']

        return MockFeature(MagicMock(), config)

    def test_compute_for_ids_flow(self):
        """Test that template method calls methods in correct order."""
        feature = self.create_mock_feature()

        # Mock the methods to track calls
        with patch.object(feature, 'load_source_data', wraps=feature.load_source_data) as mock_load, \
             patch.object(feature, 'compute_features', wraps=feature.compute_features) as mock_compute, \
             patch.object(feature, 'add_normalizations', wraps=feature.add_normalizations) as mock_norm, \
             patch.object(feature, 'add_outlier_flags', wraps=feature.add_outlier_flags) as mock_outlier, \
             patch.object(feature, 'write_to_db', return_value=2) as mock_write:

            result = feature.compute_for_ids([1])

            # Verify all methods called in order
            assert mock_load.called
            assert mock_compute.called
            assert mock_norm.called
            assert mock_outlier.called
            assert mock_write.called

            # Verify call order
            assert mock_load.call_args[0][0] == [1]
            assert result == 2

    def test_compute_for_ids_empty_source(self):
        """Test that empty source data returns 0 without further processing."""
        feature = self.create_mock_feature()

        with patch.object(feature, 'load_source_data', return_value=pd.DataFrame()), \
             patch.object(feature, 'compute_features') as mock_compute:

            result = feature.compute_for_ids([1])

            assert result == 0
            # Should not call compute_features
            assert not mock_compute.called

    def test_compute_for_ids_empty_features(self):
        """Test that empty features after computation returns 0."""
        feature = self.create_mock_feature()

        with patch.object(feature, 'compute_features', return_value=pd.DataFrame()), \
             patch.object(feature, 'write_to_db') as mock_write:

            result = feature.compute_for_ids([1])

            assert result == 0
            # Should not call write_to_db
            assert not mock_write.called


# =============================================================================
# Helper Method Tests
# =============================================================================

class TestApplyNullHandling:
    """Tests for apply_null_handling method."""

    def create_feature_with_strategy(self, null_strategy='skip'):
        """Helper to create feature with specific null strategy."""
        config = FeatureConfig(
            feature_type='test',
            output_table='test',
            null_strategy=null_strategy,
            add_zscore=False,
        )

        class TestFeature(BaseFeature):
            def load_source_data(self, ids, start=None, end=None):
                return pd.DataFrame()

            def compute_features(self, df_source):
                return df_source

            def get_output_schema(self):
                return {}

            def get_feature_columns(self):
                return []

        return TestFeature(MagicMock(), config)

    def test_apply_null_handling_delegates_to_util(self):
        """Test that apply_null_handling delegates to feature_utils."""
        feature = self.create_feature_with_strategy('forward_fill')

        df = pd.DataFrame({
            'id': [1, 1, 1],
            'close': [100.0, np.nan, 102.0],
        })

        with patch('ta_lab2.scripts.features.base_feature.apply_null_strategy') as mock_apply:
            mock_apply.return_value = pd.Series([100.0, 100.0, 102.0])
            result = feature.apply_null_handling(df)

            # Should call apply_null_strategy for 'close' column
            assert mock_apply.called

    def test_apply_null_handling_multiple_price_cols(self):
        """Test handling multiple price columns."""
        feature = self.create_feature_with_strategy('interpolate')

        df = pd.DataFrame({
            'id': [1, 1, 1],
            'open': [99.0, np.nan, 101.0],
            'high': [101.0, np.nan, 103.0],
            'low': [98.0, np.nan, 100.0],
            'close': [100.0, np.nan, 102.0],
        })

        result = feature.apply_null_handling(df)

        # Should handle all price columns
        assert 'open' in result.columns
        assert 'close' in result.columns


class TestAddNormalizations:
    """Tests for add_normalizations method."""

    def create_feature_with_zscore(self, add_zscore=True):
        """Helper to create feature with zscore config."""
        config = FeatureConfig(
            feature_type='test',
            output_table='test',
            add_zscore=add_zscore,
            zscore_window=3,
        )

        class TestFeature(BaseFeature):
            def load_source_data(self, ids, start=None, end=None):
                return pd.DataFrame()

            def compute_features(self, df_source):
                return df_source

            def get_output_schema(self):
                return {}

            def get_feature_columns(self):
                return ['feature1', 'feature2']

        return TestFeature(MagicMock(), config)

    def test_add_normalizations_when_enabled(self):
        """Test that z-score is added when configured."""
        feature = self.create_feature_with_zscore(add_zscore=True)

        df = pd.DataFrame({
            'feature1': [1, 2, 3, 4, 5],
            'feature2': [10, 20, 30, 40, 50],
        })

        with patch('ta_lab2.scripts.features.base_feature.add_zscore_util') as mock_zscore:
            feature.add_normalizations(df)

            # Should call add_zscore for each feature column
            assert mock_zscore.call_count == 2

    def test_add_normalizations_when_disabled(self):
        """Test that z-score is skipped when disabled."""
        feature = self.create_feature_with_zscore(add_zscore=False)

        df = pd.DataFrame({
            'feature1': [1, 2, 3, 4, 5],
        })

        with patch('ta_lab2.scripts.features.base_feature.add_zscore_util') as mock_zscore:
            result = feature.add_normalizations(df)

            # Should not call add_zscore
            assert not mock_zscore.called
            # Should return same df
            pd.testing.assert_frame_equal(result, df)


class TestAddOutlierFlags:
    """Tests for add_outlier_flags method."""

    def create_feature(self):
        """Helper to create feature."""
        config = FeatureConfig(feature_type='test', output_table='test')

        class TestFeature(BaseFeature):
            def load_source_data(self, ids, start=None, end=None):
                return pd.DataFrame()

            def compute_features(self, df_source):
                return df_source

            def get_output_schema(self):
                return {}

            def get_feature_columns(self):
                return ['feature1']

        return TestFeature(MagicMock(), config)

    def test_add_outlier_flags(self):
        """Test that outlier flags are added."""
        feature = self.create_feature()

        df = pd.DataFrame({
            'feature1': [1, 2, 3, 100, 4, 5],
        })

        result = feature.add_outlier_flags(df)

        # Should add outlier flag column
        assert 'feature1_is_outlier' in result.columns
        assert result['feature1_is_outlier'].dtype == bool


class TestWriteToDB:
    """Tests for write_to_db method."""

    def create_feature(self):
        """Helper to create feature."""
        config = FeatureConfig(
            feature_type='test',
            output_schema='public',
            output_table='test_table',
        )

        class TestFeature(BaseFeature):
            def load_source_data(self, ids, start=None, end=None):
                return pd.DataFrame()

            def compute_features(self, df_source):
                return df_source

            def get_output_schema(self):
                return {'id': 'INTEGER', 'value': 'DOUBLE PRECISION'}

            def get_feature_columns(self):
                return ['value']

        return TestFeature(MagicMock(), config)

    def test_write_to_db_empty(self):
        """Test that empty df returns 0 without writing."""
        feature = self.create_feature()
        df = pd.DataFrame()

        with patch.object(pd.DataFrame, 'to_sql') as mock_to_sql:
            result = feature.write_to_db(df)

            assert result == 0
            assert not mock_to_sql.called

    def test_write_to_db_calls_to_sql(self):
        """Test that non-empty df calls pandas to_sql correctly."""
        feature = self.create_feature()
        df = pd.DataFrame({
            'id': [1, 2],
            'value': [10.0, 20.0],
        })

        with patch.object(feature, '_ensure_output_table'), \
             patch.object(pd.DataFrame, 'to_sql', return_value=2) as mock_to_sql:

            result = feature.write_to_db(df)

            assert mock_to_sql.called
            # Verify to_sql called with correct parameters
            call_kwargs = mock_to_sql.call_args[1]
            assert call_kwargs['schema'] == 'public'
            assert call_kwargs['if_exists'] == 'append'
            assert call_kwargs['index'] is False

            assert result == 2
