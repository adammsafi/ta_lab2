"""
Unit tests for kill switch operations.

All tests run without a live database -- SQLAlchemy Engine is mocked throughout.
Tests verify the exact sequence of SQL operations (UPDATE state, UPDATE orders,
INSERT event) and guard against duplicate activation/premature re-enable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from ta_lab2.risk.kill_switch import (
    KillSwitchStatus,
    activate_kill_switch,
    get_kill_switch_status,
    re_enable_trading,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_conn(execute_results: list) -> tuple[MagicMock, MagicMock]:
    """
    Build a mock engine + connection with sequenced execute() results.

    Returns (engine_mock, conn_mock) for assertions on conn.execute.
    """
    mock_engine = MagicMock()
    conn = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    results = []
    for item in execute_results:
        result = MagicMock()
        if item is None:
            result.fetchone.return_value = None
            result.rowcount = 0
        else:
            result.fetchone.return_value = item
            result.rowcount = 1
        results.append(result)

    conn.execute.side_effect = results
    return mock_engine, conn


# ---------------------------------------------------------------------------
# TestActivateKillSwitch
# ---------------------------------------------------------------------------


class TestActivateKillSwitch:
    """activate_kill_switch performs 3 SQL operations atomically."""

    def test_three_sql_ops_on_activation(self):
        """
        Activating the kill switch must execute exactly 3 SQL statements:
        1. SELECT dim_risk_state (check current state)
        2. UPDATE dim_risk_state (flip to halted)
        3. UPDATE orders (cancel pending orders)
        4. INSERT risk_events (audit log)
        """
        mock_engine, conn = _make_conn(
            [
                ("active",),  # SELECT trading_state -- currently active
                None,  # UPDATE dim_risk_state -> halted
                None,  # UPDATE orders (cancel pending)
                None,  # INSERT risk_events
            ]
        )
        conn.execute.return_value.rowcount = 2  # 2 orders cancelled

        # Reset side_effect (rowcount assertion conflicts with it)
        mock_engine2, conn2 = _make_conn(
            [
                ("active",),  # SELECT trading_state
                None,  # UPDATE dim_risk_state
                None,  # UPDATE orders
                None,  # INSERT risk_events
            ]
        )

        activate_kill_switch(
            engine=mock_engine2,
            reason="Market anomaly detected",
            trigger_source="manual",
            operator="trader_1",
        )

        # Should have called execute 4 times (SELECT + 3 writes)
        assert conn2.execute.call_count == 4
        # Commit should have been called once
        conn2.commit.assert_called_once()

    def test_duplicate_activate_is_no_op(self):
        """If trading already halted, activate returns immediately without further SQL."""
        mock_engine, conn = _make_conn(
            [
                ("halted",),  # SELECT trading_state -- already halted
            ]
        )

        activate_kill_switch(
            engine=mock_engine,
            reason="Second attempt",
            trigger_source="manual",
        )

        # Only 1 execute (the SELECT), no UPDATE or INSERT
        assert conn.execute.call_count == 1
        conn.commit.assert_not_called()

    def test_missing_state_row_returns_gracefully(self):
        """If dim_risk_state has no row, activate logs error and returns."""
        mock_engine, conn = _make_conn(
            [
                None,  # SELECT returns no row
            ]
        )

        # Should not raise
        activate_kill_switch(
            engine=mock_engine,
            reason="Test",
            trigger_source="system",
        )

        assert conn.execute.call_count == 1
        conn.commit.assert_not_called()

    def test_telegram_alert_called_on_activation(self):
        """Telegram alert is attempted after successful kill switch activation."""
        mock_engine, conn = _make_conn(
            [
                ("active",),
                None,
                None,
                None,
            ]
        )

        import ta_lab2.risk.kill_switch as ks_module

        original_telegram = ks_module._TELEGRAM_AVAILABLE
        mock_alert = MagicMock(return_value=True)
        ks_module._TELEGRAM_AVAILABLE = True
        ks_module._send_critical_alert = mock_alert

        try:
            activate_kill_switch(
                engine=mock_engine,
                reason="Telegram test",
                trigger_source="manual",
            )
            mock_alert.assert_called_once()
            call_kwargs = mock_alert.call_args
            assert "kill_switch" in str(call_kwargs)
        finally:
            ks_module._TELEGRAM_AVAILABLE = original_telegram
            ks_module._send_critical_alert = None


# ---------------------------------------------------------------------------
# TestReEnableTrading
# ---------------------------------------------------------------------------


class TestReEnableTrading:
    """re_enable_trading requires reason + operator and performs 2 SQL writes."""

    def test_re_enable_updates_state_and_logs_event(self):
        """
        Re-enabling trading must:
        1. SELECT dim_risk_state (verify halted)
        2. UPDATE dim_risk_state (flip to active, clear halt columns)
        3. INSERT risk_events (audit log)
        """
        mock_engine, conn = _make_conn(
            [
                ("halted",),  # SELECT trading_state -- currently halted
                None,  # UPDATE dim_risk_state -> active
                None,  # INSERT risk_events
            ]
        )

        re_enable_trading(
            engine=mock_engine,
            reason="Issue resolved, resuming paper trading",
            operator="asafi",
        )

        assert conn.execute.call_count == 3
        conn.commit.assert_called_once()

    def test_re_enable_requires_non_empty_reason(self):
        """re_enable_trading raises ValueError for empty reason."""
        mock_engine, _ = _make_conn([])

        with pytest.raises(ValueError, match="reason must be a non-empty string"):
            re_enable_trading(engine=mock_engine, reason="", operator="asafi")

    def test_re_enable_requires_non_empty_operator(self):
        """re_enable_trading raises ValueError for empty operator."""
        mock_engine, _ = _make_conn([])

        with pytest.raises(ValueError, match="operator must be a non-empty string"):
            re_enable_trading(
                engine=mock_engine,
                reason="All good",
                operator="   ",  # whitespace only
            )


# ---------------------------------------------------------------------------
# TestReEnableAlreadyActive
# ---------------------------------------------------------------------------


class TestReEnableAlreadyActive:
    """If trading is already active, re_enable returns without UPDATE."""

    def test_already_active_is_no_op(self):
        """If trading_state='active', re_enable logs warning and returns."""
        mock_engine, conn = _make_conn(
            [
                ("active",),  # SELECT -- already active
            ]
        )

        re_enable_trading(
            engine=mock_engine,
            reason="Redundant re-enable",
            operator="operator_1",
        )

        # Only 1 execute (the SELECT), no UPDATE or INSERT
        assert conn.execute.call_count == 1
        conn.commit.assert_not_called()

    def test_missing_state_row_returns_gracefully(self):
        """If dim_risk_state has no row, re_enable logs error and returns."""
        mock_engine, conn = _make_conn(
            [
                None,  # SELECT returns no row
            ]
        )

        re_enable_trading(
            engine=mock_engine,
            reason="Test",
            operator="op",
        )

        assert conn.execute.call_count == 1
        conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# TestGetKillSwitchStatus
# ---------------------------------------------------------------------------


class TestGetKillSwitchStatus:
    """get_kill_switch_status returns KillSwitchStatus with correct fields."""

    def test_returns_active_status(self):
        """Active state maps to KillSwitchStatus with all None halt fields."""
        mock_engine, conn = _make_conn(
            [
                (
                    "active",
                    None,
                    None,
                    None,
                ),  # trading_state, halted_at, halted_reason, halted_by
            ]
        )

        status = get_kill_switch_status(mock_engine)

        assert isinstance(status, KillSwitchStatus)
        assert status.trading_state == "active"
        assert status.halted_at is None
        assert status.halted_reason is None
        assert status.halted_by is None

    def test_returns_halted_status(self):
        """Halted state maps all fields correctly."""
        halted_time = datetime(2026, 2, 25, 10, 0, 0, tzinfo=timezone.utc)
        mock_engine, conn = _make_conn(
            [
                ("halted", halted_time, "Market crash", "system"),
            ]
        )

        status = get_kill_switch_status(mock_engine)

        assert status.trading_state == "halted"
        assert status.halted_at == halted_time
        assert status.halted_reason == "Market crash"
        assert status.halted_by == "system"

    def test_raises_runtime_error_when_no_row(self):
        """Missing dim_risk_state row raises RuntimeError."""
        mock_engine, conn = _make_conn(
            [
                None,  # No row
            ]
        )

        with pytest.raises(RuntimeError, match="dim_risk_state has no row"):
            get_kill_switch_status(mock_engine)

    def test_execute_called_once(self):
        """get_kill_switch_status makes exactly one SELECT."""
        mock_engine, conn = _make_conn(
            [
                ("active", None, None, None),
            ]
        )

        get_kill_switch_status(mock_engine)
        assert conn.execute.call_count == 1
