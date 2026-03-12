"""
Unit tests for SignalReader and StaleSignalError.

All tests use unittest.mock — no live database required.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from ta_lab2.executor.signal_reader import (
    SignalReader,
    StaleSignalError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_reader():
    """Create a SignalReader with a mock engine."""
    engine = MagicMock()
    return SignalReader(engine)


def _make_conn():
    """Create a mock SQLAlchemy connection."""
    return MagicMock()


def _utc_now():
    return datetime.now(timezone.utc)


def _make_signal(
    asset_id: int, ts: datetime, direction: str = "long", position_state: str = "open"
) -> dict:
    return {
        "id": asset_id,
        "ts": ts,
        "signal_id": 1,
        "direction": direction,
        "position_state": position_state,
        "entry_price": None,
        "entry_ts": None,
        "exit_price": None,
        "exit_ts": None,
        "feature_snapshot": None,
        "params_hash": "abc",
    }


# ---------------------------------------------------------------------------
# Test 1: stale check skipped on first run (watermark is None)
# ---------------------------------------------------------------------------


def test_stale_check_skipped_on_first_run():
    """When last_watermark_ts is None, no DB query is executed and no exception raised."""
    reader = _make_reader()
    conn = _make_conn()

    # Should not raise and should not call conn.execute
    reader.check_signal_freshness(
        conn=conn,
        signal_table="signals_ema_crossover",
        signal_id=1,
        cadence_hours=26.0,
        last_watermark_ts=None,
    )

    conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: stale check raises when signal is old
# ---------------------------------------------------------------------------


def test_stale_check_raises_on_old_signal():
    """StaleSignalError raised when latest signal is older than cadence_hours."""
    reader = _make_reader()
    conn = _make_conn()

    # Latest signal 30 hours ago, cadence 26h -> stale
    latest_ts = _utc_now() - timedelta(hours=30)
    mock_row = MagicMock()
    mock_row.latest_ts = latest_ts
    conn.execute.return_value.fetchone.return_value = mock_row

    with pytest.raises(StaleSignalError, match="exceeds cadence limit"):
        reader.check_signal_freshness(
            conn=conn,
            signal_table="signals_ema_crossover",
            signal_id=1,
            cadence_hours=26.0,
            last_watermark_ts=_utc_now() - timedelta(hours=25),
        )


# ---------------------------------------------------------------------------
# Test 3: stale check passes on fresh signal
# ---------------------------------------------------------------------------


def test_stale_check_passes_on_fresh_signal():
    """No exception when latest signal is within cadence window."""
    reader = _make_reader()
    conn = _make_conn()

    # Latest signal 20 hours ago, cadence 26h -> fresh
    latest_ts = _utc_now() - timedelta(hours=20)
    mock_row = MagicMock()
    mock_row.latest_ts = latest_ts
    conn.execute.return_value.fetchone.return_value = mock_row

    # Should not raise
    reader.check_signal_freshness(
        conn=conn,
        signal_table="signals_ema_crossover",
        signal_id=1,
        cadence_hours=26.0,
        last_watermark_ts=_utc_now() - timedelta(hours=25),
    )


# ---------------------------------------------------------------------------
# Test 4: stale check raises when no signals found (MAX returns None)
# ---------------------------------------------------------------------------


def test_stale_check_raises_on_no_signals():
    """StaleSignalError raised when MAX(ts) returns None (empty table for signal_id)."""
    reader = _make_reader()
    conn = _make_conn()

    mock_row = MagicMock()
    mock_row.latest_ts = None
    conn.execute.return_value.fetchone.return_value = mock_row

    with pytest.raises(StaleSignalError, match="No signals found"):
        reader.check_signal_freshness(
            conn=conn,
            signal_table="signals_rsi_mean_revert",
            signal_id=2,
            cadence_hours=26.0,
            last_watermark_ts=_utc_now() - timedelta(hours=1),
        )


# ---------------------------------------------------------------------------
# Test 5: read_unprocessed with watermark applies ts > :watermark_ts filter
# ---------------------------------------------------------------------------


def test_read_unprocessed_with_watermark():
    """Query includes watermark clause when last_watermark_ts is provided."""
    reader = _make_reader()
    conn = _make_conn()

    # Return empty list
    conn.execute.return_value.fetchall.return_value = []

    watermark = _utc_now() - timedelta(hours=2)
    reader.read_unprocessed_signals(
        conn=conn,
        signal_table="signals_ema_crossover",
        signal_id=1,
        last_watermark_ts=watermark,
    )

    # Inspect the SQL text passed to conn.execute
    call_args = conn.execute.call_args
    sql_obj = call_args[0][0]  # first positional arg (TextClause)
    params = call_args[0][1]  # second positional arg (dict)

    assert "ts > :watermark_ts" in str(sql_obj), "Expected watermark clause in SQL"
    assert "watermark_ts" in params


# ---------------------------------------------------------------------------
# Test 6: read_unprocessed without watermark omits ts filter
# ---------------------------------------------------------------------------


def test_read_unprocessed_without_watermark():
    """Query does NOT include watermark clause when last_watermark_ts is None."""
    reader = _make_reader()
    conn = _make_conn()

    conn.execute.return_value.fetchall.return_value = []

    reader.read_unprocessed_signals(
        conn=conn,
        signal_table="signals_atr_breakout",
        signal_id=3,
        last_watermark_ts=None,
    )

    call_args = conn.execute.call_args
    sql_obj = call_args[0][0]
    params = call_args[0][1]

    assert "watermark_ts" not in str(sql_obj), "Watermark clause should be absent"
    assert "watermark_ts" not in params


# ---------------------------------------------------------------------------
# Test 7: get_latest_signal_per_asset returns latest for single asset
# ---------------------------------------------------------------------------


def test_get_latest_signal_per_asset_single_asset():
    """Returns the signal with the latest ts for a single asset."""
    ts_old = datetime(2026, 2, 20, tzinfo=timezone.utc)
    ts_mid = datetime(2026, 2, 22, tzinfo=timezone.utc)
    ts_new = datetime(2026, 2, 24, tzinfo=timezone.utc)

    signals = [
        _make_signal(asset_id=1, ts=ts_old),
        _make_signal(asset_id=1, ts=ts_new),
        _make_signal(asset_id=1, ts=ts_mid),
    ]

    result = SignalReader.get_latest_signal_per_asset(signals)

    assert len(result) == 1
    assert result[1]["ts"] == ts_new


# ---------------------------------------------------------------------------
# Test 8: get_latest_signal_per_asset handles multiple assets
# ---------------------------------------------------------------------------


def test_get_latest_signal_per_asset_multiple_assets():
    """Returns one signal per asset, each with the latest ts."""
    ts1a = datetime(2026, 2, 20, tzinfo=timezone.utc)
    ts1b = datetime(2026, 2, 24, tzinfo=timezone.utc)
    ts2a = datetime(2026, 2, 23, tzinfo=timezone.utc)

    signals = [
        _make_signal(asset_id=1, ts=ts1a),
        _make_signal(asset_id=1, ts=ts1b),
        _make_signal(asset_id=2, ts=ts2a),
    ]

    result = SignalReader.get_latest_signal_per_asset(signals)

    assert set(result.keys()) == {1, 2}
    assert result[1]["ts"] == ts1b
    assert result[2]["ts"] == ts2a


# ---------------------------------------------------------------------------
# Test 9: table validation rejects unknown table name
# ---------------------------------------------------------------------------


def test_signal_table_validation_rejects_bad_table():
    """ValueError raised when signal_table is not in the known set."""
    reader = _make_reader()
    conn = _make_conn()

    with pytest.raises(ValueError, match="Unknown signal table"):
        reader.read_unprocessed_signals(
            conn=conn,
            signal_table="cmc_signals_malicious_injection; DROP TABLE users; --",
            signal_id=1,
            last_watermark_ts=None,
        )

    with pytest.raises(ValueError, match="Unknown signal table"):
        reader.check_signal_freshness(
            conn=conn,
            signal_table="bad_table",
            signal_id=1,
            cadence_hours=26.0,
            last_watermark_ts=_utc_now(),  # non-None so we reach validation
        )
