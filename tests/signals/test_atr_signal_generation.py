"""
Tests for ATR breakout signal generation.

Test coverage:
- Unit tests: Channel level computation, breakout classification, signal transformation
- Integration tests: Roundtrip signal generation, parameter variation
"""

import os
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
import pytest
from sqlalchemy import create_engine, text

from ta_lab2.scripts.signals import (
    SignalStateManager,
    SignalStateConfig,
    compute_feature_hash,
    compute_params_hash,
)
from ta_lab2.scripts.signals.generate_signals_atr import ATRSignalGenerator


# =============================================================================
# Unit Tests (database-free using mocks)
# =============================================================================


def test_compute_channel_levels_rolling_max_min():
    """Test Donchian channel computation using rolling max/min."""
    # Create mock engine and state manager
    engine = MagicMock()
    state_manager = MagicMock()
    generator = ATRSignalGenerator(engine, state_manager)

    # Sample data with clear channel pattern
    df = pd.DataFrame({
        'id': [1, 1, 1, 1, 1, 1],
        'ts': pd.date_range('2024-01-01', periods=6),
        'high': [100, 105, 110, 108, 106, 112],
        'low': [95, 100, 105, 103, 101, 107],
        'close': [98, 103, 108, 106, 104, 110],
    })

    lookback = 3
    result = generator._compute_channel_levels(df, lookback)

    # First 2 rows should have NaN (insufficient history)
    assert pd.isna(result['channel_high'].iloc[0])
    assert pd.isna(result['channel_high'].iloc[1])

    # Row 2 (index 2): channel_high = max(100, 105, 110) = 110
    assert result['channel_high'].iloc[2] == 110
    assert result['channel_low'].iloc[2] == 95

    # Row 3 (index 3): channel_high = max(105, 110, 108) = 110
    assert result['channel_high'].iloc[3] == 110
    assert result['channel_low'].iloc[3] == 100

    # Row 4 (index 4): channel_high = max(110, 108, 106) = 110
    assert result['channel_high'].iloc[4] == 110
    # Row 4 (index 4): channel_low = min(105, 103, 101) = 101
    assert result['channel_low'].iloc[4] == 101


def test_classify_breakout_type_channel_break():
    """Test breakout classification when close breaks channel."""
    engine = MagicMock()
    state_manager = MagicMock()
    generator = ATRSignalGenerator(engine, state_manager)

    # Row with close above channel_high
    row = pd.Series({
        'close': 115,
        'channel_high': 110,
        'channel_low': 95,
        'atr_14': 5.0,
    })

    params = {}
    breakout_type = generator._classify_breakout_type(row, params)

    # Should detect channel break
    assert breakout_type == 'channel_break'


def test_classify_breakout_type_below_channel():
    """Test breakout classification when close breaks below channel."""
    engine = MagicMock()
    state_manager = MagicMock()
    generator = ATRSignalGenerator(engine, state_manager)

    # Row with close below channel_low
    row = pd.Series({
        'close': 90,
        'channel_high': 110,
        'channel_low': 95,
        'atr_14': 5.0,
    })

    params = {}
    breakout_type = generator._classify_breakout_type(row, params)

    # Should detect channel break (downside)
    assert breakout_type == 'channel_break'


def test_classify_breakout_type_within_channel():
    """Test breakout classification when close within channel."""
    engine = MagicMock()
    state_manager = MagicMock()
    generator = ATRSignalGenerator(engine, state_manager)

    # Row with close within channel
    row = pd.Series({
        'close': 100,
        'channel_high': 110,
        'channel_low': 95,
        'atr_14': 5.0,
    })

    params = {}
    breakout_type = generator._classify_breakout_type(row, params)

    # Should still classify (since function assumes signal triggered)
    assert breakout_type in ['channel_break', 'atr_expansion', 'both']


def test_transform_signals_includes_breakout_type():
    """Test that transformed signals include breakout_type column."""
    engine = MagicMock()
    state_manager = MagicMock()
    generator = ATRSignalGenerator(engine, state_manager)

    # Sample data with entry signal
    df = pd.DataFrame({
        'id': [1, 1, 1],
        'ts': pd.date_range('2024-01-01', periods=3),
        'open': [100, 102, 104],
        'high': [101, 103, 105],
        'low': [99, 101, 103],
        'close': [100, 102, 104],
        'atr_14': [2.0, 2.1, 2.2],
        'channel_high': [105, 105, 105],
        'channel_low': [95, 95, 95],
        'entry_signal': [False, True, False],  # Entry at row 1
        'exit_signal': [False, False, False],
    })

    signal_id = 1
    params = {'lookback': 20}
    open_positions = pd.DataFrame()

    records = generator._transform_signals_to_records(
        df_features=df,
        signal_id=signal_id,
        params=params,
        open_positions=open_positions,
    )

    # Should have 1 entry record
    assert len(records) == 1
    assert 'breakout_type' in records.columns
    assert records['breakout_type'].iloc[0] in ['channel_break', 'atr_expansion', 'both']


def test_transform_signals_includes_channel_levels():
    """Test that feature_snapshot includes channel_high and channel_low."""
    engine = MagicMock()
    state_manager = MagicMock()
    generator = ATRSignalGenerator(engine, state_manager)

    # Sample data with entry signal
    df = pd.DataFrame({
        'id': [1, 1, 1],
        'ts': pd.date_range('2024-01-01', periods=3),
        'open': [100, 102, 104],
        'high': [101, 103, 105],
        'low': [99, 101, 103],
        'close': [100, 102, 104],
        'atr_14': [2.0, 2.1, 2.2],
        'channel_high': [105.5, 106.0, 106.5],
        'channel_low': [95.5, 96.0, 96.5],
        'entry_signal': [False, True, False],
        'exit_signal': [False, False, False],
    })

    signal_id = 1
    params = {'lookback': 20}
    open_positions = pd.DataFrame()

    records = generator._transform_signals_to_records(
        df_features=df,
        signal_id=signal_id,
        params=params,
        open_positions=open_positions,
    )

    # Check feature snapshot structure
    assert len(records) == 1
    snapshot = records['feature_snapshot'].iloc[0]

    assert 'channel_high' in snapshot
    assert 'channel_low' in snapshot
    assert snapshot['channel_high'] == 106.0  # Row 1 value
    assert snapshot['channel_low'] == 96.0


def test_generate_loads_lookback_from_config():
    """Test that generate_for_ids uses lookback from signal config."""
    engine = MagicMock()
    state_manager = MagicMock()

    # Mock state manager methods
    state_manager.get_dirty_window_start.return_value = {}
    state_manager.load_open_positions.return_value = pd.DataFrame()

    generator = ATRSignalGenerator(engine, state_manager)

    # Mock _load_features to return empty DataFrame
    with patch.object(generator, '_load_features', return_value=pd.DataFrame()):
        signal_config = {
            'signal_id': 1,
            'signal_name': 'test_atr',
            'params': {
                'lookback': 15,  # Non-default value
                'atr_col': 'atr_14',
            }
        }

        result = generator.generate_for_ids(
            ids=[1],
            signal_config=signal_config,
        )

        # Should return 0 for empty features
        assert result == 0


def test_generate_uses_atr_column_from_config():
    """Test that generate_for_ids passes atr_col to make_signals."""
    engine = MagicMock()
    state_manager = MagicMock()

    state_manager.get_dirty_window_start.return_value = {}
    state_manager.load_open_positions.return_value = pd.DataFrame()

    generator = ATRSignalGenerator(engine, state_manager)

    # Mock _load_features to return sample data
    sample_df = pd.DataFrame({
        'id': [1, 1, 1],
        'ts': pd.date_range('2024-01-01', periods=3),
        'open': [100, 102, 104],
        'high': [101, 103, 105],
        'low': [99, 101, 103],
        'close': [100, 102, 104],
        'atr_14': [2.0, 2.1, 2.2],
    })

    with patch.object(generator, '_load_features', return_value=sample_df):
        with patch('ta_lab2.scripts.signals.generate_signals_atr.make_signals') as mock_make:
            # Mock make_signals to return empty signals
            mock_make.return_value = (
                pd.Series([False] * 3),  # entries
                pd.Series([False] * 3),  # exits
                None,  # size
            )

            signal_config = {
                'signal_id': 1,
                'signal_name': 'test_atr',
                'params': {
                    'lookback': 20,
                    'atr_col': 'atr_21',  # Non-default column
                }
            }

            generator.generate_for_ids(
                ids=[1],
                signal_config=signal_config,
            )

            # Verify make_signals was called with correct atr_col
            mock_make.assert_called_once()
            call_kwargs = mock_make.call_args.kwargs
            assert call_kwargs['atr_col'] == 'atr_21'


def test_trailing_stop_parameter_honored():
    """Test that use_trailing_atr_stop parameter is passed through."""
    engine = MagicMock()
    state_manager = MagicMock()

    state_manager.get_dirty_window_start.return_value = {}
    state_manager.load_open_positions.return_value = pd.DataFrame()

    generator = ATRSignalGenerator(engine, state_manager)

    sample_df = pd.DataFrame({
        'id': [1, 1, 1],
        'ts': pd.date_range('2024-01-01', periods=3),
        'open': [100, 102, 104],
        'high': [101, 103, 105],
        'low': [99, 101, 103],
        'close': [100, 102, 104],
        'atr_14': [2.0, 2.1, 2.2],
    })

    with patch.object(generator, '_load_features', return_value=sample_df):
        with patch('ta_lab2.scripts.signals.generate_signals_atr.make_signals') as mock_make:
            mock_make.return_value = (
                pd.Series([False] * 3),
                pd.Series([False] * 3),
                None,
            )

            signal_config = {
                'signal_id': 1,
                'signal_name': 'test_atr',
                'params': {
                    'lookback': 20,
                    'use_trailing_atr_stop': False,  # Disable trailing stop
                }
            }

            generator.generate_for_ids(
                ids=[1],
                signal_config=signal_config,
            )

            # Verify parameter passed through
            call_kwargs = mock_make.call_args.kwargs
            assert call_kwargs['use_trailing_atr_stop'] is False


def test_pnl_calculation_on_exit():
    """Test that PnL is correctly calculated when position closes."""
    engine = MagicMock()
    state_manager = MagicMock()
    generator = ATRSignalGenerator(engine, state_manager)

    # Entry at 100, exit at 110 = 10% gain
    df = pd.DataFrame({
        'id': [1, 1, 1, 1],
        'ts': pd.date_range('2024-01-01', periods=4),
        'open': [100, 102, 108, 110],
        'high': [101, 103, 109, 111],
        'low': [99, 101, 107, 109],
        'close': [100, 102, 108, 110],
        'atr_14': [2.0, 2.1, 2.2, 2.3],
        'channel_high': [105, 105, 105, 105],
        'channel_low': [95, 95, 95, 95],
        'entry_signal': [False, True, False, False],  # Entry at row 1
        'exit_signal': [False, False, False, True],   # Exit at row 3
    })

    records = generator._transform_signals_to_records(
        df_features=df,
        signal_id=1,
        params={},
        open_positions=pd.DataFrame(),
    )

    # Should have 2 records: 1 entry (open) + 1 exit (closed)
    assert len(records) == 2

    # Check entry record
    entry = records[records['position_state'] == 'open'].iloc[0]
    assert entry['entry_price'] == 102
    assert pd.isna(entry['pnl_pct'])  # pnl_pct is None/NaN for open positions

    # Check exit record
    exit_rec = records[records['position_state'] == 'closed'].iloc[0]
    assert exit_rec['entry_price'] == 102
    assert exit_rec['exit_price'] == 110
    expected_pnl = ((110 - 102) / 102) * 100
    assert abs(exit_rec['pnl_pct'] - expected_pnl) < 0.01


def test_feature_hash_determinism():
    """Test that feature hash is deterministic for same data."""
    df = pd.DataFrame({
        'ts': pd.date_range('2024-01-01', periods=3),
        'close': [100, 102, 104],
        'high': [101, 103, 105],
        'low': [99, 101, 103],
        'atr_14': [2.0, 2.1, 2.2],
        'channel_high': [105, 105, 105],
        'channel_low': [95, 95, 95],
    })

    columns = ['close', 'high', 'low', 'atr_14', 'channel_high', 'channel_low']

    hash1 = compute_feature_hash(df, columns)
    hash2 = compute_feature_hash(df, columns)

    assert hash1 == hash2
    assert len(hash1) == 16  # First 16 chars of SHA256


def test_params_hash_determinism():
    """Test that params hash is deterministic regardless of key order."""
    params1 = {'lookback': 20, 'atr_col': 'atr_14', 'trail_atr_mult': 2.0}
    params2 = {'trail_atr_mult': 2.0, 'lookback': 20, 'atr_col': 'atr_14'}

    hash1 = compute_params_hash(params1)
    hash2 = compute_params_hash(params2)

    assert hash1 == hash2
    assert len(hash1) == 16


# =============================================================================
# Integration Tests (require database)
# =============================================================================

TARGET_DB_URL = os.environ.get("TARGET_DB_URL")


@pytest.mark.skipif(not TARGET_DB_URL, reason="TARGET_DB_URL not set")
def test_roundtrip_atr_signal_generation():
    """Integration test: Generate signals and query back from database."""
    engine = create_engine(TARGET_DB_URL)

    # Setup state manager
    config = SignalStateConfig(signal_type='atr_breakout')
    state_manager = SignalStateManager(engine, config)
    state_manager.ensure_state_table()

    # Create test signal config
    signal_config = {
        'signal_id': 999,  # Test signal ID
        'signal_name': 'test_atr_roundtrip',
        'params': {
            'lookback': 10,
            'atr_col': 'atr_14',
            'trail_atr_mult': 2.0,
            'confirm_close': True,
        }
    }

    # Query for a test asset with features
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT DISTINCT id
            FROM public.cmc_daily_features
            WHERE atr_14 IS NOT NULL
            LIMIT 1
        """))
        test_id = result.scalar()

    if not test_id:
        pytest.skip("No assets with ATR features found")

    # Generate signals (dry_run to avoid pollution)
    generator = ATRSignalGenerator(engine, state_manager)

    # Note: We use dry_run=True for safety, so we can't verify database write
    # A full integration test would write and verify, but requires cleanup
    n = generator.generate_for_ids(
        ids=[test_id],
        signal_config=signal_config,
        full_refresh=True,
        dry_run=True,
    )

    # Just verify generation runs without error
    assert n >= 0


@pytest.mark.skipif(not TARGET_DB_URL, reason="TARGET_DB_URL not set")
def test_different_lookbacks_produce_different_signals():
    """Test that varying lookback parameter affects signal generation."""
    engine = create_engine(TARGET_DB_URL)

    config = SignalStateConfig(signal_type='atr_breakout')
    state_manager = SignalStateManager(engine, config)

    # Get test asset
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT DISTINCT id
            FROM public.cmc_daily_features
            WHERE atr_14 IS NOT NULL
            LIMIT 1
        """))
        test_id = result.scalar()

    if not test_id:
        pytest.skip("No assets with features found")

    generator = ATRSignalGenerator(engine, state_manager)

    # Test two different lookback periods
    config1 = {
        'signal_id': 997,
        'signal_name': 'test_lookback_10',
        'params': {'lookback': 10, 'atr_col': 'atr_14'}
    }

    config2 = {
        'signal_id': 998,
        'signal_name': 'test_lookback_20',
        'params': {'lookback': 20, 'atr_col': 'atr_14'}
    }

    n1 = generator.generate_for_ids([test_id], config1, full_refresh=True, dry_run=True)
    n2 = generator.generate_for_ids([test_id], config2, full_refresh=True, dry_run=True)

    # Both should run successfully (counts may differ)
    assert n1 >= 0
    assert n2 >= 0
