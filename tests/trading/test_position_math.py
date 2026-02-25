"""Tests for compute_position_update() -- all 12 cases from the plan.

Tests cover:
- New position from flat (long and short)
- Adding to existing position (weighted average)
- Partial close
- Full close
- Position flip (long-to-short and short-to-long)
- Accumulated realized PnL across multiple fills
- Losing trades (negative realized PnL)

All arithmetic uses Decimal -- no float anywhere.
"""

from __future__ import annotations

from decimal import Decimal


from ta_lab2.trading.position_math import compute_position_update


# ---------------------------------------------------------------------------
# Case 1: New position from flat -- buy (long)
# ---------------------------------------------------------------------------


def test_case01_new_long_from_flat():
    """Open a new long position from flat."""
    result = compute_position_update(
        current_qty=Decimal("0"),
        current_avg_cost=Decimal("0"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("1"),
        fill_price=Decimal("50000"),
    )
    assert result["quantity"] == Decimal("1")
    assert result["avg_cost_basis"] == Decimal("50000")
    assert result["realized_pnl"] == Decimal("0")


# ---------------------------------------------------------------------------
# Case 2: New position from flat -- sell (short)
# ---------------------------------------------------------------------------


def test_case02_new_short_from_flat():
    """Open a new short position from flat."""
    result = compute_position_update(
        current_qty=Decimal("0"),
        current_avg_cost=Decimal("0"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("-1"),
        fill_price=Decimal("50000"),
    )
    assert result["quantity"] == Decimal("-1")
    assert result["avg_cost_basis"] == Decimal("50000")
    assert result["realized_pnl"] == Decimal("0")


# ---------------------------------------------------------------------------
# Case 3: Add to long -- weighted average
# ---------------------------------------------------------------------------


def test_case03_add_to_long_weighted_average():
    """Add to existing long position -- cost basis is weighted average.

    (100 * 50000 + 50 * 52000) / 150 = 7600000 / 150 = 50666.666...
    """
    result = compute_position_update(
        current_qty=Decimal("100"),
        current_avg_cost=Decimal("50000"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("50"),
        fill_price=Decimal("52000"),
    )
    assert result["quantity"] == Decimal("150")
    expected_cost = (
        Decimal("100") * Decimal("50000") + Decimal("50") * Decimal("52000")
    ) / Decimal("150")
    assert result["avg_cost_basis"] == expected_cost
    assert result["realized_pnl"] == Decimal("0")


# ---------------------------------------------------------------------------
# Case 4: Add to short -- weighted average
# ---------------------------------------------------------------------------


def test_case04_add_to_short_weighted_average():
    """Add to existing short position -- cost basis is weighted average.

    (-100 * 50000 + -50 * 48000) / -150 = (-5000000 + -2400000) / -150 = 49333.333...
    Computed as: (100*50000 + 50*48000) / 150 (using abs values for cost)
    """
    result = compute_position_update(
        current_qty=Decimal("-100"),
        current_avg_cost=Decimal("50000"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("-50"),
        fill_price=Decimal("48000"),
    )
    assert result["quantity"] == Decimal("-150")
    expected_cost = (
        Decimal("100") * Decimal("50000") + Decimal("50") * Decimal("48000")
    ) / Decimal("150")
    assert result["avg_cost_basis"] == expected_cost
    assert result["realized_pnl"] == Decimal("0")


# ---------------------------------------------------------------------------
# Case 5: Partial close of long
# ---------------------------------------------------------------------------


def test_case05_partial_close_long():
    """Partially close a long position.

    Realized: (52000 - 50000) * 30 = 60000
    Cost basis unchanged on remaining 70 units.
    """
    result = compute_position_update(
        current_qty=Decimal("100"),
        current_avg_cost=Decimal("50000"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("-30"),
        fill_price=Decimal("52000"),
    )
    assert result["quantity"] == Decimal("70")
    assert result["avg_cost_basis"] == Decimal("50000")
    assert result["realized_pnl"] == Decimal("60000")


# ---------------------------------------------------------------------------
# Case 6: Full close of long
# ---------------------------------------------------------------------------


def test_case06_full_close_long():
    """Fully close a long position.

    Realized: (52000 - 50000) * 100 = 200000
    Cost basis goes to 0, quantity goes to 0.
    """
    result = compute_position_update(
        current_qty=Decimal("100"),
        current_avg_cost=Decimal("50000"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("-100"),
        fill_price=Decimal("52000"),
    )
    assert result["quantity"] == Decimal("0")
    assert result["avg_cost_basis"] == Decimal("0")
    assert result["realized_pnl"] == Decimal("200000")


# ---------------------------------------------------------------------------
# Case 7: Partial close of short (buy to cover)
# ---------------------------------------------------------------------------


def test_case07_partial_close_short():
    """Partially close a short position by buying to cover.

    Realized: (50000 - 48000) * 30 = 60000
    Cost basis unchanged on remaining -70 units.
    """
    result = compute_position_update(
        current_qty=Decimal("-100"),
        current_avg_cost=Decimal("50000"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("30"),
        fill_price=Decimal("48000"),
    )
    assert result["quantity"] == Decimal("-70")
    assert result["avg_cost_basis"] == Decimal("50000")
    assert result["realized_pnl"] == Decimal("60000")


# ---------------------------------------------------------------------------
# Case 8: Full close of short
# ---------------------------------------------------------------------------


def test_case08_full_close_short():
    """Fully close a short position.

    Realized: (50000 - 48000) * 100 = 200000
    Cost basis goes to 0, quantity goes to 0.
    """
    result = compute_position_update(
        current_qty=Decimal("-100"),
        current_avg_cost=Decimal("50000"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("100"),
        fill_price=Decimal("48000"),
    )
    assert result["quantity"] == Decimal("0")
    assert result["avg_cost_basis"] == Decimal("0")
    assert result["realized_pnl"] == Decimal("200000")


# ---------------------------------------------------------------------------
# Case 9: Long-to-short flip
# ---------------------------------------------------------------------------


def test_case09_long_to_short_flip():
    """Flip from long 100 to short 50 in one fill.

    Close 100 long: realized = (52000 - 50000) * 100 = 200000
    Open 50 short at fill price (52000).
    """
    result = compute_position_update(
        current_qty=Decimal("100"),
        current_avg_cost=Decimal("50000"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("-150"),
        fill_price=Decimal("52000"),
    )
    assert result["quantity"] == Decimal("-50")
    assert result["avg_cost_basis"] == Decimal("52000")
    assert result["realized_pnl"] == Decimal("200000")


# ---------------------------------------------------------------------------
# Case 10: Short-to-long flip
# ---------------------------------------------------------------------------


def test_case10_short_to_long_flip():
    """Flip from short 100 to long 50 in one fill.

    Close 100 short: realized = (50000 - 48000) * 100 = 200000
    Open 50 long at fill price (48000).
    """
    result = compute_position_update(
        current_qty=Decimal("-100"),
        current_avg_cost=Decimal("50000"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("150"),
        fill_price=Decimal("48000"),
    )
    assert result["quantity"] == Decimal("50")
    assert result["avg_cost_basis"] == Decimal("48000")
    assert result["realized_pnl"] == Decimal("200000")


# ---------------------------------------------------------------------------
# Case 11: Accumulating realized PnL across multiple fills
# ---------------------------------------------------------------------------


def test_case11_accumulate_realized_pnl():
    """Prior realized PnL carries forward when making a new partial close.

    Prior realized: 500
    New realized: (52000 - 50000) * 30 = 60000
    Total: 60500
    """
    result = compute_position_update(
        current_qty=Decimal("100"),
        current_avg_cost=Decimal("50000"),
        current_realized_pnl=Decimal("500"),
        fill_qty=Decimal("-30"),
        fill_price=Decimal("52000"),
    )
    assert result["quantity"] == Decimal("70")
    assert result["avg_cost_basis"] == Decimal("50000")
    assert result["realized_pnl"] == Decimal("60500")


# ---------------------------------------------------------------------------
# Case 12: Losing trade (negative realized PnL)
# ---------------------------------------------------------------------------


def test_case12_losing_trade_negative_pnl():
    """Close a long position at a loss.

    Realized: (48000 - 50000) * 100 = -200000
    """
    result = compute_position_update(
        current_qty=Decimal("100"),
        current_avg_cost=Decimal("50000"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("-100"),
        fill_price=Decimal("48000"),
    )
    assert result["quantity"] == Decimal("0")
    assert result["avg_cost_basis"] == Decimal("0")
    assert result["realized_pnl"] == Decimal("-200000")


# ---------------------------------------------------------------------------
# Return type and key checks
# ---------------------------------------------------------------------------


def test_return_dict_has_required_keys():
    """Result dict always contains exactly the three required keys."""
    result = compute_position_update(
        current_qty=Decimal("0"),
        current_avg_cost=Decimal("0"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("1"),
        fill_price=Decimal("100"),
    )
    assert set(result.keys()) == {"quantity", "avg_cost_basis", "realized_pnl"}


def test_return_values_are_decimal():
    """All returned values must be Decimal instances, never float or int."""
    result = compute_position_update(
        current_qty=Decimal("100"),
        current_avg_cost=Decimal("50000"),
        current_realized_pnl=Decimal("500"),
        fill_qty=Decimal("-30"),
        fill_price=Decimal("52000"),
    )
    assert isinstance(result["quantity"], Decimal), "quantity must be Decimal"
    assert isinstance(result["avg_cost_basis"], Decimal), (
        "avg_cost_basis must be Decimal"
    )
    assert isinstance(result["realized_pnl"], Decimal), "realized_pnl must be Decimal"


# ---------------------------------------------------------------------------
# Exact Decimal precision check for weighted average
# ---------------------------------------------------------------------------


def test_weighted_average_exact_decimal_precision():
    """Weighted average must use exact Decimal arithmetic, not float approximation.

    (100*50000 + 50*52000) / 150 must be Decimal("50666.666...")
    not a float approximation.
    """
    result = compute_position_update(
        current_qty=Decimal("100"),
        current_avg_cost=Decimal("50000"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("50"),
        fill_price=Decimal("52000"),
    )
    expected = Decimal("7600000") / Decimal("150")
    assert result["avg_cost_basis"] == expected


# ---------------------------------------------------------------------------
# Importability check
# ---------------------------------------------------------------------------


def test_importable():
    """Function must be importable from the expected module path."""
    from ta_lab2.trading.position_math import compute_position_update as fn

    assert callable(fn)
