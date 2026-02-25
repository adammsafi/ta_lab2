"""
margin_monitor.py
=================

Margin model for perpetual futures position tracking.

Provides:
    - MarginTier:                 Venue-specific tiered margin rate config
    - MarginState:                Current margin state for a single position
    - compute_margin_utilization: Core margin computation with tiered rates
    - load_margin_tiers:          Load tiers from cmc_margin_config table
    - compute_cross_margin_utilization: Portfolio-level cross-margin ratio

Threshold semantics (from CONTEXT.md / dim_risk_limits defaults):
    - margin_utilization = allocated_margin / maintenance_margin
    - >= 1.5: safe (warning=False, critical=False)
    - <= 1.5: is_liquidation_warning = True
    - <= 1.1: is_liquidation_critical = True
    - <  1.0: liquidation

All monetary values use Python Decimal for precision (as per MEMORY.md pattern:
Decimal via str(round(float, 8))).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conservative defaults (used when no tier data is available)
# ---------------------------------------------------------------------------

_DEFAULT_IM_RATE = Decimal("0.10")  # 10% initial margin
_DEFAULT_MM_RATE = Decimal("0.05")  # 5% maintenance margin
_DEFAULT_MAX_LEVERAGE = 10


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class MarginTier:
    """
    Venue-specific tiered margin rate for a position notional bracket.

    Attributes
    ----------
    notional_floor:
        Minimum position notional (inclusive) for this tier.
    notional_cap:
        Maximum position notional (exclusive) for this tier.
        Use Decimal('inf') for the last (unbounded) tier.
    initial_margin_rate:
        Initial margin as a fraction of notional (e.g., 0.008 = 0.8%).
    maintenance_margin_rate:
        Maintenance margin as a fraction of notional (e.g., 0.004 = 0.4%).
    max_leverage:
        Maximum leverage allowed in this tier (e.g., 125).
    """

    notional_floor: Decimal
    notional_cap: Decimal
    initial_margin_rate: Decimal
    maintenance_margin_rate: Decimal
    max_leverage: int

    def applies_to(self, position_value: Decimal) -> bool:
        """Return True if position_value falls within this tier."""
        return self.notional_floor <= position_value < self.notional_cap


@dataclass
class MarginState:
    """
    Current margin state for a single perpetual futures position.

    Attributes
    ----------
    venue:
        Exchange venue (e.g. 'binance').
    symbol:
        Asset symbol (e.g. 'BTC').
    position_value:
        Mark-price * abs(quantity) in quote currency.
    leverage:
        Current leverage (1 to max_leverage for the applicable tier).
    margin_mode:
        'isolated' or 'cross'.
    initial_margin:
        Required initial margin = position_value * im_rate.
    maintenance_margin:
        Required maintenance margin = position_value * mm_rate.
    margin_utilization:
        allocated_margin / maintenance_margin.
        Higher = safer.  < 1.0 = liquidation triggered.
    allocated_margin:
        Collateral held for this position.
    liquidation_price:
        Estimated price at which position would be liquidated.
        None for cross-margin positions (not estimated here).
    is_liquidation_warning:
        True when margin_utilization <= 1.5 (approaching liquidation).
    is_liquidation_critical:
        True when margin_utilization <= 1.1 (critical buffer breach).
    """

    venue: str
    symbol: str
    position_value: Decimal
    leverage: Decimal
    margin_mode: str
    initial_margin: Decimal
    maintenance_margin: Decimal
    margin_utilization: Decimal
    allocated_margin: Decimal
    liquidation_price: Optional[Decimal]
    is_liquidation_warning: bool
    is_liquidation_critical: bool


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------


def compute_margin_utilization(
    position_value: Decimal,
    allocated_margin: Decimal,
    leverage: Decimal,
    tiers: List[MarginTier],
    margin_mode: str = "isolated",
    venue: str = "",
    symbol: str = "",
    side: str = "long",
    entry_price: Optional[Decimal] = None,
) -> MarginState:
    """
    Compute margin utilization for a perpetual futures position.

    Parameters
    ----------
    position_value:
        Absolute notional = mark_price * abs(quantity).
    allocated_margin:
        Collateral held for this position.
    leverage:
        Current leverage (Decimal).
    tiers:
        Ordered list of MarginTier objects (ascending by notional_floor).
        If empty, conservative defaults (IM=10%, MM=5%) are used.
    margin_mode:
        'isolated' or 'cross'.
    venue:
        Exchange venue string (for MarginState output).
    symbol:
        Asset symbol string (for MarginState output).
    side:
        'long' or 'short' -- used for liquidation price estimation.
    entry_price:
        Entry price for liquidation price estimation.
        If None, liquidation_price will be None.

    Returns
    -------
    MarginState
        Fully populated margin state.
    """
    # --- Select applicable tier ---
    tier = _select_tier(position_value, tiers)

    if tier is not None:
        im_rate = tier.initial_margin_rate
        mm_rate = tier.maintenance_margin_rate
    else:
        # No tiers available -- use conservative defaults
        im_rate = _DEFAULT_IM_RATE
        mm_rate = _DEFAULT_MM_RATE
        logger.debug(
            "No margin tiers found for venue=%s symbol=%s; using defaults IM=%s MM=%s",
            venue,
            symbol,
            im_rate,
            mm_rate,
        )

    initial_margin = position_value * im_rate
    maintenance_margin = position_value * mm_rate

    # Avoid division by zero
    if maintenance_margin == Decimal("0"):
        margin_utilization = Decimal("0")
    else:
        margin_utilization = allocated_margin / maintenance_margin

    is_warning = margin_utilization <= Decimal("1.5")
    is_critical = margin_utilization <= Decimal("1.1")

    # Liquidation price estimation (isolated mode only)
    liq_price: Optional[Decimal] = None
    if (
        entry_price is not None
        and margin_mode == "isolated"
        and leverage > Decimal("0")
    ):
        liq_price = _estimate_liquidation_price(
            entry_price=entry_price,
            leverage=leverage,
            mm_rate=mm_rate,
            side=side,
        )

    return MarginState(
        venue=venue,
        symbol=symbol,
        position_value=position_value,
        leverage=leverage,
        margin_mode=margin_mode,
        initial_margin=initial_margin,
        maintenance_margin=maintenance_margin,
        margin_utilization=margin_utilization,
        allocated_margin=allocated_margin,
        liquidation_price=liq_price,
        is_liquidation_warning=is_warning,
        is_liquidation_critical=is_critical,
    )


def compute_cross_margin_utilization(
    positions: List[MarginState],
    total_wallet_balance: Decimal,
) -> Decimal:
    """
    Compute cross-margin utilization ratio for a portfolio.

    Cross margin: all positions share the wallet balance.
    Liquidation risk is collective -- the ratio of wallet balance to total
    maintenance margin across all positions.

    Parameters
    ----------
    positions:
        List of MarginState objects for open positions.
    total_wallet_balance:
        Total collateral available for all positions.

    Returns
    -------
    Decimal
        Utilization ratio = total_wallet_balance / sum(maintenance_margins).
        Higher is safer.  < 1.0 = collective liquidation.
        Returns Decimal('inf') if there are no positions (no maintenance margin required).
    """
    if not positions:
        return Decimal("inf")

    total_mm = sum(p.maintenance_margin for p in positions)
    if total_mm == Decimal("0"):
        return Decimal("inf")

    return total_wallet_balance / total_mm


# ---------------------------------------------------------------------------
# DB access
# ---------------------------------------------------------------------------


def load_margin_tiers(engine, venue: str, symbol: str) -> List[MarginTier]:
    """
    Load margin tiers from cmc_margin_config for the given venue and symbol.

    Parameters
    ----------
    engine:
        SQLAlchemy engine.
    venue:
        Exchange venue (e.g. 'binance').
    symbol:
        Asset symbol (e.g. 'BTC').

    Returns
    -------
    List[MarginTier]
        Ascending by notional_floor.  Empty list if no rows found.
    """
    from sqlalchemy import text

    sql = text(
        """
        SELECT
            notional_floor,
            notional_cap,
            initial_margin_rate,
            maintenance_margin_rate,
            max_leverage
        FROM cmc_margin_config
        WHERE venue  = :venue
          AND symbol = :symbol
        ORDER BY notional_floor ASC
        """
    )

    try:
        with engine.connect() as conn:
            rows = conn.execute(sql, {"venue": venue, "symbol": symbol}).fetchall()
    except Exception as exc:
        logger.warning(
            "Failed to load margin tiers for venue=%s symbol=%s: %s",
            venue,
            symbol,
            exc,
        )
        return []

    if not rows:
        logger.warning(
            "No margin tiers found in cmc_margin_config for venue=%s symbol=%s",
            venue,
            symbol,
        )
        return []

    tiers: List[MarginTier] = []
    for row in rows:
        try:
            notional_floor = _to_decimal(row[0])
            raw_cap = row[1]
            if raw_cap is None or str(raw_cap).lower() in ("inf", "infinity", ""):
                notional_cap = Decimal("inf")
            else:
                notional_cap = _to_decimal(raw_cap)

            tiers.append(
                MarginTier(
                    notional_floor=notional_floor,
                    notional_cap=notional_cap,
                    initial_margin_rate=_to_decimal(row[2]),
                    maintenance_margin_rate=_to_decimal(row[3]),
                    max_leverage=int(row[4]),
                )
            )
        except (InvalidOperation, ValueError, TypeError) as exc:
            logger.warning("Skipping malformed margin tier row %s: %s", row, exc)
            continue

    return tiers


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _select_tier(
    position_value: Decimal, tiers: List[MarginTier]
) -> Optional[MarginTier]:
    """
    Return the applicable tier for the given position notional.

    Selects the highest tier whose notional_floor <= position_value.
    Returns None if tiers is empty or no tier applies.
    """
    if not tiers:
        return None

    applicable: Optional[MarginTier] = None
    for tier in tiers:  # tiers are ordered ascending by notional_floor
        if tier.notional_floor <= position_value:
            applicable = tier
        else:
            break  # tiers are sorted; stop once we pass position_value

    return applicable


def _estimate_liquidation_price(
    entry_price: Decimal,
    leverage: Decimal,
    mm_rate: Decimal,
    side: str = "long",
) -> Decimal:
    """
    Estimate liquidation price for an isolated margin position.

    Formula (simplified, no funding):
        Long:  entry * (1 - 1/leverage + mm_rate)
        Short: entry * (1 + 1/leverage - mm_rate)

    Parameters
    ----------
    entry_price:
        Average entry price.
    leverage:
        Position leverage (Decimal).
    mm_rate:
        Maintenance margin rate for the applicable tier.
    side:
        'long' or 'short'.

    Returns
    -------
    Decimal
        Estimated liquidation price.
    """
    one_over_lev = Decimal("1") / leverage

    if side.lower() == "long":
        return entry_price * (Decimal("1") - one_over_lev + mm_rate)
    else:  # short
        return entry_price * (Decimal("1") + one_over_lev - mm_rate)


def _to_decimal(value) -> Decimal:
    """Convert a DB value to Decimal using str(round(float, 8)) pattern."""
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(round(float(value), 8)))
    except (ValueError, TypeError, InvalidOperation) as exc:
        raise ValueError(f"Cannot convert {value!r} to Decimal: {exc}") from exc
