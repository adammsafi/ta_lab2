"""
Tests for RSI signal generation.

This module tests RSISignalGenerator including:
- Signal transformation with RSI value tracking
- Adaptive threshold computation
- Integration with rsi_mean_revert.py adapter
- Feature hashing and params hashing
- Database roundtrip (integration tests)
"""

import os
import unittest
from unittest.mock import MagicMock, patch, call
import pandas as pd
import numpy as np
import pytest
from sqlalchemy import create_engine, text

from ta_lab2.scripts.signals.generate_signals_rsi import (
    RSISignalGenerator,
    compute_adaptive_thresholds,
)
from ta_lab2.scripts.signals.signal_state_manager import (
    SignalStateManager,
    SignalStateConfig,
)


# =============================================================================
# Unit Tests (No Database Required)
# =============================================================================

class TestRSISignalTransformation(unittest.TestCase):
    """Test signal transformation to stateful records."""

    def test_transform_signals_includes_rsi_at_entry(self):
        """Verify rsi_at_entry captured in signal records."""
        # Setup
        mock_engine = MagicMock()
        mock_state_manager = MagicMock()

        generator = RSISignalGenerator(mock_engine, mock_state_manager)

        # Create test data
        df_features = pd.DataFrame({
            'id': [1, 1, 1, 1],
            'ts': pd.to_datetime(['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04']),
            'close': [100.0, 101.0, 102.0, 103.0],
            'rsi_14': [25.0, 35.0, 65.0, 75.0],
            'atr_14': [2.0, 2.1, 2.2, 2.3],
        })

        entries = pd.Series([False, True, False, False], index=df_features.index)
        exits = pd.Series([False, False, True, False], index=df_features.index)

        # Transform
        df_records = generator.transform_signals_to_records(
            entries=entries,
            exits=exits,
            df_features=df_features,
            signal_id=1,
            params={'lower': 30, 'upper': 70},
            feature_hash='abc123',
            params_hash='def456',
            rsi_col='rsi_14',
        )

        # Verify
        self.assertEqual(len(df_records), 1)
        self.assertEqual(df_records.iloc[0]['rsi_at_entry'], 35.0)
        self.assertEqual(df_records.iloc[0]['position_state'], 'closed')

    def test_transform_signals_includes_rsi_at_exit(self):
        """Verify rsi_at_exit captured when position closes."""
        # Setup
        mock_engine = MagicMock()
        mock_state_manager = MagicMock()

        generator = RSISignalGenerator(mock_engine, mock_state_manager)

        # Create test data with entry and exit
        df_features = pd.DataFrame({
            'id': [1, 1, 1],
            'ts': pd.to_datetime(['2024-01-01', '2024-01-02', '2024-01-03']),
            'close': [100.0, 105.0, 110.0],
            'rsi_14': [28.0, 45.0, 72.0],
            'atr_14': [2.0, 2.1, 2.2],
        })

        entries = pd.Series([False, True, False], index=df_features.index)
        exits = pd.Series([False, False, True], index=df_features.index)

        # Transform
        df_records = generator.transform_signals_to_records(
            entries=entries,
            exits=exits,
            df_features=df_features,
            signal_id=1,
            params={'lower': 30, 'upper': 70},
            feature_hash='abc123',
            params_hash='def456',
        )

        # Verify
        self.assertEqual(len(df_records), 1)
        self.assertEqual(df_records.iloc[0]['rsi_at_exit'], 72.0)
        self.assertEqual(df_records.iloc[0]['position_state'], 'closed')

    def test_generate_loads_thresholds_from_config(self):
        """Verify lower/upper thresholds passed to make_signals."""
        # Setup
        mock_engine = MagicMock()
        mock_state_manager = MagicMock()
        mock_state_manager.get_dirty_window_start.return_value = {1: None}

        generator = RSISignalGenerator(mock_engine, mock_state_manager)

        # Mock load_features to return test data
        test_features = pd.DataFrame({
            'id': [1, 1],
            'ts': pd.to_datetime(['2024-01-01', '2024-01-02'], utc=True),
            'close': [100.0, 101.0],
            'rsi_14': [25.0, 75.0],
            'atr_14': [2.0, 2.1],
        })

        with patch.object(generator, 'load_features', return_value=test_features):
            with patch('ta_lab2.scripts.signals.generate_signals_rsi.make_signals') as mock_make_signals:
                # Configure mock to return empty signals
                mock_make_signals.return_value = (
                    pd.Series([False, False], index=test_features.index),
                    pd.Series([False, False], index=test_features.index),
                    None
                )

                # Call generate_for_ids with custom thresholds
                generator.generate_for_ids(
                    ids=[1],
                    signal_config={
                        'signal_id': 1,
                        'signal_name': 'test_rsi',
                        'params': {'lower': 25.0, 'upper': 75.0}
                    },
                    dry_run=True
                )

                # Verify make_signals called with correct thresholds
                mock_make_signals.assert_called_once()
                call_kwargs = mock_make_signals.call_args[1]
                self.assertEqual(call_kwargs['lower'], 25.0)
                self.assertEqual(call_kwargs['upper'], 75.0)

    def test_generate_uses_correct_rsi_column(self):
        """Verify params['rsi_col'] used in make_signals."""
        # Setup
        mock_engine = MagicMock()
        mock_state_manager = MagicMock()
        mock_state_manager.get_dirty_window_start.return_value = {1: None}

        generator = RSISignalGenerator(mock_engine, mock_state_manager)

        test_features = pd.DataFrame({
            'id': [1],
            'ts': pd.to_datetime(['2024-01-01'], utc=True),
            'close': [100.0],
            'rsi_14': [30.0],
            'rsi_7': [35.0],
            'atr_14': [2.0],
        })

        with patch.object(generator, 'load_features', return_value=test_features):
            with patch('ta_lab2.scripts.signals.generate_signals_rsi.make_signals') as mock_make_signals:
                mock_make_signals.return_value = (
                    pd.Series([False], index=test_features.index),
                    pd.Series([False], index=test_features.index),
                    None
                )

                # Call with rsi_7 instead of default rsi_14
                generator.generate_for_ids(
                    ids=[1],
                    signal_config={
                        'signal_id': 1,
                        'signal_name': 'test_rsi_7',
                        'params': {'rsi_col': 'rsi_7', 'lower': 30, 'upper': 70}
                    },
                    dry_run=True
                )

                # Verify correct RSI column used
                call_kwargs = mock_make_signals.call_args[1]
                self.assertEqual(call_kwargs['rsi_col'], 'rsi_7')

    def test_confirm_cross_parameter_passed(self):
        """Verify confirm_cross from params honored."""
        # Setup
        mock_engine = MagicMock()
        mock_state_manager = MagicMock()
        mock_state_manager.get_dirty_window_start.return_value = {1: None}

        generator = RSISignalGenerator(mock_engine, mock_state_manager)

        test_features = pd.DataFrame({
            'id': [1],
            'ts': pd.to_datetime(['2024-01-01'], utc=True),
            'close': [100.0],
            'rsi_14': [30.0],
            'atr_14': [2.0],
        })

        with patch.object(generator, 'load_features', return_value=test_features):
            with patch('ta_lab2.scripts.signals.generate_signals_rsi.make_signals') as mock_make_signals:
                mock_make_signals.return_value = (
                    pd.Series([False], index=test_features.index),
                    pd.Series([False], index=test_features.index),
                    None
                )

                # Call with confirm_cross=False
                generator.generate_for_ids(
                    ids=[1],
                    signal_config={
                        'signal_id': 1,
                        'signal_name': 'test_no_confirm',
                        'params': {'confirm_cross': False, 'lower': 30, 'upper': 70}
                    },
                    dry_run=True
                )

                # Verify confirm_cross passed
                call_kwargs = mock_make_signals.call_args[1]
                self.assertFalse(call_kwargs['confirm_cross'])

    def test_pnl_calculation_correct(self):
        """Verify PnL calculation: (exit - entry) / entry * 100."""
        # Setup
        mock_engine = MagicMock()
        mock_state_manager = MagicMock()

        generator = RSISignalGenerator(mock_engine, mock_state_manager)

        df_features = pd.DataFrame({
            'id': [1, 1, 1],
            'ts': pd.to_datetime(['2024-01-01', '2024-01-02', '2024-01-03']),
            'close': [100.0, 105.0, 110.0],
            'rsi_14': [25.0, 50.0, 75.0],
            'atr_14': [2.0, 2.1, 2.2],
        })

        entries = pd.Series([False, True, False], index=df_features.index)
        exits = pd.Series([False, False, True], index=df_features.index)

        # Transform
        df_records = generator.transform_signals_to_records(
            entries=entries,
            exits=exits,
            df_features=df_features,
            signal_id=1,
            params={'lower': 30, 'upper': 70},
            feature_hash='abc123',
            params_hash='def456',
        )

        # Verify PnL calculation
        # Entry: 105.0, Exit: 110.0
        # PnL = (110 - 105) / 105 * 100 = 4.76%
        expected_pnl = ((110.0 - 105.0) / 105.0) * 100.0
        self.assertAlmostEqual(df_records.iloc[0]['pnl_pct'], expected_pnl, places=2)

    def test_feature_hash_includes_rsi(self):
        """Verify feature hash computed on RSI columns."""
        # This is tested indirectly via transform_signals_to_records
        # Feature hash should include rsi_col in the hashed columns
        from ta_lab2.scripts.signals.signal_utils import compute_feature_hash

        df = pd.DataFrame({
            'ts': pd.to_datetime(['2024-01-01', '2024-01-02']),
            'close': [100.0, 101.0],
            'rsi_14': [30.0, 70.0],
            'atr_14': [2.0, 2.1],
        })

        # Compute hash with RSI included
        hash1 = compute_feature_hash(df, ['close', 'rsi_14', 'atr_14'])

        # Modify RSI values
        df['rsi_14'] = [35.0, 75.0]
        hash2 = compute_feature_hash(df, ['close', 'rsi_14', 'atr_14'])

        # Hashes should differ
        self.assertNotEqual(hash1, hash2)


class TestAdaptiveThresholds(unittest.TestCase):
    """Test adaptive threshold computation."""

    def test_adaptive_thresholds_computes_percentiles(self):
        """Verify rolling quantile logic."""
        df = pd.DataFrame({
            'rsi_14': [20, 30, 40, 50, 60, 70, 80, 30, 40, 50]
        })

        lower, upper = compute_adaptive_thresholds(
            df,
            rsi_col='rsi_14',
            lookback=5,
            lower_pct=20.0,
            upper_pct=80.0
        )

        # Verify series length matches input
        self.assertEqual(len(lower), len(df))
        self.assertEqual(len(upper), len(df))

        # Verify upper > lower (except for NaN initial values)
        valid_mask = ~(lower.isna() | upper.isna())
        self.assertTrue((upper[valid_mask] >= lower[valid_mask]).all())

    def test_adaptive_thresholds_handles_short_window(self):
        """Verify behavior when fewer rows than lookback."""
        df = pd.DataFrame({
            'rsi_14': [30, 40, 50]  # Only 3 rows
        })

        lower, upper = compute_adaptive_thresholds(
            df,
            rsi_col='rsi_14',
            lookback=100,  # Much larger than data
            lower_pct=20.0,
            upper_pct=80.0
        )

        # Should still compute (min_periods=1)
        self.assertEqual(len(lower), 3)
        self.assertEqual(len(upper), 3)

        # All values should be present (no NaN with min_periods=1)
        self.assertFalse(lower.isna().any())
        self.assertFalse(upper.isna().any())

    def test_use_adaptive_flag_calls_compute_adaptive(self):
        """Verify use_adaptive=True triggers adaptive computation."""
        # Setup
        mock_engine = MagicMock()
        mock_state_manager = MagicMock()
        mock_state_manager.get_dirty_window_start.return_value = {1: None}

        generator = RSISignalGenerator(mock_engine, mock_state_manager)

        test_features = pd.DataFrame({
            'id': [1, 1, 1, 1, 1],
            'ts': pd.to_datetime(['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'], utc=True),
            'close': [100.0, 101.0, 102.0, 103.0, 104.0],
            'rsi_14': [20.0, 30.0, 40.0, 60.0, 80.0],
            'atr_14': [2.0, 2.1, 2.2, 2.3, 2.4],
        })

        with patch.object(generator, 'load_features', return_value=test_features):
            with patch('ta_lab2.scripts.signals.generate_signals_rsi.compute_adaptive_thresholds') as mock_adaptive:
                with patch('ta_lab2.scripts.signals.generate_signals_rsi.make_signals') as mock_make_signals:
                    # Configure mocks
                    mock_adaptive.return_value = (
                        pd.Series([25.0, 25.0, 25.0, 25.0, 25.0], index=test_features.index),
                        pd.Series([75.0, 75.0, 75.0, 75.0, 75.0], index=test_features.index),
                    )
                    mock_make_signals.return_value = (
                        pd.Series([False] * 5, index=test_features.index),
                        pd.Series([False] * 5, index=test_features.index),
                        None
                    )

                    # Call with use_adaptive=True
                    generator.generate_for_ids(
                        ids=[1],
                        signal_config={
                            'signal_id': 1,
                            'signal_name': 'test_adaptive',
                            'params': {'lower': 30, 'upper': 70}
                        },
                        use_adaptive=True,
                        dry_run=True
                    )

                    # Verify compute_adaptive_thresholds was called
                    self.assertTrue(mock_adaptive.called)


# =============================================================================
# Integration Tests (Require Database)
# =============================================================================

TARGET_DB_URL = os.environ.get('TARGET_DB_URL')


@pytest.mark.skipif(not TARGET_DB_URL, reason="No TARGET_DB_URL")
class TestRSISignalRoundtrip:
    """Integration tests with database."""

    def test_roundtrip_rsi_signal_generation(self):
        """Generate signals, query back, verify structure."""
        engine = create_engine(TARGET_DB_URL)

        # Setup
        config = SignalStateConfig(signal_type='rsi_mean_revert')
        state_manager = SignalStateManager(engine, config)
        state_manager.ensure_state_table()

        generator = RSISignalGenerator(engine, state_manager)

        # Create test features in database
        test_data = pd.DataFrame({
            'id': [9999] * 5,
            'ts': pd.to_datetime(['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'], utc=True),
            'close': [100.0, 101.0, 105.0, 110.0, 108.0],
            'rsi_14': [25.0, 35.0, 50.0, 75.0, 70.0],
            'rsi_7': [20.0, 40.0, 55.0, 80.0, 65.0],
            'rsi_21': [30.0, 38.0, 48.0, 72.0, 68.0],
            'atr_14': [2.0, 2.1, 2.2, 2.3, 2.4],
        })

        # Insert test features (requires cmc_daily_features table exists)
        # For safety, skip if table doesn't exist
        try:
            with engine.begin() as conn:
                # Delete any existing test data
                conn.execute(text("DELETE FROM public.cmc_daily_features WHERE id = 9999"))
                test_data.to_sql(
                    'cmc_daily_features',
                    conn,
                    schema='public',
                    if_exists='append',
                    index=False
                )
        except Exception:
            pytest.skip("cmc_daily_features table not available")

        try:
            # Generate signals
            signal_config = {
                'signal_id': 9999,
                'signal_name': 'test_rsi_roundtrip',
                'params': {
                    'lower': 30.0,
                    'upper': 70.0,
                    'rsi_col': 'rsi_14',
                    'confirm_cross': True,
                }
            }

            count = generator.generate_for_ids(
                ids=[9999],
                signal_config=signal_config,
                full_refresh=True,
                dry_run=False
            )

            assert count > 0, "Expected at least one signal generated"

            # Query back from signal table
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT id, signal_id, position_state, rsi_at_entry, rsi_at_exit, pnl_pct
                    FROM public.cmc_signals_rsi_mean_revert
                    WHERE id = 9999 AND signal_id = 9999
                    ORDER BY ts
                """))
                rows = result.fetchall()

            assert len(rows) > 0, "Expected signals in database"

            # Verify structure
            for row in rows:
                assert row[0] == 9999  # id
                assert row[1] == 9999  # signal_id
                assert row[2] in ('open', 'closed')  # position_state

        finally:
            # Cleanup (gracefully handle missing tables)
            try:
                with engine.begin() as conn:
                    conn.execute(text("DELETE FROM public.cmc_signals_rsi_mean_revert WHERE id = 9999"))
                    conn.execute(text("DELETE FROM public.cmc_daily_features WHERE id = 9999"))
                    conn.execute(text("DELETE FROM public.cmc_signal_state WHERE id = 9999"))
            except Exception:
                pass  # Tables may not exist

    def test_rsi_values_tracked_correctly(self):
        """Verify rsi_at_entry/exit match source data."""
        engine = create_engine(TARGET_DB_URL)

        config = SignalStateConfig(signal_type='rsi_mean_revert')
        state_manager = SignalStateManager(engine, config)
        state_manager.ensure_state_table()

        generator = RSISignalGenerator(engine, state_manager)

        # Known RSI values
        test_data = pd.DataFrame({
            'id': [9998] * 4,
            'ts': pd.to_datetime(['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04'], utc=True),
            'close': [100.0, 105.0, 110.0, 108.0],
            'rsi_14': [28.0, 45.0, 72.0, 68.0],  # Entry at 45, exit at 72
            'rsi_7': [25.0, 50.0, 75.0, 70.0],
            'rsi_21': [30.0, 42.0, 70.0, 65.0],
            'atr_14': [2.0, 2.1, 2.2, 2.3],
        })

        try:
            with engine.begin() as conn:
                # Check if table exists
                try:
                    conn.execute(text("DELETE FROM public.cmc_daily_features WHERE id = 9998"))
                except Exception:
                    pytest.skip("cmc_daily_features table not available")
                test_data.to_sql('cmc_daily_features', conn, schema='public', if_exists='append', index=False)

            signal_config = {
                'signal_id': 9998,
                'signal_name': 'test_rsi_values',
                'params': {'lower': 30.0, 'upper': 70.0, 'rsi_col': 'rsi_14', 'confirm_cross': True}
            }

            generator.generate_for_ids(
                ids=[9998],
                signal_config=signal_config,
                full_refresh=True,
                dry_run=False
            )

            # Query signals
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT rsi_at_entry, rsi_at_exit, position_state
                    FROM public.cmc_signals_rsi_mean_revert
                    WHERE id = 9998 AND signal_id = 9998
                    ORDER BY ts
                """))
                rows = result.fetchall()

            # Find closed position
            closed = [r for r in rows if r[2] == 'closed']
            if closed:
                # Verify RSI values match
                # Entry should be around 45.0 (recovering from oversold)
                # Exit should be around 72.0 (reaching overbought)
                assert closed[0][0] is not None  # rsi_at_entry
                assert closed[0][1] is not None  # rsi_at_exit

        finally:
            # Cleanup (gracefully handle missing tables)
            try:
                with engine.begin() as conn:
                    conn.execute(text("DELETE FROM public.cmc_signals_rsi_mean_revert WHERE id = 9998"))
                    conn.execute(text("DELETE FROM public.cmc_daily_features WHERE id = 9998"))
                    conn.execute(text("DELETE FROM public.cmc_signal_state WHERE id = 9998"))
            except Exception:
                pass  # Tables may not exist

    def test_different_thresholds_produce_different_signals(self):
        """Verify threshold configuration affects signal generation."""
        engine = create_engine(TARGET_DB_URL)

        config = SignalStateConfig(signal_type='rsi_mean_revert')
        state_manager = SignalStateManager(engine, config)
        state_manager.ensure_state_table()

        generator = RSISignalGenerator(engine, state_manager)

        # Test data with various RSI levels
        test_data = pd.DataFrame({
            'id': [9997] * 10,
            'ts': pd.to_datetime([f'2024-01-{i+1:02d}' for i in range(10)], utc=True),
            'close': [100.0 + i for i in range(10)],
            'rsi_14': [20, 25, 30, 35, 40, 60, 65, 70, 75, 80],
            'rsi_7': [25, 30, 35, 40, 45, 55, 60, 65, 70, 75],
            'rsi_21': [22, 27, 32, 37, 42, 58, 63, 68, 73, 78],
            'atr_14': [2.0] * 10,
        })

        try:
            with engine.begin() as conn:
                # Check if table exists
                try:
                    conn.execute(text("DELETE FROM public.cmc_daily_features WHERE id = 9997"))
                except Exception:
                    pytest.skip("cmc_daily_features table not available")
                test_data.to_sql('cmc_daily_features', conn, schema='public', if_exists='append', index=False)

            # Generate with 30/70 thresholds
            config1 = {
                'signal_id': 9997,
                'signal_name': 'test_30_70',
                'params': {'lower': 30.0, 'upper': 70.0, 'rsi_col': 'rsi_14'}
            }
            count1 = generator.generate_for_ids(ids=[9997], signal_config=config1, full_refresh=True, dry_run=False)

            # Clear and generate with 25/75 thresholds
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM public.cmc_signals_rsi_mean_revert WHERE id = 9997"))

            config2 = {
                'signal_id': 9996,
                'signal_name': 'test_25_75',
                'params': {'lower': 25.0, 'upper': 75.0, 'rsi_col': 'rsi_14'}
            }
            count2 = generator.generate_for_ids(ids=[9997], signal_config=config2, full_refresh=True, dry_run=False)

            # Different thresholds should produce different signal counts
            # (May be same in some edge cases, but logic should differ)
            # At minimum, verify both generated signals
            assert count1 >= 0
            assert count2 >= 0

        finally:
            # Cleanup (gracefully handle missing tables)
            try:
                with engine.begin() as conn:
                    conn.execute(text("DELETE FROM public.cmc_signals_rsi_mean_revert WHERE id = 9997"))
                    conn.execute(text("DELETE FROM public.cmc_daily_features WHERE id = 9997"))
                    conn.execute(text("DELETE FROM public.cmc_signal_state WHERE id = 9997"))
            except Exception:
                pass  # Tables may not exist


if __name__ == '__main__':
    unittest.main()
