"""
Unit tests for PositionSizer, compute_target_position, compute_order_delta, and ExecutorConfig.

All tests are pure arithmetic — no database required.
All quantity assertions use Decimal for precision.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from ta_lab2.executor.position_sizer import (
    ExecutorConfig,
    PositionSizer,
    REGIME_MULTIPLIERS,
    compute_order_delta,
    compute_target_position,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_config(
    sizing_mode: str = "fixed_fraction",
    position_fraction: float = 0.10,
    max_position_fraction: float = 0.50,
) -> ExecutorConfig:
    """Build a minimal ExecutorConfig for testing."""
    return ExecutorConfig(
        config_id=1,
        config_name="test-config",
        signal_type="ema_crossover",
        signal_id=1,
        exchange="paper",
        sizing_mode=sizing_mode,
        position_fraction=position_fraction,
        max_position_fraction=max_position_fraction,
        fill_price_mode="bar_close",
        cadence_hours=26.0,
        last_processed_signal_ts=None,
        initial_capital=Decimal("100000"),
    )


def _long_signal(position_state: str = "open") -> dict:
    return {
        "id": 1,
        "ts": datetime(2026, 2, 25, tzinfo=timezone.utc),
        "direction": "long",
        "position_state": position_state,
    }


def _short_signal(position_state: str = "open") -> dict:
    return {
        "id": 1,
        "ts": datetime(2026, 2, 25, tzinfo=timezone.utc),
        "direction": "short",
        "position_state": position_state,
    }


# portfolio=100,000; price=50,000; fraction=0.10 -> qty = 100000*0.10/50000 = 0.2
PORTFOLIO = Decimal("100000")
PRICE = Decimal("50000")
EXPECTED_BASE_QTY = Decimal("0.2")


# ---------------------------------------------------------------------------
# Test 1: fixed_fraction long
# ---------------------------------------------------------------------------


def test_fixed_fraction_long():
    """portfolio=100000, price=50000, fraction=0.10 -> qty=0.2 BTC (long)."""
    config = _base_config(sizing_mode="fixed_fraction", position_fraction=0.10)
    signal = _long_signal()

    qty = PositionSizer.compute_target_position(
        latest_signal=signal,
        portfolio_value=PORTFOLIO,
        current_price=PRICE,
        config=config,
    )

    assert qty == EXPECTED_BASE_QTY


# ---------------------------------------------------------------------------
# Test 2: fixed_fraction short
# ---------------------------------------------------------------------------


def test_fixed_fraction_short():
    """Short direction returns negative quantity."""
    config = _base_config(sizing_mode="fixed_fraction", position_fraction=0.10)
    signal = _short_signal()

    qty = PositionSizer.compute_target_position(
        latest_signal=signal,
        portfolio_value=PORTFOLIO,
        current_price=PRICE,
        config=config,
    )

    assert qty == -EXPECTED_BASE_QTY


# ---------------------------------------------------------------------------
# Test 3: closed signal returns zero
# ---------------------------------------------------------------------------


def test_closed_signal_returns_zero():
    """position_state='closed' -> target quantity is 0."""
    config = _base_config()
    signal = _long_signal(position_state="closed")

    qty = PositionSizer.compute_target_position(
        latest_signal=signal,
        portfolio_value=PORTFOLIO,
        current_price=PRICE,
        config=config,
    )

    assert qty == Decimal("0")


# ---------------------------------------------------------------------------
# Test 4: no signal returns zero
# ---------------------------------------------------------------------------


def test_no_signal_returns_zero():
    """latest_signal=None -> target quantity is 0."""
    config = _base_config()

    qty = PositionSizer.compute_target_position(
        latest_signal=None,
        portfolio_value=PORTFOLIO,
        current_price=PRICE,
        config=config,
    )

    assert qty == Decimal("0")


# ---------------------------------------------------------------------------
# Test 5: regime_adjusted bull_low_vol (multiplier=1.0)
# ---------------------------------------------------------------------------


def test_regime_adjusted_bull_low_vol():
    """Regime bull_low_vol has multiplier 1.0 -> same as fixed fraction."""
    config = _base_config(sizing_mode="regime_adjusted", position_fraction=0.10)
    signal = _long_signal()

    qty = PositionSizer.compute_target_position(
        latest_signal=signal,
        portfolio_value=PORTFOLIO,
        current_price=PRICE,
        config=config,
        regime_label="bull_low_vol",
    )

    # 100000 * (0.10 * 1.0) / 50000 = 0.2
    assert qty == EXPECTED_BASE_QTY


# ---------------------------------------------------------------------------
# Test 6: regime_adjusted bear_high_vol (multiplier=0.0)
# ---------------------------------------------------------------------------


def test_regime_adjusted_bear_high_vol():
    """Regime bear_high_vol has multiplier 0.0 -> target quantity is 0."""
    config = _base_config(sizing_mode="regime_adjusted", position_fraction=0.10)
    signal = _long_signal()

    qty = PositionSizer.compute_target_position(
        latest_signal=signal,
        portfolio_value=PORTFOLIO,
        current_price=PRICE,
        config=config,
        regime_label="bear_high_vol",
    )

    assert qty == Decimal("0")


# ---------------------------------------------------------------------------
# Test 7: regime_adjusted ranging (multiplier=0.5)
# ---------------------------------------------------------------------------


def test_regime_adjusted_ranging():
    """Regime ranging has multiplier 0.5 -> half of fixed fraction qty."""
    config = _base_config(sizing_mode="regime_adjusted", position_fraction=0.10)
    signal = _long_signal()

    qty = PositionSizer.compute_target_position(
        latest_signal=signal,
        portfolio_value=PORTFOLIO,
        current_price=PRICE,
        config=config,
        regime_label="ranging",
    )

    # 100000 * (0.10 * 0.5) / 50000 = 0.1
    assert qty == EXPECTED_BASE_QTY * Decimal("0.5")


# ---------------------------------------------------------------------------
# Test 8: regime_adjusted unknown regime defaults to 1.0
# ---------------------------------------------------------------------------


def test_regime_adjusted_unknown_regime():
    """Unknown regime label defaults to multiplier 1.0 (same as fixed fraction)."""
    config = _base_config(sizing_mode="regime_adjusted", position_fraction=0.10)
    signal = _long_signal()

    qty = PositionSizer.compute_target_position(
        latest_signal=signal,
        portfolio_value=PORTFOLIO,
        current_price=PRICE,
        config=config,
        regime_label="sideways_mystery_regime",
    )

    assert qty == EXPECTED_BASE_QTY


# ---------------------------------------------------------------------------
# Test 9: signal_strength full confidence (1.0) -> same as fixed
# ---------------------------------------------------------------------------


def test_signal_strength_full():
    """Signal confidence 1.0 -> no reduction, same as fixed fraction."""
    config = _base_config(sizing_mode="signal_strength", position_fraction=0.10)
    signal = _long_signal()

    qty = PositionSizer.compute_target_position(
        latest_signal=signal,
        portfolio_value=PORTFOLIO,
        current_price=PRICE,
        config=config,
        signal_confidence=1.0,
    )

    assert qty == EXPECTED_BASE_QTY


# ---------------------------------------------------------------------------
# Test 10: signal_strength half confidence (0.5) -> half qty
# ---------------------------------------------------------------------------


def test_signal_strength_half():
    """Signal confidence 0.5 -> half of base qty."""
    config = _base_config(sizing_mode="signal_strength", position_fraction=0.10)
    signal = _long_signal()

    qty = PositionSizer.compute_target_position(
        latest_signal=signal,
        portfolio_value=PORTFOLIO,
        current_price=PRICE,
        config=config,
        signal_confidence=0.5,
    )

    # 100000 * (0.10 * 0.5) / 50000 = 0.1
    assert qty == EXPECTED_BASE_QTY * Decimal("0.5")


# ---------------------------------------------------------------------------
# Test 11: signal_strength minimum 10% floor
# ---------------------------------------------------------------------------


def test_signal_strength_minimum_10pct():
    """Confidence below 10% is clamped to 10% floor."""
    config = _base_config(sizing_mode="signal_strength", position_fraction=0.10)
    signal = _long_signal()

    qty = PositionSizer.compute_target_position(
        latest_signal=signal,
        portfolio_value=PORTFOLIO,
        current_price=PRICE,
        config=config,
        signal_confidence=0.01,  # should be clamped to 0.10
    )

    # 100000 * (0.10 * 0.10) / 50000 = 0.02
    expected = PORTFOLIO * Decimal("0.10") * Decimal("0.10") / PRICE
    assert qty == expected


# ---------------------------------------------------------------------------
# Test 12: max fraction cap
# ---------------------------------------------------------------------------


def test_max_fraction_cap():
    """Effective fraction is capped at max_position_fraction."""
    # fraction=0.50 but max=0.20
    config = _base_config(
        sizing_mode="fixed_fraction",
        position_fraction=0.50,
        max_position_fraction=0.20,
    )
    signal = _long_signal()

    qty = PositionSizer.compute_target_position(
        latest_signal=signal,
        portfolio_value=PORTFOLIO,
        current_price=PRICE,
        config=config,
    )

    # Should be capped: 100000 * 0.20 / 50000 = 0.4
    expected = PORTFOLIO * Decimal("0.20") / PRICE
    assert qty == expected


# ---------------------------------------------------------------------------
# Test 13: compute_order_delta buy (current=0, target=0.2)
# ---------------------------------------------------------------------------


def test_compute_order_delta_buy():
    """No position -> buy to reach target."""
    delta = PositionSizer.compute_order_delta(
        current_qty=Decimal("0"),
        target_qty=Decimal("0.2"),
    )
    assert delta == Decimal("0.2")


# ---------------------------------------------------------------------------
# Test 14: compute_order_delta sell (current=0.2, target=0)
# ---------------------------------------------------------------------------


def test_compute_order_delta_sell():
    """Full position -> sell to close."""
    delta = PositionSizer.compute_order_delta(
        current_qty=Decimal("0.2"),
        target_qty=Decimal("0"),
    )
    assert delta == Decimal("-0.2")


# ---------------------------------------------------------------------------
# Test 15: compute_order_delta rebalance (current=0.18, target=0.20)
# ---------------------------------------------------------------------------


def test_compute_order_delta_rebalance():
    """Partial position -> buy small delta to rebalance."""
    delta = PositionSizer.compute_order_delta(
        current_qty=Decimal("0.18"),
        target_qty=Decimal("0.20"),
    )
    assert delta == Decimal("0.02")


# ---------------------------------------------------------------------------
# Additional: module-level convenience wrappers delegate correctly
# ---------------------------------------------------------------------------


def test_module_level_compute_target_position():
    """Module-level compute_target_position delegates to PositionSizer."""
    config = _base_config()
    signal = _long_signal()

    qty = compute_target_position(
        latest_signal=signal,
        portfolio_value=PORTFOLIO,
        current_price=PRICE,
        config=config,
    )
    assert qty == EXPECTED_BASE_QTY


def test_module_level_compute_order_delta():
    """Module-level compute_order_delta delegates to PositionSizer."""
    delta = compute_order_delta(Decimal("0.1"), Decimal("0.3"))
    assert delta == Decimal("0.2")


# ---------------------------------------------------------------------------
# REGIME_MULTIPLIERS sanity check
# ---------------------------------------------------------------------------


def test_regime_multipliers_keys():
    """REGIME_MULTIPLIERS contains expected regime keys."""
    expected_keys = {
        "bull_low_vol",
        "bull_high_vol",
        "ranging",
        "bear_low_vol",
        "bear_high_vol",
    }
    assert set(REGIME_MULTIPLIERS.keys()) == expected_keys


def test_regime_multipliers_types():
    """All REGIME_MULTIPLIERS values are Decimal."""
    for key, value in REGIME_MULTIPLIERS.items():
        assert isinstance(value, Decimal), (
            f"Expected Decimal for key '{key}', got {type(value)}"
        )
