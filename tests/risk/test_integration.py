"""
Integration tests for the risk module.

Verifies that all 3 sub-modules (risk_engine, kill_switch, override_manager) work
together as a cohesive package. All tests run without a live database.

Test classes:
    1. TestCheckOrderPriorityOrder     -- kill switch -> CB -> position cap -> portfolio cap -> allow
    2. TestRiskEngineWithOverrideManager -- shared engine instance, independent operations
    3. TestFullModuleImports           -- all 10 public symbols importable from ta_lab2.risk
    4. TestCLIEntryPoints              -- both CLIs have callable main()
    5. TestDocstringExecutorIntegration -- RiskEngine documents the executor integration point
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from ta_lab2.risk import OverrideManager, RiskEngine


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _default_limits_row():
    """
    Simulate dim_risk_limits portfolio-wide defaults row.
    Columns: max_position_pct, max_portfolio_pct, daily_loss_pct_threshold,
             cb_consecutive_losses_n, cb_loss_threshold_pct, cb_cooldown_hours,
             allow_overrides, asset_id, strategy_id
    """
    return [
        (
            Decimal("0.15"),  # max_position_pct
            Decimal("0.80"),  # max_portfolio_pct
            Decimal("0.03"),  # daily_loss_pct_threshold
            3,  # cb_consecutive_losses_n
            Decimal("0.0"),  # cb_loss_threshold_pct
            Decimal("24.0"),  # cb_cooldown_hours
            True,  # allow_overrides
            None,  # asset_id
            None,  # strategy_id
        )
    ]


def _make_engine_with_sequence(
    execute_side_effects: list,
) -> tuple[MagicMock, MagicMock]:
    """
    Build a mock SQLAlchemy engine that uses engine.connect() and sequences
    through execute_side_effects for successive calls.

    Returns (engine_mock, conn_mock).
    """
    engine = MagicMock()
    conn = MagicMock()
    conn.execute.side_effect = execute_side_effects
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


def _make_result(fetchone=None, fetchall=None, rowcount=0) -> MagicMock:
    """Build a single mock SQL result."""
    r = MagicMock()
    r.fetchone.return_value = fetchone
    r.fetchall.return_value = (
        fetchall if fetchall is not None else ([] if fetchone is None else [fetchone])
    )
    r.rowcount = rowcount
    return r


def _active_state() -> MagicMock:
    return _make_result(fetchone=("active",))


def _halted_state() -> MagicMock:
    return _make_result(fetchone=("halted",))


def _tail_risk_normal() -> MagicMock:
    """Gate 1.5: tail_risk_state = 'normal' (no tail risk active)."""
    return _make_result(fetchone=("normal",))


def _no_cb_tripped() -> MagicMock:
    return _make_result(fetchone=("{}",))


def _limits_result() -> MagicMock:
    return _make_result(fetchall=_default_limits_row())


def _log_event_result() -> MagicMock:
    return _make_result(fetchone=None)


# ---------------------------------------------------------------------------
# Test 1: TestCheckOrderPriorityOrder
# ---------------------------------------------------------------------------


class TestCheckOrderPriorityOrder:
    """
    Verify check_order gate priority: kill_switch -> circuit_breaker ->
    position_cap -> portfolio_cap -> allow.

    Each gate is tested by enabling just that gate and verifying the
    result transitions from allowed -> blocked at the correct stage.
    """

    def test_kill_switch_blocks_before_circuit_breaker(self):
        """When kill switch is active, order is blocked before circuit breaker check."""
        engine, conn = _make_engine_with_sequence(
            [
                _halted_state(),  # Gate 1: _is_halted -> halted
                _log_event_result(),  # _log_event INSERT
            ]
        )

        re = RiskEngine(engine)
        result = re.check_order(
            order_qty=Decimal("1"),
            order_side="buy",
            fill_price=Decimal("1000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("100000"),
        )

        assert result.allowed is False
        assert "Kill switch" in result.blocked_reason
        # CB check never reached (no limits load for CB)
        assert conn.execute.call_count == 2  # state SELECT + log_event INSERT

    def test_circuit_breaker_blocks_before_position_cap(self):
        """When CB is tripped, order is blocked before position cap check."""
        cb_key = "1:1"
        tripped_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        engine, conn = _make_engine_with_sequence(
            [
                _active_state(),  # Gate 1: active -> pass
                _tail_risk_normal(),  # Gate 1.5: tail risk normal -> pass
                _limits_result(),  # Gate 2: _load_limits for CB cooldown
                _make_result(
                    fetchone=(json.dumps({cb_key: tripped_at}),)
                ),  # CB tripped 1h ago
                # No limits load for position cap -- CB short-circuits
            ]
        )

        re = RiskEngine(engine)
        result = re.check_order(
            order_qty=Decimal("1"),
            order_side="buy",
            fill_price=Decimal("1000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("100000"),
        )

        assert result.allowed is False
        assert "Circuit breaker" in result.blocked_reason
        # Position cap limits were NOT loaded (4 ops: active + tail_risk + limits_CB + cb_tripped)
        assert conn.execute.call_count == 4

    def test_position_cap_blocks_before_portfolio_cap(self):
        """When position is at cap, order is blocked before portfolio cap check."""
        engine, conn = _make_engine_with_sequence(
            [
                _active_state(),  # Gate 1: active
                _tail_risk_normal(),  # Gate 1.5: tail risk normal
                _limits_result(),  # Gate 2: limits for CB cooldown
                _no_cb_tripped(),  # Gate 2: CB not tripped
                _limits_result(),  # Gate 3: limits for position/portfolio cap
                _log_event_result(),  # position_cap_blocked event
            ]
        )

        re = RiskEngine(engine)
        # Portfolio = 100000, cap = 15% = 15000. Current = 15000 (at cap).
        result = re.check_order(
            order_qty=Decimal("1"),
            order_side="buy",
            fill_price=Decimal("1000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("15000"),  # At 15% cap
            portfolio_value=Decimal("100000"),
        )

        assert result.allowed is False
        assert "cap" in result.blocked_reason.lower()

    def test_all_gates_pass_allows_order(self):
        """When all gates pass, order is allowed with original or adjusted quantity."""
        engine, conn = _make_engine_with_sequence(
            [
                _active_state(),  # Gate 1: active
                _tail_risk_normal(),  # Gate 1.5: tail risk normal
                _limits_result(),  # Gate 2: limits for CB cooldown
                _no_cb_tripped(),  # Gate 2: CB not tripped
                _limits_result(),  # Gate 3/4: limits for caps
            ]
        )

        re = RiskEngine(engine)
        # Small order well within all limits
        result = re.check_order(
            order_qty=Decimal("0.01"),
            order_side="buy",
            fill_price=Decimal("50000"),  # Notional = 500
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("1000000"),  # cap = 150000
        )

        assert result.allowed is True
        assert result.adjusted_quantity == Decimal("0.01")
        assert result.blocked_reason is None

    def test_kill_switch_gate_runs_first_always(self):
        """Kill switch is always the first check regardless of other state."""
        # Even with CB tripped AND position over cap, kill switch fires first
        engine, conn = _make_engine_with_sequence(
            [
                _halted_state(),  # Gate 1 fires immediately
                _log_event_result(),  # log event
            ]
        )

        re = RiskEngine(engine)
        result = re.check_order(
            order_qty=Decimal("100"),
            order_side="buy",
            fill_price=Decimal("1000"),
            asset_id=99,
            strategy_id=99,
            current_position_value=Decimal("999999"),  # Way over cap
            portfolio_value=Decimal("100000"),
        )

        assert result.allowed is False
        assert "Kill switch" in result.blocked_reason
        # Only 2 executes: state check + log event
        assert conn.execute.call_count == 2

    def test_sell_order_skips_position_and_portfolio_cap_gates(self):
        """Sell orders bypass gates 3 and 4 (position cap and portfolio cap)."""
        engine, conn = _make_engine_with_sequence(
            [
                _active_state(),  # Gate 1: active
                _tail_risk_normal(),  # Gate 1.5: tail risk normal
                _limits_result(),  # Gate 2: limits for CB
                _no_cb_tripped(),  # Gate 2: CB not tripped
                _limits_result(),  # Gate 3: limits loaded (even for sell -- side check is inside)
            ]
        )

        re = RiskEngine(engine)
        # Sell order -- even with massive current position, should pass
        result = re.check_order(
            order_qty=Decimal("50"),
            order_side="sell",
            fill_price=Decimal("1000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("500000"),  # Hugely over cap
            portfolio_value=Decimal("100000"),
        )

        assert result.allowed is True
        assert result.adjusted_quantity == Decimal("50")


# ---------------------------------------------------------------------------
# Test 2: TestRiskEngineWithOverrideManager
# ---------------------------------------------------------------------------


class TestRiskEngineWithOverrideManager:
    """
    Verify RiskEngine and OverrideManager can share the same SQLAlchemy engine
    instance and operate independently without interference.
    """

    def test_risk_engine_and_override_manager_share_engine(self):
        """Both objects accept the same engine instance without error."""
        shared_engine = MagicMock()
        conn = MagicMock()
        shared_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        shared_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        shared_engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
        shared_engine.begin.return_value.__exit__ = MagicMock(return_value=False)

        # Both accept the same engine -- no exceptions on init
        re = RiskEngine(shared_engine)
        mgr = OverrideManager(shared_engine)

        assert re._engine is shared_engine
        assert mgr._engine is shared_engine

    def test_risk_engine_check_order_does_not_affect_override_manager_state(self):
        """check_order and OverrideManager.get_active_overrides use different DB paths."""
        # RiskEngine uses engine.connect(); OverrideManager.get_active_overrides uses engine.connect()
        # They don't share any in-memory state -- verify by running both on separate mocks.
        re_engine = MagicMock()
        re_conn = MagicMock()
        re_conn.execute.side_effect = [
            _active_state(),
            _tail_risk_normal(),  # Gate 1.5: tail risk check
            _limits_result(),
            _no_cb_tripped(),
            _limits_result(),
        ]
        re_engine.connect.return_value.__enter__ = MagicMock(return_value=re_conn)
        re_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mgr_engine = MagicMock()
        mgr_conn = MagicMock()
        mgr_result = MagicMock()
        mgr_result.fetchall.return_value = []
        mgr_conn.execute.return_value = mgr_result
        mgr_engine.connect.return_value.__enter__ = MagicMock(return_value=mgr_conn)
        mgr_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        re = RiskEngine(re_engine)
        mgr = OverrideManager(mgr_engine)

        check_result = re.check_order(
            order_qty=Decimal("0.01"),
            order_side="buy",
            fill_price=Decimal("50000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("1000000"),
        )
        active = mgr.get_active_overrides()

        assert check_result.allowed is True
        assert active == []


# ---------------------------------------------------------------------------
# Test 3: TestFullModuleImports
# ---------------------------------------------------------------------------


class TestFullModuleImports:
    """All 10 public symbols are importable from ta_lab2.risk."""

    def test_import_risk_engine(self):
        from ta_lab2.risk import RiskEngine

        assert RiskEngine is not None

    def test_import_risk_check_result(self):
        from ta_lab2.risk import RiskCheckResult

        assert RiskCheckResult is not None

    def test_import_risk_limits(self):
        from ta_lab2.risk import RiskLimits

        assert RiskLimits is not None

    def test_import_activate_kill_switch(self):
        from ta_lab2.risk import activate_kill_switch

        assert callable(activate_kill_switch)

    def test_import_re_enable_trading(self):
        from ta_lab2.risk import re_enable_trading

        assert callable(re_enable_trading)

    def test_import_get_kill_switch_status(self):
        from ta_lab2.risk import get_kill_switch_status

        assert callable(get_kill_switch_status)

    def test_import_kill_switch_status(self):
        from ta_lab2.risk import KillSwitchStatus

        assert KillSwitchStatus is not None

    def test_import_print_kill_switch_status(self):
        from ta_lab2.risk import print_kill_switch_status

        assert callable(print_kill_switch_status)

    def test_import_override_manager(self):
        from ta_lab2.risk import OverrideManager

        assert OverrideManager is not None

    def test_import_override_info(self):
        from ta_lab2.risk import OverrideInfo

        assert OverrideInfo is not None

    def test_all_exports_in_dunder_all(self):
        """Every must-have symbol is listed in __all__."""
        import ta_lab2.risk as risk_pkg

        required_exports = {
            "RiskEngine",
            "RiskCheckResult",
            "RiskLimits",
            "activate_kill_switch",
            "re_enable_trading",
            "get_kill_switch_status",
            "KillSwitchStatus",
            "print_kill_switch_status",
            "OverrideManager",
            "OverrideInfo",
        }
        missing = required_exports - set(risk_pkg.__all__)
        assert not missing, f"Missing from __all__: {missing}"


# ---------------------------------------------------------------------------
# Test 4: TestCLIEntryPoints
# ---------------------------------------------------------------------------


class TestCLIEntryPoints:
    """Both CLIs have a callable main() function importable as a module."""

    def test_kill_switch_cli_main_is_callable(self):
        """kill_switch_cli.main() is importable and callable."""
        from ta_lab2.scripts.risk.kill_switch_cli import main

        assert callable(main)

    def test_override_cli_main_is_callable(self):
        """override_cli.main() is importable and callable."""
        from ta_lab2.scripts.risk.override_cli import main

        assert callable(main)

    def test_kill_switch_cli_main_with_help_exits(self):
        """kill_switch_cli main() raises SystemExit(0) for --help."""
        from ta_lab2.scripts.risk.kill_switch_cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_override_cli_main_with_help_exits(self):
        """override_cli main() raises SystemExit(0) for --help."""
        from ta_lab2.scripts.risk.override_cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["--help"])
        assert exc_info.value.code == 0

    def test_kill_switch_cli_build_parser_has_subcommands(self):
        """Parser has activate, disable, status subcommands."""
        from ta_lab2.scripts.risk.kill_switch_cli import build_parser

        parser = build_parser()
        # Build a namespace for each subcommand to verify they parse correctly
        args_status = parser.parse_args(["status"])
        assert args_status.command == "status"

        args_activate = parser.parse_args(["activate", "--reason", "test halt"])
        assert args_activate.reason == "test halt"

        args_disable = parser.parse_args(
            ["disable", "--reason", "resolved", "--operator", "asafi"]
        )
        assert args_disable.operator == "asafi"

    def test_override_cli_build_parser_has_subcommands(self):
        """Parser has create, revert, list subcommands."""
        from ta_lab2.scripts.risk.override_cli import build_parser

        parser = build_parser()
        args_list = parser.parse_args(["list"])
        assert args_list.command == "list"

        args_create = parser.parse_args(
            [
                "create",
                "--asset-id",
                "1",
                "--strategy-id",
                "2",
                "--action",
                "flat",
                "--reason",
                "liquidity concern",
                "--operator",
                "asafi",
            ]
        )
        assert args_create.asset_id == 1
        assert args_create.action == "flat"
        assert args_create.sticky is False

        args_create_sticky = parser.parse_args(
            [
                "create",
                "--asset-id",
                "1",
                "--strategy-id",
                "2",
                "--action",
                "flat",
                "--reason",
                "sticky test",
                "--operator",
                "asafi",
                "--sticky",
            ]
        )
        assert args_create_sticky.sticky is True


# ---------------------------------------------------------------------------
# Test 5: TestDocstringExecutorIntegration
# ---------------------------------------------------------------------------


class TestDocstringExecutorIntegration:
    """RiskEngine class docstring documents the Phase 45 executor integration point."""

    def test_risk_engine_has_docstring(self):
        """RiskEngine has a non-empty docstring."""
        assert RiskEngine.__doc__ is not None
        assert len(RiskEngine.__doc__.strip()) > 0

    def test_docstring_mentions_check_order(self):
        """Docstring references check_order() method for executor wiring."""
        assert "check_order" in RiskEngine.__doc__

    def test_docstring_mentions_executor_integration(self):
        """Docstring explicitly documents the executor integration point."""
        doc = RiskEngine.__doc__
        assert "executor" in doc.lower() or "Executor" in doc

    def test_docstring_mentions_check_daily_loss(self):
        """Docstring references check_daily_loss() for daily risk monitoring."""
        assert "check_daily_loss" in RiskEngine.__doc__

    def test_docstring_mentions_update_circuit_breaker(self):
        """Docstring references update_circuit_breaker() for per-trade recording."""
        assert "update_circuit_breaker" in RiskEngine.__doc__

    def test_check_order_has_docstring(self):
        """check_order() method also has a docstring."""
        assert RiskEngine.check_order.__doc__ is not None
        assert len(RiskEngine.check_order.__doc__.strip()) > 0

    def test_risk_engine_module_docstring_present(self):
        """risk_engine module has a top-level docstring."""
        import ta_lab2.risk.risk_engine as re_mod

        assert re_mod.__doc__ is not None
        assert "executor" in re_mod.__doc__.lower() or "RiskEngine" in re_mod.__doc__
