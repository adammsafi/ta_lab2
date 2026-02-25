"""
Tests for margin_monitor.py

All tests use Decimal for precision and do NOT require a database connection.
DB-dependent load_margin_tiers is tested via mock engine.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock


from ta_lab2.risk.margin_monitor import (
    MarginState,
    MarginTier,
    compute_cross_margin_utilization,
    compute_margin_utilization,
    load_margin_tiers,
    _select_tier,
    _estimate_liquidation_price,
    _to_decimal,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _binance_btc_tier1() -> MarginTier:
    """Binance BTC Tier 1: 0-50K notional, IM=0.8%, MM=0.4%, 125x max."""
    return MarginTier(
        notional_floor=Decimal("0"),
        notional_cap=Decimal("50000"),
        initial_margin_rate=Decimal("0.008"),
        maintenance_margin_rate=Decimal("0.004"),
        max_leverage=125,
    )


def _binance_btc_tier2() -> MarginTier:
    """Binance BTC Tier 2: 50K-250K notional, IM=1%, MM=0.5%, 100x max."""
    return MarginTier(
        notional_floor=Decimal("50000"),
        notional_cap=Decimal("250000"),
        initial_margin_rate=Decimal("0.01"),
        maintenance_margin_rate=Decimal("0.005"),
        max_leverage=100,
    )


def _binance_btc_tier3() -> MarginTier:
    """Binance BTC Tier 3: 250K+ notional, IM=2%, MM=1%, 50x max."""
    return MarginTier(
        notional_floor=Decimal("250000"),
        notional_cap=Decimal("inf"),
        initial_margin_rate=Decimal("0.02"),
        maintenance_margin_rate=Decimal("0.01"),
        max_leverage=50,
    )


def _standard_tiers() -> list[MarginTier]:
    return [_binance_btc_tier1(), _binance_btc_tier2(), _binance_btc_tier3()]


# ---------------------------------------------------------------------------
# MarginTier -- dataclass
# ---------------------------------------------------------------------------


class TestMarginTier:
    def test_applies_to_within_tier(self):
        tier = _binance_btc_tier1()
        assert tier.applies_to(Decimal("30000")) is True

    def test_applies_to_at_floor(self):
        tier = _binance_btc_tier1()
        assert tier.applies_to(Decimal("0")) is True

    def test_applies_to_at_cap_exclusive(self):
        """Cap is exclusive."""
        tier = _binance_btc_tier1()
        assert tier.applies_to(Decimal("50000")) is False

    def test_applies_to_infinite_cap(self):
        tier = _binance_btc_tier3()
        assert tier.applies_to(Decimal("10000000")) is True


# ---------------------------------------------------------------------------
# compute_margin_utilization -- core function
# ---------------------------------------------------------------------------


class TestComputeMarginUtilization:
    """Tests with Binance BTC Tier 1 (0-50K, IM=0.8%, MM=0.4%)."""

    def test_tier1_basic_computation(self):
        """30K notional, 3x leverage, 400 allocated -> verify margin fields."""
        tiers = _standard_tiers()
        state = compute_margin_utilization(
            position_value=Decimal("30000"),
            allocated_margin=Decimal("400"),
            leverage=Decimal("3"),
            tiers=tiers,
            margin_mode="isolated",
            venue="binance",
            symbol="BTC",
        )

        # IM = 30000 * 0.008 = 240
        assert state.initial_margin == Decimal("240")
        # MM = 30000 * 0.004 = 120
        assert state.maintenance_margin == Decimal("120")
        # utilization = 400 / 120 = 3.333...
        expected_util = Decimal("400") / Decimal("120")
        assert abs(state.margin_utilization - expected_util) < Decimal("0.0001")

    def test_tier_selection_30k_uses_tier1(self):
        """30K notional uses Tier 1 (MM=0.4%)."""
        tiers = _standard_tiers()
        state = compute_margin_utilization(
            position_value=Decimal("30000"),
            allocated_margin=Decimal("400"),
            leverage=Decimal("3"),
            tiers=tiers,
        )
        # MM rate = 0.4% -> MM = 30000 * 0.004 = 120
        assert state.maintenance_margin == Decimal("120")

    def test_tier_selection_100k_uses_tier2(self):
        """100K notional uses Tier 2 (MM=0.5%)."""
        tiers = _standard_tiers()
        state = compute_margin_utilization(
            position_value=Decimal("100000"),
            allocated_margin=Decimal("1000"),
            leverage=Decimal("5"),
            tiers=tiers,
        )
        # Tier 2: MM rate = 0.5% -> MM = 100000 * 0.005 = 500
        assert state.maintenance_margin == Decimal("500")

    def test_tier_selection_300k_uses_tier3(self):
        """300K notional uses Tier 3 (MM=1%)."""
        tiers = _standard_tiers()
        state = compute_margin_utilization(
            position_value=Decimal("300000"),
            allocated_margin=Decimal("5000"),
            leverage=Decimal("5"),
            tiers=tiers,
        )
        # Tier 3: MM rate = 1% -> MM = 300000 * 0.01 = 3000
        assert state.maintenance_margin == Decimal("3000")

    def test_warning_threshold_at_1_5(self):
        """margin_utilization == 1.5 -> is_liquidation_warning = True."""
        tiers = _standard_tiers()
        # MM = 30000 * 0.004 = 120; we want util = 1.5 -> allocated = 120 * 1.5 = 180
        state = compute_margin_utilization(
            position_value=Decimal("30000"),
            allocated_margin=Decimal("180"),
            leverage=Decimal("3"),
            tiers=tiers,
        )
        assert state.margin_utilization == Decimal("1.5")
        assert state.is_liquidation_warning is True
        assert state.is_liquidation_critical is False

    def test_critical_threshold_at_1_1(self):
        """margin_utilization == 1.1 -> is_liquidation_critical = True."""
        tiers = _standard_tiers()
        # MM = 120; util = 1.1 -> allocated = 120 * 1.1 = 132
        state = compute_margin_utilization(
            position_value=Decimal("30000"),
            allocated_margin=Decimal("132"),
            leverage=Decimal("3"),
            tiers=tiers,
        )
        assert state.margin_utilization == Decimal("1.1")
        assert state.is_liquidation_warning is True
        assert state.is_liquidation_critical is True

    def test_safe_margin_above_1_5(self):
        """margin_utilization = 3.0 -> both warning and critical are False."""
        tiers = _standard_tiers()
        # MM = 120; util = 3.0 -> allocated = 360
        state = compute_margin_utilization(
            position_value=Decimal("30000"),
            allocated_margin=Decimal("360"),
            leverage=Decimal("3"),
            tiers=tiers,
        )
        assert state.margin_utilization == Decimal("3")
        assert state.is_liquidation_warning is False
        assert state.is_liquidation_critical is False

    def test_warning_below_1_5_but_above_1_1(self):
        """1.1 < margin_utilization < 1.5 -> warning True, critical False."""
        tiers = _standard_tiers()
        # MM = 120; util = 1.3 -> allocated = 156
        state = compute_margin_utilization(
            position_value=Decimal("30000"),
            allocated_margin=Decimal("156"),
            leverage=Decimal("3"),
            tiers=tiers,
        )
        # util = 156/120 = 1.3
        assert state.margin_utilization == Decimal("1.3")
        assert state.is_liquidation_warning is True
        assert state.is_liquidation_critical is False

    def test_no_tiers_uses_conservative_defaults(self):
        """Empty tier list -> IM=10%, MM=5% defaults applied."""
        state = compute_margin_utilization(
            position_value=Decimal("10000"),
            allocated_margin=Decimal("600"),
            leverage=Decimal("10"),
            tiers=[],  # No tiers
        )
        # Default IM = 10% -> 1000; MM = 5% -> 500
        assert state.initial_margin == Decimal("1000")
        assert state.maintenance_margin == Decimal("500")
        # util = 600 / 500 = 1.2
        assert state.margin_utilization == Decimal("1.2")
        assert state.is_liquidation_warning is True  # 1.2 <= 1.5
        assert state.is_liquidation_critical is False  # 1.2 > 1.1

    def test_state_fields_populated(self):
        """Verify venue, symbol, mode, leverage fields are passed through."""
        tiers = _standard_tiers()
        state = compute_margin_utilization(
            position_value=Decimal("30000"),
            allocated_margin=Decimal("400"),
            leverage=Decimal("5"),
            tiers=tiers,
            margin_mode="isolated",
            venue="binance",
            symbol="BTC",
        )
        assert state.venue == "binance"
        assert state.symbol == "BTC"
        assert state.margin_mode == "isolated"
        assert state.leverage == Decimal("5")
        assert state.position_value == Decimal("30000")
        assert state.allocated_margin == Decimal("400")


# ---------------------------------------------------------------------------
# Liquidation price estimation
# ---------------------------------------------------------------------------


class TestLiquidationPriceEstimation:
    def test_long_liquidation_price_below_entry(self):
        """Long position: liquidation price is below entry price."""
        # entry=50000, leverage=10x, mm_rate=0.4%
        # liq = 50000 * (1 - 1/10 + 0.004) = 50000 * 0.904 = 45200
        liq = _estimate_liquidation_price(
            entry_price=Decimal("50000"),
            leverage=Decimal("10"),
            mm_rate=Decimal("0.004"),
            side="long",
        )
        assert liq == Decimal("50000") * (
            Decimal("1") - Decimal("1") / Decimal("10") + Decimal("0.004")
        )
        assert liq < Decimal("50000"), "Long liq price must be below entry"

    def test_short_liquidation_price_above_entry(self):
        """Short position: liquidation price is above entry price."""
        # entry=50000, leverage=10x, mm_rate=0.4%
        # liq = 50000 * (1 + 1/10 - 0.004) = 50000 * 1.096 = 54800
        liq = _estimate_liquidation_price(
            entry_price=Decimal("50000"),
            leverage=Decimal("10"),
            mm_rate=Decimal("0.004"),
            side="short",
        )
        assert liq > Decimal("50000"), "Short liq price must be above entry"

    def test_compute_margin_with_entry_price_isolated(self):
        """compute_margin_utilization populates liquidation_price for isolated mode."""
        tiers = _standard_tiers()
        state = compute_margin_utilization(
            position_value=Decimal("30000"),
            allocated_margin=Decimal("400"),
            leverage=Decimal("10"),
            tiers=tiers,
            margin_mode="isolated",
            side="long",
            entry_price=Decimal("50000"),
        )
        assert state.liquidation_price is not None
        assert state.liquidation_price < Decimal("50000")

    def test_compute_margin_without_entry_price_no_liq_price(self):
        """Without entry_price, liquidation_price is None."""
        tiers = _standard_tiers()
        state = compute_margin_utilization(
            position_value=Decimal("30000"),
            allocated_margin=Decimal("400"),
            leverage=Decimal("10"),
            tiers=tiers,
            margin_mode="isolated",
        )
        assert state.liquidation_price is None

    def test_compute_margin_cross_mode_no_liq_price(self):
        """Cross margin mode: liquidation_price is None even with entry_price."""
        tiers = _standard_tiers()
        state = compute_margin_utilization(
            position_value=Decimal("30000"),
            allocated_margin=Decimal("400"),
            leverage=Decimal("10"),
            tiers=tiers,
            margin_mode="cross",
            side="long",
            entry_price=Decimal("50000"),
        )
        # Cross mode -> no per-position liq price estimated
        assert state.liquidation_price is None

    def test_short_liquidation_price_formula(self):
        """Short liq formula: entry * (1 + 1/lev - mm_rate)."""
        liq = _estimate_liquidation_price(
            entry_price=Decimal("100"),
            leverage=Decimal("5"),
            mm_rate=Decimal("0.01"),
            side="short",
        )
        expected = Decimal("100") * (
            Decimal("1") + Decimal("1") / Decimal("5") - Decimal("0.01")
        )
        assert liq == expected


# ---------------------------------------------------------------------------
# Cross margin utilization
# ---------------------------------------------------------------------------


class TestCrossMarginUtilization:
    def _make_state(self, mm: Decimal) -> MarginState:
        """Return a MarginState with given maintenance_margin."""
        return MarginState(
            venue="binance",
            symbol="BTC",
            position_value=Decimal("10000"),
            leverage=Decimal("5"),
            margin_mode="cross",
            initial_margin=Decimal("80"),
            maintenance_margin=mm,
            margin_utilization=Decimal("2"),
            allocated_margin=Decimal("200"),
            liquidation_price=None,
            is_liquidation_warning=False,
            is_liquidation_critical=False,
        )

    def test_two_positions_cross_margin(self):
        """Two positions: wallet / sum(MM) correct."""
        pos1 = self._make_state(Decimal("100"))
        pos2 = self._make_state(Decimal("200"))
        wallet = Decimal("900")
        util = compute_cross_margin_utilization([pos1, pos2], wallet)
        # 900 / 300 = 3.0
        assert util == Decimal("3")

    def test_three_positions_with_fractions(self):
        """Three positions with fractional MMs."""
        p1 = self._make_state(Decimal("120"))
        p2 = self._make_state(Decimal("80"))
        p3 = self._make_state(Decimal("50"))
        wallet = Decimal("500")
        util = compute_cross_margin_utilization([p1, p2, p3], wallet)
        # 500 / 250 = 2.0
        assert util == Decimal("2")

    def test_no_positions_returns_infinity(self):
        """No positions -> returns Decimal('inf')."""
        util = compute_cross_margin_utilization([], Decimal("10000"))
        assert util == Decimal("inf")

    def test_below_one_means_liquidation_risk(self):
        """util < 1.0 -> wallet cannot cover maintenance margins."""
        pos = self._make_state(Decimal("1000"))
        wallet = Decimal("800")
        util = compute_cross_margin_utilization([pos], wallet)
        assert util < Decimal("1")


# ---------------------------------------------------------------------------
# load_margin_tiers -- mock DB tests
# ---------------------------------------------------------------------------


class TestLoadMarginTiers:
    def _make_mock_engine(self, rows):
        mock_engine = MagicMock()
        conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        conn.execute.return_value = mock_result
        return mock_engine

    def test_returns_list_of_margin_tiers(self):
        """Valid DB rows are converted to MarginTier objects."""
        rows = [
            (0, 50000, 0.008, 0.004, 125),
            (50000, 250000, 0.01, 0.005, 100),
        ]
        engine = self._make_mock_engine(rows)
        tiers = load_margin_tiers(engine, "binance", "BTC")

        assert len(tiers) == 2
        assert isinstance(tiers[0], MarginTier)
        assert tiers[0].notional_floor == Decimal("0")
        assert tiers[0].max_leverage == 125
        assert tiers[1].notional_floor == Decimal("50000")

    def test_empty_rows_returns_empty_list(self, caplog):
        """No DB rows -> empty list + WARNING logged."""
        engine = self._make_mock_engine([])

        import logging

        with caplog.at_level(logging.WARNING, logger="ta_lab2.risk.margin_monitor"):
            tiers = load_margin_tiers(engine, "binance", "BTC")

        assert tiers == []
        assert any("No margin tiers found" in r.message for r in caplog.records)

    def test_db_exception_returns_empty_list(self, caplog):
        """DB exception -> empty list + WARNING logged (no crash)."""
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = Exception("DB down")

        import logging

        with caplog.at_level(logging.WARNING, logger="ta_lab2.risk.margin_monitor"):
            tiers = load_margin_tiers(mock_engine, "binance", "BTC")

        assert tiers == []
        assert any("Failed to load margin tiers" in r.message for r in caplog.records)

    def test_decimal_precision_preserved(self):
        """DB float values converted via Decimal(str(round(float, 8)))."""
        rows = [(0, 50000, 0.00800000, 0.00400000, 125)]
        engine = self._make_mock_engine(rows)
        tiers = load_margin_tiers(engine, "binance", "BTC")

        assert len(tiers) == 1
        # Should be precise Decimal
        assert isinstance(tiers[0].initial_margin_rate, Decimal)
        assert isinstance(tiers[0].maintenance_margin_rate, Decimal)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


class TestPrivateHelpers:
    def test_select_tier_empty_returns_none(self):
        assert _select_tier(Decimal("10000"), []) is None

    def test_select_tier_tier1_selected_for_low_notional(self):
        tiers = _standard_tiers()
        tier = _select_tier(Decimal("30000"), tiers)
        assert tier is not None
        assert tier.max_leverage == 125  # Tier 1

    def test_select_tier_tier2_selected_for_mid_notional(self):
        tiers = _standard_tiers()
        tier = _select_tier(Decimal("100000"), tiers)
        assert tier is not None
        assert tier.max_leverage == 100  # Tier 2

    def test_select_tier_tier3_selected_for_high_notional(self):
        tiers = _standard_tiers()
        tier = _select_tier(Decimal("500000"), tiers)
        assert tier is not None
        assert tier.max_leverage == 50  # Tier 3

    def test_to_decimal_from_float(self):
        result = _to_decimal(0.008)
        assert isinstance(result, Decimal)

    def test_to_decimal_from_decimal(self):
        d = Decimal("0.008")
        result = _to_decimal(d)
        assert result == d

    def test_to_decimal_from_string(self):
        result = _to_decimal("0.004")
        assert result == Decimal("0.004")
