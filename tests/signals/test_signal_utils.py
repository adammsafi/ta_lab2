"""
Tests for signal_utils - Feature hashing and signal configuration loading.

Tests verify reproducibility utilities produce deterministic results and
signal configuration is correctly loaded from dim_signals.
"""

import os
from unittest import mock
import pandas as pd
import pytest
from sqlalchemy import create_engine

from ta_lab2.scripts.signals.signal_utils import (
    compute_feature_hash,
    compute_params_hash,
    load_active_signals,
)


# =============================================================================
# Feature Hash Tests
# =============================================================================


def test_compute_feature_hash_deterministic():
    """Verify compute_feature_hash produces same hash for same data."""
    df = pd.DataFrame(
        {
            "ts": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "close": [100.0, 101.0, 102.0],
            "ema_21": [99.5, 100.5, 101.5],
        }
    )

    hash1 = compute_feature_hash(df, ["close", "ema_21"])
    hash2 = compute_feature_hash(df, ["close", "ema_21"])

    assert hash1 == hash2
    assert len(hash1) == 16  # First 16 chars of SHA256


def test_compute_feature_hash_changes_on_data_change():
    """Verify hash changes when data changes."""
    df1 = pd.DataFrame(
        {
            "ts": ["2024-01-01", "2024-01-02"],
            "close": [100.0, 101.0],
        }
    )

    df2 = pd.DataFrame(
        {
            "ts": ["2024-01-01", "2024-01-02"],
            "close": [100.0, 102.0],  # Different value
        }
    )

    hash1 = compute_feature_hash(df1, ["close"])
    hash2 = compute_feature_hash(df2, ["close"])

    assert hash1 != hash2


def test_compute_feature_hash_order_independent():
    """Verify hash is same regardless of row order (internally sorted by ts)."""
    df1 = pd.DataFrame(
        {
            "ts": ["2024-01-01", "2024-01-02", "2024-01-03"],
            "close": [100.0, 101.0, 102.0],
        }
    )

    df2 = pd.DataFrame(
        {
            "ts": ["2024-01-03", "2024-01-01", "2024-01-02"],  # Different order
            "close": [102.0, 100.0, 101.0],
        }
    )

    hash1 = compute_feature_hash(df1, ["close"])
    hash2 = compute_feature_hash(df2, ["close"])

    assert hash1 == hash2  # Same hash despite different input order


def test_compute_feature_hash_raises_on_empty_df():
    """Verify compute_feature_hash raises ValueError on empty DataFrame."""
    df = pd.DataFrame()

    with pytest.raises(ValueError, match="empty DataFrame"):
        compute_feature_hash(df, ["close"])


def test_compute_feature_hash_raises_on_missing_column():
    """Verify compute_feature_hash raises KeyError if column missing."""
    df = pd.DataFrame(
        {
            "ts": ["2024-01-01"],
            "close": [100.0],
        }
    )

    with pytest.raises(KeyError):
        compute_feature_hash(df, ["ema_21"])  # Column doesn't exist


# =============================================================================
# Params Hash Tests
# =============================================================================


def test_compute_params_hash_sorted_keys():
    """Verify params hash is same regardless of key insertion order."""
    params1 = {"fast_period": 9, "slow_period": 21}
    params2 = {"slow_period": 21, "fast_period": 9}

    hash1 = compute_params_hash(params1)
    hash2 = compute_params_hash(params2)

    assert hash1 == hash2
    assert len(hash1) == 16


def test_compute_params_hash_changes_on_value_change():
    """Verify hash changes when parameter values change."""
    params1 = {"fast_period": 9, "slow_period": 21}
    params2 = {"fast_period": 9, "slow_period": 50}

    hash1 = compute_params_hash(params1)
    hash2 = compute_params_hash(params2)

    assert hash1 != hash2


# =============================================================================
# load_active_signals Tests (with mocks)
# =============================================================================


def test_load_active_signals_filters_inactive():
    """Verify load_active_signals filters by is_active=TRUE."""
    mock_engine = mock.MagicMock()

    # Mock database result
    mock_result = mock.MagicMock()
    mock_result.fetchall.return_value = [
        (1, "ema_9_21_long", {"fast_period": 9, "slow_period": 21}),
    ]

    mock_conn = mock.MagicMock()
    mock_conn.execute.return_value = mock_result
    mock_engine.connect().__enter__.return_value = mock_conn

    signals = load_active_signals(mock_engine, "ema_crossover")

    # Verify SQL filters by is_active
    executed_sql = str(mock_conn.execute.call_args[0][0])
    assert "is_active = TRUE" in executed_sql
    assert "signal_type = :signal_type" in executed_sql


def test_load_active_signals_returns_list_of_dicts():
    """Verify load_active_signals returns list of dicts with expected structure."""
    mock_engine = mock.MagicMock()

    # Mock database result
    mock_result = mock.MagicMock()
    mock_result.fetchall.return_value = [
        (1, "ema_9_21_long", {"fast_period": 9, "slow_period": 21}),
        (2, "ema_21_50_long", {"fast_period": 21, "slow_period": 50}),
    ]

    mock_conn = mock.MagicMock()
    mock_conn.execute.return_value = mock_result
    mock_engine.connect().__enter__.return_value = mock_conn

    signals = load_active_signals(mock_engine, "ema_crossover")

    assert isinstance(signals, list)
    assert len(signals) == 2
    assert signals[0]["signal_id"] == 1
    assert signals[0]["signal_name"] == "ema_9_21_long"
    assert signals[0]["params"]["fast_period"] == 9


def test_load_active_signals_filters_by_signal_id():
    """Verify load_active_signals can filter by specific signal_id."""
    mock_engine = mock.MagicMock()

    # Mock database result
    mock_result = mock.MagicMock()
    mock_result.fetchall.return_value = [
        (2, "ema_21_50_long", {"fast_period": 21, "slow_period": 50}),
    ]

    mock_conn = mock.MagicMock()
    mock_conn.execute.return_value = mock_result
    mock_engine.connect().__enter__.return_value = mock_conn

    signals = load_active_signals(mock_engine, "ema_crossover", signal_id=2)

    # Verify SQL includes signal_id filter
    executed_sql = str(mock_conn.execute.call_args[0][0])
    assert "signal_id = :signal_id" in executed_sql

    assert len(signals) == 1
    assert signals[0]["signal_id"] == 2


# =============================================================================
# Integration Tests (require database)
# =============================================================================


@pytest.mark.skipif(
    not os.environ.get("TARGET_DB_URL"),
    reason="No TARGET_DB_URL - skip integration test",
)
def test_load_active_signals_integration():
    """Integration test: Load active signals from real database."""
    db_url = os.environ.get("TARGET_DB_URL")
    engine = create_engine(db_url)

    signals = load_active_signals(engine, "ema_crossover")

    # Should have at least the seed data (3 EMA crossover signals)
    assert len(signals) >= 3
    assert all("signal_id" in s for s in signals)
    assert all("signal_name" in s for s in signals)
    assert all("params" in s for s in signals)

    # Verify params are parsed dicts
    assert isinstance(signals[0]["params"], dict)
