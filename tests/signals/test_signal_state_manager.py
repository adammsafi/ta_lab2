"""
Tests for SignalStateManager - State management for signal positions.

Uses unittest.mock for database-free unit tests following Phase 7 pattern.
Integration tests skip gracefully without database (pytest.mark.skipif).
"""

import os
from unittest import mock
from unittest.mock import MagicMock
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from ta_lab2.scripts.signals import SignalStateManager, SignalStateConfig


# =============================================================================
# Unit Tests (database-free with mocks)
# =============================================================================


def test_config_immutable():
    """Verify SignalStateConfig is frozen (immutable)."""
    config = SignalStateConfig(signal_type="ema_crossover")

    with pytest.raises(Exception):  # FrozenInstanceError
        config.state_schema = "other"


def test_ensure_state_table_executes_create():
    """Verify ensure_state_table executes CREATE TABLE SQL."""
    mock_engine = MagicMock()
    config = SignalStateConfig(signal_type="ema_crossover")

    manager = SignalStateManager(mock_engine, config)
    manager.ensure_state_table()

    # Verify SQL was executed via begin context manager
    mock_engine.begin.assert_called_once()
    conn = mock_engine.begin().__enter__()
    conn.execute.assert_called_once()

    # Verify SQL contains CREATE TABLE
    executed_sql = str(conn.execute.call_args[0][0])
    assert "CREATE TABLE" in executed_sql
    assert "cmc_signal_state" in executed_sql


def test_load_open_positions_returns_dataframe():
    """Verify load_open_positions returns DataFrame with expected columns."""
    mock_engine = MagicMock()
    config = SignalStateConfig(signal_type="ema_crossover")

    # Mock pd.read_sql to return test data
    test_df = pd.DataFrame(
        {
            "id": [1, 1],
            "signal_id": [1, 1],
            "ts": ["2024-01-01", "2024-01-02"],
            "direction": ["long", "long"],
            "position_state": ["open", "open"],
            "entry_ts": ["2024-01-01", "2024-01-02"],
            "entry_price": [100.0, 101.0],
            "feature_snapshot": [{"close": 100.0}, {"close": 101.0}],
            "signal_version": ["v1", "v1"],
            "feature_version_hash": ["abc123", "abc123"],
            "params_hash": ["def456", "def456"],
        }
    )

    with mock.patch("pandas.read_sql", return_value=test_df):
        manager = SignalStateManager(mock_engine, config)
        result = manager.load_open_positions(ids=[1], signal_id=1)

    assert isinstance(result, pd.DataFrame)
    assert len(result) == 2
    assert "id" in result.columns
    assert "position_state" in result.columns


def test_load_open_positions_empty_returns_empty_df():
    """Verify load_open_positions returns empty DataFrame when no open positions."""
    mock_engine = MagicMock()
    config = SignalStateConfig(signal_type="ema_crossover")

    # Mock pd.read_sql to raise exception (table doesn't exist)
    with mock.patch("pandas.read_sql", side_effect=Exception("table not found")):
        manager = SignalStateManager(mock_engine, config)
        result = manager.load_open_positions(ids=[1], signal_id=1)

    assert isinstance(result, pd.DataFrame)
    assert len(result) == 0
    assert "id" in result.columns
    assert "position_state" in result.columns


def test_update_state_after_generation_upserts():
    """Verify update_state_after_generation executes UPSERT SQL."""
    mock_engine = MagicMock()
    config = SignalStateConfig(signal_type="ema_crossover")

    # Mock rowcount
    mock_result = MagicMock()
    mock_result.rowcount = 5
    mock_engine.begin().__enter__().execute.return_value = mock_result

    manager = SignalStateManager(mock_engine, config)
    row_count = manager.update_state_after_generation(
        signal_table="cmc_signals_ema_crossover", signal_id=1
    )

    assert row_count == 5

    # Verify SQL was executed
    conn = mock_engine.begin().__enter__()
    conn.execute.assert_called_once()

    # Verify SQL contains UPSERT keywords
    executed_call = conn.execute.call_args
    executed_sql = str(executed_call[0][0])
    assert "INSERT INTO" in executed_sql
    assert "ON CONFLICT" in executed_sql
    assert "cmc_signal_state" in executed_sql


def test_get_dirty_window_start_returns_dict():
    """Verify get_dirty_window_start returns timestamp dict."""
    mock_engine = MagicMock()
    config = SignalStateConfig(signal_type="ema_crossover")

    # Mock pd.read_sql to return state data
    test_df = pd.DataFrame(
        {
            "id": [1, 52],
            "last_entry_ts": ["2024-01-01", "2024-01-05"],
        }
    )

    with mock.patch("pandas.read_sql", return_value=test_df):
        manager = SignalStateManager(mock_engine, config)
        result = manager.get_dirty_window_start(ids=[1, 52], signal_id=1)

    assert isinstance(result, dict)
    assert 1 in result
    assert 52 in result
    assert isinstance(result[1], pd.Timestamp)


def test_get_dirty_window_start_no_state_returns_none():
    """Verify get_dirty_window_start returns None for IDs without state."""
    mock_engine = MagicMock()
    config = SignalStateConfig(signal_type="ema_crossover")

    # Mock pd.read_sql to return empty DataFrame
    with mock.patch("pandas.read_sql", return_value=pd.DataFrame()):
        manager = SignalStateManager(mock_engine, config)
        result = manager.get_dirty_window_start(ids=[999], signal_id=1)

    assert result[999] is None


# =============================================================================
# Integration Tests (require database)
# =============================================================================


@pytest.mark.skipif(
    not os.environ.get("TARGET_DB_URL"),
    reason="No TARGET_DB_URL - skip integration test",
)
def test_roundtrip_open_positions():
    """Integration test: Insert signal, load open positions, verify match."""
    db_url = os.environ.get("TARGET_DB_URL")
    engine = create_engine(db_url)
    config = SignalStateConfig(signal_type="ema_crossover")

    manager = SignalStateManager(engine, config)

    # Ensure tables exist
    manager.ensure_state_table()

    # Insert test signal (open position)
    with engine.begin() as conn:
        # Clean up any existing test data
        conn.execute(
            text(
                """
            DELETE FROM public.cmc_signals_ema_crossover
            WHERE id = 999999 AND signal_id = 1
        """
            )
        )

        # Insert test signal
        conn.execute(
            text(
                """
            INSERT INTO public.cmc_signals_ema_crossover
            (id, ts, signal_id, direction, position_state, entry_ts, entry_price, feature_snapshot)
            VALUES
            (999999, '2024-01-01', 1, 'long', 'open', '2024-01-01', 100.0, '{"close": 100.0}'::jsonb)
        """
            )
        )

    # Load open positions
    open_positions = manager.load_open_positions(ids=[999999], signal_id=1)

    # Verify
    assert len(open_positions) == 1
    assert open_positions.iloc[0]["id"] == 999999
    assert open_positions.iloc[0]["position_state"] == "open"
    assert open_positions.iloc[0]["entry_price"] == 100.0

    # Clean up
    with engine.begin() as conn:
        conn.execute(
            text(
                """
            DELETE FROM public.cmc_signals_ema_crossover
            WHERE id = 999999 AND signal_id = 1
        """
            )
        )
