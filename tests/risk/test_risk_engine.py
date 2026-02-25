"""
Unit tests for RiskEngine.

All tests run without a live database -- SQLAlchemy Engine is mocked throughout.
The mock connection returns controlled SQL results allowing precise gate testing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock


from ta_lab2.risk.risk_engine import RiskCheckResult, RiskEngine, RiskLimits


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(sql_returns: list) -> MagicMock:
    """
    Build a mock SQLAlchemy engine that sequences through ``sql_returns``
    for successive .execute() calls.

    Each item in sql_returns is either:
    - A list of tuples (rows returned)
    - A single tuple (single-row result)
    - None (no rows / non-SELECT statement)
    """
    mock_engine = MagicMock()
    conn = MagicMock()
    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    results = []
    for item in sql_returns:
        result = MagicMock()
        if item is None:
            result.fetchone.return_value = None
            result.fetchall.return_value = []
            result.rowcount = 0
        elif isinstance(item, list):
            result.fetchone.return_value = item[0] if item else None
            result.fetchall.return_value = item
            result.rowcount = len(item)
        else:
            # Single tuple
            result.fetchone.return_value = item
            result.fetchall.return_value = [item]
            result.rowcount = 1
        results.append(result)

    conn.execute.side_effect = results
    return mock_engine


def _active_state_row():
    """Simulate dim_risk_state with active trading."""
    return ("active",)


def _halted_state_row():
    """Simulate dim_risk_state with halted trading."""
    return ("halted",)


def _tail_risk_normal_row():
    """Simulate dim_risk_state tail_risk_state = 'normal' (Gate 1.5)."""
    return ("normal",)


def _no_cb_tripped():
    """Simulate cb_breaker_tripped_at = '{}'."""
    return ("{}",)


def _default_limits_row():
    """
    Simulate dim_risk_limits portfolio-wide defaults row.
    Columns: max_position_pct, max_portfolio_pct, daily_loss_pct_threshold,
             cb_consecutive_losses_n, cb_loss_threshold_pct, cb_cooldown_hours,
             allow_overrides, asset_id, strategy_id,
             margin_alert_threshold, liquidation_kill_threshold
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
            Decimal("1.5"),  # margin_alert_threshold
            Decimal("1.1"),  # liquidation_kill_threshold
        )
    ]


def _no_perp_position():
    """Simulate cmc_perp_positions returning no active position (Gate 1.6 passes)."""
    result = MagicMock()
    result.fetchone.return_value = None
    return result


# ---------------------------------------------------------------------------
# TestRiskLimits
# ---------------------------------------------------------------------------


class TestRiskLimits:
    """Validate RiskLimits dataclass defaults and custom values."""

    def test_default_values(self):
        limits = RiskLimits()
        assert limits.max_position_pct == 0.15
        assert limits.max_portfolio_pct == 0.80
        assert limits.daily_loss_pct_threshold == 0.03
        assert limits.cb_consecutive_losses_n == 3
        assert limits.cb_loss_threshold_pct == 0.0
        assert limits.cb_cooldown_hours == 24.0
        assert limits.allow_overrides is True

    def test_custom_values(self):
        limits = RiskLimits(
            max_position_pct=0.05,
            max_portfolio_pct=0.50,
            daily_loss_pct_threshold=0.02,
            cb_consecutive_losses_n=5,
            cb_loss_threshold_pct=-0.01,
            cb_cooldown_hours=12.0,
            allow_overrides=False,
        )
        assert limits.max_position_pct == 0.05
        assert limits.max_portfolio_pct == 0.50
        assert limits.daily_loss_pct_threshold == 0.02
        assert limits.cb_consecutive_losses_n == 5
        assert limits.cb_loss_threshold_pct == -0.01
        assert limits.cb_cooldown_hours == 12.0
        assert limits.allow_overrides is False


# ---------------------------------------------------------------------------
# TestRiskCheckResult
# ---------------------------------------------------------------------------


class TestRiskCheckResult:
    """Validate RiskCheckResult dataclass."""

    def test_allowed_result(self):
        result = RiskCheckResult(allowed=True, adjusted_quantity=Decimal("0.5"))
        assert result.allowed is True
        assert result.adjusted_quantity == Decimal("0.5")
        assert result.blocked_reason is None

    def test_blocked_result(self):
        result = RiskCheckResult(
            allowed=False, blocked_reason="Kill switch active -- trading halted"
        )
        assert result.allowed is False
        assert result.adjusted_quantity is None
        assert "Kill switch" in result.blocked_reason


# ---------------------------------------------------------------------------
# TestCheckOrderKillSwitch
# ---------------------------------------------------------------------------


class TestCheckOrderKillSwitch:
    """Kill switch gate blocks all orders immediately."""

    def test_halted_state_blocks_order(self):
        """When trading_state='halted', check_order() returns blocked with kill switch reason."""
        # Gate 1 (_is_halted) reads trading_state; returns "halted"
        # The _log_event call also needs an execute + commit
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        # First execute: dim_risk_state trading_state = 'halted'
        halted_result = MagicMock()
        halted_result.fetchone.return_value = ("halted",)
        # Second execute: _log_event INSERT (no result needed)
        log_result = MagicMock()
        log_result.fetchone.return_value = None

        conn.execute.side_effect = [halted_result, log_result]

        engine = RiskEngine(mock_engine)
        result = engine.check_order(
            order_qty=Decimal("0.1"),
            order_side="buy",
            fill_price=Decimal("50000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("100000"),
        )

        assert result.allowed is False
        assert "Kill switch" in result.blocked_reason
        assert result.adjusted_quantity is None

    def test_active_state_does_not_block_at_gate_1(self):
        """When trading_state='active', kill switch gate passes."""
        # _is_circuit_breaker_tripped calls _load_limits first, then reads cb_breaker_tripped_at.
        # Order: active -> tail_risk(normal) -> limits(for CB cooldown) -> cb_tripped -> limits(for cap gates)
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        # Gate 1: active
        active_result = MagicMock()
        active_result.fetchone.return_value = ("active",)
        # Gate 1.5: tail_risk_state = 'normal'
        tail_risk_result = MagicMock()
        tail_risk_result.fetchone.return_value = ("normal",)
        # Gate 2: _load_limits inside _is_circuit_breaker_tripped (needs cooldown)
        limits_for_cb = MagicMock()
        limits_for_cb.fetchall.return_value = _default_limits_row()
        # Gate 2: cb_breaker_tripped_at = '{}'
        cb_result = MagicMock()
        cb_result.fetchone.return_value = ("{}",)
        # Gate 3: limits for position/portfolio cap
        limits_for_caps = MagicMock()
        limits_for_caps.fetchall.return_value = _default_limits_row()
        # Gate 1.6: cmc_perp_positions -- no perp position, gate passes
        perp_pos_result = _no_perp_position()

        conn.execute.side_effect = [
            active_result,
            tail_risk_result,
            limits_for_cb,
            cb_result,
            limits_for_caps,
            perp_pos_result,
        ]

        engine = RiskEngine(mock_engine)
        result = engine.check_order(
            order_qty=Decimal("0.01"),  # Very small order
            order_side="buy",
            fill_price=Decimal("50000"),  # Notional = 500
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("100000"),  # cap = 15000
        )

        assert result.allowed is True


# ---------------------------------------------------------------------------
# TestCheckOrderPositionCap
# ---------------------------------------------------------------------------


class TestCheckOrderPositionCap:
    """Position cap scales down order quantity rather than rejecting."""

    def test_scale_down_to_position_cap(self):
        """
        Portfolio = 100000, cap = 15% = 15000.
        Current position = 5000. Available = 10000.
        Order: 30 units @ 500 = 15000 notional.
        Expected: scaled to 10000 / 500 = 20 units.

        Call order: active -> tail_risk(normal) -> limits(CB) -> cb_tripped -> limits(caps) -> log_event
        """
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        active_result = MagicMock()
        active_result.fetchone.return_value = ("active",)
        tail_risk_result = MagicMock()
        tail_risk_result.fetchone.return_value = ("normal",)
        limits_for_cb = MagicMock()
        limits_for_cb.fetchall.return_value = _default_limits_row()
        cb_result = MagicMock()
        cb_result.fetchone.return_value = ("{}",)
        limits_for_caps = MagicMock()
        limits_for_caps.fetchall.return_value = _default_limits_row()
        # _log_event for position_cap_scaled
        log_result = MagicMock()
        log_result.fetchone.return_value = None

        # Gate 1.6: cmc_perp_positions -- no perp position, gate passes
        perp_pos_result = _no_perp_position()

        conn.execute.side_effect = [
            active_result,
            tail_risk_result,
            limits_for_cb,
            cb_result,
            limits_for_caps,
            log_result,
            perp_pos_result,
        ]

        engine = RiskEngine(mock_engine)
        result = engine.check_order(
            order_qty=Decimal("30"),
            order_side="buy",
            fill_price=Decimal("500"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("5000"),
            portfolio_value=Decimal("100000"),
        )

        assert result.allowed is True
        # Available = 15000 - 5000 = 10000; scaled = 10000 / 500 = 20
        assert result.adjusted_quantity == Decimal("20")

    def test_position_cap_exact_boundary(self):
        """Order fits exactly within position cap -- no scaling needed."""
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        active_result = MagicMock()
        active_result.fetchone.return_value = ("active",)
        tail_risk_result = MagicMock()
        tail_risk_result.fetchone.return_value = ("normal",)
        limits_for_cb = MagicMock()
        limits_for_cb.fetchall.return_value = _default_limits_row()
        cb_result = MagicMock()
        cb_result.fetchone.return_value = ("{}",)
        limits_for_caps = MagicMock()
        limits_for_caps.fetchall.return_value = _default_limits_row()

        # Gate 1.6: cmc_perp_positions -- no perp position, gate passes
        perp_pos_result = _no_perp_position()

        conn.execute.side_effect = [
            active_result,
            tail_risk_result,
            limits_for_cb,
            cb_result,
            limits_for_caps,
            perp_pos_result,
        ]

        engine = RiskEngine(mock_engine)
        # Portfolio = 100000, cap = 15% = 15000
        # Order: 10 units @ 1000 = 10000 notional, current = 0 -> total = 10000 < 15000
        result = engine.check_order(
            order_qty=Decimal("10"),
            order_side="buy",
            fill_price=Decimal("1000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("100000"),
        )

        assert result.allowed is True
        assert result.adjusted_quantity == Decimal("10")


# ---------------------------------------------------------------------------
# TestCheckOrderPositionCapExhausted
# ---------------------------------------------------------------------------


class TestCheckOrderPositionCapExhausted:
    """When position is already at or beyond cap, order is blocked."""

    def test_position_already_at_cap_blocks_buy(self):
        """Current position >= max_position -- buy blocked."""
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        active_result = MagicMock()
        active_result.fetchone.return_value = ("active",)
        tail_risk_result = MagicMock()
        tail_risk_result.fetchone.return_value = ("normal",)
        limits_for_cb = MagicMock()
        limits_for_cb.fetchall.return_value = _default_limits_row()
        cb_result = MagicMock()
        cb_result.fetchone.return_value = ("{}",)
        limits_for_caps = MagicMock()
        limits_for_caps.fetchall.return_value = _default_limits_row()
        log_result = MagicMock()
        log_result.fetchone.return_value = None

        conn.execute.side_effect = [
            active_result,
            tail_risk_result,
            limits_for_cb,
            cb_result,
            limits_for_caps,
            log_result,
        ]

        engine = RiskEngine(mock_engine)
        # Portfolio = 100000, cap = 15% = 15000
        # Current position = 15000 (exactly at cap)
        result = engine.check_order(
            order_qty=Decimal("1"),
            order_side="buy",
            fill_price=Decimal("1000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("15000"),
            portfolio_value=Decimal("100000"),
        )

        assert result.allowed is False
        assert "cap exhausted" in result.blocked_reason.lower()

    def test_sell_order_bypasses_position_cap(self):
        """Sell orders skip position cap and portfolio cap checks."""
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        active_result = MagicMock()
        active_result.fetchone.return_value = ("active",)
        tail_risk_result = MagicMock()
        tail_risk_result.fetchone.return_value = ("normal",)
        limits_for_cb = MagicMock()
        limits_for_cb.fetchall.return_value = _default_limits_row()
        cb_result = MagicMock()
        cb_result.fetchone.return_value = ("{}",)
        limits_for_caps = MagicMock()
        limits_for_caps.fetchall.return_value = _default_limits_row()

        conn.execute.side_effect = [
            active_result,
            tail_risk_result,
            limits_for_cb,
            cb_result,
            limits_for_caps,
        ]

        engine = RiskEngine(mock_engine)
        # Even with huge position, sell should be allowed
        result = engine.check_order(
            order_qty=Decimal("100"),
            order_side="sell",
            fill_price=Decimal("1000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("200000"),  # Way over cap
            portfolio_value=Decimal("100000"),
        )

        assert result.allowed is True
        assert result.adjusted_quantity == Decimal("100")


# ---------------------------------------------------------------------------
# TestCheckOrderAllClear
# ---------------------------------------------------------------------------


class TestCheckOrderAllClear:
    """Small order within all limits passes all 5 gates."""

    def test_small_buy_order_passes_all_gates(self):
        """0.1 BTC @ 50000 = 5000 notional. Portfolio = 1M, cap = 150000. All pass."""
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        active_result = MagicMock()
        active_result.fetchone.return_value = ("active",)
        tail_risk_result = MagicMock()
        tail_risk_result.fetchone.return_value = ("normal",)
        limits_for_cb = MagicMock()
        limits_for_cb.fetchall.return_value = _default_limits_row()
        cb_result = MagicMock()
        cb_result.fetchone.return_value = ("{}",)
        limits_for_caps = MagicMock()
        limits_for_caps.fetchall.return_value = _default_limits_row()

        # Gate 1.6: cmc_perp_positions -- no perp position, gate passes
        perp_pos_result = _no_perp_position()

        conn.execute.side_effect = [
            active_result,
            tail_risk_result,
            limits_for_cb,
            cb_result,
            limits_for_caps,
            perp_pos_result,
        ]

        engine = RiskEngine(mock_engine)
        result = engine.check_order(
            order_qty=Decimal("0.1"),
            order_side="buy",
            fill_price=Decimal("50000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("1000000"),
        )

        assert result.allowed is True
        assert result.adjusted_quantity == Decimal("0.1")
        assert result.blocked_reason is None


# ---------------------------------------------------------------------------
# TestCircuitBreakerTripped
# ---------------------------------------------------------------------------


class TestCircuitBreakerTripped:
    """Circuit breaker gate blocks orders when breaker is tripped and within cooldown."""

    def test_tripped_within_cooldown_blocks_order(self):
        """When cb_breaker_tripped_at has a recent timestamp, order is blocked."""
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        # Gate 1: active
        active_result = MagicMock()
        active_result.fetchone.return_value = ("active",)
        # Gate 1.5: tail risk normal
        tail_risk_result = MagicMock()
        tail_risk_result.fetchone.return_value = ("normal",)
        # Gate 2: cb tripped 1 hour ago (within 24h cooldown)
        cb_key = "1:1"
        tripped_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        cb_tripped_result = MagicMock()
        cb_tripped_result.fetchone.return_value = (json.dumps({cb_key: tripped_at}),)
        # _load_limits for cooldown check
        limits_result = MagicMock()
        limits_result.fetchall.return_value = _default_limits_row()

        conn.execute.side_effect = [
            active_result,
            tail_risk_result,
            limits_result,
            cb_tripped_result,
        ]

        engine = RiskEngine(mock_engine)
        result = engine.check_order(
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


# ---------------------------------------------------------------------------
# TestUpdateCircuitBreaker
# ---------------------------------------------------------------------------


class TestUpdateCircuitBreaker:
    """update_circuit_breaker increments counter and trips at N consecutive losses."""

    def _make_cb_engine(self, initial_losses: dict, initial_tripped: dict) -> MagicMock:
        """Build engine mock for circuit breaker update tests."""
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        return mock_engine, conn

    def test_increment_to_n_trips_breaker(self):
        """
        With N=3: after 2 prior losses (count=2), a third loss (PnL<0) should trip.
        """
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        cb_key = "1:1"
        initial_losses = {cb_key: 2}  # Already at 2

        # _load_limits call
        limits_result = MagicMock()
        limits_result.fetchall.return_value = _default_limits_row()

        # SELECT cb_consecutive_losses
        losses_result = MagicMock()
        losses_result.fetchone.return_value = (json.dumps(initial_losses),)

        # UPDATE cb_consecutive_losses (no return needed)
        update_losses_result = MagicMock()
        update_losses_result.fetchone.return_value = None

        # SELECT cb_breaker_tripped_at (for recording trip timestamp)
        tripped_result = MagicMock()
        tripped_result.fetchone.return_value = ("{}",)

        # UPDATE cb_breaker_tripped_at (no return needed)
        update_tripped_result = MagicMock()
        update_tripped_result.fetchone.return_value = None

        # _log_event INSERT
        log_result = MagicMock()
        log_result.fetchone.return_value = None

        conn.execute.side_effect = [
            limits_result,
            losses_result,
            update_losses_result,
            tripped_result,
            update_tripped_result,
            log_result,
        ]

        engine = RiskEngine(mock_engine)
        tripped = engine.update_circuit_breaker(
            strategy_id=1,
            realized_pnl=Decimal("-500"),  # Loss
            asset_id=1,
        )

        assert tripped is True

    def test_profit_resets_loss_counter(self):
        """A profitable trade resets the consecutive loss counter to 0."""
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        cb_key = "1:1"
        initial_losses = {cb_key: 2}  # Had 2 losses

        limits_result = MagicMock()
        limits_result.fetchall.return_value = _default_limits_row()

        losses_result = MagicMock()
        losses_result.fetchone.return_value = (json.dumps(initial_losses),)

        update_result = MagicMock()
        update_result.fetchone.return_value = None

        conn.execute.side_effect = [limits_result, losses_result, update_result]

        engine = RiskEngine(mock_engine)
        tripped = engine.update_circuit_breaker(
            strategy_id=1,
            realized_pnl=Decimal("200"),  # Profit
            asset_id=1,
        )

        assert tripped is False
        # Verify UPDATE was called with count=0
        update_call = conn.execute.call_args_list[2]
        params = update_call[0][1]  # second positional arg is params dict
        updated_losses = json.loads(params["cb_losses"])
        assert updated_losses[cb_key] == 0

    def test_first_loss_increments_to_one(self):
        """First loss increments counter from 0 to 1 -- does not trip (N=3)."""
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        cb_key = "None:1"
        limits_result = MagicMock()
        limits_result.fetchall.return_value = _default_limits_row()

        losses_result = MagicMock()
        losses_result.fetchone.return_value = ("{}",)

        update_result = MagicMock()
        update_result.fetchone.return_value = None

        conn.execute.side_effect = [limits_result, losses_result, update_result]

        engine = RiskEngine(mock_engine)
        tripped = engine.update_circuit_breaker(
            strategy_id=1,
            realized_pnl=Decimal("-100"),  # Loss
            asset_id=None,
        )

        assert tripped is False


# ---------------------------------------------------------------------------
# TestCircuitBreakerCooldownAutoReset
# ---------------------------------------------------------------------------


class TestCircuitBreakerCooldownAutoReset:
    """Circuit breaker auto-resets when cooldown period has elapsed."""

    def test_elapsed_cooldown_allows_order(self):
        """Breaker tripped 25 hours ago with 24h cooldown -> auto-reset -> order allowed."""
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        cb_key = "1:1"
        tripped_at = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()

        # Gate 1: active
        active_result = MagicMock()
        active_result.fetchone.return_value = ("active",)
        # Gate 1.5: tail risk normal
        tail_risk_result = MagicMock()
        tail_risk_result.fetchone.return_value = ("normal",)
        # Gate 2: _load_limits (for cooldown)
        limits_result = MagicMock()
        limits_result.fetchall.return_value = _default_limits_row()
        # cb_breaker_tripped_at has entry -- but 25h elapsed
        cb_tripped_result = MagicMock()
        cb_tripped_result.fetchone.return_value = (json.dumps({cb_key: tripped_at}),)
        # Auto-reset reads cb_consecutive_losses
        losses_row_result = MagicMock()
        losses_row_result.fetchone.return_value = (json.dumps({cb_key: 3}),)
        # Auto-reset UPDATE
        update_result = MagicMock()
        update_result.fetchone.return_value = None

        # Gate 3: limits load again
        limits_result2 = MagicMock()
        limits_result2.fetchall.return_value = _default_limits_row()

        # Gate 1.6: cmc_perp_positions -- no perp position, gate passes
        perp_pos_result = _no_perp_position()

        conn.execute.side_effect = [
            active_result,
            tail_risk_result,
            limits_result,
            cb_tripped_result,
            losses_row_result,
            update_result,
            limits_result2,
            perp_pos_result,
        ]

        engine = RiskEngine(mock_engine)
        result = engine.check_order(
            order_qty=Decimal("0.01"),
            order_side="buy",
            fill_price=Decimal("50000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("1000000"),
        )

        assert result.allowed is True
