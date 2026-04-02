"""
StopMonitor - Real-time stop-loss and take-profit monitor for open positions.

Runs as a daemon thread that polls the PriceCache every ~1 second.  For any
open position that has a stop_price or take_profit price set (recorded on the
associated orders row), it compares the live price from PriceCache and triggers
a close order when the threshold is crossed.

Trigger logic
-------------
* **Stop-loss (stop):** Triggers when price <= stop_price (long) or
  price >= stop_price (short).
* **Take-profit (tp):** Triggers when price >= tp_price (long) or
  price <= tp_price (short).

On trigger, StopMonitor:
1. Creates a market close order directly in ``orders`` with status ``'created'``
   then immediately advances to ``'submitted'``.
2. Calls ``OrderManager.process_fill`` with the current live price (plus a
   configurable slippage bps).
3. Sends a Telegram alert with the outcome.
4. Marks the triggering order row as ``'cancelled'`` (the original stop/TP
   order is superseded by the fill) so it is not re-triggered.

Thread-safety
-------------
* PriceCache is RLock-protected (all reads are safe from any thread).
* DB writes go through ``OrderManager`` which uses ``engine.begin()``
  (atomic per operation).
* A set ``_pending_triggers`` tracks in-flight asset_ids so that two
  concurrent iterations cannot double-trigger the same position.  The set
  is protected by a ``threading.Lock``.

Symbol resolution
-----------------
Asset symbols are loaded once at startup via ``_load_asset_symbol_map``:
``SELECT id, symbol FROM public.dim_assets``

Exports: StopMonitor
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.executor.price_cache import PriceCache
from ta_lab2.notifications import telegram
from ta_lab2.trading.order_manager import FillData, OrderManager

__all__ = ["StopMonitor"]

logger = logging.getLogger(__name__)

# Default slippage applied to stop/TP fills (basis points).
_DEFAULT_SLIPPAGE_BPS = Decimal("5")  # 0.05 %

# How often to reload the open-position list from DB (seconds).
# Between refreshes, positions are re-checked against the in-memory snapshot.
_POSITION_REFRESH_INTERVAL = 10.0  # seconds


def _load_asset_symbol_map(engine: Engine) -> dict[int, str]:
    """Load id -> symbol mapping from dim_assets.

    Returns an empty dict on failure (non-fatal; symbol will show as 'id=N').
    """
    sql = text("SELECT id, symbol FROM public.dim_assets ORDER BY id")
    try:
        with engine.connect() as conn:
            rows = conn.execute(sql).fetchall()
        return {int(r.id): str(r.symbol) for r in rows}
    except Exception as exc:  # noqa: BLE001
        logger.warning("StopMonitor: could not load dim_assets symbol map: %s", exc)
        return {}


def _apply_slippage(price: Decimal, side: str, slippage_bps: Decimal) -> Decimal:
    """Apply slippage to a fill price.

    For a close sell (long position stop/TP), slippage reduces the fill price.
    For a close buy (short position stop/TP), slippage increases the fill price.
    """
    factor = slippage_bps / Decimal("10000")
    if side == "sell":
        return price * (Decimal("1") - factor)
    return price * (Decimal("1") + factor)


class StopMonitor(threading.Thread):
    """Daemon thread that monitors open positions for stop/TP triggers.

    Parameters
    ----------
    engine : Engine
        SQLAlchemy engine (NullPool recommended for long-running processes).
    price_cache : PriceCache
        Shared thread-safe price cache populated by WebSocket feeds.
    poll_interval_secs : float
        How often to scan all open positions, in seconds.  Default 1.0.
    slippage_bps : Decimal
        Slippage applied to each triggered fill, in basis points.  Default 5.
    strategy_id : int
        Strategy identifier written to fill records.  Default 0.

    Usage
    -----
    monitor = StopMonitor(engine, price_cache)
    monitor.start()
    # ... runs until monitor.stop() is called or process exits
    monitor.stop()
    monitor.join(timeout=5)
    """

    def __init__(
        self,
        engine: Engine,
        price_cache: PriceCache,
        poll_interval_secs: float = 1.0,
        slippage_bps: Decimal = _DEFAULT_SLIPPAGE_BPS,
        strategy_id: int = 0,
    ) -> None:
        super().__init__(daemon=True, name="StopMonitor")
        self.engine = engine
        self.price_cache = price_cache
        self.poll_interval = poll_interval_secs
        self.slippage_bps = slippage_bps
        self.strategy_id = strategy_id

        self._stop_event = threading.Event()
        self._pending_lock = threading.Lock()
        # asset_ids currently being triggered (prevents double-trigger)
        self._pending_triggers: set[int] = set()

        # Cached symbol map (refreshed at startup)
        self._symbol_map: dict[int, str] = {}
        # Cached open stop/TP orders; refreshed every _POSITION_REFRESH_INTERVAL s
        self._open_orders: list[dict[str, Any]] = []
        self._last_order_refresh: float = 0.0

    # ------------------------------------------------------------------
    # Public control API
    # ------------------------------------------------------------------

    def start(self) -> "StopMonitor":  # type: ignore[override]
        """Start the monitor thread and return self (for chaining)."""
        self._symbol_map = _load_asset_symbol_map(self.engine)
        logger.info("StopMonitor: loaded %d asset symbols", len(self._symbol_map))
        super().start()
        logger.info(
            "StopMonitor: daemon thread started (poll=%.1fs)", self.poll_interval
        )
        return self

    def stop(self) -> None:
        """Signal the monitor thread to exit on its next iteration."""
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Thread entry point — runs until stop() is called."""
        logger.info("StopMonitor: entering run loop")
        while not self._stop_event.is_set():
            try:
                self._check_all_positions()
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "StopMonitor: unhandled error in _check_all_positions: %s", exc
                )
            self._stop_event.wait(timeout=self.poll_interval)
        logger.info("StopMonitor: run loop exited cleanly")

    # ------------------------------------------------------------------
    # Position loading
    # ------------------------------------------------------------------

    def _maybe_refresh_orders(self) -> None:
        """Refresh the cached open stop/TP orders if TTL has elapsed."""
        now = time.monotonic()
        if now - self._last_order_refresh < _POSITION_REFRESH_INTERVAL:
            return
        try:
            self._open_orders = self._load_open_stop_tp_orders()
            self._last_order_refresh = now
            logger.debug(
                "StopMonitor: refreshed order cache — %d open stop/TP orders",
                len(self._open_orders),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("StopMonitor: order cache refresh failed: %s", exc)

    def _load_open_stop_tp_orders(self) -> list[dict[str, Any]]:
        """Load orders with stop or TP prices that are still open (not filled/cancelled).

        Joins positions to ensure the position is actually open (qty != 0).

        Returns a list of dicts with keys:
            order_id, asset_id, side, stop_price, tp_price,
            quantity, avg_cost_basis, exchange, strategy_id
        """
        sql = text(
            """
            SELECT
                o.order_id,
                o.asset_id,
                o.side,
                o.stop_price,
                o.limit_price  AS tp_price,
                p.quantity,
                p.avg_cost_basis,
                o.exchange,
                p.strategy_id
            FROM public.orders o
            JOIN public.positions p
                ON  p.asset_id    = o.asset_id
                AND p.exchange    = o.exchange
                AND p.strategy_id = :strategy_id
            WHERE
                o.status NOT IN ('filled', 'cancelled', 'rejected', 'expired')
                AND p.quantity != 0
                AND (o.stop_price IS NOT NULL OR o.limit_price IS NOT NULL)
                AND o.order_type IN ('stop', 'limit', 'stop_limit', 'market')
            ORDER BY o.asset_id
            """
        )
        with self.engine.connect() as conn:
            rows = conn.execute(sql, {"strategy_id": self.strategy_id}).fetchall()

        result = []
        for r in rows:
            result.append(
                {
                    "order_id": str(r.order_id),
                    "asset_id": int(r.asset_id),
                    "side": str(r.side),
                    "stop_price": Decimal(str(r.stop_price))
                    if r.stop_price is not None
                    else None,
                    "tp_price": Decimal(str(r.tp_price))
                    if r.tp_price is not None
                    else None,
                    "quantity": Decimal(str(r.quantity)),
                    "avg_cost_basis": Decimal(str(r.avg_cost_basis))
                    if r.avg_cost_basis
                    else Decimal("0"),
                    "exchange": str(r.exchange),
                    "strategy_id": int(r.strategy_id),
                }
            )
        return result

    # ------------------------------------------------------------------
    # Check loop
    # ------------------------------------------------------------------

    def _check_all_positions(self) -> None:
        """Scan cached open stop/TP orders against PriceCache prices."""
        self._maybe_refresh_orders()

        for order in self._open_orders:
            asset_id = order["asset_id"]
            symbol = self._symbol_map.get(asset_id, f"id={asset_id}")

            # Skip assets already being triggered
            with self._pending_lock:
                if asset_id in self._pending_triggers:
                    continue

            price = self.price_cache.get(symbol)
            if price is None:
                logger.debug(
                    "StopMonitor: no price in cache for symbol=%s (asset_id=%s), skipping",
                    symbol,
                    asset_id,
                )
                continue

            trigger_type = self._detect_trigger(order, price)
            if trigger_type is None:
                continue

            # Mark as pending before spawning trigger to prevent race
            with self._pending_lock:
                self._pending_triggers.add(asset_id)

            try:
                self._trigger_stop_tp(order, price, symbol, trigger_type)
            except Exception as exc:  # noqa: BLE001
                logger.exception(
                    "StopMonitor: trigger failed for asset_id=%s trigger=%s: %s",
                    asset_id,
                    trigger_type,
                    exc,
                )
            finally:
                with self._pending_lock:
                    self._pending_triggers.discard(asset_id)

    def _detect_trigger(self, order: dict[str, Any], price: Decimal) -> str | None:
        """Return 'STOP', 'TP', or None based on current price vs thresholds.

        Convention:
          - side='buy' means a LONG position (opened via buy order).
          - side='sell' means a SHORT position (opened via sell order).
        For a long:  STOP triggers when price <= stop_price
                     TP triggers when price >= tp_price
        For a short: STOP triggers when price >= stop_price
                     TP triggers when price <= tp_price
        """
        is_long = order["side"] == "buy"
        stop_price = order["stop_price"]
        tp_price = order["tp_price"]

        if stop_price is not None:
            if is_long and price <= stop_price:
                return "STOP"
            if not is_long and price >= stop_price:
                return "STOP"

        if tp_price is not None:
            if is_long and price >= tp_price:
                return "TP"
            if not is_long and price <= tp_price:
                return "TP"

        return None

    # ------------------------------------------------------------------
    # Trigger execution
    # ------------------------------------------------------------------

    def _trigger_stop_tp(
        self,
        order: dict[str, Any],
        price: Decimal,
        symbol: str,
        trigger_type: str,
    ) -> None:
        """Execute a stop or TP trigger atomically.

        Steps:
        1. Create a market close order in ``orders``.
        2. Process fill via OrderManager (applies slippage, updates positions).
        3. Cancel the original stop/TP order row.
        4. Send Telegram alert.
        5. Invalidate cached order list so it refreshes on next iteration.
        """
        asset_id = order["asset_id"]
        original_order_id = order["order_id"]
        quantity = order["quantity"]
        avg_cost = order["avg_cost_basis"]
        exchange = order["exchange"]
        strategy_id = order["strategy_id"]

        # Close side is opposite of the position side
        is_long = order["side"] == "buy"
        close_side = "sell" if is_long else "buy"
        close_qty = abs(quantity)

        # Apply slippage to fill price
        fill_price = _apply_slippage(price, close_side, self.slippage_bps)

        logger.info(
            "StopMonitor: triggering %s for asset_id=%s symbol=%s "
            "price=%s fill_price=%s qty=%s side=%s",
            trigger_type,
            asset_id,
            symbol,
            price,
            fill_price,
            close_qty,
            close_side,
        )

        try:
            close_order_id = self._create_close_order(
                asset_id=asset_id,
                exchange=exchange,
                side=close_side,
                quantity=close_qty,
                fill_price=fill_price,
                trigger_type=trigger_type,
            )
        except Exception as exc:
            logger.error(
                "StopMonitor: could not create close order for asset_id=%s: %s",
                asset_id,
                exc,
            )
            raise

        # Process fill
        fill_data = FillData(
            order_id=close_order_id,
            fill_qty=close_qty,
            fill_price=fill_price,
            fee_amount=Decimal("0"),
            exchange_fill_id=str(uuid.uuid4()),
            filled_at=datetime.now(timezone.utc),
            strategy_id=strategy_id,
        )

        try:
            fill_id = OrderManager.process_fill(self.engine, fill_data)
        except Exception as exc:
            logger.error(
                "StopMonitor: process_fill failed for asset_id=%s order=%s: %s",
                asset_id,
                close_order_id,
                exc,
            )
            raise

        # Cancel the original stop/TP order (no longer needed)
        try:
            self._cancel_original_order(original_order_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "StopMonitor: could not cancel original order %s: %s",
                original_order_id,
                exc,
            )

        # Compute unrealized PnL at trigger (for alert context)
        if is_long:
            pnl = (fill_price - avg_cost) * close_qty
        else:
            pnl = (avg_cost - fill_price) * close_qty
        pnl_str = f"{'+' if pnl >= 0 else ''}{float(pnl):.2f}"

        alert_text = (
            f"[{trigger_type}] {symbol} triggered at {float(price):.4f} | "
            f"Qty: {float(close_qty):.6f} | Fill: {float(fill_price):.4f} | "
            f"PnL: {pnl_str}"
        )
        logger.info("StopMonitor: %s", alert_text)
        telegram.send_alert(
            title=f"{trigger_type} Triggered",
            message=alert_text,
            severity="warning" if trigger_type == "STOP" else "info",
        )

        logger.info(
            "StopMonitor: %s complete — asset_id=%s fill_id=%s",
            trigger_type,
            asset_id,
            fill_id,
        )

        # Force order cache refresh on next iteration
        self._last_order_refresh = 0.0

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    def _create_close_order(
        self,
        asset_id: int,
        exchange: str,
        side: str,
        quantity: Decimal,
        fill_price: Decimal,
        trigger_type: str,
    ) -> str:
        """Insert a market close order and immediately set status to 'submitted'.

        Returns the new order_id (UUID string).
        """
        order_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        note = f"stop_monitor_{trigger_type.lower()}"

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO public.orders (
                        order_id, asset_id, exchange, side, order_type, quantity,
                        status, filled_qty, remaining_qty, environment,
                        client_order_id, created_at, updated_at
                    ) VALUES (
                        :order_id, :asset_id, :exchange, :side, 'market', :quantity,
                        'submitted', 0, :quantity, 'live',
                        :client_order_id, :now, :now
                    )
                    """
                ),
                {
                    "order_id": order_id,
                    "asset_id": asset_id,
                    "exchange": exchange,
                    "side": side,
                    "quantity": str(quantity),
                    "client_order_id": note,
                    "now": now,
                },
            )
            # Audit event: created
            conn.execute(
                text(
                    """
                    INSERT INTO public.order_events (
                        event_id, order_id, from_status, to_status, reason
                    ) VALUES (
                        :event_id, :order_id, NULL, 'submitted', :reason
                    )
                    """
                ),
                {
                    "event_id": str(uuid.uuid4()),
                    "order_id": order_id,
                    "reason": f"stop_monitor auto-close ({trigger_type})",
                },
            )

        logger.debug(
            "StopMonitor: created close order order_id=%s asset_id=%s side=%s qty=%s",
            order_id,
            asset_id,
            side,
            quantity,
        )
        return order_id

    def _cancel_original_order(self, order_id: str) -> None:
        """Cancel the original stop/TP order so it is not re-triggered."""
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE public.orders
                    SET status = 'cancelled', updated_at = now()
                    WHERE order_id = :order_id
                      AND status NOT IN ('filled', 'cancelled', 'rejected', 'expired')
                    """
                ),
                {"order_id": order_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO public.order_events (
                        event_id, order_id, from_status, to_status, reason
                    ) VALUES (
                        :event_id, :order_id, 'submitted', 'cancelled',
                        'stop_monitor: superseded by triggered fill'
                    )
                    """
                ),
                {
                    "event_id": str(uuid.uuid4()),
                    "order_id": order_id,
                },
            )
        logger.debug("StopMonitor: cancelled original order %s", order_id)
