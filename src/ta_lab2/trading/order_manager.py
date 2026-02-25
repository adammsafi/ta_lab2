"""OrderManager: atomic order/fill/position writes for the OMS.

All database operations use raw text() SQL with SQLAlchemy engine.begin()
to ensure atomicity. Every fill atomically updates 4 tables (cmc_fills,
cmc_orders, cmc_positions, cmc_order_events) or rolls back entirely.
Failures are captured in cmc_order_dead_letter via a separate connection.

Pattern: stateless -- all methods are static. Callers pass the engine.
"""

from __future__ import annotations

import json
import logging
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.trading.position_math import compute_position_update

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# State machine: valid transitions for the 7-state order lifecycle.
# Terminal states (filled, cancelled, rejected, expired) have no outgoing
# transitions.
# ---------------------------------------------------------------------------
VALID_TRANSITIONS: dict[str, list[str]] = {
    "created": ["submitted"],
    "submitted": ["partial_fill", "filled", "cancelled", "rejected", "expired"],
    "partial_fill": ["partial_fill", "filled", "cancelled"],
    "filled": [],
    "cancelled": [],
    "rejected": [],
    "expired": [],
}

_TERMINAL_STATUSES = frozenset({"filled", "cancelled", "rejected", "expired"})


# ---------------------------------------------------------------------------
# FillData: immutable value object passed to process_fill
# ---------------------------------------------------------------------------
@dataclass
class FillData:
    """Represents a single fill event received from an exchange or simulator.

    fill_qty is always POSITIVE; direction is inferred from the order side.
    """

    order_id: str
    fill_qty: Decimal
    fill_price: Decimal
    fee_amount: Decimal = field(default_factory=lambda: Decimal("0"))
    fee_currency: Optional[str] = None
    exchange_fill_id: Optional[str] = None
    filled_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# OrderManager: stateless class, all methods are static
# ---------------------------------------------------------------------------
class OrderManager:
    """Handles all order/fill/position writes for the OMS.

    All public methods wrap an inner _do_* method in try/except.  On failure
    the exception is recorded in cmc_order_dead_letter (via a SEPARATE
    engine.begin() connection so the dead-letter write cannot be rolled back
    by the original failure) and then re-raised to the caller.
    """

    # ------------------------------------------------------------------
    # promote_paper_order
    # ------------------------------------------------------------------

    @staticmethod
    def promote_paper_order(
        engine: Engine,
        paper_order_uuid: str,
        environment: str = "sandbox",
    ) -> str:
        """Read a paper_orders row and create the corresponding cmc_orders row.

        Returns the new order_id (UUID string) on success.
        Raises ValueError if the paper order is not found.
        """
        try:
            return OrderManager._do_promote_paper_order(
                engine, paper_order_uuid, environment
            )
        except Exception as exc:
            logger.error(
                "promote_paper_order failed for paper_order_uuid=%s: %s",
                paper_order_uuid,
                exc,
            )
            OrderManager._write_dead_letter(
                engine,
                operation_type="promote_order",
                order_id=None,
                payload_dict={
                    "paper_order_uuid": paper_order_uuid,
                    "environment": environment,
                },
                exc=exc,
            )
            raise

    @staticmethod
    def _do_promote_paper_order(
        engine: Engine,
        paper_order_uuid: str,
        environment: str,
    ) -> str:
        with engine.begin() as conn:
            # Read paper order
            row = conn.execute(
                text(
                    """
                    SELECT order_uuid, signal_id, asset_id, exchange, pair,
                           side, order_type, quantity, limit_price, stop_price,
                           client_order_id, environment
                    FROM public.paper_orders
                    WHERE order_uuid = :uuid
                    """
                ),
                {"uuid": paper_order_uuid},
            ).fetchone()

            if row is None:
                raise ValueError(
                    f"paper_orders row not found for order_uuid={paper_order_uuid!r}"
                )

            order_id = str(uuid.uuid4())
            qty = row.quantity if row.quantity is not None else Decimal("0")

            # Insert into cmc_orders
            conn.execute(
                text(
                    """
                    INSERT INTO public.cmc_orders (
                        order_id, paper_order_uuid, signal_id, asset_id,
                        exchange, pair, side, order_type, quantity,
                        limit_price, stop_price, status, filled_qty,
                        remaining_qty, environment, client_order_id
                    ) VALUES (
                        :order_id, :paper_order_uuid, :signal_id, :asset_id,
                        :exchange, :pair, :side, :order_type, :quantity,
                        :limit_price, :stop_price, 'created', 0,
                        :remaining_qty, :environment, :client_order_id
                    )
                    """
                ),
                {
                    "order_id": order_id,
                    "paper_order_uuid": paper_order_uuid,
                    "signal_id": row.signal_id,
                    "asset_id": row.asset_id,
                    "exchange": row.exchange,
                    "pair": row.pair,
                    "side": row.side,
                    "order_type": row.order_type,
                    "quantity": str(qty),
                    "limit_price": str(row.limit_price)
                    if row.limit_price is not None
                    else None,
                    "stop_price": str(row.stop_price)
                    if row.stop_price is not None
                    else None,
                    "remaining_qty": str(qty),
                    "environment": environment,
                    "client_order_id": row.client_order_id,
                },
            )

            # Insert 'created' event
            conn.execute(
                text(
                    """
                    INSERT INTO public.cmc_order_events (
                        event_id, order_id, from_status, to_status, reason
                    ) VALUES (
                        :event_id, :order_id, NULL, 'created',
                        'promoted from paper_orders'
                    )
                    """
                ),
                {"event_id": str(uuid.uuid4()), "order_id": order_id},
            )

        logger.info(
            "promote_paper_order: paper_order_uuid=%s -> order_id=%s",
            paper_order_uuid,
            order_id,
        )
        return order_id

    # ------------------------------------------------------------------
    # process_fill
    # ------------------------------------------------------------------

    @staticmethod
    def process_fill(engine: Engine, fill_data: FillData) -> str:
        """Process a fill event atomically.

        Atomically:
          1. Inserts a row into cmc_fills
          2. Updates filled_qty / remaining_qty / avg_fill_price / status on cmc_orders
          3. Upserts the position in cmc_positions (with SELECT FOR UPDATE lock)
          4. Inserts an audit event into cmc_order_events

        Returns the new fill_id (UUID string) on success.
        On any failure, writes to cmc_order_dead_letter and re-raises.
        """
        try:
            return OrderManager._do_process_fill(engine, fill_data)
        except Exception as exc:
            logger.error(
                "process_fill failed for order_id=%s: %s",
                fill_data.order_id,
                exc,
            )
            OrderManager._write_dead_letter(
                engine,
                operation_type="process_fill",
                order_id=fill_data.order_id,
                payload_dict={
                    "order_id": fill_data.order_id,
                    "fill_qty": str(fill_data.fill_qty),
                    "fill_price": str(fill_data.fill_price),
                    "fee_amount": str(fill_data.fee_amount),
                    "fee_currency": fill_data.fee_currency,
                    "exchange_fill_id": fill_data.exchange_fill_id,
                    "filled_at": fill_data.filled_at.isoformat()
                    if fill_data.filled_at
                    else None,
                },
                exc=exc,
            )
            raise

    @staticmethod
    def _do_process_fill(engine: Engine, fill_data: FillData) -> str:
        with engine.begin() as conn:
            # ----------------------------------------------------------
            # Step 1: Read order with FOR SHARE lock
            # ----------------------------------------------------------
            order_row = conn.execute(
                text(
                    """
                    SELECT order_id, asset_id, exchange, side, quantity,
                           filled_qty, remaining_qty, avg_fill_price, status
                    FROM public.cmc_orders
                    WHERE order_id = :order_id
                    FOR SHARE
                    """
                ),
                {"order_id": fill_data.order_id},
            ).fetchone()

            if order_row is None:
                raise ValueError(
                    f"cmc_orders row not found for order_id={fill_data.order_id!r}"
                )

            OrderManager._validate_fill_transition(
                from_status=order_row.status,
                fill_qty=fill_data.fill_qty,
                order=order_row,
            )

            # ----------------------------------------------------------
            # Step 2: Lock position row with FOR UPDATE
            # ----------------------------------------------------------
            pos_row = conn.execute(
                text(
                    """
                    SELECT quantity, avg_cost_basis, realized_pnl
                    FROM public.cmc_positions
                    WHERE asset_id = :asset_id AND exchange = :exchange
                    FOR UPDATE
                    """
                ),
                {"asset_id": order_row.asset_id, "exchange": order_row.exchange},
            ).fetchone()

            if pos_row is not None:
                current_qty = Decimal(str(pos_row.quantity))
                current_cost = Decimal(str(pos_row.avg_cost_basis))
                current_rpnl = Decimal(str(pos_row.realized_pnl))
            else:
                current_qty = Decimal("0")
                current_cost = Decimal("0")
                current_rpnl = Decimal("0")

            # ----------------------------------------------------------
            # Step 3: Insert fill
            # ----------------------------------------------------------
            fill_id = str(uuid.uuid4())
            filled_at = fill_data.filled_at if fill_data.filled_at is not None else None

            conn.execute(
                text(
                    """
                    INSERT INTO public.cmc_fills (
                        fill_id, order_id, fill_qty, fill_price, fee_amount,
                        fee_currency, side, exchange, exchange_fill_id
                        {filled_at_col}
                    ) VALUES (
                        :fill_id, :order_id, :fill_qty, :fill_price, :fee_amount,
                        :fee_currency, :side, :exchange, :exchange_fill_id
                        {filled_at_val}
                    )
                    """.format(
                        filled_at_col=", filled_at" if filled_at is not None else "",
                        filled_at_val=", :filled_at" if filled_at is not None else "",
                    )
                ),
                {
                    "fill_id": fill_id,
                    "order_id": fill_data.order_id,
                    "fill_qty": str(fill_data.fill_qty),
                    "fill_price": str(fill_data.fill_price),
                    "fee_amount": str(fill_data.fee_amount),
                    "fee_currency": fill_data.fee_currency,
                    "side": order_row.side,
                    "exchange": order_row.exchange,
                    "exchange_fill_id": fill_data.exchange_fill_id,
                    **({"filled_at": filled_at} if filled_at is not None else {}),
                },
            )

            # ----------------------------------------------------------
            # Step 4: Update order
            # ----------------------------------------------------------
            old_filled_qty = Decimal(str(order_row.filled_qty))
            new_filled_qty = old_filled_qty + fill_data.fill_qty
            new_remaining = Decimal(str(order_row.quantity)) - new_filled_qty

            # Weighted average fill price
            old_avg = (
                Decimal(str(order_row.avg_fill_price))
                if order_row.avg_fill_price is not None
                else Decimal("0")
            )
            old_total_value = old_filled_qty * old_avg
            fill_value = fill_data.fill_qty * fill_data.fill_price
            new_avg_fill_price = (old_total_value + fill_value) / new_filled_qty

            to_status = "filled" if new_remaining <= Decimal("0") else "partial_fill"

            conn.execute(
                text(
                    """
                    UPDATE public.cmc_orders
                    SET filled_qty = :filled_qty,
                        remaining_qty = :remaining_qty,
                        avg_fill_price = :avg_fill_price,
                        status = :status,
                        updated_at = now()
                    WHERE order_id = :order_id
                    """
                ),
                {
                    "filled_qty": str(new_filled_qty),
                    "remaining_qty": str(max(new_remaining, Decimal("0"))),
                    "avg_fill_price": str(new_avg_fill_price),
                    "status": to_status,
                    "order_id": fill_data.order_id,
                },
            )

            # ----------------------------------------------------------
            # Step 5: Upsert position
            # ----------------------------------------------------------
            # Signed fill qty: positive for buy, negative for sell
            signed_fill = (
                fill_data.fill_qty if order_row.side == "buy" else -fill_data.fill_qty
            )

            pos_update = compute_position_update(
                current_qty=current_qty,
                current_avg_cost=current_cost,
                current_realized_pnl=current_rpnl,
                fill_qty=signed_fill,
                fill_price=fill_data.fill_price,
            )

            conn.execute(
                text(
                    """
                    INSERT INTO public.cmc_positions (
                        asset_id, exchange, quantity, avg_cost_basis,
                        realized_pnl, last_fill_id, last_updated
                    ) VALUES (
                        :asset_id, :exchange, :quantity, :avg_cost_basis,
                        :realized_pnl, :last_fill_id, now()
                    )
                    ON CONFLICT (asset_id, exchange) DO UPDATE SET
                        quantity = EXCLUDED.quantity,
                        avg_cost_basis = EXCLUDED.avg_cost_basis,
                        realized_pnl = EXCLUDED.realized_pnl,
                        last_fill_id = EXCLUDED.last_fill_id,
                        last_updated = now()
                    """
                ),
                {
                    "asset_id": order_row.asset_id,
                    "exchange": order_row.exchange,
                    "quantity": str(pos_update["quantity"]),
                    "avg_cost_basis": str(pos_update["avg_cost_basis"]),
                    "realized_pnl": str(pos_update["realized_pnl"]),
                    "last_fill_id": fill_id,
                },
            )

            # ----------------------------------------------------------
            # Step 6: Insert audit event
            # ----------------------------------------------------------
            conn.execute(
                text(
                    """
                    INSERT INTO public.cmc_order_events (
                        event_id, order_id, from_status, to_status, fill_id
                    ) VALUES (
                        :event_id, :order_id, :from_status, :to_status, :fill_id
                    )
                    """
                ),
                {
                    "event_id": str(uuid.uuid4()),
                    "order_id": fill_data.order_id,
                    "from_status": order_row.status,
                    "to_status": to_status,
                    "fill_id": fill_id,
                },
            )

        logger.info(
            "process_fill: order_id=%s fill_id=%s qty=%s -> status=%s",
            fill_data.order_id,
            fill_id,
            fill_data.fill_qty,
            to_status,
        )
        return fill_id

    # ------------------------------------------------------------------
    # update_order_status
    # ------------------------------------------------------------------

    @staticmethod
    def update_order_status(
        engine: Engine,
        order_id: str,
        new_status: str,
        reason: Optional[str] = None,
    ) -> None:
        """Validate and apply a status transition on a cmc_orders row.

        Raises ValueError if:
        - The order is not found.
        - The transition from the current status to new_status is not valid
          according to VALID_TRANSITIONS.
        """
        with engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT status FROM public.cmc_orders
                    WHERE order_id = :order_id
                    FOR UPDATE
                    """
                ),
                {"order_id": order_id},
            ).fetchone()

            if row is None:
                raise ValueError(f"cmc_orders row not found for order_id={order_id!r}")

            current_status = row.status
            allowed = VALID_TRANSITIONS.get(current_status, [])

            if new_status not in allowed:
                raise ValueError(
                    f"Invalid order status transition: {current_status!r} -> {new_status!r}. "
                    f"Allowed transitions from {current_status!r}: {allowed}"
                )

            conn.execute(
                text(
                    """
                    UPDATE public.cmc_orders
                    SET status = :status, updated_at = now()
                    WHERE order_id = :order_id
                    """
                ),
                {"status": new_status, "order_id": order_id},
            )

            conn.execute(
                text(
                    """
                    INSERT INTO public.cmc_order_events (
                        event_id, order_id, from_status, to_status, reason
                    ) VALUES (
                        :event_id, :order_id, :from_status, :to_status, :reason
                    )
                    """
                ),
                {
                    "event_id": str(uuid.uuid4()),
                    "order_id": order_id,
                    "from_status": current_status,
                    "to_status": new_status,
                    "reason": reason,
                },
            )

        logger.info(
            "update_order_status: order_id=%s %s -> %s",
            order_id,
            current_status,
            new_status,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_fill_transition(from_status: str, fill_qty: Decimal, order) -> None:
        """Raise ValueError if the fill is not valid given current order state."""
        if from_status in _TERMINAL_STATUSES:
            raise ValueError(f"Cannot fill order in terminal status={from_status!r}")

        remaining = Decimal(str(order.remaining_qty))
        if fill_qty > remaining:
            raise ValueError(
                f"fill_qty={fill_qty} exceeds remaining_qty={remaining} "
                f"for order_id={order.order_id!r}"
            )

    @staticmethod
    def _write_dead_letter(
        engine: Engine,
        operation_type: str,
        order_id: Optional[str],
        payload_dict: dict,
        exc: Exception,
    ) -> None:
        """Write a dead-letter record using a SEPARATE engine.begin() connection.

        This ensures the DLQ write cannot be rolled back by the original
        transaction failure. Uses its own connection so it always commits.
        """
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        """
                        INSERT INTO public.cmc_order_dead_letter (
                            dlq_id, operation_type, order_id, payload,
                            error_reason, error_stacktrace
                        ) VALUES (
                            :dlq_id, :operation_type, :order_id, :payload,
                            :error_reason, :error_stacktrace
                        )
                        """
                    ),
                    {
                        "dlq_id": str(uuid.uuid4()),
                        "operation_type": operation_type,
                        "order_id": order_id,
                        "payload": json.dumps(payload_dict),
                        "error_reason": str(exc),
                        "error_stacktrace": traceback.format_exc(),
                    },
                )
            logger.info(
                "_write_dead_letter: recorded failure for operation_type=%s order_id=%s",
                operation_type,
                order_id,
            )
        except Exception as dlq_exc:
            logger.critical(
                "_write_dead_letter FAILED (DLQ write error) for operation_type=%s "
                "order_id=%s: %s",
                operation_type,
                order_id,
                dlq_exc,
            )
