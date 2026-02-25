"""Position math for the order/fill store.

Pure functions -- no side effects, no DB access, no logging.
All arithmetic uses Decimal for exact financial computation.

Pattern: NautilusTrader net-quantity model (NETTING mode).
Signed quantity: positive = long, negative = short, zero = flat.
"""

from __future__ import annotations

from decimal import Decimal


def compute_position_update(
    current_qty: Decimal,
    current_avg_cost: Decimal,
    current_realized_pnl: Decimal,
    fill_qty: Decimal,
    fill_price: Decimal,
) -> dict[str, Decimal]:
    """Compute updated position fields after a fill event.

    Uses the net-quantity model (NautilusTrader NETTING pattern).
    All parameters and return values use Decimal for exact arithmetic.

    Args:
        current_qty: Signed current position quantity.
            Positive = long, negative = short, zero = flat.
        current_avg_cost: Per-unit weighted average cost basis.
        current_realized_pnl: Cumulative realized PnL so far.
        fill_qty: Signed fill quantity.
            Positive = buy fill, negative = sell fill.
        fill_price: Execution price for this fill.

    Returns:
        Dict with keys:
            quantity:        New signed position quantity.
            avg_cost_basis:  New per-unit weighted average cost basis.
            realized_pnl:    Updated cumulative realized PnL.
    """
    new_qty = current_qty + fill_qty

    # ------------------------------------------------------------------
    # Case 1: New position from flat
    # ------------------------------------------------------------------
    if current_qty == Decimal("0"):
        return {
            "quantity": new_qty,
            "avg_cost_basis": fill_price,
            "realized_pnl": current_realized_pnl,
        }

    # ------------------------------------------------------------------
    # Case 2: Adding to existing position in the same direction
    #         fill_qty must have the same sign as current_qty (both long
    #         or both short) -- this is the only true "add" scenario.
    # ------------------------------------------------------------------
    fill_adds_to_position = (current_qty > Decimal("0")) == (fill_qty > Decimal("0"))
    if fill_adds_to_position:
        # Weighted average cost: (old_total_cost + fill_cost) / new_qty
        # For short positions both current_qty and fill_qty are negative;
        # the ratio is still correct because the negatives cancel in division.
        old_total_cost = current_qty * current_avg_cost
        fill_total_cost = fill_qty * fill_price
        new_avg_cost = (old_total_cost + fill_total_cost) / new_qty
        return {
            "quantity": new_qty,
            "avg_cost_basis": new_avg_cost,
            "realized_pnl": current_realized_pnl,
        }

    # ------------------------------------------------------------------
    # Case 3: Closing (partial or full) or flipping direction
    # ------------------------------------------------------------------
    # Determine how many units are being closed vs opened.
    if abs(fill_qty) <= abs(current_qty):
        # Partial close or exact full close -- no flip.
        closed_qty = abs(fill_qty)
    else:
        # Flip: close the entire current position first,
        # then open the remainder in the opposite direction.
        closed_qty = abs(current_qty)

    # Realized PnL on the closed portion.
    #   Long position: realized = (sell_price - avg_cost) * closed_qty
    #   Short position: realized = (avg_cost - buy_price) * closed_qty
    if current_qty > Decimal("0"):
        realized = (fill_price - current_avg_cost) * closed_qty
    else:
        realized = (current_avg_cost - fill_price) * closed_qty

    new_realized_pnl = current_realized_pnl + realized

    if new_qty == Decimal("0"):
        # Full close -- position is flat.
        return {
            "quantity": Decimal("0"),
            "avg_cost_basis": Decimal("0"),
            "realized_pnl": new_realized_pnl,
        }

    # Check if this is a partial close (no direction change) or a flip.
    # A flip means the sign of new_qty is opposite to current_qty.
    is_flip = (current_qty > Decimal("0")) != (new_qty > Decimal("0"))

    if is_flip:
        # Position flip -- open new position in opposite direction at fill price.
        return {
            "quantity": new_qty,
            "avg_cost_basis": fill_price,
            "realized_pnl": new_realized_pnl,
        }

    # Partial close -- cost basis of the remaining units is unchanged.
    return {
        "quantity": new_qty,
        "avg_cost_basis": current_avg_cost,
        "realized_pnl": new_realized_pnl,
    }
