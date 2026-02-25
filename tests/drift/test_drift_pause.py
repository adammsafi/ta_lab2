"""Unit tests for drift pause operations -- use unittest.mock, no live DB."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from ta_lab2.drift.drift_metrics import DriftMetrics
from ta_lab2.drift.drift_pause import (
    activate_drift_pause,
    check_drift_escalation,
    check_drift_threshold,
    disable_drift_pause,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_metrics(
    tracking_error_5d=None,
    config_id=1,
    asset_id=100,
) -> DriftMetrics:
    from datetime import date

    return DriftMetrics(
        metric_date=date(2026, 2, 25),
        config_id=config_id,
        asset_id=asset_id,
        signal_type="ema_crossover",
        pit_replay_run_id=None,
        cur_replay_run_id=None,
        paper_trade_count=5,
        replay_trade_count=5,
        unmatched_paper=0,
        unmatched_replay=0,
        paper_cumulative_pnl=100.0,
        replay_pit_cumulative_pnl=95.0,
        replay_cur_cumulative_pnl=95.0,
        absolute_pnl_diff=5.0,
        data_revision_pnl_diff=0.0,
        tracking_error_5d=tracking_error_5d,
        tracking_error_30d=None,
        paper_sharpe=1.0,
        replay_sharpe=0.9,
        sharpe_divergence=0.1,
        threshold_breach=False,
        drift_pct_of_threshold=None,
    )


def _make_mock_engine():
    """Create a mock SQLAlchemy engine with context manager support."""
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


# ---------------------------------------------------------------------------
# activate_drift_pause
# ---------------------------------------------------------------------------


def test_activate_drift_pause_executes_sql():
    """activate_drift_pause() should UPDATE dim_risk_state and INSERT cmc_risk_events."""
    engine, conn = _make_mock_engine()

    activate_drift_pause(engine, reason="TE breach", tracking_error=0.02, config_id=1)

    # Verify two SQL calls were made (UPDATE + INSERT)
    assert conn.execute.call_count == 2

    first_call_sql = str(conn.execute.call_args_list[0][0][0])
    second_call_sql = str(conn.execute.call_args_list[1][0][0])

    assert "UPDATE dim_risk_state" in first_call_sql
    assert "drift_paused" in first_call_sql
    assert "INSERT INTO cmc_risk_events" in second_call_sql
    assert "drift_pause_activated" in second_call_sql


# ---------------------------------------------------------------------------
# disable_drift_pause
# ---------------------------------------------------------------------------


def test_disable_drift_pause_validates_inputs():
    """disable_drift_pause() should raise ValueError on empty reason or operator."""
    engine, _ = _make_mock_engine()

    with pytest.raises(ValueError, match="reason"):
        disable_drift_pause(engine, reason="", operator="trader_1")

    with pytest.raises(ValueError, match="reason"):
        disable_drift_pause(engine, reason="  ", operator="trader_1")

    with pytest.raises(ValueError, match="operator"):
        disable_drift_pause(engine, reason="manual disable", operator="")

    with pytest.raises(ValueError, match="operator"):
        disable_drift_pause(engine, reason="manual disable", operator="  ")


def test_disable_drift_pause_executes_sql():
    """disable_drift_pause() should UPDATE dim_risk_state and INSERT cmc_risk_events."""
    engine, conn = _make_mock_engine()

    disable_drift_pause(engine, reason="Manually resolved", operator="trader_1")

    assert conn.execute.call_count == 2

    first_call_sql = str(conn.execute.call_args_list[0][0][0])
    second_call_sql = str(conn.execute.call_args_list[1][0][0])

    assert "UPDATE dim_risk_state" in first_call_sql
    assert "drift_paused" in first_call_sql
    assert "FALSE" in first_call_sql
    assert "INSERT INTO cmc_risk_events" in second_call_sql
    assert "drift_pause_disabled" in second_call_sql


# ---------------------------------------------------------------------------
# check_drift_threshold
# ---------------------------------------------------------------------------


def test_check_drift_threshold_none_tracking_error():
    """DriftMetrics with tracking_error_5d=None -> returns False, no pause activated."""
    engine, conn = _make_mock_engine()
    metrics = _make_metrics(tracking_error_5d=None)

    result = check_drift_threshold(engine, metrics)

    assert result is False
    engine.connect.assert_not_called()


def test_check_drift_threshold_below_warning():
    """tracking_error < 75% of threshold -> returns False, no Telegram, no pause."""
    engine, conn = _make_mock_engine()

    threshold_row = MagicMock()
    threshold_row.__getitem__ = MagicMock(side_effect=lambda i: [0.015, 0.005, 5][i])
    conn.execute.return_value.fetchone.return_value = threshold_row

    metrics = _make_metrics(tracking_error_5d=0.005)

    with patch("ta_lab2.drift.drift_pause._TELEGRAM_AVAILABLE", False):
        with patch("ta_lab2.drift.drift_pause.activate_drift_pause") as mock_pause:
            result = check_drift_threshold(engine, metrics)

    assert result is False
    mock_pause.assert_not_called()


def test_check_drift_threshold_warning_zone():
    """tracking_error between 75% and 100% of threshold -> False, send_alert called with severity=warning."""
    engine, conn = _make_mock_engine()

    threshold_row = MagicMock()
    threshold_row.__getitem__ = MagicMock(side_effect=lambda i: [0.015, 0.005, 5][i])
    conn.execute.return_value.fetchone.return_value = threshold_row

    metrics = _make_metrics(tracking_error_5d=0.013)

    with patch("ta_lab2.drift.drift_pause._TELEGRAM_AVAILABLE", True):
        with patch("ta_lab2.drift.drift_pause._send_alert") as mock_alert:
            with patch("ta_lab2.drift.drift_pause.activate_drift_pause") as mock_pause:
                result = check_drift_threshold(engine, metrics)

    assert result is False
    mock_pause.assert_not_called()
    mock_alert.assert_called_once()
    call_kwargs = mock_alert.call_args
    # Verify severity="warning" was passed (keyword or positional)
    severity_passed = call_kwargs[1].get("severity") if call_kwargs[1] else None
    if severity_passed is None and len(call_kwargs[0]) >= 3:
        severity_passed = call_kwargs[0][2]
    assert severity_passed == "warning"


def test_check_drift_threshold_breach():
    """tracking_error > threshold -> returns True, activate_drift_pause called."""
    engine, conn = _make_mock_engine()

    threshold_row = MagicMock()
    threshold_row.__getitem__ = MagicMock(side_effect=lambda i: [0.015, 0.005, 5][i])
    conn.execute.return_value.fetchone.return_value = threshold_row

    metrics = _make_metrics(tracking_error_5d=0.020, config_id=3)

    with patch("ta_lab2.drift.drift_pause.activate_drift_pause") as mock_pause:
        result = check_drift_threshold(engine, metrics)

    assert result is True
    mock_pause.assert_called_once()
    call_args = mock_pause.call_args
    # Verify tracking_error and config_id passed
    kwargs = call_args[1]
    positional = call_args[0]
    tracking_error_val = (
        kwargs.get("tracking_error")
        if kwargs
        else (positional[2] if len(positional) > 2 else None)
    )
    config_id_val = (
        kwargs.get("config_id")
        if kwargs
        else (positional[3] if len(positional) > 3 else None)
    )
    assert tracking_error_val == 0.020
    assert config_id_val == 3


# ---------------------------------------------------------------------------
# check_drift_escalation
# ---------------------------------------------------------------------------


def test_check_drift_escalation_not_paused():
    """drift_paused=False -> returns False immediately."""
    engine, conn = _make_mock_engine()

    state_row = MagicMock()
    state_row.__getitem__ = MagicMock(side_effect=lambda i: [False, None, 3][i])
    conn.execute.return_value.fetchone.return_value = state_row

    result = check_drift_escalation(engine)

    assert result is False


def test_check_drift_escalation_within_window():
    """drift_paused=True but paused only 1 day ago with 3-day escalation -> returns False."""
    engine, conn = _make_mock_engine()

    now = datetime.now(timezone.utc)
    paused_at = now - timedelta(days=1)  # Only 1 day ago

    state_row = MagicMock()
    state_row.__getitem__ = MagicMock(side_effect=lambda i: [True, paused_at, 3][i])
    conn.execute.return_value.fetchone.return_value = state_row

    # Patch at the module where activate_kill_switch is imported
    with patch("ta_lab2.drift.drift_pause.activate_kill_switch") as mock_ks:
        result = check_drift_escalation(engine)

    assert result is False
    mock_ks.assert_not_called()


def test_check_drift_escalation_expired():
    """drift_paused=True and paused 5 days ago with 3-day escalation -> kill switch activated, returns True."""
    engine, conn = _make_mock_engine()

    now = datetime.now(timezone.utc)
    paused_at = now - timedelta(days=5)  # 5 days ago > 3-day window

    state_row = MagicMock()
    state_row.__getitem__ = MagicMock(side_effect=lambda i: [True, paused_at, 3][i])
    conn.execute.return_value.fetchone.return_value = state_row

    with patch("ta_lab2.drift.drift_pause.activate_kill_switch") as mock_ks:
        result = check_drift_escalation(engine)

    assert result is True
    mock_ks.assert_called_once()
    call_args = mock_ks.call_args
    assert "drift_monitor" in str(call_args)
    assert "escalated" in str(call_args).lower() or "drift" in str(call_args).lower()
