"""
Unit tests for ReturnsFeature module.

Tests cover:
- Configuration defaults and customization
- Source data loading (mocked)
- Returns computation (bar-to-bar and multi-day)
- Gap tracking
- Z-score normalization
- Outlier detection
- Full template method flow
- Edge cases (empty data, single row, all NULLs)
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ta_lab2.scripts.features.returns_feature import ReturnsFeature, ReturnsConfig


class TestReturnsConfig(unittest.TestCase):
    """Test ReturnsConfig dataclass."""

    def test_returns_config_defaults(self):
        """Test default configuration values."""
        config = ReturnsConfig()

        self.assertEqual(config.feature_type, "returns")
        self.assertEqual(config.output_table, "cmc_returns_daily")
        self.assertEqual(config.null_strategy, "skip")
        self.assertEqual(config.add_zscore, True)
        self.assertEqual(config.zscore_window, 252)
        self.assertEqual(
            config.lookback_windows,
            (1, 3, 5, 7, 14, 21, 30, 63, 126, 252),
        )

    def test_returns_config_custom_windows(self):
        """Test custom lookback windows."""
        config = ReturnsConfig(
            lookback_windows=(1, 7, 30),
            zscore_window=60,
        )

        self.assertEqual(config.lookback_windows, (1, 7, 30))
        self.assertEqual(config.zscore_window, 60)


class TestReturnsFeatureSourceData(unittest.TestCase):
    """Test source data loading."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = ReturnsConfig()
        self.feature = ReturnsFeature(self.mock_engine, self.config)

    @patch('ta_lab2.scripts.features.returns_feature.pd.read_sql')
    def test_load_source_data_query(self, mock_read_sql):
        """Test SQL query construction for source data."""
        # Setup mock
        mock_read_sql.return_value = pd.DataFrame({
            'id': [1, 1, 1],
            'ts': pd.date_range('2024-01-01', periods=3, freq='D', tz='UTC'),
            'close': [100.0, 102.0, 101.0],
        })

        # Load data
        df = self.feature.load_source_data(
            ids=[1],
            start='2024-01-01',
            end='2024-01-03',
        )

        # Verify query was called
        self.assertTrue(mock_read_sql.called)
        call_args = mock_read_sql.call_args
        query_text = str(call_args[0][0])

        # Check query contains expected elements
        self.assertIn('cmc_price_bars_1d', query_text)
        self.assertIn('id IN (1)', query_text)
        self.assertIn("time_close >= '2024-01-01'", query_text)
        self.assertIn("time_close <= '2024-01-03'", query_text)
        self.assertIn('ORDER BY id, ts ASC', query_text)

        # Verify result
        self.assertEqual(len(df), 3)
        self.assertListEqual(list(df.columns), ['id', 'ts', 'close'])

    def test_load_source_data_empty_ids(self):
        """Test loading with empty ID list."""
        df = self.feature.load_source_data(ids=[])
        self.assertTrue(df.empty)


class TestReturnsFeatureComputation(unittest.TestCase):
    """Test returns computation logic."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = ReturnsConfig(lookback_windows=(1, 3, 5))
        self.feature = ReturnsFeature(self.mock_engine, self.config)

    def test_compute_features_basic(self):
        """Test basic returns calculation."""
        # Create source data with known returns
        # Price sequence: 100, 105, 110 -> +5%, +4.76%
        df_source = pd.DataFrame({
            'id': [1, 1, 1],
            'ts': pd.date_range('2024-01-01', periods=3, freq='D', tz='UTC'),
            'close': [100.0, 105.0, 110.0],
        })

        # Mock get_lookback_windows
        with patch.object(self.feature, 'get_lookback_windows', return_value=[1, 3, 5]):
            df_features = self.feature.compute_features(df_source)

        # Verify columns exist
        self.assertIn('ret_1d_pct', df_features.columns)
        self.assertIn('ret_1d_log', df_features.columns)
        self.assertIn('ret_3d_pct', df_features.columns)
        self.assertIn('gap_days', df_features.columns)

        # Verify 1-day percent return
        # Row 0: NaN (no previous)
        # Row 1: (105 - 100) / 100 = 0.05
        # Row 2: (110 - 105) / 105 ≈ 0.0476
        self.assertTrue(pd.isna(df_features.iloc[0]['ret_1d_pct']))
        self.assertAlmostEqual(df_features.iloc[1]['ret_1d_pct'], 0.05, places=4)
        self.assertAlmostEqual(df_features.iloc[2]['ret_1d_pct'], 0.0476, places=4)

        # Verify 1-day log return
        # log(105/100) ≈ 0.04879
        self.assertAlmostEqual(df_features.iloc[1]['ret_1d_log'], 0.04879, places=4)

    def test_compute_features_gap_days(self):
        """Test gap_days tracking."""
        # Create source data with a gap
        df_source = pd.DataFrame({
            'id': [1, 1, 1],
            'ts': pd.to_datetime([
                '2024-01-01',
                '2024-01-02',
                '2024-01-05',  # 3-day gap
            ], utc=True),
            'close': [100.0, 102.0, 105.0],
        })

        with patch.object(self.feature, 'get_lookback_windows', return_value=[1, 3]):
            df_features = self.feature.compute_features(df_source)

        # Verify gap_days
        self.assertTrue(pd.isna(df_features.iloc[0]['gap_days']))  # First row
        self.assertEqual(df_features.iloc[1]['gap_days'], 1)  # Normal 1-day
        self.assertEqual(df_features.iloc[2]['gap_days'], 3)  # 3-day gap

    def test_compute_features_multiple_assets(self):
        """Test computation with multiple assets."""
        df_source = pd.DataFrame({
            'id': [1, 1, 2, 2],
            'ts': pd.date_range('2024-01-01', periods=4, freq='D', tz='UTC').tolist() * 1,
            'close': [100.0, 105.0, 200.0, 210.0],
        })
        # Adjust to proper structure
        df_source = pd.DataFrame({
            'id': [1, 1, 2, 2],
            'ts': [
                pd.Timestamp('2024-01-01', tz='UTC'),
                pd.Timestamp('2024-01-02', tz='UTC'),
                pd.Timestamp('2024-01-01', tz='UTC'),
                pd.Timestamp('2024-01-02', tz='UTC'),
            ],
            'close': [100.0, 105.0, 200.0, 210.0],
        })

        with patch.object(self.feature, 'get_lookback_windows', return_value=[1]):
            df_features = self.feature.compute_features(df_source)

        # Verify each asset processed separately
        asset1 = df_features[df_features['id'] == 1].reset_index(drop=True)
        asset2 = df_features[df_features['id'] == 2].reset_index(drop=True)

        # Asset 1: 5% return
        self.assertAlmostEqual(asset1.iloc[1]['ret_1d_pct'], 0.05, places=4)

        # Asset 2: 5% return
        self.assertAlmostEqual(asset2.iloc[1]['ret_1d_pct'], 0.05, places=4)

    def test_compute_features_multi_day_returns(self):
        """Test multi-day returns calculation."""
        # Create price data with known multi-day returns
        # Prices: 100, 110, 121 -> 10% per day
        df_source = pd.DataFrame({
            'id': [1] * 5,
            'ts': pd.date_range('2024-01-01', periods=5, freq='D', tz='UTC'),
            'close': [100.0, 110.0, 121.0, 133.1, 146.41],  # ~10% per day
        })

        with patch.object(self.feature, 'get_lookback_windows', return_value=[1, 3]):
            df_features = self.feature.compute_features(df_source)

        # Verify 3-day return exists
        self.assertIn('ret_3d_pct', df_features.columns)

        # Row 3 should have 3-day return: (133.1 - 100) / 100 = 0.331
        ret_3d = df_features.iloc[3]['ret_3d_pct']
        self.assertAlmostEqual(ret_3d, 0.331, places=3)

    def test_add_normalizations_zscore_columns(self):
        """Test that z-score columns are added for key windows."""
        # Create computed features
        df = pd.DataFrame({
            'id': [1] * 300,
            'ts': pd.date_range('2024-01-01', periods=300, freq='D', tz='UTC'),
            'ret_1d_pct': np.random.randn(300) * 0.01,
            'ret_7d_pct': np.random.randn(300) * 0.02,
            'ret_30d_pct': np.random.randn(300) * 0.05,
        })

        # Apply normalization
        df_norm = self.feature.add_normalizations(df)

        # Verify z-score columns exist
        self.assertIn('ret_1d_pct_zscore', df_norm.columns)
        self.assertIn('ret_7d_pct_zscore', df_norm.columns)
        self.assertIn('ret_30d_pct_zscore', df_norm.columns)

        # Verify z-scores are calculated (last row should have value after 252-day window)
        self.assertTrue(pd.notna(df_norm.iloc[-1]['ret_1d_pct_zscore']))


class TestReturnsFeatureOutliers(unittest.TestCase):
    """Test outlier detection."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = ReturnsConfig()
        self.feature = ReturnsFeature(self.mock_engine, self.config)

    def test_add_outlier_flags_extreme_returns(self):
        """Test outlier flagging for extreme returns."""
        # Create data with extreme outlier (need more extreme value for 4 sigma)
        df = pd.DataFrame({
            'id': [1] * 20,
            'ts': pd.date_range('2024-01-01', periods=20, freq='D', tz='UTC'),
            'ret_1d_pct': [0.01] * 10 + [50.0] + [0.01] * 9,  # 50.0 is extreme outlier
            'ret_7d_pct': [0.05] * 20,
            'ret_30d_pct': [0.10] * 20,
        })

        # Apply outlier detection
        df_flagged = self.feature.add_outlier_flags(df)

        # Verify is_outlier column exists
        self.assertIn('is_outlier', df_flagged.columns)

        # Verify extreme return is flagged (use == True instead of is True for numpy bool)
        self.assertEqual(df_flagged.iloc[10]['is_outlier'], True)

        # Verify normal returns are not flagged
        self.assertEqual(df_flagged.iloc[0]['is_outlier'], False)


class TestReturnsFeatureFullFlow(unittest.TestCase):
    """Test full template method flow."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = ReturnsConfig(lookback_windows=(1, 7))
        self.feature = ReturnsFeature(self.mock_engine, self.config)

    @patch('ta_lab2.scripts.features.returns_feature.ReturnsFeature.write_to_db')
    @patch('ta_lab2.scripts.features.returns_feature.ReturnsFeature.load_source_data')
    @patch('ta_lab2.scripts.features.returns_feature.ReturnsFeature.get_lookback_windows')
    def test_compute_for_ids_full_flow(
        self,
        mock_get_windows,
        mock_load_source,
        mock_write,
    ):
        """Test complete compute_for_ids template method."""
        # Setup mocks
        mock_get_windows.return_value = [1, 7]

        dates = pd.date_range('2024-01-01', periods=10, freq='D', tz='UTC')
        mock_load_source.return_value = pd.DataFrame({
            'id': [1] * 10,
            'ts': dates,
            'close': [100 + i for i in range(10)],
        })

        mock_write.return_value = 10

        # Execute
        rows = self.feature.compute_for_ids(ids=[1])

        # Verify flow
        mock_load_source.assert_called_once_with([1], None, None)
        mock_get_windows.assert_called()
        mock_write.assert_called_once()

        # Verify result
        self.assertEqual(rows, 10)


class TestReturnsFeatureEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = ReturnsConfig()
        self.feature = ReturnsFeature(self.mock_engine, self.config)

    def test_empty_source_data(self):
        """Test handling of empty source data."""
        df_source = pd.DataFrame()

        with patch.object(self.feature, 'get_lookback_windows', return_value=[1]):
            df_features = self.feature.compute_features(df_source)

        # Should return empty DataFrame
        self.assertTrue(df_features.empty)

    def test_single_row_data(self):
        """Test handling of single row (no previous for returns)."""
        df_source = pd.DataFrame({
            'id': [1],
            'ts': [pd.Timestamp('2024-01-01', tz='UTC')],
            'close': [100.0],
        })

        with patch.object(self.feature, 'get_lookback_windows', return_value=[1]):
            df_features = self.feature.compute_features(df_source)

        # Should have NaN for returns (no previous)
        self.assertTrue(pd.isna(df_features.iloc[0]['ret_1d_pct']))
        self.assertTrue(pd.isna(df_features.iloc[0]['gap_days']))

    def test_get_feature_columns(self):
        """Test get_feature_columns returns expected list."""
        config = ReturnsConfig(lookback_windows=(1, 3, 7))
        feature = ReturnsFeature(self.mock_engine, config)

        columns = feature.get_feature_columns()

        # Should include bar-to-bar and multi-day
        self.assertIn('ret_1d_pct', columns)
        self.assertIn('ret_1d_log', columns)
        self.assertIn('ret_3d_pct', columns)
        self.assertIn('ret_7d_pct', columns)

        # Should not duplicate ret_1d_pct
        self.assertEqual(columns.count('ret_1d_pct'), 1)

    def test_get_output_schema(self):
        """Test get_output_schema returns complete schema."""
        schema = self.feature.get_output_schema()

        # Verify key columns
        self.assertIn('id', schema)
        self.assertIn('ts', schema)
        self.assertIn('close', schema)
        self.assertIn('ret_1d_pct', schema)
        self.assertIn('ret_1d_log', schema)
        self.assertIn('ret_7d_pct', schema)
        self.assertIn('ret_30d_pct', schema)
        self.assertIn('ret_1d_pct_zscore', schema)
        self.assertIn('gap_days', schema)
        self.assertIn('is_outlier', schema)

        # Verify types
        self.assertEqual(schema['id'], 'INTEGER')
        self.assertEqual(schema['ts'], 'TIMESTAMPTZ')
        self.assertEqual(schema['ret_1d_pct'], 'DOUBLE PRECISION')


class TestReturnsFeatureRepr(unittest.TestCase):
    """Test string representation."""

    def test_repr(self):
        """Test __repr__ method."""
        mock_engine = MagicMock()
        config = ReturnsConfig(lookback_windows=(1, 7, 30))
        feature = ReturnsFeature(mock_engine, config)

        repr_str = repr(feature)

        self.assertIn('ReturnsFeature', repr_str)
        self.assertIn('cmc_returns_daily', repr_str)
        self.assertIn('(1, 7, 30)', repr_str)


if __name__ == '__main__':
    unittest.main()
