"""Fill price computation engine for paper trading simulation.

Supports three slippage modes:
- "zero"      : no slippage, fill at exact base price (backtest parity)
- "fixed"     : deterministic bps offset (base_bps applied uniformly)
- "lognormal" : volume-adaptive base bps * log-normal noise via seeded RNG

All prices use Decimal arithmetic for financial correctness.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

import numpy as np


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FillResult:
    """Result of a simulated fill."""

    fill_qty: Decimal
    fill_price: Decimal
    is_partial: bool


@dataclass
class FillSimulatorConfig:
    """Configuration for FillSimulator.

    Attributes:
        slippage_mode: One of "zero", "fixed", "lognormal".
        slippage_base_bps: Base slippage in basis points (1 bps = 0.01%).
        slippage_noise_sigma: Sigma for log-normal noise multiplier.
        volume_impact_factor: Scales effective bps with order size.
        order_fraction: Fraction of ADV the order represents (default 0.1%).
        rejection_rate: Probability [0, 1] that an order is rejected.
        partial_fill_rate: Probability [0, 1] that fill is partial.
        partial_fill_min_pct: Minimum fraction of order_qty filled when partial.
        execution_delay_bars: Number of bars to delay execution (informational).
        seed: RNG seed for reproducibility. None = non-deterministic.
    """

    slippage_mode: str = "zero"
    slippage_base_bps: float = 3.0
    slippage_noise_sigma: float = 0.5
    volume_impact_factor: float = 0.1
    order_fraction: float = 0.001
    rejection_rate: float = 0.0
    partial_fill_rate: float = 0.0
    partial_fill_min_pct: float = 0.3
    execution_delay_bars: int = 0
    seed: int | None = 42


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

_VALID_MODES = frozenset({"zero", "fixed", "lognormal"})

# Decimal precision: 8 decimal places (sufficient for crypto prices and BTC sats)
_QUANT = Decimal("0.00000001")


def _to_decimal(value: float) -> Decimal:
    """Convert float to Decimal via string to avoid IEEE 754 representation artifacts."""
    return Decimal(str(round(value, 8)))


class FillSimulator:
    """Simulates order fills with configurable slippage, rejection, and partial fills.

    All price computations use Decimal arithmetic. Intermediate slippage
    calculations use float (numpy) for performance, then convert to Decimal
    at the final step.

    Parameters
    ----------
    config:
        FillSimulatorConfig controlling slippage mode, rates, and RNG seed.
    """

    def __init__(self, config: FillSimulatorConfig) -> None:
        self._cfg = config
        self._rng: np.random.Generator = np.random.default_rng(config.seed)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_fill_price(self, base_price: Decimal, side: str) -> Decimal:
        """Compute the fill price after applying slippage.

        Parameters
        ----------
        base_price:
            Reference price (e.g., bar close or mid-quote) as Decimal.
        side:
            Order side: "buy" or "sell".

        Returns
        -------
        Decimal
            Fill price with slippage applied. Buy fills are adverse (higher);
            sell fills are adverse (lower).

        Raises
        ------
        ValueError
            If slippage_mode is not one of "zero", "fixed", "lognormal".
        """
        mode = self._cfg.slippage_mode
        if mode not in _VALID_MODES:
            raise ValueError(
                f"Unknown slippage_mode={mode!r}. Must be one of {sorted(_VALID_MODES)}."
            )

        if mode == "zero":
            return base_price

        if mode == "fixed":
            return self._apply_fixed_slippage(base_price, side)

        # mode == "lognormal"
        return self._apply_lognormal_slippage(base_price, side)

    def simulate_fill(
        self,
        order_qty: Decimal,
        base_price: Decimal,
        side: str,
    ) -> FillResult | None:
        """Simulate a complete order fill including rejection and partial fill logic.

        Parameters
        ----------
        order_qty:
            Requested order quantity (positive).
        base_price:
            Reference price for slippage computation.
        side:
            Order side: "buy" or "sell".

        Returns
        -------
        FillResult | None
            None when the order is rejected (simulated exchange rejection).
            FillResult with fill_qty, fill_price, and is_partial flag otherwise.
        """
        # Step 1: Rejection check
        if self._rng.random() < self._cfg.rejection_rate:
            return None

        # Step 2: Compute fill price with slippage
        fill_price = self.compute_fill_price(base_price, side)

        # Step 3: Partial fill check
        if self._rng.random() < self._cfg.partial_fill_rate:
            min_pct = self._cfg.partial_fill_min_pct
            # Random fraction in [min_pct, 1.0)
            fill_pct = min_pct + self._rng.random() * (1.0 - min_pct)
            fill_qty = self._round_qty(order_qty * Decimal(str(fill_pct)))
            # Clamp: never exceed order_qty, never go below floor
            floor = self._round_qty(order_qty * Decimal(str(min_pct)))
            fill_qty = max(floor, min(fill_qty, order_qty))
            return FillResult(fill_qty=fill_qty, fill_price=fill_price, is_partial=True)

        return FillResult(fill_qty=order_qty, fill_price=fill_price, is_partial=False)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_fixed_slippage(self, base_price: Decimal, side: str) -> Decimal:
        """Apply deterministic bps offset."""
        offset = float(base_price) * (self._cfg.slippage_base_bps / 10_000.0)
        if side == "buy":
            result = float(base_price) + offset
        else:
            result = float(base_price) - offset
        return _to_decimal(result)

    def _apply_lognormal_slippage(self, base_price: Decimal, side: str) -> Decimal:
        """Apply volume-adaptive log-normal slippage noise."""
        cfg = self._cfg
        # Effective bps = base_bps * (1 + volume_impact * order_fraction)
        effective_bps = cfg.slippage_base_bps * (
            1.0 + cfg.volume_impact_factor * cfg.order_fraction
        )
        # Log-normal noise: median = 1 (unbiased in expectation on log scale)
        noise = self._rng.lognormal(mean=0.0, sigma=cfg.slippage_noise_sigma)
        total_bps = effective_bps * noise
        offset = float(base_price) * (total_bps / 10_000.0)
        if side == "buy":
            result = float(base_price) + offset
        else:
            result = float(base_price) - offset
        return _to_decimal(result)

    @staticmethod
    def _round_qty(qty: Decimal) -> Decimal:
        """Round quantity to 8 decimal places using ROUND_HALF_UP."""
        return qty.quantize(_QUANT, rounding=ROUND_HALF_UP)
