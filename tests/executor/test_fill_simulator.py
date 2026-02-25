"""TDD test suite for FillSimulator — fill price computation and order simulation."""

from decimal import Decimal

import pytest

from ta_lab2.executor.fill_simulator import (
    FillResult,
    FillSimulator,
    FillSimulatorConfig,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sim(
    slippage_mode: str = "zero",
    slippage_base_bps: float = 3.0,
    slippage_noise_sigma: float = 0.5,
    rejection_rate: float = 0.0,
    partial_fill_rate: float = 0.0,
    partial_fill_min_pct: float = 0.3,
    seed: int | None = 42,
) -> FillSimulator:
    cfg = FillSimulatorConfig(
        slippage_mode=slippage_mode,
        slippage_base_bps=slippage_base_bps,
        slippage_noise_sigma=slippage_noise_sigma,
        rejection_rate=rejection_rate,
        partial_fill_rate=partial_fill_rate,
        partial_fill_min_pct=partial_fill_min_pct,
        seed=seed,
    )
    return FillSimulator(cfg)


PRICE = Decimal("50000.00")
QTY = Decimal("1.0")


# ---------------------------------------------------------------------------
# 1. Zero slippage mode
# ---------------------------------------------------------------------------


class TestZeroSlippage:
    def test_buy_returns_exact_base_price(self):
        sim = _make_sim(slippage_mode="zero")
        fill_price = sim.compute_fill_price(PRICE, side="buy")
        assert fill_price == PRICE, f"Expected {PRICE}, got {fill_price}"

    def test_sell_returns_exact_base_price(self):
        sim = _make_sim(slippage_mode="zero")
        fill_price = sim.compute_fill_price(PRICE, side="sell")
        assert fill_price == PRICE, f"Expected {PRICE}, got {fill_price}"

    def test_price_is_decimal_type(self):
        sim = _make_sim(slippage_mode="zero")
        fill_price = sim.compute_fill_price(PRICE, side="buy")
        assert isinstance(fill_price, Decimal), (
            f"Expected Decimal, got {type(fill_price)}"
        )


# ---------------------------------------------------------------------------
# 2. Fixed slippage mode
# ---------------------------------------------------------------------------


class TestFixedSlippage:
    def test_buy_3bps_on_50000(self):
        """50000 * 3/10000 = 15.0 -> 50000 + 15 = 50015"""
        sim = _make_sim(slippage_mode="fixed", slippage_base_bps=3.0)
        fill_price = sim.compute_fill_price(PRICE, side="buy")
        assert fill_price == Decimal("50015.0"), f"Got {fill_price}"

    def test_sell_3bps_on_50000(self):
        """50000 * 3/10000 = 15.0 -> 50000 - 15 = 49985"""
        sim = _make_sim(slippage_mode="fixed", slippage_base_bps=3.0)
        fill_price = sim.compute_fill_price(PRICE, side="sell")
        assert fill_price == Decimal("49985.0"), f"Got {fill_price}"

    def test_buy_is_adverse_higher(self):
        sim = _make_sim(slippage_mode="fixed", slippage_base_bps=3.0)
        fill_price = sim.compute_fill_price(PRICE, side="buy")
        assert fill_price > PRICE

    def test_sell_is_adverse_lower(self):
        sim = _make_sim(slippage_mode="fixed", slippage_base_bps=3.0)
        fill_price = sim.compute_fill_price(PRICE, side="sell")
        assert fill_price < PRICE

    def test_result_is_decimal(self):
        sim = _make_sim(slippage_mode="fixed", slippage_base_bps=3.0)
        result = sim.compute_fill_price(PRICE, side="buy")
        assert isinstance(result, Decimal)


# ---------------------------------------------------------------------------
# 3. Log-normal slippage mode
# ---------------------------------------------------------------------------


class TestLognormalSlippage:
    def test_buy_adverse_over_100_runs(self):
        """Over 100 draws, average fill should be ABOVE base_price for buys."""
        sim = _make_sim(
            slippage_mode="lognormal", slippage_base_bps=3.0, slippage_noise_sigma=0.5
        )
        fills = [sim.compute_fill_price(PRICE, side="buy") for _ in range(100)]
        avg = sum(fills) / len(fills)
        assert avg > PRICE, f"Expected avg > {PRICE}, got {avg}"

    def test_sell_adverse_over_100_runs(self):
        """Over 100 draws, average fill should be BELOW base_price for sells."""
        sim = _make_sim(
            slippage_mode="lognormal", slippage_base_bps=3.0, slippage_noise_sigma=0.5
        )
        fills = [sim.compute_fill_price(PRICE, side="sell") for _ in range(100)]
        avg = sum(fills) / len(fills)
        assert avg < PRICE, f"Expected avg < {PRICE}, got {avg}"

    def test_all_prices_are_decimal(self):
        sim = _make_sim(slippage_mode="lognormal")
        for _ in range(10):
            result = sim.compute_fill_price(PRICE, side="buy")
            assert isinstance(result, Decimal), f"Got {type(result)}"

    def test_seeded_rng_is_reproducible(self):
        """Two simulators with same seed produce identical price sequences."""
        sim_a = _make_sim(slippage_mode="lognormal", seed=42)
        sim_b = _make_sim(slippage_mode="lognormal", seed=42)
        prices_a = [sim_a.compute_fill_price(PRICE, side="buy") for _ in range(20)]
        prices_b = [sim_b.compute_fill_price(PRICE, side="buy") for _ in range(20)]
        assert prices_a == prices_b, "Same seed must produce identical sequence"

    def test_different_seeds_differ(self):
        """Two simulators with different seeds should (almost certainly) produce different prices."""
        sim_a = _make_sim(slippage_mode="lognormal", seed=1)
        sim_b = _make_sim(slippage_mode="lognormal", seed=999)
        prices_a = [sim_a.compute_fill_price(PRICE, side="buy") for _ in range(20)]
        prices_b = [sim_b.compute_fill_price(PRICE, side="buy") for _ in range(20)]
        assert prices_a != prices_b, (
            "Different seeds should produce different sequences"
        )


# ---------------------------------------------------------------------------
# 4. simulate_fill — rejection
# ---------------------------------------------------------------------------


class TestSimulateFillRejection:
    def test_rejection_rate_1_always_none(self):
        sim = _make_sim(slippage_mode="zero", rejection_rate=1.0)
        for _ in range(20):
            result = sim.simulate_fill(QTY, PRICE, side="buy")
            assert result is None, "rejection_rate=1.0 must always return None"

    def test_rejection_rate_0_never_none(self):
        sim = _make_sim(slippage_mode="zero", rejection_rate=0.0)
        for _ in range(20):
            result = sim.simulate_fill(QTY, PRICE, side="buy")
            assert result is not None, "rejection_rate=0.0 must never return None"

    def test_rejection_returns_none_not_false(self):
        sim = _make_sim(slippage_mode="zero", rejection_rate=1.0)
        result = sim.simulate_fill(QTY, PRICE, side="buy")
        assert result is None


# ---------------------------------------------------------------------------
# 5. simulate_fill — full fill
# ---------------------------------------------------------------------------


class TestSimulateFillFull:
    def test_full_fill_qty_equals_order_qty(self):
        sim = _make_sim(slippage_mode="zero", partial_fill_rate=0.0)
        result = sim.simulate_fill(QTY, PRICE, side="buy")
        assert result is not None
        assert result.fill_qty == QTY

    def test_full_fill_is_partial_false(self):
        sim = _make_sim(slippage_mode="zero", partial_fill_rate=0.0)
        result = sim.simulate_fill(QTY, PRICE, side="buy")
        assert result is not None
        assert result.is_partial is False

    def test_full_fill_price_zero_slippage(self):
        sim = _make_sim(slippage_mode="zero")
        result = sim.simulate_fill(QTY, PRICE, side="buy")
        assert result is not None
        assert result.fill_price == PRICE

    def test_fillresult_types(self):
        sim = _make_sim(slippage_mode="zero")
        result = sim.simulate_fill(QTY, PRICE, side="buy")
        assert result is not None
        assert isinstance(result.fill_qty, Decimal)
        assert isinstance(result.fill_price, Decimal)
        assert isinstance(result.is_partial, bool)


# ---------------------------------------------------------------------------
# 6. simulate_fill — partial fills
# ---------------------------------------------------------------------------


class TestSimulateFillPartial:
    def test_partial_fill_qty_less_than_order(self):
        sim = _make_sim(slippage_mode="zero", partial_fill_rate=1.0)
        result = sim.simulate_fill(QTY, PRICE, side="buy")
        assert result is not None
        assert result.fill_qty < QTY, (
            f"Expected partial qty < {QTY}, got {result.fill_qty}"
        )

    def test_partial_fill_is_partial_true(self):
        sim = _make_sim(slippage_mode="zero", partial_fill_rate=1.0)
        result = sim.simulate_fill(QTY, PRICE, side="buy")
        assert result is not None
        assert result.is_partial is True

    def test_partial_fill_minimum_30_pct(self):
        """fill_qty must be >= 0.3 * order_qty (default partial_fill_min_pct=0.3)"""
        sim = _make_sim(
            slippage_mode="zero", partial_fill_rate=1.0, partial_fill_min_pct=0.3
        )
        order_qty = Decimal("100.0")
        for _ in range(30):
            result = sim.simulate_fill(order_qty, PRICE, side="buy")
            assert result is not None
            assert result.fill_qty >= Decimal("0.3") * order_qty, (
                f"fill_qty={result.fill_qty} < 30% of {order_qty}"
            )

    def test_partial_fill_never_exceeds_order_qty(self):
        sim = _make_sim(slippage_mode="zero", partial_fill_rate=1.0)
        order_qty = Decimal("100.0")
        for _ in range(30):
            result = sim.simulate_fill(order_qty, PRICE, side="buy")
            assert result is not None
            assert result.fill_qty <= order_qty

    def test_partial_fill_qty_is_decimal(self):
        sim = _make_sim(slippage_mode="zero", partial_fill_rate=1.0)
        result = sim.simulate_fill(QTY, PRICE, side="buy")
        assert result is not None
        assert isinstance(result.fill_qty, Decimal)


# ---------------------------------------------------------------------------
# 7. FillResult dataclass fields
# ---------------------------------------------------------------------------


class TestFillResultDataclass:
    def test_fillresult_has_fill_qty(self):
        result = FillResult(
            fill_qty=Decimal("1.0"), fill_price=Decimal("50000"), is_partial=False
        )
        assert result.fill_qty == Decimal("1.0")

    def test_fillresult_has_fill_price(self):
        result = FillResult(
            fill_qty=Decimal("1.0"), fill_price=Decimal("50000"), is_partial=False
        )
        assert result.fill_price == Decimal("50000")

    def test_fillresult_has_is_partial(self):
        result = FillResult(
            fill_qty=Decimal("1.0"), fill_price=Decimal("50000"), is_partial=False
        )
        assert result.is_partial is False


# ---------------------------------------------------------------------------
# 8. FillSimulatorConfig defaults
# ---------------------------------------------------------------------------


class TestFillSimulatorConfigDefaults:
    def test_default_slippage_mode_zero(self):
        cfg = FillSimulatorConfig()
        assert cfg.slippage_mode == "zero"

    def test_default_slippage_base_bps(self):
        cfg = FillSimulatorConfig()
        assert cfg.slippage_base_bps == 3.0

    def test_default_rejection_rate(self):
        cfg = FillSimulatorConfig()
        assert cfg.rejection_rate == 0.0

    def test_default_partial_fill_rate(self):
        cfg = FillSimulatorConfig()
        assert cfg.partial_fill_rate == 0.0

    def test_default_seed(self):
        cfg = FillSimulatorConfig()
        assert cfg.seed == 42

    def test_default_partial_fill_min_pct(self):
        cfg = FillSimulatorConfig()
        assert cfg.partial_fill_min_pct == 0.3


# ---------------------------------------------------------------------------
# 9. Invalid slippage mode
# ---------------------------------------------------------------------------


class TestInvalidMode:
    def test_unknown_slippage_mode_raises(self):
        sim = _make_sim(slippage_mode="bad_mode")
        with pytest.raises((ValueError, KeyError, NotImplementedError)):
            sim.compute_fill_price(PRICE, side="buy")
