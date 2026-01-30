"""
Tests for EMA signal generation - EMASignalGenerator class.

Tests verify signal generation from cmc_daily_features using ema_trend adapter,
stateful position tracking, and reproducibility through feature hashing.
"""

import os
from unittest import mock
import pandas as pd
import pytest
from sqlalchemy import create_engine

from ta_lab2.scripts.signals import SignalStateManager, SignalStateConfig
from ta_lab2.scripts.signals.generate_signals_ema import EMASignalGenerator


# =============================================================================
# Unit Tests (mocked database)
# =============================================================================

def test_transform_signals_creates_entry_record():
    """Verify transform creates position_state='open' for entry signals."""
    mock_engine = mock.MagicMock()
    mock_state_manager = mock.MagicMock()

    generator = EMASignalGenerator(mock_engine, mock_state_manager)

    # Sample feature data
    df = pd.DataFrame({
        'id': [1, 1, 1],
        'ts': pd.to_datetime(['2024-01-01', '2024-01-02', '2024-01-03']),
        'close': [100.0, 101.0, 102.0],
        'ema_9': [99.0, 100.0, 101.0],
        'ema_21': [98.0, 99.0, 100.0],
        'rsi_14': [45.0, 50.0, 55.0],
        'atr_14': [2.0, 2.1, 2.2],
    })

    entries = pd.Series([True, False, False], index=df.index)
    exits = pd.Series([False, False, False], index=df.index)

    signal_config = {
        'signal_id': 1,
        'params': {'fast_period': 9, 'slow_period': 21, 'direction': 'long'}
    }

    records = generator._transform_signals_to_records(
        df=df,
        entries=entries,
        exits=exits,
        signal_id=1,
        params=signal_config['params'],
        open_positions=pd.DataFrame(),
    )

    assert len(records) == 1
    assert records.iloc[0]['position_state'] == 'open'
    assert records.iloc[0]['entry_price'] == 100.0
    assert records.iloc[0]['entry_ts'] == pd.Timestamp('2024-01-01')
    assert pd.isna(records.iloc[0]['exit_price'])


def test_transform_signals_closes_open_position():
    """Verify exit signal closes matching open position."""
    mock_engine = mock.MagicMock()
    mock_state_manager = mock.MagicMock()

    generator = EMASignalGenerator(mock_engine, mock_state_manager)

    # Sample feature data
    df = pd.DataFrame({
        'id': [1, 1, 1],
        'ts': pd.to_datetime(['2024-01-01', '2024-01-02', '2024-01-03']),
        'close': [100.0, 101.0, 102.0],
        'ema_9': [99.0, 100.0, 101.0],
        'ema_21': [98.0, 99.0, 100.0],
        'rsi_14': [45.0, 50.0, 55.0],
        'atr_14': [2.0, 2.1, 2.2],
    })

    # Entry at idx 0, exit at idx 2
    entries = pd.Series([True, False, False], index=df.index)
    exits = pd.Series([False, False, True], index=df.index)

    signal_config = {
        'signal_id': 1,
        'params': {'fast_period': 9, 'slow_period': 21, 'direction': 'long'}
    }

    records = generator._transform_signals_to_records(
        df=df,
        entries=entries,
        exits=exits,
        signal_id=1,
        params=signal_config['params'],
        open_positions=pd.DataFrame(),
    )

    # Should have 2 records: 1 entry, 1 exit
    assert len(records) == 2
    assert records.iloc[0]['position_state'] == 'open'
    assert records.iloc[1]['position_state'] == 'closed'
    assert records.iloc[1]['exit_price'] == 102.0
    assert not pd.isna(records.iloc[1]['pnl_pct'])


def test_transform_signals_computes_pnl_correctly():
    """Verify PnL calculation: (exit - entry) / entry * 100."""
    mock_engine = mock.MagicMock()
    mock_state_manager = mock.MagicMock()

    generator = EMASignalGenerator(mock_engine, mock_state_manager)

    df = pd.DataFrame({
        'id': [1, 1],
        'ts': pd.to_datetime(['2024-01-01', '2024-01-02']),
        'close': [100.0, 105.0],
        'ema_9': [99.0, 104.0],
        'ema_21': [98.0, 103.0],
        'rsi_14': [45.0, 50.0],
        'atr_14': [2.0, 2.1],
    })

    entries = pd.Series([True, False], index=df.index)
    exits = pd.Series([False, True], index=df.index)

    records = generator._transform_signals_to_records(
        df=df,
        entries=entries,
        exits=exits,
        signal_id=1,
        params={'fast_period': 9, 'slow_period': 21, 'direction': 'long'},
        open_positions=pd.DataFrame(),
    )

    # PnL = (105 - 100) / 100 * 100 = 5.0%
    exit_record = records[records['position_state'] == 'closed'].iloc[0]
    assert exit_record['pnl_pct'] == pytest.approx(5.0)


def test_transform_signals_includes_feature_snapshot():
    """Verify feature_snapshot contains close, fast_ema, slow_ema, rsi, atr."""
    mock_engine = mock.MagicMock()
    mock_state_manager = mock.MagicMock()

    generator = EMASignalGenerator(mock_engine, mock_state_manager)

    df = pd.DataFrame({
        'id': [1],
        'ts': pd.to_datetime(['2024-01-01']),
        'close': [100.0],
        'ema_9': [99.0],
        'ema_21': [98.0],
        'rsi_14': [45.0],
        'atr_14': [2.0],
    })

    entries = pd.Series([True], index=df.index)
    exits = pd.Series([False], index=df.index)

    records = generator._transform_signals_to_records(
        df=df,
        entries=entries,
        exits=exits,
        signal_id=1,
        params={'fast_period': 9, 'slow_period': 21, 'direction': 'long'},
        open_positions=pd.DataFrame(),
    )

    snapshot = records.iloc[0]['feature_snapshot']
    assert isinstance(snapshot, dict)
    assert 'close' in snapshot
    assert 'fast_ema' in snapshot
    assert 'slow_ema' in snapshot
    assert 'rsi_14' in snapshot
    assert 'atr_14' in snapshot
    assert snapshot['close'] == 100.0
    assert snapshot['fast_ema'] == 99.0


def test_transform_signals_includes_version_hashes():
    """Verify records include feature_version_hash and params_hash."""
    mock_engine = mock.MagicMock()
    mock_state_manager = mock.MagicMock()

    generator = EMASignalGenerator(mock_engine, mock_state_manager)

    df = pd.DataFrame({
        'id': [1],
        'ts': pd.to_datetime(['2024-01-01']),
        'close': [100.0],
        'ema_9': [99.0],
        'ema_21': [98.0],
        'rsi_14': [45.0],
        'atr_14': [2.0],
    })

    entries = pd.Series([True], index=df.index)
    exits = pd.Series([False], index=df.index)

    records = generator._transform_signals_to_records(
        df=df,
        entries=entries,
        exits=exits,
        signal_id=1,
        params={'fast_period': 9, 'slow_period': 21, 'direction': 'long'},
        open_positions=pd.DataFrame(),
    )

    assert 'feature_version_hash' in records.columns
    assert 'params_hash' in records.columns
    assert len(records.iloc[0]['feature_version_hash']) == 16
    assert len(records.iloc[0]['params_hash']) == 16


def test_generate_for_ids_loads_features_from_db():
    """Verify generate_for_ids loads features from cmc_daily_features."""
    mock_engine = mock.MagicMock()
    mock_state_manager = mock.MagicMock()

    # Mock load_open_positions
    mock_state_manager.load_open_positions.return_value = pd.DataFrame()
    mock_state_manager.get_dirty_window_start.return_value = {1: None}

    # Mock read_sql to verify query
    with mock.patch('pandas.read_sql') as mock_read_sql:
        mock_read_sql.return_value = pd.DataFrame({
            'id': [1, 1],
            'ts': pd.to_datetime(['2024-01-01', '2024-01-02']),
            'close': [100.0, 101.0],
            'ema_9': [99.0, 100.0],
            'ema_21': [98.0, 99.0],
            'rsi_14': [45.0, 50.0],
            'atr_14': [2.0, 2.1],
        })

        generator = EMASignalGenerator(mock_engine, mock_state_manager)

        # Mock make_signals to return no signals (avoid transform logic)
        with mock.patch('ta_lab2.scripts.signals.generate_signals_ema.make_signals') as mock_make_signals:
            mock_make_signals.return_value = (
                pd.Series([False, False]),
                pd.Series([False, False]),
                None
            )

            signal_config = {
                'signal_id': 1,
                'signal_name': 'ema_9_21_long',
                'params': {'fast_period': 9, 'slow_period': 21, 'direction': 'long'}
            }

            generator.generate_for_ids(
                ids=[1],
                signal_config=signal_config,
                full_refresh=True,
                dry_run=True,
            )

            # Verify read_sql was called
            assert mock_read_sql.called
            # Verify SQL contains expected columns
            call_args = mock_read_sql.call_args
            sql = str(call_args[0][0])
            assert 'cmc_daily_features' in sql
            assert 'ema_9' in sql
            assert 'ema_21' in sql


def test_generate_for_ids_calls_ema_trend_make_signals():
    """Verify generate_for_ids calls ema_trend.make_signals with correct params."""
    mock_engine = mock.MagicMock()
    mock_state_manager = mock.MagicMock()

    mock_state_manager.load_open_positions.return_value = pd.DataFrame()
    mock_state_manager.get_dirty_window_start.return_value = {1: None}

    with mock.patch('pandas.read_sql') as mock_read_sql:
        mock_read_sql.return_value = pd.DataFrame({
            'id': [1],
            'ts': pd.to_datetime(['2024-01-01']),
            'close': [100.0],
            'ema_9': [99.0],
            'ema_21': [98.0],
            'rsi_14': [45.0],
            'atr_14': [2.0],
            'ema_10': [99.5],
            'ema_50': [97.0],
            'ema_200': [95.0],
        })

        generator = EMASignalGenerator(mock_engine, mock_state_manager)

        with mock.patch('ta_lab2.scripts.signals.generate_signals_ema.make_signals') as mock_make_signals:
            mock_make_signals.return_value = (
                pd.Series([False]),
                pd.Series([False]),
                None
            )

            signal_config = {
                'signal_id': 1,
                'signal_name': 'ema_9_21_long',
                'params': {
                    'fast_period': 9,
                    'slow_period': 21,
                    'direction': 'long',
                    'use_rsi_filter': True,
                }
            }

            generator.generate_for_ids(
                ids=[1],
                signal_config=signal_config,
                dry_run=True,
            )

            # Verify make_signals was called with correct params
            assert mock_make_signals.called
            call_kwargs = mock_make_signals.call_args[1]
            assert call_kwargs['fast_ema'] == 'ema_9'
            assert call_kwargs['slow_ema'] == 'ema_21'
            assert call_kwargs['use_rsi_filter'] is True
            assert call_kwargs['allow_shorts'] is False


def test_generate_for_ids_respects_full_refresh_flag():
    """Verify full_refresh=True ignores state and loads all history."""
    mock_engine = mock.MagicMock()
    mock_state_manager = mock.MagicMock()

    mock_state_manager.load_open_positions.return_value = pd.DataFrame()
    mock_state_manager.get_dirty_window_start.return_value = {1: pd.Timestamp('2024-01-15')}

    with mock.patch('pandas.read_sql') as mock_read_sql:
        mock_read_sql.return_value = pd.DataFrame()  # Empty result

        generator = EMASignalGenerator(mock_engine, mock_state_manager)

        signal_config = {
            'signal_id': 1,
            'signal_name': 'test',
            'params': {'fast_period': 9, 'slow_period': 21}
        }

        generator.generate_for_ids(
            ids=[1],
            signal_config=signal_config,
            full_refresh=True,
            dry_run=True,
        )

        # When full_refresh=True, should NOT call get_dirty_window_start
        assert not mock_state_manager.get_dirty_window_start.called


def test_generate_for_ids_incremental_uses_dirty_window():
    """Verify full_refresh=False uses dirty window from state."""
    mock_engine = mock.MagicMock()
    mock_state_manager = mock.MagicMock()

    mock_state_manager.load_open_positions.return_value = pd.DataFrame()
    mock_state_manager.get_dirty_window_start.return_value = {1: pd.Timestamp('2024-01-15')}

    with mock.patch('pandas.read_sql') as mock_read_sql:
        mock_read_sql.return_value = pd.DataFrame()

        generator = EMASignalGenerator(mock_engine, mock_state_manager)

        signal_config = {
            'signal_id': 1,
            'signal_name': 'test',
            'params': {'fast_period': 9, 'slow_period': 21}
        }

        generator.generate_for_ids(
            ids=[1],
            signal_config=signal_config,
            full_refresh=False,
            dry_run=True,
        )

        # Should call get_dirty_window_start when incremental
        assert mock_state_manager.get_dirty_window_start.called


def test_dry_run_does_not_write():
    """Verify dry_run=True skips database write."""
    mock_engine = mock.MagicMock()
    mock_state_manager = mock.MagicMock()

    mock_state_manager.load_open_positions.return_value = pd.DataFrame()
    mock_state_manager.get_dirty_window_start.return_value = {1: None}

    with mock.patch('pandas.read_sql') as mock_read_sql:
        mock_read_sql.return_value = pd.DataFrame({
            'id': [1],
            'ts': pd.to_datetime(['2024-01-01']),
            'close': [100.0],
            'ema_9': [99.0],
            'ema_21': [98.0],
            'rsi_14': [45.0],
            'atr_14': [2.0],
            'ema_10': [99.5],
            'ema_50': [97.0],
            'ema_200': [95.0],
        })

        generator = EMASignalGenerator(mock_engine, mock_state_manager)

        with mock.patch('ta_lab2.scripts.signals.generate_signals_ema.make_signals') as mock_make_signals:
            # Return one entry signal to create a record
            mock_make_signals.return_value = (
                pd.Series([True]),
                pd.Series([False]),
                None
            )

            signal_config = {
                'signal_id': 1,
                'signal_name': 'test',
                'params': {'fast_period': 9, 'slow_period': 21, 'direction': 'long'}
            }

            # Mock _write_signals to verify it's NOT called
            with mock.patch.object(generator, '_write_signals') as mock_write:
                n = generator.generate_for_ids(
                    ids=[1],
                    signal_config=signal_config,
                    dry_run=True,
                )

                # Should return count of records
                assert n == 1
                # But should NOT write to database
                assert not mock_write.called


# =============================================================================
# Integration Tests (require database)
# =============================================================================

@pytest.mark.skipif(
    not os.environ.get("TARGET_DB_URL"),
    reason="No TARGET_DB_URL - skip integration test"
)
def test_roundtrip_signal_generation():
    """Integration test: Generate signals and query back."""
    pytest.skip("Integration test requires test data setup - implement when needed")


@pytest.mark.skipif(
    not os.environ.get("TARGET_DB_URL"),
    reason="No TARGET_DB_URL - skip integration test"
)
def test_incremental_refresh_carries_open_positions():
    """Integration test: Verify open positions carried forward in incremental refresh."""
    pytest.skip("Integration test requires test data setup - implement when needed")
