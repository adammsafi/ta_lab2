"""
Unit tests for RiskEngine Gate 1.6 -- Margin/Liquidation check.

Gate 1.6 is the margin/liquidation buffer check for perpetual futures positions.
It is only active for buy orders; sell orders always bypass it.

Severity ordering (most to least severe -- checked in this order):
    1. Critical (<=1.1x maintenance margin)  -> blocks order
    2. Warning  (<=1.5x maintenance margin)  -> logs event only, does NOT block
    3. Buffer   (<=2.0x maintenance margin)  -> blocks order
    4. Safe     (>2.0x)                      -> passes (returns None)

All tests use mocked DB -- no live database required.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(side_effects: list) -> tuple[MagicMock, MagicMock]:
    """
    Build a mock SQLAlchemy engine that sequences through side_effects
    for successive .execute() calls.

    Returns (engine_mock, conn_mock).
    """
    engine = MagicMock()
    conn = MagicMock()
    conn.execute.side_effect = side_effects
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


def _default_limits_row():
    """
    Full dim_risk_limits row including new margin threshold columns.
    Columns (indices 0-10):
        0: max_position_pct, 1: max_portfolio_pct, 2: daily_loss_pct_threshold,
        3: cb_consecutive_losses_n, 4: cb_loss_threshold_pct, 5: cb_cooldown_hours,
        6: allow_overrides, 7: asset_id, 8: strategy_id,
        9: margin_alert_threshold, 10: liquidation_kill_threshold
    """
    return [
        (
            Decimal("0.15"),
            Decimal("0.80"),
            Decimal("0.03"),
            3,
            Decimal("0.0"),
            Decimal("24.0"),
            True,
            None,
            None,
            Decimal("1.5"),
            Decimal("1.1"),
        )
    ]


def _active_state():
    return _make_result(fetchone=("active",))


def _tail_risk_normal():
    return _make_result(fetchone=("normal",))


def _no_cb_tripped():
    return _make_result(fetchone=("{}",))


def _limits_result():
    return _make_result(fetchall=_default_limits_row())


def _log_event_result():
    return _make_result(fetchone=None)


def _no_perp_position():
    """No active perp position -- Gate 1.6 passes immediately."""
    return _make_result(fetchone=None)


def _perp_position_row(
    venue: str = "binance",
    symbol: str = "BTC",
    allocated_margin: float = 5000.0,
    leverage: float = 10.0,
    margin_mode: str = "isolated",
    side: str = "long",
    mark_price: float = 50000.0,
    quantity: float = 1.0,
    avg_entry_price: float = 48000.0,
) -> MagicMock:
    """
    Simulate a cmc_perp_positions row.

    position_value = mark_price * quantity = 50000 * 1.0 = 50000
    Default tier not loaded from DB (empty tiers -> defaults: IM=10%, MM=5%)
    maintenance_margin = position_value * 0.05 = 50000 * 0.05 = 2500
    margin_utilization = allocated_margin / maintenance_margin
    """
    row = (
        venue,
        symbol,
        Decimal(str(allocated_margin)),  # allocated_margin
        Decimal(str(leverage)),  # leverage
        margin_mode,  # margin_mode
        side,  # side
        Decimal(str(mark_price)),  # mark_price
        Decimal(str(quantity)),  # quantity
        Decimal(str(avg_entry_price)),  # avg_entry_price
    )
    return _make_result(fetchone=row)


def _empty_margin_tiers():
    """No margin tiers in cmc_margin_config -- forces conservative defaults."""
    return _make_result(fetchall=[])


def _buy_order_full_sequence(
    perp_position_mock=None,
    margin_tiers_mock=None,
    limits_row=None,
    log_events_count: int = 0,
) -> list:
    """
    Build the full mock side_effect list for a buy order that passes gates 1-4
    and reaches Gate 1.6.

    Gate 1.6 will execute:
        1. cmc_perp_positions SELECT
        2. (if position found) cmc_margin_config SELECT for tiers
        3. (if gate triggered) cmc_risk_events INSERT (log event)

    Args:
        perp_position_mock: result for cmc_perp_positions query (None = no position)
        margin_tiers_mock:  result for cmc_margin_config query (None = skip, only if position found)
        limits_row:         _default_limits_row() or custom
        log_events_count:   number of log event INSERTs expected
    """
    lim = limits_row or _default_limits_row()
    seq = [
        _active_state(),  # Gate 1: _is_halted
        _tail_risk_normal(),  # Gate 1.5: check_tail_risk_state
        _make_result(fetchall=lim),  # Gate 2: _load_limits (CB cooldown)
        _no_cb_tripped(),  # Gate 2: cb_breaker_tripped_at
        _make_result(fetchall=lim),  # Gate 3/4: _load_limits (caps)
        perp_position_mock or _no_perp_position(),  # Gate 1.6: cmc_perp_positions
    ]
    if margin_tiers_mock is not None:
        seq.append(margin_tiers_mock)
    for _ in range(log_events_count):
        seq.append(_log_event_result())
    return seq


# ---------------------------------------------------------------------------
# TestRiskLimitsNewFields
# ---------------------------------------------------------------------------


class TestRiskLimitsNewFields:
    """RiskLimits dataclass has the two new margin threshold fields."""

    def test_default_margin_alert_threshold(self):
        from ta_lab2.risk.risk_engine import RiskLimits

        limits = RiskLimits()
        assert limits.margin_alert_threshold == 1.5

    def test_default_liquidation_kill_threshold(self):
        from ta_lab2.risk.risk_engine import RiskLimits

        limits = RiskLimits()
        assert limits.liquidation_kill_threshold == 1.1

    def test_custom_margin_thresholds(self):
        from ta_lab2.risk.risk_engine import RiskLimits

        limits = RiskLimits(
            margin_alert_threshold=2.0,
            liquidation_kill_threshold=1.2,
        )
        assert limits.margin_alert_threshold == 2.0
        assert limits.liquidation_kill_threshold == 1.2

    def test_load_limits_reads_new_columns(self):
        """_load_limits() reads margin_alert_threshold and liquidation_kill_threshold from DB."""
        from ta_lab2.risk.risk_engine import RiskEngine

        engine, conn = _make_engine([_limits_result()])
        re = RiskEngine(engine)
        limits = re._load_limits()
        assert limits.margin_alert_threshold == 1.5
        assert limits.liquidation_kill_threshold == 1.1

    def test_load_limits_null_columns_use_defaults(self):
        """If margin threshold columns are NULL (older DB rows), _load_limits falls back to defaults."""
        from ta_lab2.risk.risk_engine import RiskEngine, RiskLimits

        # Row with NULL for columns 9 and 10
        null_row = [
            (
                Decimal("0.15"),
                Decimal("0.80"),
                Decimal("0.03"),
                3,
                Decimal("0.0"),
                Decimal("24.0"),
                True,
                None,
                None,
                None,  # margin_alert_threshold = NULL
                None,  # liquidation_kill_threshold = NULL
            )
        ]
        engine, conn = _make_engine([_make_result(fetchall=null_row)])
        re = RiskEngine(engine)
        limits = re._load_limits()

        _defaults = RiskLimits()
        assert limits.margin_alert_threshold == _defaults.margin_alert_threshold
        assert limits.liquidation_kill_threshold == _defaults.liquidation_kill_threshold


# ---------------------------------------------------------------------------
# TestMarginGateDirectMethod
# ---------------------------------------------------------------------------


class TestMarginGateDirectMethod:
    """Unit tests for _check_margin_gate() private method."""

    def _make_re_with_perp_position(
        self,
        allocated_margin: float,
        mark_price: float = 50000.0,
        quantity: float = 1.0,
        with_log_event: bool = True,
    ):
        """
        Build RiskEngine mock for _check_margin_gate tests.

        With default MM=5% (no tiers loaded):
            maintenance_margin = mark_price * quantity * 0.05 = 50000 * 1.0 * 0.05 = 2500
            margin_utilization = allocated_margin / 2500
        """
        from ta_lab2.risk.risk_engine import RiskEngine, RiskLimits

        side_effects = [
            _perp_position_row(
                allocated_margin=allocated_margin,
                mark_price=mark_price,
                quantity=quantity,
            ),
            _empty_margin_tiers(),  # cmc_margin_config returns no tiers
        ]
        if with_log_event:
            side_effects.append(_log_event_result())

        engine, conn = _make_engine(side_effects)
        re = RiskEngine(engine)
        limits = RiskLimits()
        return re, limits

    def test_sell_order_returns_none_immediately(self):
        """Sell orders bypass margin gate -- no DB query made."""
        from ta_lab2.risk.risk_engine import RiskEngine, RiskLimits

        engine, conn = _make_engine([])  # No DB calls expected
        re = RiskEngine(engine)
        limits = RiskLimits()

        result = re._check_margin_gate(
            asset_id=1,
            strategy_id=1,
            order_side="sell",
            limits=limits,
        )

        assert result is None
        assert conn.execute.call_count == 0

    def test_no_perp_position_returns_none(self):
        """When cmc_perp_positions has no active position, gate returns None (passes)."""
        from ta_lab2.risk.risk_engine import RiskEngine, RiskLimits

        engine, conn = _make_engine([_no_perp_position()])
        re = RiskEngine(engine)
        limits = RiskLimits()

        result = re._check_margin_gate(
            asset_id=1,
            strategy_id=1,
            order_side="buy",
            limits=limits,
        )

        assert result is None

    def test_margin_safe_3x_returns_none(self):
        """With 3.0x margin utilization (safe), gate returns None."""
        # allocated=7500, MM=2500 -> util = 7500/2500 = 3.0 > 2.0 (safe)
        re, limits = self._make_re_with_perp_position(
            allocated_margin=7500.0, with_log_event=False
        )
        result = re._check_margin_gate(
            asset_id=1, strategy_id=1, order_side="buy", limits=limits
        )
        assert result is None

    def test_margin_above_2x_buffer_returns_none(self):
        """With 2.1x margin utilization (above 2x buffer), gate returns None."""
        # allocated=5250, MM=2500 -> util = 5250/2500 = 2.1 > 2.0 (safe)
        re, limits = self._make_re_with_perp_position(
            allocated_margin=5250.0, with_log_event=False
        )
        result = re._check_margin_gate(
            asset_id=1, strategy_id=1, order_side="buy", limits=limits
        )
        assert result is None

    def test_margin_exactly_2x_buffer_blocks(self):
        """Margin exactly at 2.0x triggers buffer check (blocks order).

        Gate checks: util <= 2.0 -> buffer (1.1 < 1.5 < 2.0 is checked LAST).
        2.0 is NOT > 2.0, so buffer gate fires.
        """
        # allocated=5000, MM=2500 -> util = 5000/2500 = 2.0 <= 2.0 -> buffer
        re, limits = self._make_re_with_perp_position(
            allocated_margin=5000.0, with_log_event=True
        )
        result = re._check_margin_gate(
            asset_id=1, strategy_id=1, order_side="buy", limits=limits
        )
        assert result == "buffer"

    def test_margin_below_2x_buffer_blocks_with_buffer_reason(self):
        """1.8x margin utilization triggers buffer check -- blocks order."""
        # allocated=4500, MM=2500 -> util = 4500/2500 = 1.8
        # 1.1 < 1.5 < 1.8 <= 2.0 -> buffer
        re, limits = self._make_re_with_perp_position(
            allocated_margin=4500.0, with_log_event=True
        )
        result = re._check_margin_gate(
            asset_id=1, strategy_id=1, order_side="buy", limits=limits
        )
        assert result == "buffer"

    def test_margin_warning_1_4x_logs_but_does_not_block(self):
        """1.4x margin utilization triggers warning -- logs event but returns 'warning' (NOT blocking)."""
        # allocated=3500, MM=2500 -> util = 3500/2500 = 1.4
        # 1.1 < 1.4 <= 1.5 -> warning
        re, limits = self._make_re_with_perp_position(
            allocated_margin=3500.0, with_log_event=True
        )
        result = re._check_margin_gate(
            asset_id=1, strategy_id=1, order_side="buy", limits=limits
        )
        assert result == "warning"

    def test_margin_exactly_at_warning_threshold_logs_only(self):
        """1.5x margin utilization (exactly at threshold) triggers warning -- logs but does NOT block."""
        # allocated=3750, MM=2500 -> util = 3750/2500 = 1.5 <= 1.5 -> warning
        re, limits = self._make_re_with_perp_position(
            allocated_margin=3750.0, with_log_event=True
        )
        result = re._check_margin_gate(
            asset_id=1, strategy_id=1, order_side="buy", limits=limits
        )
        assert result == "warning"

    def test_margin_critical_1x_blocks_order(self):
        """1.0x margin utilization triggers critical -- blocks order."""
        # allocated=2500, MM=2500 -> util = 2500/2500 = 1.0 <= 1.1 -> critical
        re, limits = self._make_re_with_perp_position(
            allocated_margin=2500.0, with_log_event=True
        )
        result = re._check_margin_gate(
            asset_id=1, strategy_id=1, order_side="buy", limits=limits
        )
        assert result == "critical"

    def test_margin_exactly_at_critical_threshold_blocks(self):
        """1.1x margin utilization (exactly at threshold) triggers critical -- blocks order."""
        # allocated=2750, MM=2500 -> util = 2750/2500 = 1.1 <= 1.1 -> critical
        re, limits = self._make_re_with_perp_position(
            allocated_margin=2750.0, with_log_event=True
        )
        result = re._check_margin_gate(
            asset_id=1, strategy_id=1, order_side="buy", limits=limits
        )
        assert result == "critical"

    def test_no_margin_tiers_uses_fallback_defaults(self):
        """When cmc_margin_config has no tiers, conservative defaults (IM=10%, MM=5%) apply."""
        from ta_lab2.risk.risk_engine import RiskEngine, RiskLimits

        # No tiers -> MM=5% -> maintenance_margin = 50000 * 1.0 * 0.05 = 2500
        # allocated = 7500 -> util = 7500 / 2500 = 3.0 -> safe
        engine, conn = _make_engine(
            [
                _perp_position_row(allocated_margin=7500.0),
                _empty_margin_tiers(),
            ]
        )
        re = RiskEngine(engine)
        limits = RiskLimits()

        result = re._check_margin_gate(
            asset_id=1, strategy_id=1, order_side="buy", limits=limits
        )
        assert result is None


# ---------------------------------------------------------------------------
# TestMarginGateEventLogging
# ---------------------------------------------------------------------------


class TestMarginGateEventLogging:
    """Verify correct event types are logged for each margin gate result."""

    def _run_gate_and_capture_log(
        self, allocated_margin: float
    ) -> tuple[str | None, str | None]:
        """
        Run _check_margin_gate with given allocated_margin and capture logged event_type.

        Returns (gate_result, logged_event_type).
        """
        from ta_lab2.risk.risk_engine import RiskEngine, RiskLimits

        logged_events = []

        def _capture_log(event_type, trigger_source, reason, **kwargs):
            logged_events.append((event_type, trigger_source))

        engine, conn = _make_engine(
            [
                _perp_position_row(allocated_margin=allocated_margin),
                _empty_margin_tiers(),
                _log_event_result(),
            ]
        )
        re = RiskEngine(engine)
        re._log_event = _capture_log  # type: ignore[method-assign]
        limits = RiskLimits()

        result = re._check_margin_gate(
            asset_id=1, strategy_id=1, order_side="buy", limits=limits
        )
        event_type = logged_events[0][0] if logged_events else None
        return result, event_type

    def test_critical_logs_liquidation_critical_event(self):
        """Critical gate (<=1.1x) logs event_type='liquidation_critical'."""
        # util = 2750/2500 = 1.1 -> critical
        result, event_type = self._run_gate_and_capture_log(allocated_margin=2750.0)
        assert result == "critical"
        assert event_type == "liquidation_critical"

    def test_warning_logs_liquidation_warning_event(self):
        """Warning gate (<=1.5x, >1.1x) logs event_type='liquidation_warning'."""
        # util = 3500/2500 = 1.4 -> warning
        result, event_type = self._run_gate_and_capture_log(allocated_margin=3500.0)
        assert result == "warning"
        assert event_type == "liquidation_warning"

    def test_buffer_logs_margin_alert_event(self):
        """Buffer gate (<=2.0x, >1.5x) logs event_type='margin_alert'."""
        # util = 4500/2500 = 1.8 -> buffer
        result, event_type = self._run_gate_and_capture_log(allocated_margin=4500.0)
        assert result == "buffer"
        assert event_type == "margin_alert"

    def test_safe_logs_no_event(self):
        """Safe gate (>2.0x) logs no event."""
        from ta_lab2.risk.risk_engine import RiskEngine, RiskLimits

        logged_events = []

        def _capture_log(event_type, **kwargs):
            logged_events.append(event_type)

        engine, conn = _make_engine(
            [
                _perp_position_row(allocated_margin=7500.0),  # util = 3.0 -> safe
                _empty_margin_tiers(),
            ]
        )
        re = RiskEngine(engine)
        re._log_event = _capture_log  # type: ignore[method-assign]
        limits = RiskLimits()

        result = re._check_margin_gate(
            asset_id=1, strategy_id=1, order_side="buy", limits=limits
        )
        assert result is None
        assert not logged_events


# ---------------------------------------------------------------------------
# TestCheckOrderMarginGateIntegration
# ---------------------------------------------------------------------------


class TestCheckOrderMarginGateIntegration:
    """
    Verify that check_order() correctly integrates Gate 1.6 results:
    - "critical" -> RiskCheckResult(allowed=False)
    - "buffer"   -> RiskCheckResult(allowed=False)
    - "warning"  -> RiskCheckResult(allowed=True) -- warning does NOT block
    - None       -> RiskCheckResult(allowed=True) -- no perp position
    """

    def test_critical_produces_blocked_result(self):
        """Gate 1.6 'critical' result -> check_order returns allowed=False."""
        from ta_lab2.risk.risk_engine import RiskEngine

        # util = 2750/2500 = 1.1 -> critical
        seq = _buy_order_full_sequence(
            perp_position_mock=_perp_position_row(allocated_margin=2750.0),
            margin_tiers_mock=_empty_margin_tiers(),
            log_events_count=1,
        )
        engine, conn = _make_engine(seq)
        re = RiskEngine(engine)

        result = re.check_order(
            order_qty=Decimal("0.01"),
            order_side="buy",
            fill_price=Decimal("50000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("1000000"),
        )

        assert result.allowed is False
        assert "liquidation critical" in result.blocked_reason.lower()

    def test_buffer_produces_blocked_result(self):
        """Gate 1.6 'buffer' result -> check_order returns allowed=False."""
        from ta_lab2.risk.risk_engine import RiskEngine

        # util = 4500/2500 = 1.8 -> buffer
        seq = _buy_order_full_sequence(
            perp_position_mock=_perp_position_row(allocated_margin=4500.0),
            margin_tiers_mock=_empty_margin_tiers(),
            log_events_count=1,
        )
        engine, conn = _make_engine(seq)
        re = RiskEngine(engine)

        result = re.check_order(
            order_qty=Decimal("0.01"),
            order_side="buy",
            fill_price=Decimal("50000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("1000000"),
        )

        assert result.allowed is False
        assert "margin buffer" in result.blocked_reason.lower()

    def test_warning_produces_allowed_result(self):
        """Gate 1.6 'warning' result -> check_order returns allowed=True (warning does NOT block)."""
        from ta_lab2.risk.risk_engine import RiskEngine

        # util = 3500/2500 = 1.4 -> warning
        seq = _buy_order_full_sequence(
            perp_position_mock=_perp_position_row(allocated_margin=3500.0),
            margin_tiers_mock=_empty_margin_tiers(),
            log_events_count=1,
        )
        engine, conn = _make_engine(seq)
        re = RiskEngine(engine)

        result = re.check_order(
            order_qty=Decimal("0.01"),
            order_side="buy",
            fill_price=Decimal("50000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("1000000"),
        )

        assert result.allowed is True
        assert result.adjusted_quantity == Decimal("0.01")
        assert result.blocked_reason is None

    def test_no_perp_position_produces_allowed_result(self):
        """Gate 1.6 with no perp position -> check_order returns allowed=True."""
        from ta_lab2.risk.risk_engine import RiskEngine

        seq = _buy_order_full_sequence(
            perp_position_mock=_no_perp_position(),
        )
        engine, conn = _make_engine(seq)
        re = RiskEngine(engine)

        result = re.check_order(
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

    def test_sell_order_bypasses_margin_gate_entirely(self):
        """Sell orders do not trigger Gate 1.6 -- Gate 1.6 is inside the buy-only block."""
        from ta_lab2.risk.risk_engine import RiskEngine

        # Sell order sequence: active -> tail_risk -> limits(CB) -> cb -> limits(caps)
        # Gate 1.6 is inside 'if order_side.lower() == "buy"' -> skipped for sell
        engine, conn = _make_engine(
            [
                _active_state(),
                _tail_risk_normal(),
                _limits_result(),
                _no_cb_tripped(),
                _limits_result(),
                # No Gate 1.6 mock -- if it runs, StopIteration would fail the test
            ]
        )
        re = RiskEngine(engine)

        result = re.check_order(
            order_qty=Decimal("1.0"),
            order_side="sell",
            fill_price=Decimal("50000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("1000000"),
        )

        assert result.allowed is True

    def test_critical_blocked_reason_mentions_threshold(self):
        """Critical blocked reason mentions the kill threshold value."""
        from ta_lab2.risk.risk_engine import RiskEngine

        # util = 2500/2500 = 1.0 -> critical
        seq = _buy_order_full_sequence(
            perp_position_mock=_perp_position_row(allocated_margin=2500.0),
            margin_tiers_mock=_empty_margin_tiers(),
            log_events_count=1,
        )
        engine, conn = _make_engine(seq)
        re = RiskEngine(engine)

        result = re.check_order(
            order_qty=Decimal("0.01"),
            order_side="buy",
            fill_price=Decimal("50000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("1000000"),
        )

        assert result.allowed is False
        # Blocked reason must reference threshold
        assert "1.1" in result.blocked_reason

    def test_buffer_blocked_reason_mentions_2x(self):
        """Buffer blocked reason mentions the 2x maintenance margin requirement."""
        from ta_lab2.risk.risk_engine import RiskEngine

        # util = 1.8 -> buffer
        seq = _buy_order_full_sequence(
            perp_position_mock=_perp_position_row(allocated_margin=4500.0),
            margin_tiers_mock=_empty_margin_tiers(),
            log_events_count=1,
        )
        engine, conn = _make_engine(seq)
        re = RiskEngine(engine)

        result = re.check_order(
            order_qty=Decimal("0.01"),
            order_side="buy",
            fill_price=Decimal("50000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("1000000"),
        )

        assert result.allowed is False
        assert "2x" in result.blocked_reason


# ---------------------------------------------------------------------------
# TestMarginGateThresholdOrdering
# ---------------------------------------------------------------------------


class TestMarginGateThresholdOrdering:
    """
    Verify the most-severe-first check order:
        critical (<=1.1x) -> warning (<=1.5x) -> buffer (<=2.0x) -> safe (>2.0x)

    This prevents dead code -- a util of 1.0x must hit 'critical' first,
    not 'warning' or 'buffer'.
    """

    def _run(self, allocated_margin: float) -> Optional[str]:
        """Run _check_margin_gate and return the result string."""
        from ta_lab2.risk.risk_engine import RiskEngine, RiskLimits

        side_effects = [
            _perp_position_row(allocated_margin=allocated_margin),
            _empty_margin_tiers(),
        ]
        # Add log event mock if needed (critical/warning/buffer all log)
        if allocated_margin < 7500.0:  # util < 3.0 -> some gate fires
            side_effects.append(_log_event_result())

        engine, conn = _make_engine(side_effects)
        re = RiskEngine(engine)
        limits = RiskLimits()
        return re._check_margin_gate(
            asset_id=1, strategy_id=1, order_side="buy", limits=limits
        )

    def test_util_0_9x_returns_critical_not_warning_or_buffer(self):
        """0.9x util hits critical first (< 1.1 < 1.5 < 2.0)."""
        # allocated = 0.9 * 2500 = 2250
        result = self._run(allocated_margin=2250.0)
        assert result == "critical"

    def test_util_1_1x_returns_critical(self):
        """1.1x hits critical (<=1.1x)."""
        result = self._run(allocated_margin=2750.0)
        assert result == "critical"

    def test_util_1_2x_returns_warning(self):
        """1.2x hits warning (>1.1x, <=1.5x)."""
        result = self._run(allocated_margin=3000.0)
        assert result == "warning"

    def test_util_1_5x_returns_warning(self):
        """1.5x hits warning (<=1.5x)."""
        result = self._run(allocated_margin=3750.0)
        assert result == "warning"

    def test_util_1_6x_returns_buffer(self):
        """1.6x hits buffer (>1.5x, <=2.0x)."""
        result = self._run(allocated_margin=4000.0)
        assert result == "buffer"

    def test_util_2_0x_returns_buffer(self):
        """2.0x hits buffer (<=2.0x)."""
        result = self._run(allocated_margin=5000.0)
        assert result == "buffer"

    def test_util_2_1x_returns_none(self):
        """2.1x is safe (>2.0x), returns None."""
        result = self._run(allocated_margin=5250.0)
        assert result is None

    def test_util_3_0x_returns_none(self):
        """3.0x is safe (>2.0x), returns None."""
        result = self._run(allocated_margin=7500.0)
        assert result is None
