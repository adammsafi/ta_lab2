"""
Unit tests for TAFeature module.

Tests cover:
- Configuration defaults and customization
- Indicator parameter loading from database
- RSI computation (multiple periods)
- MACD computation (multiple parameter sets)
- Stochastic computation
- Bollinger Bands computation
- ATR computation
- ADX computation
- Null handling (interpolate strategy)
- Missing volume graceful handling
- Full template method flow
- Dynamic indicator filtering
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from ta_lab2.scripts.features.ta_feature import TAFeature, TAConfig


class TestTAConfig(unittest.TestCase):
    """Test TAConfig dataclass."""

    def test_ta_config_defaults(self):
        """Test default configuration values."""
        config = TAConfig()

        self.assertEqual(config.feature_type, "ta")
        self.assertEqual(config.output_table, "cmc_ta_daily")
        self.assertEqual(config.null_strategy, "interpolate")
        self.assertEqual(config.add_zscore, True)
        self.assertEqual(config.zscore_window, 252)
        self.assertEqual(config.load_indicators_from_db, True)

    def test_ta_config_custom(self):
        """Test custom configuration."""
        config = TAConfig(
            null_strategy="skip",
            add_zscore=False,
            load_indicators_from_db=False,
        )

        self.assertEqual(config.null_strategy, "skip")
        self.assertEqual(config.add_zscore, False)
        self.assertEqual(config.load_indicators_from_db, False)


class TestTAFeatureIndicatorLoading(unittest.TestCase):
    """Test indicator parameter loading from database."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = TAConfig()
        self.feature = TAFeature(self.mock_engine, self.config)

    @patch("ta_lab2.scripts.features.ta_feature.text")
    def test_load_indicator_params_from_db(self, mock_text):
        """Test loading indicator parameters from dim_indicators."""
        # Mock database result
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("rsi", "rsi_14", '{"period": 14}'),
            ("macd", "macd_12_26_9", '{"fast": 12, "slow": 26, "signal": 9}'),
            ("stoch", "stoch_14_3", '{"k": 14, "d": 3}'),
        ]
        mock_conn.execute.return_value = mock_result
        self.mock_engine.connect.return_value.__enter__.return_value = mock_conn

        # Load indicators
        indicators = self.feature.load_indicator_params()

        # Verify results
        self.assertEqual(len(indicators), 3)
        self.assertEqual(indicators[0]["indicator_type"], "rsi")
        self.assertEqual(indicators[0]["indicator_name"], "rsi_14")
        self.assertEqual(indicators[0]["params"], {"period": 14})
        self.assertEqual(indicators[1]["indicator_type"], "macd")
        self.assertEqual(indicators[1]["params"], {"fast": 12, "slow": 26, "signal": 9})

    def test_get_default_indicators(self):
        """Test default indicator parameters when not loading from DB."""
        config = TAConfig(load_indicators_from_db=False)
        feature = TAFeature(self.mock_engine, config)

        indicators = feature.load_indicator_params()

        # Verify default indicators
        self.assertEqual(len(indicators), 9)
        indicator_names = [ind["indicator_name"] for ind in indicators]
        self.assertIn("rsi_14", indicator_names)
        self.assertIn("macd_12_26_9", indicator_names)
        self.assertIn("stoch_14_3", indicator_names)
        self.assertIn("bb_20_2", indicator_names)


class TestTAFeatureRSI(unittest.TestCase):
    """Test RSI computation."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = TAConfig(load_indicators_from_db=False)
        self.feature = TAFeature(self.mock_engine, self.config)

    def test_compute_rsi_14(self):
        """Test RSI calculation with period 14."""
        # Create price data with variable trend (mixed gains/losses for RSI)
        np.random.seed(42)
        base_prices = [100]
        for i in range(49):
            # Random walk with slight upward bias
            change = np.random.randn() * 2 + 0.1
            base_prices.append(base_prices[-1] + change)

        df = pd.DataFrame(
            {
                "id": [1] * 50,
                "ts": pd.date_range("2024-01-01", periods=50, freq="D", tz="UTC"),
                "close": base_prices,
            }
        )

        # Compute RSI
        params = {"period": 14}
        self.feature._compute_rsi(df, params)

        # Verify RSI column exists
        self.assertIn("rsi_14", df.columns)

        # Verify RSI is in valid range (0-100)
        rsi_values = df["rsi_14"].dropna()
        self.assertTrue(len(rsi_values) > 0, "RSI should have some non-null values")
        self.assertTrue((rsi_values >= 0).all())
        self.assertTrue((rsi_values <= 100).all())

    def test_compute_rsi_multiple_periods(self):
        """Test multiple RSI periods (7, 14, 21)."""
        df = pd.DataFrame(
            {
                "id": [1] * 50,
                "ts": pd.date_range("2024-01-01", periods=50, freq="D", tz="UTC"),
                "close": [100 + i * 0.5 for i in range(50)],
            }
        )

        # Compute RSI with different periods
        for period in [7, 14, 21]:
            params = {"period": period}
            self.feature._compute_rsi(df, params)

        # Verify all columns exist
        self.assertIn("rsi_7", df.columns)
        self.assertIn("rsi_14", df.columns)
        self.assertIn("rsi_21", df.columns)

        # All should be in valid range
        for col in ["rsi_7", "rsi_14", "rsi_21"]:
            values = df[col].dropna()
            if len(values) > 0:
                self.assertTrue((values >= 0).all())
                self.assertTrue((values <= 100).all())


class TestTAFeatureMACD(unittest.TestCase):
    """Test MACD computation."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = TAConfig(load_indicators_from_db=False)
        self.feature = TAFeature(self.mock_engine, self.config)

    def test_compute_macd_standard(self):
        """Test MACD with standard 12/26/9 parameters."""
        df = pd.DataFrame(
            {
                "id": [1] * 50,
                "ts": pd.date_range("2024-01-01", periods=50, freq="D", tz="UTC"),
                "close": [100 + i * 0.5 for i in range(50)],
            }
        )

        # Compute MACD
        params = {"fast": 12, "slow": 26, "signal": 9}
        self.feature._compute_macd(df, params)

        # Verify columns exist
        self.assertIn("macd_12_26", df.columns)
        self.assertIn("macd_signal_9", df.columns)
        self.assertIn("macd_hist_12_26_9", df.columns)

        # Verify histogram = macd - signal
        macd_values = df["macd_12_26"].dropna()
        signal_values = df["macd_signal_9"].dropna()
        hist_values = df["macd_hist_12_26_9"].dropna()

        # Check histogram calculation for overlapping non-null values
        for idx in macd_values.index:
            if idx in signal_values.index and idx in hist_values.index:
                expected_hist = macd_values[idx] - signal_values[idx]
                self.assertAlmostEqual(hist_values[idx], expected_hist, places=5)

    def test_compute_macd_fast(self):
        """Test MACD with fast 8/17/9 parameters."""
        df = pd.DataFrame(
            {
                "id": [1] * 40,
                "ts": pd.date_range("2024-01-01", periods=40, freq="D", tz="UTC"),
                "close": [100 + i * 0.3 for i in range(40)],
            }
        )

        # Compute fast MACD
        params = {"fast": 8, "slow": 17, "signal": 9}
        self.feature._compute_macd(df, params)

        # Verify columns exist
        self.assertIn("macd_8_17", df.columns)
        self.assertIn("macd_signal_9", df.columns)
        self.assertIn("macd_hist_8_17_9", df.columns)


class TestTAFeatureStochastic(unittest.TestCase):
    """Test Stochastic computation."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = TAConfig(load_indicators_from_db=False)
        self.feature = TAFeature(self.mock_engine, self.config)

    def test_compute_stochastic(self):
        """Test Stochastic %K/%D calculation."""
        # Create OHLC data
        df = pd.DataFrame(
            {
                "id": [1] * 20,
                "ts": pd.date_range("2024-01-01", periods=20, freq="D", tz="UTC"),
                "open": [100 + i for i in range(20)],
                "high": [102 + i for i in range(20)],
                "low": [99 + i for i in range(20)],
                "close": [101 + i for i in range(20)],
            }
        )

        # Compute Stochastic
        params = {"k": 14, "d": 3}
        self.feature._compute_stoch(df, params)

        # Verify columns exist
        self.assertIn("stoch_k_14", df.columns)
        self.assertIn("stoch_d_3", df.columns)

        # Verify values are in valid range (0-100)
        k_values = df["stoch_k_14"].dropna()
        d_values = df["stoch_d_3"].dropna()

        self.assertTrue((k_values >= 0).all())
        self.assertTrue((k_values <= 100).all())
        self.assertTrue((d_values >= 0).all())
        self.assertTrue((d_values <= 100).all())


class TestTAFeatureBollingerBands(unittest.TestCase):
    """Test Bollinger Bands computation."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = TAConfig(load_indicators_from_db=False)
        self.feature = TAFeature(self.mock_engine, self.config)

    def test_compute_bollinger(self):
        """Test Bollinger Bands with 20/2 parameters."""
        df = pd.DataFrame(
            {
                "id": [1] * 30,
                "ts": pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC"),
                "close": [100 + np.sin(i / 5) * 5 for i in range(30)],
            }
        )

        # Compute Bollinger Bands
        params = {"window": 20, "n_sigma": 2.0}
        self.feature._compute_bollinger(df, params)

        # Verify columns exist
        self.assertIn("bb_ma_20", df.columns)
        self.assertIn("bb_up_20_2", df.columns)
        self.assertIn("bb_lo_20_2", df.columns)
        self.assertIn("bb_width_20", df.columns)

        # Verify upper > ma > lower
        valid_idx = df["bb_ma_20"].notna()
        if valid_idx.any():
            self.assertTrue(
                (df.loc[valid_idx, "bb_up_20_2"] >= df.loc[valid_idx, "bb_ma_20"]).all()
            )
            self.assertTrue(
                (df.loc[valid_idx, "bb_ma_20"] >= df.loc[valid_idx, "bb_lo_20_2"]).all()
            )


class TestTAFeatureATR(unittest.TestCase):
    """Test ATR computation."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = TAConfig(load_indicators_from_db=False)
        self.feature = TAFeature(self.mock_engine, self.config)

    def test_compute_atr(self):
        """Test ATR calculation."""
        df = pd.DataFrame(
            {
                "id": [1] * 20,
                "ts": pd.date_range("2024-01-01", periods=20, freq="D", tz="UTC"),
                "open": [100 + i for i in range(20)],
                "high": [105 + i for i in range(20)],
                "low": [98 + i for i in range(20)],
                "close": [102 + i for i in range(20)],
            }
        )

        # Compute ATR
        params = {"period": 14}
        self.feature._compute_atr(df, params)

        # Verify column exists
        self.assertIn("atr_14", df.columns)

        # Verify ATR is positive
        atr_values = df["atr_14"].dropna()
        self.assertTrue((atr_values > 0).all())


class TestTAFeatureADX(unittest.TestCase):
    """Test ADX computation."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = TAConfig(load_indicators_from_db=False)
        self.feature = TAFeature(self.mock_engine, self.config)

    def test_compute_adx(self):
        """Test ADX calculation."""
        df = pd.DataFrame(
            {
                "id": [1] * 30,
                "ts": pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC"),
                "open": [100 + i for i in range(30)],
                "high": [105 + i for i in range(30)],
                "low": [98 + i for i in range(30)],
                "close": [102 + i for i in range(30)],
            }
        )

        # Compute ADX
        params = {"period": 14}
        self.feature._compute_adx(df, params)

        # Verify column exists
        self.assertIn("adx_14", df.columns)

        # Verify ADX is in valid range (0-100)
        adx_values = df["adx_14"].dropna()
        self.assertTrue((adx_values >= 0).all())
        self.assertTrue((adx_values <= 100).all())


class TestTAFeatureNullHandling(unittest.TestCase):
    """Test null handling with interpolate strategy."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = TAConfig(
            null_strategy="interpolate",
            load_indicators_from_db=False,
        )
        self.feature = TAFeature(self.mock_engine, self.config)

    def test_null_handling_interpolate(self):
        """Test that gaps are interpolated before indicator computation."""
        # Create data with gaps
        df_source = pd.DataFrame(
            {
                "id": [1] * 10,
                "ts": pd.date_range("2024-01-01", periods=10, freq="D", tz="UTC"),
                "close": [
                    100.0,
                    101.0,
                    np.nan,
                    np.nan,
                    104.0,
                    105.0,
                    106.0,
                    107.0,
                    108.0,
                    109.0,
                ],
            }
        )

        # Apply null handling
        df_handled = self.feature.apply_null_handling(df_source)

        # Verify nulls are filled
        self.assertFalse(df_handled["close"].isna().any())

        # Verify interpolation (should fill with linear values)
        # 101 -> 102 -> 103 -> 104
        self.assertAlmostEqual(df_handled.iloc[2]["close"], 102.0, places=1)
        self.assertAlmostEqual(df_handled.iloc[3]["close"], 103.0, places=1)


class TestTAFeatureMissingVolume(unittest.TestCase):
    """Test graceful handling of missing volume."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = TAConfig(load_indicators_from_db=False)
        self.feature = TAFeature(self.mock_engine, self.config)

    def test_missing_volume_graceful(self):
        """Test that indicators work without volume column."""
        # Create OHLC data without volume
        df = pd.DataFrame(
            {
                "id": [1] * 30,
                "ts": pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC"),
                "open": [100 + i for i in range(30)],
                "high": [105 + i for i in range(30)],
                "low": [98 + i for i in range(30)],
                "close": [102 + i for i in range(30)],
            }
        )

        # Compute RSI (doesn't need volume)
        params = {"period": 14}
        result = self.feature._compute_rsi(df, params)

        # Should succeed
        self.assertIn("rsi_14", result.columns)


class TestTAFeatureFullFlow(unittest.TestCase):
    """Test full template method flow."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = TAConfig(load_indicators_from_db=False)
        self.feature = TAFeature(self.mock_engine, self.config)

    @patch("ta_lab2.scripts.features.ta_feature.pd.read_sql")
    def test_compute_for_ids_full_flow(self, mock_read_sql):
        """Test compute_for_ids template method."""
        # Mock source data
        mock_read_sql.return_value = pd.DataFrame(
            {
                "id": [1] * 30,
                "ts": pd.date_range("2024-01-01", periods=30, freq="D", tz="UTC"),
                "open": [100 + i for i in range(30)],
                "high": [105 + i for i in range(30)],
                "low": [98 + i for i in range(30)],
                "close": [102 + i for i in range(30)],
                "volume": [1000000.0] * 30,
            }
        )

        # Mock write_to_db to avoid actual database writes
        with patch.object(self.feature, "write_to_db", return_value=30):
            rows = self.feature.compute_for_ids(ids=[1], start="2024-01-01")

        # Verify it ran
        self.assertEqual(rows, 30)


class TestTAFeatureDynamicIndicators(unittest.TestCase):
    """Test dynamic indicator configuration."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_engine = MagicMock()
        self.config = TAConfig()
        self.feature = TAFeature(self.mock_engine, self.config)

    @patch("ta_lab2.scripts.features.ta_feature.text")
    def test_dynamic_indicators_only_active(self, mock_text):
        """Test that only active indicators are computed."""
        # Mock database with only RSI active
        mock_conn = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [
            ("rsi", "rsi_14", '{"period": 14}'),
        ]
        mock_conn.execute.return_value = mock_result
        self.mock_engine.connect.return_value.__enter__.return_value = mock_conn

        # Load indicators
        indicators = self.feature.load_indicator_params()

        # Verify only RSI is loaded
        self.assertEqual(len(indicators), 1)
        self.assertEqual(indicators[0]["indicator_type"], "rsi")

    def test_get_feature_columns_dynamic(self):
        """Test feature columns list is dynamic based on active indicators."""
        # Use default indicators
        config = TAConfig(load_indicators_from_db=False)
        feature = TAFeature(self.mock_engine, config)

        # Get feature columns
        feature_cols = feature.get_feature_columns()

        # Verify expected columns
        self.assertIn("rsi_14", feature_cols)
        self.assertIn("macd_12_26", feature_cols)
        self.assertIn("stoch_k_14", feature_cols)
        self.assertIn("bb_ma_20", feature_cols)
        self.assertIn("atr_14", feature_cols)
        self.assertIn("adx_14", feature_cols)


if __name__ == "__main__":
    unittest.main()
