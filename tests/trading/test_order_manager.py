"""Unit tests for OrderManager state transitions and fill processing.

All tests use unittest.mock -- no live database required.
Tests cover:
- VALID_TRANSITIONS completeness and correctness
- FillData dataclass construction and defaults
- _validate_fill_transition: terminal status rejection, overfill rejection
- process_fill SQL execution order (mocked connection)
- Dead-letter error capture on process_fill failure
- update_order_status invalid transition raises ValueError
- promote_paper_order dead-letter on failure
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ta_lab2.trading.order_manager import (
    VALID_TRANSITIONS,
    FillData,
    OrderManager,
    _TERMINAL_STATUSES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine(conn_results=None):
    """Return a mock SQLAlchemy engine.

    conn_results: list of values that conn.execute(...).fetchone() will return
    in sequence. If None, returns MagicMock() for every fetchone call.
    """
    engine = MagicMock()
    conn = MagicMock()

    # engine.begin() returns a context manager that yields conn
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=conn)
    cm.__exit__ = MagicMock(return_value=False)
    engine.begin.return_value = cm

    if conn_results is not None:
        execute_mock = MagicMock()
        execute_mock.fetchone.side_effect = conn_results
        conn.execute.return_value = execute_mock
    return engine, conn


def _order_row(
    order_id="oid-1",
    asset_id=1,
    exchange="paper",
    side="buy",
    quantity="10",
    filled_qty="0",
    remaining_qty="10",
    avg_fill_price=None,
    status="submitted",
):
    """Build a mock order row (SimpleNamespace mimicking SQLAlchemy Row)."""
    return SimpleNamespace(
        order_id=order_id,
        asset_id=asset_id,
        exchange=exchange,
        side=side,
        quantity=Decimal(quantity),
        filled_qty=Decimal(filled_qty),
        remaining_qty=Decimal(remaining_qty),
        avg_fill_price=Decimal(avg_fill_price) if avg_fill_price else None,
        status=status,
    )


def _pos_row(quantity="5", avg_cost_basis="100", realized_pnl="0"):
    return SimpleNamespace(
        quantity=Decimal(quantity),
        avg_cost_basis=Decimal(avg_cost_basis),
        realized_pnl=Decimal(realized_pnl),
    )


# ===========================================================================
# TestValidTransitions
# ===========================================================================


class TestValidTransitions:
    """VALID_TRANSITIONS dict correctness tests -- no DB required."""

    def test_all_seven_states_present(self):
        expected = {
            "created",
            "submitted",
            "partial_fill",
            "filled",
            "cancelled",
            "rejected",
            "expired",
        }
        assert set(VALID_TRANSITIONS.keys()) == expected

    def test_terminal_states_have_no_transitions(self):
        for status in ("filled", "cancelled", "rejected", "expired"):
            assert VALID_TRANSITIONS[status] == [], (
                f"Terminal status {status!r} must have no outgoing transitions"
            )

    def test_created_transitions(self):
        assert VALID_TRANSITIONS["created"] == ["submitted"]

    def test_submitted_transitions(self):
        allowed = set(VALID_TRANSITIONS["submitted"])
        assert "partial_fill" in allowed
        assert "filled" in allowed
        assert "cancelled" in allowed
        assert "rejected" in allowed
        assert "expired" in allowed

    def test_partial_fill_transitions(self):
        allowed = set(VALID_TRANSITIONS["partial_fill"])
        assert "partial_fill" in allowed, (
            "partial fill can receive another partial fill"
        )
        assert "filled" in allowed, "partial fill can reach filled"
        assert "cancelled" in allowed, "partial fill can be cancelled"
        # Should NOT allow going back to created/submitted
        assert "created" not in allowed
        assert "submitted" not in allowed

    def test_terminal_statuses_frozenset(self):
        """_TERMINAL_STATUSES must include filled, cancelled, rejected, expired."""
        assert _TERMINAL_STATUSES == frozenset(
            {"filled", "cancelled", "rejected", "expired"}
        )

    def test_no_self_loops_for_non_partial(self):
        """Only partial_fill should loop to itself."""
        for status, nexts in VALID_TRANSITIONS.items():
            if status == "partial_fill":
                assert status in nexts
            else:
                assert status not in nexts, f"Unexpected self-loop for {status!r}"


# ===========================================================================
# TestFillData
# ===========================================================================


class TestFillData:
    """FillData dataclass construction and defaults -- no DB required."""

    def test_construction_required_fields(self):
        fd = FillData(
            order_id="abc",
            fill_qty=Decimal("1"),
            fill_price=Decimal("50000"),
        )
        assert fd.order_id == "abc"
        assert fd.fill_qty == Decimal("1")
        assert fd.fill_price == Decimal("50000")

    def test_defaults(self):
        fd = FillData(
            order_id="abc",
            fill_qty=Decimal("1"),
            fill_price=Decimal("100"),
        )
        assert fd.fee_amount == Decimal("0")
        assert fd.fee_currency is None
        assert fd.exchange_fill_id is None
        assert fd.filled_at is None

    def test_decimal_types_preserved(self):
        fd = FillData(
            order_id="abc",
            fill_qty=Decimal("2.5"),
            fill_price=Decimal("48000.75"),
            fee_amount=Decimal("0.01"),
        )
        assert isinstance(fd.fill_qty, Decimal)
        assert isinstance(fd.fill_price, Decimal)
        assert isinstance(fd.fee_amount, Decimal)

    def test_fee_amounts_are_independent(self):
        """Default fee_amount uses factory, not a shared mutable default."""
        fd1 = FillData(order_id="a", fill_qty=Decimal("1"), fill_price=Decimal("100"))
        fd2 = FillData(order_id="b", fill_qty=Decimal("1"), fill_price=Decimal("100"))
        assert fd1.fee_amount is not fd2.fee_amount

    def test_optional_fields_can_be_set(self):
        from datetime import datetime, timezone

        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fd = FillData(
            order_id="abc",
            fill_qty=Decimal("1"),
            fill_price=Decimal("100"),
            fee_amount=Decimal("0.5"),
            fee_currency="USD",
            exchange_fill_id="exfill-123",
            filled_at=ts,
        )
        assert fd.fee_currency == "USD"
        assert fd.exchange_fill_id == "exfill-123"
        assert fd.filled_at == ts


# ===========================================================================
# TestValidateFillTransition
# ===========================================================================


class TestValidateFillTransition:
    """Direct tests of _validate_fill_transition static method -- no DB."""

    def test_terminal_filled_raises(self):
        order = _order_row(status="filled", remaining_qty="0")
        with pytest.raises(ValueError, match="terminal status"):
            OrderManager._validate_fill_transition(
                from_status="filled",
                fill_qty=Decimal("1"),
                order=order,
            )

    def test_terminal_cancelled_raises(self):
        order = _order_row(status="cancelled", remaining_qty="5")
        with pytest.raises(ValueError, match="terminal status"):
            OrderManager._validate_fill_transition(
                from_status="cancelled",
                fill_qty=Decimal("1"),
                order=order,
            )

    def test_terminal_rejected_raises(self):
        order = _order_row(status="rejected", remaining_qty="10")
        with pytest.raises(ValueError, match="terminal status"):
            OrderManager._validate_fill_transition(
                from_status="rejected",
                fill_qty=Decimal("1"),
                order=order,
            )

    def test_terminal_expired_raises(self):
        order = _order_row(status="expired", remaining_qty="10")
        with pytest.raises(ValueError, match="terminal status"):
            OrderManager._validate_fill_transition(
                from_status="expired",
                fill_qty=Decimal("1"),
                order=order,
            )

    def test_overfill_raises(self):
        """fill_qty > remaining_qty must raise ValueError."""
        order = _order_row(status="submitted", remaining_qty="5")
        with pytest.raises(ValueError, match="exceeds remaining_qty"):
            OrderManager._validate_fill_transition(
                from_status="submitted",
                fill_qty=Decimal("6"),
                order=order,
            )

    def test_exact_fill_passes(self):
        """fill_qty == remaining_qty is allowed (final fill)."""
        order = _order_row(status="submitted", remaining_qty="10")
        # Should not raise
        OrderManager._validate_fill_transition(
            from_status="submitted",
            fill_qty=Decimal("10"),
            order=order,
        )

    def test_valid_partial_fill_passes(self):
        order = _order_row(status="submitted", remaining_qty="10")
        OrderManager._validate_fill_transition(
            from_status="submitted",
            fill_qty=Decimal("3"),
            order=order,
        )

    def test_partial_fill_accepts_another_fill(self):
        """An order already in partial_fill can receive another fill."""
        order = _order_row(status="partial_fill", remaining_qty="7")
        OrderManager._validate_fill_transition(
            from_status="partial_fill",
            fill_qty=Decimal("7"),
            order=order,
        )


# ===========================================================================
# TestProcessFill
# ===========================================================================


class TestProcessFill:
    """process_fill SQL execution order via mock engine."""

    def _make_fill_data(self, order_id="oid-1"):
        return FillData(
            order_id=order_id,
            fill_qty=Decimal("5"),
            fill_price=Decimal("50000"),
        )

    def _setup_conn_for_fill(self, conn, order=None, pos=None):
        """Configure conn.execute().fetchone() side_effect sequence.

        Sequence expected by _do_process_fill:
          1. SELECT ... FOR SHARE -> order_row
          2. SELECT ... FOR UPDATE (position) -> pos_row or None
        Subsequent execute() calls don't return fetchone results.
        """
        if order is None:
            order = _order_row()
        results = [order, pos]
        execute_return = MagicMock()
        execute_return.fetchone.side_effect = results
        conn.execute.return_value = execute_return

    def test_process_fill_calls_engine_begin(self):
        """process_fill must use engine.begin() for atomicity."""
        engine, conn = _make_engine()
        order = _order_row(status="submitted", remaining_qty="10")
        self._setup_conn_for_fill(conn, order=order, pos=None)

        OrderManager._do_process_fill(engine, self._make_fill_data())

        engine.begin.assert_called_once()

    def test_process_fill_select_for_share_first(self):
        """First execute() call must use FOR SHARE (order lock)."""
        engine, conn = _make_engine()
        order = _order_row(status="submitted", remaining_qty="10")
        self._setup_conn_for_fill(conn, order=order, pos=None)

        OrderManager._do_process_fill(engine, self._make_fill_data())

        first_call = conn.execute.call_args_list[0]
        sql_str = str(first_call[0][0])
        assert "FOR SHARE" in sql_str, "First query must lock order with FOR SHARE"

    def test_process_fill_select_for_update_second(self):
        """Second execute() call must use FOR UPDATE (position lock)."""
        engine, conn = _make_engine()
        order = _order_row(status="submitted", remaining_qty="10")
        self._setup_conn_for_fill(conn, order=order, pos=None)

        OrderManager._do_process_fill(engine, self._make_fill_data())

        second_call = conn.execute.call_args_list[1]
        sql_str = str(second_call[0][0])
        assert "FOR UPDATE" in sql_str, (
            "Second query must lock position with FOR UPDATE"
        )

    def test_process_fill_inserts_fill_record(self):
        """Third execute() must INSERT into cmc_fills."""
        engine, conn = _make_engine()
        order = _order_row(status="submitted", remaining_qty="10")
        self._setup_conn_for_fill(conn, order=order, pos=None)

        OrderManager._do_process_fill(engine, self._make_fill_data())

        third_call = conn.execute.call_args_list[2]
        sql_str = str(third_call[0][0])
        assert "cmc_fills" in sql_str

    def test_process_fill_updates_order(self):
        """Fourth execute() must UPDATE cmc_orders."""
        engine, conn = _make_engine()
        order = _order_row(status="submitted", remaining_qty="10")
        self._setup_conn_for_fill(conn, order=order, pos=None)

        OrderManager._do_process_fill(engine, self._make_fill_data())

        fourth_call = conn.execute.call_args_list[3]
        sql_str = str(fourth_call[0][0])
        assert "UPDATE" in sql_str and "cmc_orders" in sql_str

    def test_process_fill_upserts_position(self):
        """Fifth execute() must INSERT INTO cmc_positions ... ON CONFLICT."""
        engine, conn = _make_engine()
        order = _order_row(status="submitted", remaining_qty="10")
        self._setup_conn_for_fill(conn, order=order, pos=None)

        OrderManager._do_process_fill(engine, self._make_fill_data())

        fifth_call = conn.execute.call_args_list[4]
        sql_str = str(fifth_call[0][0])
        assert "cmc_positions" in sql_str
        assert "ON CONFLICT" in sql_str

    def test_process_fill_inserts_audit_event(self):
        """Sixth execute() must INSERT into cmc_order_events."""
        engine, conn = _make_engine()
        order = _order_row(status="submitted", remaining_qty="10")
        self._setup_conn_for_fill(conn, order=order, pos=None)

        OrderManager._do_process_fill(engine, self._make_fill_data())

        sixth_call = conn.execute.call_args_list[5]
        sql_str = str(sixth_call[0][0])
        assert "cmc_order_events" in sql_str

    def test_process_fill_exactly_six_sql_calls(self):
        """_do_process_fill must make exactly 6 execute() calls."""
        engine, conn = _make_engine()
        order = _order_row(status="submitted", remaining_qty="10")
        self._setup_conn_for_fill(conn, order=order, pos=None)

        OrderManager._do_process_fill(engine, self._make_fill_data())

        assert conn.execute.call_count == 6

    def test_process_fill_returns_fill_id_string(self):
        """Return value must be a UUID-formatted string."""
        engine, conn = _make_engine()
        order = _order_row(status="submitted", remaining_qty="10")
        self._setup_conn_for_fill(conn, order=order, pos=None)

        fill_id = OrderManager._do_process_fill(engine, self._make_fill_data())

        assert isinstance(fill_id, str)
        # Validate UUID format
        uuid.UUID(fill_id)

    def test_partial_fill_status_partial(self):
        """A partial fill (remaining > 0) sets status to partial_fill."""
        engine, conn = _make_engine()
        order = _order_row(status="submitted", remaining_qty="10")
        self._setup_conn_for_fill(conn, order=order, pos=None)

        OrderManager._do_process_fill(
            engine,
            FillData(
                order_id="oid-1",
                fill_qty=Decimal("5"),
                fill_price=Decimal("50000"),
            ),
        )

        # Find the UPDATE cmc_orders call and verify status param
        update_call = conn.execute.call_args_list[3]
        params = update_call[0][1]
        assert params["status"] == "partial_fill"

    def test_final_fill_status_filled(self):
        """A fill that exhausts remaining_qty sets status to filled."""
        engine, conn = _make_engine()
        order = _order_row(status="submitted", remaining_qty="10")
        self._setup_conn_for_fill(conn, order=order, pos=None)

        OrderManager._do_process_fill(
            engine,
            FillData(
                order_id="oid-1",
                fill_qty=Decimal("10"),
                fill_price=Decimal("50000"),
            ),
        )

        update_call = conn.execute.call_args_list[3]
        params = update_call[0][1]
        assert params["status"] == "filled"

    def test_partial_fill_updates_filled_qty(self):
        """filled_qty param reflects old_filled + fill_qty."""
        engine, conn = _make_engine()
        order = _order_row(
            status="partial_fill",
            filled_qty="3",
            remaining_qty="7",
        )
        self._setup_conn_for_fill(conn, order=order, pos=None)

        OrderManager._do_process_fill(
            engine,
            FillData(
                order_id="oid-1",
                fill_qty=Decimal("4"),
                fill_price=Decimal("50000"),
            ),
        )

        update_call = conn.execute.call_args_list[3]
        params = update_call[0][1]
        assert Decimal(params["filled_qty"]) == Decimal("7")
        assert Decimal(params["remaining_qty"]) == Decimal("3")

    def test_avg_fill_price_first_fill(self):
        """On first fill (avg_fill_price=None), avg equals fill_price."""
        engine, conn = _make_engine()
        order = _order_row(status="submitted", remaining_qty="10", avg_fill_price=None)
        self._setup_conn_for_fill(conn, order=order, pos=None)

        OrderManager._do_process_fill(
            engine,
            FillData(
                order_id="oid-1",
                fill_qty=Decimal("5"),
                fill_price=Decimal("50000"),
            ),
        )

        update_call = conn.execute.call_args_list[3]
        params = update_call[0][1]
        assert Decimal(params["avg_fill_price"]) == Decimal("50000")

    def test_avg_fill_price_weighted_average(self):
        """Second fill computes weighted average: (0*45k + 5*50k) / 5 = 50k,
        then (5*50k + 5*52k) / 10 = 51k."""
        engine, conn = _make_engine()
        order = _order_row(
            status="partial_fill",
            filled_qty="5",
            remaining_qty="5",
            avg_fill_price="50000",
        )
        self._setup_conn_for_fill(conn, order=order, pos=None)

        OrderManager._do_process_fill(
            engine,
            FillData(
                order_id="oid-1",
                fill_qty=Decimal("5"),
                fill_price=Decimal("52000"),
            ),
        )

        update_call = conn.execute.call_args_list[3]
        params = update_call[0][1]
        # (5*50000 + 5*52000) / 10 = 510000/10 = 51000
        assert Decimal(params["avg_fill_price"]) == Decimal("51000")

    def test_sell_order_uses_negative_signed_fill(self):
        """Sell fill passes negative signed_fill to compute_position_update."""
        engine, conn = _make_engine()
        order = _order_row(status="submitted", remaining_qty="10", side="sell")
        self._setup_conn_for_fill(
            conn,
            order=order,
            pos=_pos_row(quantity="10", avg_cost_basis="50000"),
        )

        with patch("ta_lab2.trading.order_manager.compute_position_update") as mock_cpu:
            mock_cpu.return_value = {
                "quantity": Decimal("0"),
                "avg_cost_basis": Decimal("0"),
                "realized_pnl": Decimal("10000"),
            }
            OrderManager._do_process_fill(
                engine,
                FillData(
                    order_id="oid-1",
                    fill_qty=Decimal("5"),
                    fill_price=Decimal("51000"),
                ),
            )

        mock_cpu.assert_called_once()
        call_kwargs = mock_cpu.call_args[1]
        assert call_kwargs["fill_qty"] == Decimal("-5"), (
            "Sell fills must pass negative fill_qty to compute_position_update"
        )

    def test_order_not_found_raises_value_error(self):
        """process_fill raises ValueError when order_id not found."""
        engine, conn = _make_engine()
        execute_mock = MagicMock()
        execute_mock.fetchone.return_value = None
        conn.execute.return_value = execute_mock

        with pytest.raises(ValueError, match="not found"):
            OrderManager._do_process_fill(
                engine,
                FillData(
                    order_id="nonexistent",
                    fill_qty=Decimal("1"),
                    fill_price=Decimal("100"),
                ),
            )


# ===========================================================================
# TestDeadLetter
# ===========================================================================


class TestDeadLetter:
    """Dead-letter error capture tests."""

    def test_process_fill_calls_dead_letter_on_failure(self):
        """process_fill must call _write_dead_letter when _do_process_fill raises."""
        engine = MagicMock()
        fill_data = FillData(
            order_id="oid-fail",
            fill_qty=Decimal("1"),
            fill_price=Decimal("100"),
        )

        with patch.object(
            OrderManager, "_do_process_fill", side_effect=RuntimeError("DB exploded")
        ):
            with patch.object(OrderManager, "_write_dead_letter") as mock_dlq:
                with pytest.raises(RuntimeError, match="DB exploded"):
                    OrderManager.process_fill(engine, fill_data)

        mock_dlq.assert_called_once()
        call_kwargs = mock_dlq.call_args[1]
        assert call_kwargs["operation_type"] == "process_fill"
        assert call_kwargs["order_id"] == "oid-fail"

    def test_original_exception_is_reraised(self):
        """After writing dead-letter, the original exception propagates."""
        engine = MagicMock()
        fill_data = FillData(
            order_id="oid-fail",
            fill_qty=Decimal("1"),
            fill_price=Decimal("100"),
        )

        with patch.object(
            OrderManager, "_do_process_fill", side_effect=ValueError("specific error")
        ):
            with patch.object(OrderManager, "_write_dead_letter"):
                with pytest.raises(ValueError, match="specific error"):
                    OrderManager.process_fill(engine, fill_data)

    def test_dead_letter_write_uses_separate_connection(self):
        """_write_dead_letter calls engine.begin() independently."""
        engine, conn = _make_engine()
        execute_mock = MagicMock()
        conn.execute.return_value = execute_mock

        exc = RuntimeError("test error")
        OrderManager._write_dead_letter(
            engine,
            operation_type="process_fill",
            order_id="oid-1",
            payload_dict={"test": True},
            exc=exc,
        )

        engine.begin.assert_called_once()

    def test_dead_letter_inserts_to_correct_table(self):
        """_write_dead_letter must INSERT into cmc_order_dead_letter."""
        engine, conn = _make_engine()
        execute_mock = MagicMock()
        conn.execute.return_value = execute_mock

        OrderManager._write_dead_letter(
            engine,
            operation_type="promote_order",
            order_id=None,
            payload_dict={"paper_order_uuid": "abc"},
            exc=ValueError("not found"),
        )

        first_call = conn.execute.call_args_list[0]
        sql_str = str(first_call[0][0])
        assert "cmc_order_dead_letter" in sql_str

    def test_dead_letter_serializes_payload_as_json(self):
        """payload_dict must be JSON-serialized before insert."""
        engine, conn = _make_engine()
        execute_mock = MagicMock()
        conn.execute.return_value = execute_mock

        payload = {"order_id": "abc", "fill_qty": "5"}
        OrderManager._write_dead_letter(
            engine,
            operation_type="process_fill",
            order_id="abc",
            payload_dict=payload,
            exc=RuntimeError("failure"),
        )

        first_call = conn.execute.call_args_list[0]
        params = first_call[0][1]
        # payload must be a string (JSON-encoded)
        assert isinstance(params["payload"], str)
        parsed = json.loads(params["payload"])
        assert parsed["order_id"] == "abc"

    def test_dead_letter_failure_does_not_raise(self):
        """If _write_dead_letter itself fails, it must NOT raise (just log CRITICAL)."""
        engine = MagicMock()
        # Make engine.begin() raise so the DLQ write fails
        engine.begin.side_effect = ConnectionError("DB totally dead")

        # Should not raise -- logs at CRITICAL
        OrderManager._write_dead_letter(
            engine,
            operation_type="process_fill",
            order_id="oid-1",
            payload_dict={},
            exc=RuntimeError("original"),
        )


# ===========================================================================
# TestUpdateOrderStatus
# ===========================================================================


class TestUpdateOrderStatus:
    """update_order_status validation and SQL tests."""

    def _mock_engine_with_status(self, current_status: str):
        """Return engine whose first fetchone returns a row with given status."""
        engine, conn = _make_engine()
        status_row = SimpleNamespace(status=current_status)
        execute_mock = MagicMock()
        execute_mock.fetchone.return_value = status_row
        conn.execute.return_value = execute_mock
        return engine, conn

    def test_invalid_transition_raises_value_error(self):
        """created -> filled is not a valid transition."""
        engine, _ = self._mock_engine_with_status("created")
        with pytest.raises(ValueError, match="Invalid order status transition"):
            OrderManager.update_order_status(engine, "oid-1", "filled")

    def test_invalid_transition_terminal_to_any(self):
        """Terminal status -> any new status must raise ValueError."""
        for terminal in ("filled", "cancelled", "rejected", "expired"):
            engine, _ = self._mock_engine_with_status(terminal)
            with pytest.raises(ValueError):
                OrderManager.update_order_status(engine, "oid-1", "submitted")

    def test_valid_transition_created_to_submitted(self):
        """created -> submitted is valid; must not raise."""
        engine, conn = self._mock_engine_with_status("created")
        # Should not raise
        OrderManager.update_order_status(engine, "oid-1", "submitted")
        # Verify UPDATE was called
        calls = [str(c[0][0]) for c in conn.execute.call_args_list]
        assert any("UPDATE" in s and "cmc_orders" in s for s in calls)

    def test_valid_transition_inserts_event(self):
        """Valid transition must INSERT into cmc_order_events."""
        engine, conn = self._mock_engine_with_status("submitted")
        OrderManager.update_order_status(
            engine, "oid-1", "cancelled", reason="user cancelled"
        )
        calls = [str(c[0][0]) for c in conn.execute.call_args_list]
        assert any("cmc_order_events" in s for s in calls)

    def test_reason_is_passed_to_event_insert(self):
        """Reason string must appear in the INSERT params for cmc_order_events."""
        engine, conn = self._mock_engine_with_status("submitted")
        execute_mock = MagicMock()
        execute_mock.fetchone.return_value = SimpleNamespace(status="submitted")
        conn.execute.return_value = execute_mock

        OrderManager.update_order_status(
            engine, "oid-1", "rejected", reason="insufficient margin"
        )

        # Find the event INSERT call (last call)
        event_call = conn.execute.call_args_list[-1]
        params = event_call[0][1]
        assert params["reason"] == "insufficient margin"

    def test_order_not_found_raises_value_error(self):
        """update_order_status raises ValueError if order not found."""
        engine, conn = _make_engine()
        execute_mock = MagicMock()
        execute_mock.fetchone.return_value = None
        conn.execute.return_value = execute_mock

        with pytest.raises(ValueError, match="not found"):
            OrderManager.update_order_status(engine, "nonexistent", "submitted")

    def test_partial_fill_to_partial_fill(self):
        """partial_fill -> partial_fill is valid (self-loop for multi-fill orders)."""
        engine, conn = self._mock_engine_with_status("partial_fill")
        OrderManager.update_order_status(engine, "oid-1", "partial_fill")
        calls = [str(c[0][0]) for c in conn.execute.call_args_list]
        assert any("UPDATE" in s and "cmc_orders" in s for s in calls)

    def test_submitted_to_expired(self):
        """submitted -> expired is valid."""
        engine, conn = self._mock_engine_with_status("submitted")
        OrderManager.update_order_status(engine, "oid-1", "expired")
        calls = [str(c[0][0]) for c in conn.execute.call_args_list]
        assert any("UPDATE" in s for s in calls)


# ===========================================================================
# TestPromotePaperOrder
# ===========================================================================


class TestPromotePaperOrder:
    """promote_paper_order tests via mocked engine."""

    def test_dead_letter_on_failure(self):
        """promote_paper_order calls _write_dead_letter on any failure."""
        engine = MagicMock()

        with patch.object(
            OrderManager,
            "_do_promote_paper_order",
            side_effect=ValueError("paper_orders row not found"),
        ):
            with patch.object(OrderManager, "_write_dead_letter") as mock_dlq:
                with pytest.raises(ValueError):
                    OrderManager.promote_paper_order(engine, "uuid-not-found")

        mock_dlq.assert_called_once()
        call_kwargs = mock_dlq.call_args[1]
        assert call_kwargs["operation_type"] == "promote_order"
        assert call_kwargs["order_id"] is None

    def test_paper_order_not_found_raises(self):
        """_do_promote_paper_order raises ValueError when row is None."""
        engine, conn = _make_engine()
        execute_mock = MagicMock()
        execute_mock.fetchone.return_value = None
        conn.execute.return_value = execute_mock

        with pytest.raises(ValueError, match="not found"):
            OrderManager._do_promote_paper_order(engine, "no-such-uuid", "sandbox")

    def test_promote_returns_order_id(self):
        """_do_promote_paper_order returns a UUID string on success."""
        engine, conn = _make_engine()
        paper_row = SimpleNamespace(
            order_uuid="paper-uuid",
            signal_id=None,
            asset_id=1,
            exchange="paper",
            pair="BTC-USD",
            side="buy",
            order_type="market",
            quantity=Decimal("1"),
            limit_price=None,
            stop_price=None,
            client_order_id=None,
            environment="sandbox",
        )
        execute_mock = MagicMock()
        execute_mock.fetchone.return_value = paper_row
        conn.execute.return_value = execute_mock

        order_id = OrderManager._do_promote_paper_order(engine, "paper-uuid", "sandbox")

        assert isinstance(order_id, str)
        uuid.UUID(order_id)  # Validates UUID format

    def test_promote_inserts_into_cmc_orders(self):
        """_do_promote_paper_order must INSERT into cmc_orders."""
        engine, conn = _make_engine()
        paper_row = SimpleNamespace(
            order_uuid="paper-uuid",
            signal_id=None,
            asset_id=1,
            exchange="paper",
            pair="BTC-USD",
            side="buy",
            order_type="market",
            quantity=Decimal("2"),
            limit_price=None,
            stop_price=None,
            client_order_id=None,
            environment="sandbox",
        )
        execute_mock = MagicMock()
        execute_mock.fetchone.return_value = paper_row
        conn.execute.return_value = execute_mock

        OrderManager._do_promote_paper_order(engine, "paper-uuid", "sandbox")

        all_sql = [str(c[0][0]) for c in conn.execute.call_args_list]
        assert any("cmc_orders" in s for s in all_sql)
        assert any("cmc_order_events" in s for s in all_sql)

    def test_promote_original_exception_reraised(self):
        """If promotion fails, the original exception is re-raised after DLQ."""
        engine = MagicMock()

        with patch.object(
            OrderManager,
            "_do_promote_paper_order",
            side_effect=ConnectionError("db down"),
        ):
            with patch.object(OrderManager, "_write_dead_letter"):
                with pytest.raises(ConnectionError, match="db down"):
                    OrderManager.promote_paper_order(engine, "some-uuid")
