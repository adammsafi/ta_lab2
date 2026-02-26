"""
Integration tests for Phase 51 Perps Readiness components.

Verifies that FundingAdjuster, MarginMonitor, and RiskEngine Gate 1.6 work
together as a cohesive set of components for perpetual futures paper trading.

All tests use mocked DB and synthetic data -- no live database required.

Test classes:
    1. TestFullModuleImports         -- all Phase 51 symbols importable
    2. TestFundingToMarginFlow       -- compute funding -> reduces available margin
    3. TestMarginGateBlocksCritical  -- Gate 1.6 blocks at 1.05x util
    4. TestMarginGateAllowsWarning   -- Gate 1.6 logs but allows at 1.4x util
    5. TestMarginGateBlocksBuffer    -- Gate 1.6 blocks at 1.8x util (< 2x)
    6. TestFundingSignConvention     -- long/short sign convention is opposite
    7. TestPerpsPackageStructure     -- all Phase 51 modules importable
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pandas as pd


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(side_effects: list) -> tuple[MagicMock, MagicMock]:
    """Build a mock SQLAlchemy engine that sequences through side_effects."""
    engine = MagicMock()
    conn = MagicMock()
    conn.execute.side_effect = side_effects
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


def _make_result(fetchone=None, fetchall=None, rowcount=0) -> MagicMock:
    r = MagicMock()
    r.fetchone.return_value = fetchone
    r.fetchall.return_value = (
        fetchall if fetchall is not None else ([] if fetchone is None else [fetchone])
    )
    r.rowcount = rowcount
    return r


def _default_limits_row():
    """Full limits row including new Phase 51 margin threshold columns."""
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
            Decimal("1.5"),  # margin_alert_threshold
            Decimal("1.1"),  # liquidation_kill_threshold
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
    return _make_result(fetchone=None)


def _perp_position_row(
    allocated_margin: float,
    venue: str = "binance",
    symbol: str = "BTC",
    mark_price: float = 50000.0,
    quantity: float = 1.0,
    leverage: float = 10.0,
    side: str = "long",
    margin_mode: str = "isolated",
    avg_entry_price: float = 48000.0,
) -> MagicMock:
    """
    Simulate cmc_perp_positions row.

    With empty tiers (MM=5% default):
        maintenance_margin = mark_price * quantity * 0.05 = 50000 * 1.0 * 0.05 = 2500
        margin_utilization = allocated_margin / 2500
    """
    row = (
        venue,
        symbol,
        Decimal(str(allocated_margin)),
        Decimal(str(leverage)),
        margin_mode,
        side,
        Decimal(str(mark_price)),
        Decimal(str(quantity)),
        Decimal(str(avg_entry_price)),
    )
    return _make_result(fetchone=row)


def _empty_tiers():
    return _make_result(fetchall=[])


def _buy_order_full_sequence(
    perp_mock=None,
    tiers_mock=None,
    log_count: int = 0,
) -> list:
    """Build the full DB call sequence for a buy order reaching Gate 1.6."""
    seq = [
        _active_state(),
        _tail_risk_normal(),
        _limits_result(),
        _no_cb_tripped(),
        _limits_result(),
        perp_mock or _no_perp_position(),
    ]
    if tiers_mock is not None:
        seq.append(tiers_mock)
    for _ in range(log_count):
        seq.append(_log_event_result())
    return seq


# ---------------------------------------------------------------------------
# Test 1: TestFullModuleImports
# ---------------------------------------------------------------------------


class TestFullModuleImports:
    """All new Phase 51 symbols are importable from ta_lab2.risk and ta_lab2.backtests."""

    def test_margin_state_importable_from_risk(self):
        from ta_lab2.risk import MarginState

        assert MarginState is not None

    def test_margin_tier_importable_from_risk(self):
        from ta_lab2.risk import MarginTier

        assert MarginTier is not None

    def test_compute_margin_utilization_importable_from_risk(self):
        from ta_lab2.risk import compute_margin_utilization

        assert callable(compute_margin_utilization)

    def test_load_margin_tiers_importable_from_risk(self):
        from ta_lab2.risk import load_margin_tiers

        assert callable(load_margin_tiers)

    def test_compute_cross_margin_utilization_importable_from_risk(self):
        from ta_lab2.risk import compute_cross_margin_utilization

        assert callable(compute_cross_margin_utilization)

    def test_funding_adjuster_importable_from_backtests(self):
        from ta_lab2.backtests import FundingAdjuster

        assert FundingAdjuster is not None

    def test_funding_adjusted_result_importable_from_backtests(self):
        from ta_lab2.backtests import FundingAdjustedResult

        assert FundingAdjustedResult is not None

    def test_compute_funding_payments_importable_from_backtests(self):
        from ta_lab2.backtests import compute_funding_payments

        assert callable(compute_funding_payments)

    def test_all_margin_exports_in_risk_dunder_all(self):
        """Margin symbols are listed in ta_lab2.risk.__all__."""
        import ta_lab2.risk as risk_pkg

        for symbol in [
            "MarginTier",
            "MarginState",
            "compute_margin_utilization",
            "load_margin_tiers",
            "compute_cross_margin_utilization",
        ]:
            assert symbol in risk_pkg.__all__, (
                f"{symbol} missing from ta_lab2.risk.__all__"
            )

    def test_funding_exports_in_backtests_dunder_all(self):
        """Funding symbols are listed in ta_lab2.backtests.__all__."""
        import ta_lab2.backtests as bt_pkg

        for symbol in [
            "FundingAdjuster",
            "FundingAdjustedResult",
            "compute_funding_payments",
        ]:
            assert symbol in bt_pkg.__all__, (
                f"{symbol} missing from ta_lab2.backtests.__all__"
            )

    def test_existing_risk_exports_still_present(self):
        """Phase 46 symbols remain exportable after Phase 51 additions."""
        from ta_lab2.risk import KillSwitchStatus, OverrideManager, RiskEngine

        assert RiskEngine is not None
        assert KillSwitchStatus is not None
        assert OverrideManager is not None


# ---------------------------------------------------------------------------
# Test 2: TestFundingToMarginFlow
# ---------------------------------------------------------------------------


class TestFundingToMarginFlow:
    """
    Demonstrate funding payments reducing available margin over time.

    Scenario: long BTC position, positive funding rate (longs pay).
    Cumulative funding reduces equity, representing reduced available margin.
    """

    def test_positive_funding_reduces_long_equity(self):
        """Positive funding rate reduces long position equity over 30 bars."""
        from ta_lab2.backtests import compute_funding_payments

        idx = pd.date_range("2025-01-01", periods=30, freq="D")
        position_timeline = pd.Series([100_000.0] * 30, index=idx)
        funding_rates = pd.Series([0.0001] * 30, index=idx)  # 0.01% per day

        payments = compute_funding_payments(
            position_timeline=position_timeline,
            funding_rates=funding_rates,
            is_short=False,
        )

        # For longs with positive rate: payments are negative (outflow)
        assert (payments < 0).all(), (
            "Long position with positive rate should have negative payments"
        )
        assert abs(float(payments.sum())) > 0, "Cumulative funding should be non-zero"

    def test_negative_funding_benefits_long(self):
        """Negative funding rate (longs receive) produces positive payments."""
        from ta_lab2.backtests import compute_funding_payments

        idx = pd.date_range("2025-01-01", periods=10, freq="D")
        position_timeline = pd.Series([50_000.0] * 10, index=idx)
        funding_rates = pd.Series([-0.0002] * 10, index=idx)  # negative rate

        payments = compute_funding_payments(
            position_timeline=position_timeline,
            funding_rates=funding_rates,
            is_short=False,
        )

        assert (payments > 0).all(), (
            "Negative funding rate benefits longs (positive inflow)"
        )

    def test_funding_reduces_margin_state_utilization_concept(self):
        """
        Demonstrates the funding-to-margin link:
        cumulative funding paid reduces available equity, which in practice
        reduces the collateral available for margin.

        This is a conceptual flow test -- shows that after cumulative funding
        is paid out, a position's effective allocated margin is lower.
        """
        from ta_lab2.backtests import compute_funding_payments
        from ta_lab2.risk import compute_margin_utilization

        idx = pd.date_range("2025-01-01", periods=30, freq="D")
        position_value = Decimal("50000")  # 1 BTC at 50k

        # Initial allocated margin
        initial_allocated = Decimal("5000")

        # Simulate 30 days of 0.01% daily funding
        position_timeline = pd.Series([float(position_value)] * 30, index=idx)
        funding_rates = pd.Series([0.0001] * 30, index=idx)

        payments = compute_funding_payments(
            position_timeline=position_timeline,
            funding_rates=funding_rates,
            is_short=False,
        )

        cumulative_funding_paid = Decimal(str(abs(float(payments.sum()))))
        adjusted_margin = initial_allocated - cumulative_funding_paid

        # Margin utilization BEFORE funding payments
        state_before = compute_margin_utilization(
            position_value=position_value,
            allocated_margin=initial_allocated,
            leverage=Decimal("10"),
            tiers=[],
        )

        # Margin utilization AFTER funding payments (reduced collateral)
        state_after = compute_margin_utilization(
            position_value=position_value,
            allocated_margin=adjusted_margin,
            leverage=Decimal("10"),
            tiers=[],
        )

        # Funding payments reduce margin utilization (closer to liquidation)
        assert state_after.margin_utilization < state_before.margin_utilization, (
            "Cumulative funding should reduce margin utilization"
        )
        assert cumulative_funding_paid > Decimal("0"), "Should have paid some funding"


# ---------------------------------------------------------------------------
# Test 3: TestMarginGateBlocksCritical
# ---------------------------------------------------------------------------


class TestMarginGateBlocksCritical:
    """Gate 1.6 blocks buy orders when margin utilization is at or below 1.05x."""

    def test_critical_util_1_05x_blocks_buy(self):
        """At 1.05x utilization, Gate 1.6 blocks the buy order."""
        from ta_lab2.risk.risk_engine import RiskEngine

        # allocated = 2625, MM = 2500 -> util = 1.05 <= 1.1 -> critical
        seq = _buy_order_full_sequence(
            perp_mock=_perp_position_row(allocated_margin=2625.0),
            tiers_mock=_empty_tiers(),
            log_count=1,
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

    def test_critical_threshold_is_1_1x(self):
        """Exactly 1.1x utilization also triggers critical block."""
        from ta_lab2.risk.risk_engine import RiskEngine

        # allocated = 2750, MM = 2500 -> util = 1.1 -> critical
        seq = _buy_order_full_sequence(
            perp_mock=_perp_position_row(allocated_margin=2750.0),
            tiers_mock=_empty_tiers(),
            log_count=1,
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


# ---------------------------------------------------------------------------
# Test 4: TestMarginGateAllowsWarning
# ---------------------------------------------------------------------------


class TestMarginGateAllowsWarning:
    """Gate 1.6 logs warning but allows buy orders at 1.4x utilization."""

    def test_warning_util_1_4x_allows_order(self):
        """At 1.4x utilization, Gate 1.6 logs warning but allows the buy order."""
        from ta_lab2.risk.risk_engine import RiskEngine

        # allocated = 3500, MM = 2500 -> util = 1.4 -> warning (logs, does NOT block)
        seq = _buy_order_full_sequence(
            perp_mock=_perp_position_row(allocated_margin=3500.0),
            tiers_mock=_empty_tiers(),
            log_count=1,
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

        assert result.allowed is True, (
            "Warning does NOT block -- order should be allowed"
        )
        assert result.blocked_reason is None
        assert result.adjusted_quantity == Decimal("0.01")

    def test_warning_check_order_allowed_true_not_false(self):
        """The 'warning' gate result explicitly does NOT set allowed=False."""
        from ta_lab2.risk.risk_engine import RiskEngine

        # util = 1.4x -> warning
        seq = _buy_order_full_sequence(
            perp_mock=_perp_position_row(allocated_margin=3500.0),
            tiers_mock=_empty_tiers(),
            log_count=1,
        )
        engine, conn = _make_engine(seq)
        re = RiskEngine(engine)

        result = re.check_order(
            order_qty=Decimal("0.5"),
            order_side="buy",
            fill_price=Decimal("50000"),
            asset_id=1,
            strategy_id=1,
            current_position_value=Decimal("0"),
            portfolio_value=Decimal("1000000"),
        )

        # Critical assertion: warning produces allowed=True
        assert result.allowed is True
        assert result.blocked_reason is None


# ---------------------------------------------------------------------------
# Test 5: TestMarginGateBlocksBuffer
# ---------------------------------------------------------------------------


class TestMarginGateBlocksBuffer:
    """Gate 1.6 blocks buy orders when margin is below 2x maintenance (proactive buffer)."""

    def test_buffer_util_1_8x_blocks_order(self):
        """At 1.8x utilization (below 2x buffer), Gate 1.6 blocks buy order."""
        from ta_lab2.risk.risk_engine import RiskEngine

        # allocated = 4500, MM = 2500 -> util = 1.8 -> buffer (>1.5, <=2.0)
        seq = _buy_order_full_sequence(
            perp_mock=_perp_position_row(allocated_margin=4500.0),
            tiers_mock=_empty_tiers(),
            log_count=1,
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

    def test_buffer_blocked_reason_mentions_2x(self):
        """Buffer block reason mentions the 2x maintenance margin requirement."""
        from ta_lab2.risk.risk_engine import RiskEngine

        # util = 1.8 -> buffer
        seq = _buy_order_full_sequence(
            perp_mock=_perp_position_row(allocated_margin=4500.0),
            tiers_mock=_empty_tiers(),
            log_count=1,
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
# Test 6: TestFundingSignConvention
# ---------------------------------------------------------------------------


class TestFundingSignConvention:
    """Same funding rate applied to long and short produces opposite sign payments."""

    def test_long_positive_rate_is_negative_payment(self):
        """Long position paying positive rate has negative cash flow."""
        from ta_lab2.backtests import compute_funding_payments

        idx = pd.date_range("2025-01-01", periods=5, freq="D")
        position_timeline = pd.Series([10_000.0] * 5, index=idx)
        funding_rates = pd.Series([0.001] * 5, index=idx)  # positive rate

        payments = compute_funding_payments(
            position_timeline=position_timeline,
            funding_rates=funding_rates,
            is_short=False,  # long
        )

        assert (payments < 0).all(), (
            "Long pays positive rate -> negative payment (outflow)"
        )

    def test_short_positive_rate_is_positive_payment(self):
        """Short position receiving positive rate has positive cash flow."""
        from ta_lab2.backtests import compute_funding_payments

        idx = pd.date_range("2025-01-01", periods=5, freq="D")
        position_timeline = pd.Series([10_000.0] * 5, index=idx)
        funding_rates = pd.Series([0.001] * 5, index=idx)  # positive rate

        payments = compute_funding_payments(
            position_timeline=position_timeline,
            funding_rates=funding_rates,
            is_short=True,  # short
        )

        assert (payments > 0).all(), (
            "Short receives positive rate -> positive payment (inflow)"
        )

    def test_long_and_short_payments_are_exact_opposites(self):
        """Long payment = -Short payment for the same position and rate."""
        from ta_lab2.backtests import compute_funding_payments

        idx = pd.date_range("2025-01-01", periods=10, freq="D")
        position_timeline = pd.Series([25_000.0] * 10, index=idx)
        funding_rates = pd.Series([0.0005] * 10, index=idx)

        long_payments = compute_funding_payments(
            position_timeline=position_timeline,
            funding_rates=funding_rates,
            is_short=False,
        )
        short_payments = compute_funding_payments(
            position_timeline=position_timeline,
            funding_rates=funding_rates,
            is_short=True,
        )

        # Long and short payments must be exact opposites
        pd.testing.assert_series_equal(
            long_payments,
            -short_payments,
            check_names=False,
        )

    def test_long_positive_rate_short_negative_rate_same_side(self):
        """Negative rate: long receives, short pays (opposite convention)."""
        from ta_lab2.backtests import compute_funding_payments

        idx = pd.date_range("2025-01-01", periods=5, freq="D")
        position_timeline = pd.Series([10_000.0] * 5, index=idx)
        funding_rates = pd.Series([-0.001] * 5, index=idx)  # negative rate

        long_payments = compute_funding_payments(
            position_timeline=position_timeline,
            funding_rates=funding_rates,
            is_short=False,
        )
        short_payments = compute_funding_payments(
            position_timeline=position_timeline,
            funding_rates=funding_rates,
            is_short=True,
        )

        # Negative rate -> longs receive (positive), shorts pay (negative)
        assert (long_payments > 0).all(), (
            "Negative rate: long receives (positive inflow)"
        )
        assert (short_payments < 0).all(), (
            "Negative rate: short pays (negative outflow)"
        )


# ---------------------------------------------------------------------------
# Test 7: TestPerpsPackageStructure
# ---------------------------------------------------------------------------


class TestPerpsPackageStructure:
    """All Phase 51 modules are importable with correct structure."""

    def test_funding_fetchers_importable(self):
        from ta_lab2.scripts.perps import funding_fetchers

        assert funding_fetchers is not None

    def test_refresh_funding_rates_importable(self):
        from ta_lab2.scripts.perps import refresh_funding_rates

        assert refresh_funding_rates is not None

    def test_margin_monitor_importable(self):
        from ta_lab2.risk import margin_monitor

        assert margin_monitor is not None

    def test_backtests_funding_adjuster_importable(self):
        from ta_lab2.backtests import funding_adjuster

        assert funding_adjuster is not None

    def test_margin_monitor_exposes_core_symbols(self):
        """margin_monitor module exposes all documented public symbols."""
        from ta_lab2.risk.margin_monitor import (
            MarginState,
            MarginTier,
            compute_cross_margin_utilization,
            compute_margin_utilization,
            load_margin_tiers,
        )

        assert MarginTier is not None
        assert MarginState is not None
        assert callable(compute_margin_utilization)
        assert callable(load_margin_tiers)
        assert callable(compute_cross_margin_utilization)

    def test_funding_adjuster_exposes_core_symbols(self):
        """funding_adjuster module exposes all documented public symbols."""
        from ta_lab2.backtests.funding_adjuster import (
            FundingAdjustedResult,
            FundingAdjuster,
            compute_funding_payments,
        )

        assert FundingAdjuster is not None
        assert FundingAdjustedResult is not None
        assert callable(compute_funding_payments)

    def test_risk_engine_module_has_margin_gate_method(self):
        """RiskEngine has the _check_margin_gate method."""
        from ta_lab2.risk.risk_engine import RiskEngine

        assert hasattr(RiskEngine, "_check_margin_gate")
        assert callable(RiskEngine._check_margin_gate)

    def test_risk_limits_has_margin_fields(self):
        """RiskLimits has margin_alert_threshold and liquidation_kill_threshold fields."""
        from ta_lab2.risk.risk_engine import RiskLimits

        limits = RiskLimits()
        assert hasattr(limits, "margin_alert_threshold")
        assert hasattr(limits, "liquidation_kill_threshold")
        assert limits.margin_alert_threshold == 1.5
        assert limits.liquidation_kill_threshold == 1.1
