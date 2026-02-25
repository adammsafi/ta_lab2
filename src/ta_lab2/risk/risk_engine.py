"""
RiskEngine: Order-level risk gate for paper trading.

Checks every order through 6 sequential gates before allowing execution:
  1.  Kill switch -- immediate block if trading is halted
  1.5 Tail risk -- block if FLATTEN, halve buy qty if REDUCE
  2.  Circuit breaker -- block if per-strategy breaker is tripped
  3.  Per-asset position cap -- scale down quantity if it would exceed max_position_pct
  4.  Portfolio utilization cap -- scale down if total exposure would exceed max_portfolio_pct
  5.  All pass -- allow with (possibly adjusted) quantity

Limits are hot-reloaded from dim_risk_limits on each check_order() call.
State (kill switch, circuit breaker, tail risk) is read from dim_risk_state.

Usage:
    from sqlalchemy import create_engine
    from ta_lab2.risk import RiskEngine

    engine = create_engine(db_url)
    re = RiskEngine(engine)
    result = re.check_order(
        order_qty=Decimal("0.5"),
        order_side="buy",
        fill_price=Decimal("50000"),
        asset_id=1,
        strategy_id=1,
        current_position_value=Decimal("5000"),
        portfolio_value=Decimal("100000"),
    )
    if result.allowed:
        # use result.adjusted_quantity
        ...
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

if TYPE_CHECKING:
    from ta_lab2.risk.flatten_trigger import FlattenTriggerResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional Telegram import -- gracefully degrade if not configured
# ---------------------------------------------------------------------------
try:
    from ta_lab2.notifications.telegram import (
        send_critical_alert as _send_critical_alert,
    )

    _TELEGRAM_AVAILABLE = True
except ImportError:
    _send_critical_alert = None  # type: ignore[assignment]
    _TELEGRAM_AVAILABLE = False


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RiskLimits:
    """
    Risk limit parameters loaded from dim_risk_limits.

    Defaults match the DB seed row (portfolio-wide defaults).
    """

    max_position_pct: float = 0.15
    """Maximum single-asset position as a fraction of portfolio value."""

    max_portfolio_pct: float = 0.80
    """Maximum total portfolio utilization fraction."""

    daily_loss_pct_threshold: float = 0.03
    """Kill switch triggers when daily drawdown exceeds this fraction."""

    cb_consecutive_losses_n: int = 3
    """Number of consecutive losses before circuit breaker trips."""

    cb_loss_threshold_pct: float = 0.0
    """Minimum loss size that counts as a qualifying loss (0 = any loss)."""

    cb_cooldown_hours: float = 24.0
    """Hours before an auto-tripped circuit breaker auto-resets."""

    allow_overrides: bool = True
    """Whether discretionary overrides are permitted for this scope."""


@dataclass
class RiskCheckResult:
    """
    Result of RiskEngine.check_order().

    When allowed=True, adjusted_quantity holds the (possibly scaled) order size.
    When allowed=False, blocked_reason explains why.
    """

    allowed: bool
    adjusted_quantity: Optional[Decimal] = None
    blocked_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# RiskEngine
# ---------------------------------------------------------------------------


class RiskEngine:
    """
    Order-level risk gate. Call check_order() before every paper order submission.

    The engine is stateless across calls except for the injected SQLAlchemy engine.
    All reads are fresh per-call to capture live state changes.

    Executor integration (Phase 45 wiring):
    ----------------------------------------
    The paper trading executor (ta_lab2.scripts.paper_trading.executor) should
    integrate RiskEngine as follows:

        1. Instantiate once at executor startup::

               from ta_lab2.risk import RiskEngine
               risk = RiskEngine(db_engine)

        2. Call check_order() before every order submission::

               result = risk.check_order(
                   order_qty=signal_qty,
                   order_side=signal_side,
                   fill_price=mid_price,
                   asset_id=asset_id,
                   strategy_id=strategy_id,
                   current_position_value=pos_value,
                   portfolio_value=portfolio_value,
               )
               if not result.allowed:
                   logger.warning("Order blocked: %s", result.blocked_reason)
                   return
               qty_to_submit = result.adjusted_quantity

        2b. Gate 1.5 (tail risk) is checked automatically inside check_order().
            No separate call needed. FLATTEN blocks all orders; REDUCE halves buy qty.

        3. Call check_daily_loss() once per trading day (e.g., at session open)
           to auto-trigger the kill switch on drawdown threshold breach::

               if risk.check_daily_loss():
                   logger.critical("Daily loss kill switch triggered")
                   return

        4. Call update_circuit_breaker() after each closed trade::

               risk.update_circuit_breaker(
                   strategy_id=strategy_id,
                   realized_pnl=trade_pnl,
                   asset_id=asset_id,
               )

    The executor must NOT cache the kill switch state -- check_order() reads fresh
    state on every call, ensuring CLI-triggered halts take effect immediately.
    """

    def __init__(self, engine: Engine) -> None:
        """
        Initialise RiskEngine.

        Args:
            engine: SQLAlchemy Engine connected to the paper trading database.
        """
        self._engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_order(
        self,
        order_qty: Decimal,
        order_side: str,
        fill_price: Decimal,
        asset_id: int,
        strategy_id: int,
        current_position_value: Decimal,
        portfolio_value: Decimal,
    ) -> RiskCheckResult:
        """
        Run order through all 5 risk gates.

        Gates are checked in priority order. The first blocking gate short-circuits
        the remaining checks. Position/portfolio cap gates scale down quantity rather
        than outright rejecting (unless the position is already exhausted).

        Args:
            order_qty: Requested order size (in base asset units, e.g. BTC).
            order_side: "buy" or "sell".
            fill_price: Expected fill price (used to compute order notional value).
            asset_id: Asset ID (matches cmc_assets.id).
            strategy_id: Strategy ID generating the signal.
            current_position_value: Current position notional for this asset.
            portfolio_value: Total portfolio notional value.

        Returns:
            RiskCheckResult with allowed flag, adjusted_quantity, and blocked_reason.
        """
        order_notional = order_qty * fill_price

        # Gate 1: Kill switch -- fast exit before any DB reads
        if self._is_halted():
            self._log_event(
                event_type="kill_switch_activated",
                trigger_source="system",
                reason="Order blocked by active kill switch",
                asset_id=asset_id,
                strategy_id=strategy_id,
                metadata={"order_qty": str(order_qty), "order_side": order_side},
            )
            return RiskCheckResult(
                allowed=False,
                blocked_reason="Kill switch active -- trading halted",
            )

        # Gate 1.5: Tail risk state
        tail_state, size_mult = self.check_tail_risk_state(asset_id, strategy_id)
        if tail_state == "flatten":
            self._log_event(
                event_type="tail_risk_escalated",
                trigger_source="tail_risk",
                reason="Order blocked by tail risk FLATTEN state",
                asset_id=asset_id,
                strategy_id=strategy_id,
                metadata={"tail_risk_state": "flatten", "order_side": order_side},
            )
            return RiskCheckResult(
                allowed=False,
                blocked_reason="Tail risk: FLATTEN state active -- all new orders blocked",
            )
        if tail_state == "reduce" and order_side.lower() == "buy":
            # Halve buy order quantity in REDUCE state
            order_qty = (order_qty * Decimal(str(size_mult))).quantize(
                Decimal("0.00000001")
            )
            order_notional = order_qty * fill_price
            logger.info("Tail risk REDUCE: buy order quantity halved to %s", order_qty)

        # Gate 2: Circuit breaker
        cb_key = f"{asset_id}:{strategy_id}"
        if self._is_circuit_breaker_tripped(
            cb_key, asset_id=asset_id, strategy_id=strategy_id
        ):
            return RiskCheckResult(
                allowed=False,
                blocked_reason=f"Circuit breaker tripped for asset_id={asset_id} strategy_id={strategy_id}",
            )

        # Gate 3: Load limits (hot-reload)
        limits = self._load_limits(asset_id=asset_id, strategy_id=strategy_id)

        # Gates 3-4 only apply to buy orders (sells reduce exposure)
        if order_side.lower() == "buy":
            # Gate 3: Per-asset position cap
            max_position_value = portfolio_value * Decimal(str(limits.max_position_pct))
            projected_position = current_position_value + order_notional

            if current_position_value >= max_position_value:
                # Already at or over cap
                self._log_event(
                    event_type="position_cap_blocked",
                    trigger_source="system",
                    reason=(
                        f"Position cap exhausted: current={current_position_value} "
                        f">= max={max_position_value:.2f} (portfolio={portfolio_value} "
                        f"x {limits.max_position_pct:.0%})"
                    ),
                    asset_id=asset_id,
                    strategy_id=strategy_id,
                    metadata={
                        "order_qty": str(order_qty),
                        "current_position_value": str(current_position_value),
                        "max_position_value": str(max_position_value),
                    },
                )
                return RiskCheckResult(
                    allowed=False,
                    blocked_reason=(
                        f"Position cap exhausted for asset_id={asset_id}: "
                        f"current={current_position_value} >= cap={max_position_value:.2f}"
                    ),
                )

            if projected_position > max_position_value:
                # Scale down to fit within cap
                available_capacity = max_position_value - current_position_value
                scaled_qty = (available_capacity / fill_price).quantize(
                    Decimal("0.00000001")
                )
                self._log_event(
                    event_type="position_cap_scaled",
                    trigger_source="system",
                    reason=(
                        f"Order scaled from {order_qty} to {scaled_qty} to fit "
                        f"position cap {limits.max_position_pct:.0%}"
                    ),
                    asset_id=asset_id,
                    strategy_id=strategy_id,
                    metadata={
                        "original_qty": str(order_qty),
                        "scaled_qty": str(scaled_qty),
                        "available_capacity": str(available_capacity),
                    },
                )
                order_qty = scaled_qty
                order_notional = order_qty * fill_price

            # Gate 4: Portfolio utilization cap
            max_portfolio_value = portfolio_value * Decimal(
                str(limits.max_portfolio_pct)
            )
            # Approximate: treat current_position_value as this asset's contribution
            # The caller provides portfolio_value as current total utilization
            if order_notional > (portfolio_value - current_position_value) * Decimal(
                str(limits.max_portfolio_pct)
            ):
                # Scale down to remaining portfolio capacity
                remaining_capacity = max_portfolio_value - current_position_value
                if remaining_capacity <= Decimal("0"):
                    return RiskCheckResult(
                        allowed=False,
                        blocked_reason=(
                            f"Portfolio utilization cap exhausted: "
                            f"max={max_portfolio_value:.2f} already reached"
                        ),
                    )
                scaled_qty = (remaining_capacity / fill_price).quantize(
                    Decimal("0.00000001")
                )
                if scaled_qty < order_qty:
                    order_qty = scaled_qty

        # Gate 5: All pass
        return RiskCheckResult(
            allowed=True,
            adjusted_quantity=order_qty,
        )

    def check_tail_risk_state(
        self,
        asset_id: Optional[int] = None,
        strategy_id: Optional[int] = None,
    ) -> tuple[str, float]:
        """
        Read tail_risk_state from dim_risk_state.

        Returns (state, size_multiplier):
          ('normal', 1.0)  -- no change to order sizing
          ('reduce', 0.5)  -- halve buy order quantities
          ('flatten', 0.0) -- block all new orders

        Args:
            asset_id:    Unused (reserved for future asset-specific tail risk).
            strategy_id: Unused (reserved for future strategy-specific tail risk).

        Returns:
            Tuple of (state_string, size_multiplier_float).
        """
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT tail_risk_state FROM dim_risk_state WHERE state_id = 1")
            ).fetchone()
        if row is None or row[0] == "normal":
            return ("normal", 1.0)
        if row[0] == "reduce":
            return ("reduce", 0.5)
        if row[0] == "flatten":
            return ("flatten", 0.0)
        return ("normal", 1.0)  # safe default for unexpected values

    def evaluate_tail_risk_state(
        self,
        asset_id: int = 1,
        api_healthy: bool = True,
        correlation_30d: Optional[float] = None,
    ) -> "FlattenTriggerResult":
        """
        Daily tail risk evaluation.

        Reads current 20d rolling vol and latest daily return from the returns table,
        computes the trigger state via check_flatten_trigger(), applies cooldown logic
        for de-escalation, and updates dim_risk_state if the state has changed.

        De-escalation requirements (prevents premature clearing):
          FLATTEN -> REDUCE:  21-day cooldown AND 3 consecutive days of vol below reduce threshold
          REDUCE  -> NORMAL:  14-day cooldown AND 3 consecutive days of vol below reduce threshold
        Escalation is immediate (no cooldown).

        Call once per day from run_daily_refresh.py or the executor daily cycle.

        Args:
            asset_id:        Asset ID to use as the market proxy (default 1 = BTC).
            api_healthy:     Pass False if the exchange API is unreachable.
            correlation_30d: Current BTC/ETH 30d rolling correlation, or None to skip check.

        Returns:
            FlattenTriggerResult describing the current (possibly held) state.
        """
        from ta_lab2.risk.flatten_trigger import (
            EscalationState,
            FlattenTriggerResult,
            check_flatten_trigger,
        )

        # 1. Read current state from DB
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                SELECT tail_risk_state, tail_risk_triggered_at, tail_risk_cleared_at
                FROM dim_risk_state WHERE state_id = 1
                """
                )
            ).fetchone()

        current_state = row[0] if row else "normal"
        triggered_at = row[1] if row else None

        # 2. Load market data: latest daily return and 20 bars for rolling vol
        with self._engine.connect() as conn:
            ret_row = conn.execute(
                text(
                    """
                SELECT ret_arith FROM cmc_returns_bars_multi_tf_u
                WHERE id = :asset_id AND tf = '1D' AND ret_arith IS NOT NULL
                ORDER BY "timestamp" DESC LIMIT 1
                """
                ),
                {"asset_id": asset_id},
            ).fetchone()

            vol_rows = conn.execute(
                text(
                    """
                SELECT ret_arith FROM cmc_returns_bars_multi_tf_u
                WHERE id = :asset_id AND tf = '1D' AND ret_arith IS NOT NULL
                ORDER BY "timestamp" DESC LIMIT 20
                """
                ),
                {"asset_id": asset_id},
            ).fetchall()

        if ret_row is None or len(vol_rows) < 20:
            logger.warning(
                "Insufficient data for tail risk evaluation (need 20 bars, got %d)",
                len(vol_rows) if vol_rows else 0,
            )
            return FlattenTriggerResult(
                state=EscalationState(current_state),
                trigger_type=None,
                trigger_value=None,
                threshold_used=0.0,
                details="Insufficient data for evaluation",
            )

        import numpy as np

        latest_return = float(ret_row[0])
        rolling_vol = float(np.std([float(r[0]) for r in vol_rows]))

        # 3. Evaluate trigger conditions
        trigger_result = check_flatten_trigger(
            rolling_vol_20d=rolling_vol,
            latest_daily_return=latest_return,
            api_healthy=api_healthy,
            correlation_30d=correlation_30d,
        )

        new_state = trigger_result.state.value

        # 4. Apply cooldown logic for de-escalation
        # Escalation (normal->reduce, reduce->flatten, normal->flatten) is always immediate.
        # De-escalation requires BOTH cooldown elapsed AND 3 consecutive clear vol days.
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        state_order = {"normal": 0, "reduce": 1, "flatten": 2}

        if state_order.get(new_state, 0) < state_order.get(current_state, 0):
            # De-escalation requested -- apply cooldown gates
            cooldown_days = 21 if current_state == "flatten" else 14

            cooldown_met = False
            if triggered_at is not None:
                elapsed = (now - triggered_at).days
                cooldown_met = elapsed >= cooldown_days
            else:
                cooldown_met = True  # no triggered_at means safe to de-escalate

            # Check 3-consecutive-day vol requirement (only if cooldown passed)
            vol_clear_met = False
            if cooldown_met:
                with self._engine.connect() as conn:
                    # Load 23 bars to compute rolling 20d vol for 3 trailing days
                    recent_rows = conn.execute(
                        text(
                            """
                        SELECT ret_arith FROM cmc_returns_bars_multi_tf_u
                        WHERE id = :asset_id AND tf = '1D' AND ret_arith IS NOT NULL
                        ORDER BY "timestamp" DESC LIMIT 23
                        """
                        ),
                        {"asset_id": asset_id},
                    ).fetchall()

                if len(recent_rows) >= 22:
                    all_rets = [float(r[0]) for r in recent_rows]
                    reduce_threshold = 0.0923  # default reduce_vol_threshold
                    consecutive_clear = 0
                    for offset in range(3):
                        window = all_rets[offset : offset + 20]
                        if len(window) == 20:
                            vol_day = float(np.std(window))
                            if vol_day < reduce_threshold:
                                consecutive_clear += 1
                            else:
                                break
                    vol_clear_met = consecutive_clear >= 3
                    logger.info(
                        "Tail risk de-escalation vol check: %d/3 consecutive days below threshold (%.4f)",
                        consecutive_clear,
                        reduce_threshold,
                    )
                else:
                    logger.info(
                        "Insufficient data for 3-day vol clear check (need 23 bars, got %d)",
                        len(recent_rows),
                    )

            if not cooldown_met:
                elapsed = (now - triggered_at).days if triggered_at else 0
                logger.info(
                    "Tail risk de-escalation blocked by cooldown: %d/%d days elapsed",
                    elapsed,
                    cooldown_days,
                )
                new_state = current_state
                trigger_result = FlattenTriggerResult(
                    state=EscalationState(current_state),
                    trigger_type=trigger_result.trigger_type,
                    trigger_value=trigger_result.trigger_value,
                    threshold_used=trigger_result.threshold_used,
                    details=f"De-escalation blocked by cooldown ({elapsed}/{cooldown_days} days)",
                )
            elif not vol_clear_met:
                logger.info(
                    "Tail risk de-escalation blocked: vol not below threshold for 3 consecutive days",
                )
                new_state = current_state
                trigger_result = FlattenTriggerResult(
                    state=EscalationState(current_state),
                    trigger_type=trigger_result.trigger_type,
                    trigger_value=trigger_result.trigger_value,
                    threshold_used=trigger_result.threshold_used,
                    details="De-escalation blocked: vol not below reduce threshold for 3 consecutive days",
                )

        # 5. Update DB if state changed
        if new_state != current_state:
            is_escalation = state_order.get(new_state, 0) > state_order.get(
                current_state, 0
            )
            with self._engine.begin() as conn:
                if is_escalation:
                    conn.execute(
                        text(
                            """
                        UPDATE dim_risk_state
                        SET tail_risk_state = :new_state,
                            tail_risk_triggered_at = :now,
                            tail_risk_trigger_reason = :reason,
                            updated_at = :now
                        WHERE state_id = 1
                        """
                        ),
                        {
                            "new_state": new_state,
                            "now": now,
                            "reason": trigger_result.details,
                        },
                    )
                else:
                    conn.execute(
                        text(
                            """
                        UPDATE dim_risk_state
                        SET tail_risk_state = :new_state,
                            tail_risk_cleared_at = :now,
                            tail_risk_trigger_reason = :reason,
                            updated_at = :now
                        WHERE state_id = 1
                        """
                        ),
                        {
                            "new_state": new_state,
                            "now": now,
                            "reason": trigger_result.details,
                        },
                    )

            event_type = "tail_risk_escalated" if is_escalation else "tail_risk_cleared"
            self._log_event(
                event_type=event_type,
                trigger_source="tail_risk",
                reason=(
                    f"State changed: {current_state} -> {new_state}. {trigger_result.details}"
                ),
                asset_id=asset_id,
                metadata={
                    "old_state": current_state,
                    "new_state": new_state,
                    "trigger_type": trigger_result.trigger_type,
                    "trigger_value": trigger_result.trigger_value,
                    "threshold_used": trigger_result.threshold_used,
                    "rolling_vol_20d": rolling_vol,
                    "latest_daily_return": latest_return,
                },
            )
            logger.warning(
                "Tail risk state changed: %s -> %s (%s)",
                current_state,
                new_state,
                trigger_result.details,
            )

        return trigger_result

    def check_daily_loss(self) -> bool:
        """
        Compute daily drawdown from day-open portfolio value and trigger kill switch if exceeded.

        Reads day_open_portfolio_value and last_day_open_date from dim_risk_state.
        If today's date is a new day, updates the day-open value from cmc_positions (if available).
        Computes drawdown as (day_open - current) / day_open.

        Returns:
            True if kill switch was triggered, False otherwise.
        """
        limits = self._load_limits()

        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                SELECT trading_state, day_open_portfolio_value, last_day_open_date
                FROM dim_risk_state
                WHERE state_id = 1
                """
                )
            ).fetchone()

        if row is None:
            logger.warning("dim_risk_state has no row -- skipping daily loss check")
            return False

        trading_state, day_open_value, last_day_open_date = row

        if trading_state == "halted":
            logger.debug("Trading already halted -- skipping daily loss check")
            return False

        if day_open_value is None:
            logger.debug(
                "day_open_portfolio_value not set -- skipping daily loss check"
            )
            return False

        # Try to get current portfolio value from cmc_positions
        current_value = self._compute_portfolio_value()
        if current_value is None:
            logger.debug(
                "Cannot compute current portfolio value -- skipping daily loss check"
            )
            return False

        day_open_value = Decimal(str(day_open_value))
        if day_open_value <= 0:
            return False

        drawdown = (day_open_value - current_value) / day_open_value
        threshold = Decimal(str(limits.daily_loss_pct_threshold))

        logger.debug(
            "Daily loss check: day_open=%s current=%s drawdown=%.4f threshold=%.4f",
            day_open_value,
            current_value,
            float(drawdown),
            float(threshold),
        )

        if drawdown >= threshold:
            logger.warning(
                "Daily loss threshold exceeded: drawdown=%.4f >= threshold=%.4f -- activating kill switch",
                float(drawdown),
                float(threshold),
            )
            from ta_lab2.risk.kill_switch import activate_kill_switch

            activate_kill_switch(
                engine=self._engine,
                reason=(
                    f"Daily loss stop triggered: drawdown={drawdown:.4f} "
                    f">= threshold={threshold:.4f}"
                ),
                trigger_source="daily_loss_stop",
            )
            return True

        return False

    def update_circuit_breaker(
        self,
        strategy_id: int,
        realized_pnl: Decimal,
        asset_id: Optional[int] = None,
    ) -> bool:
        """
        Record a completed trade result and trip the circuit breaker if N consecutive losses reached.

        A loss is any trade with realized_pnl < 0 (or below cb_loss_threshold_pct of notional).
        A profit resets the consecutive loss counter.

        Args:
            strategy_id: Strategy that produced the trade.
            realized_pnl: Realized PnL for the trade (negative = loss).
            asset_id: Optional asset scope (None = portfolio-level counter).

        Returns:
            True if circuit breaker was tripped, False otherwise.
        """
        limits = self._load_limits(asset_id=asset_id, strategy_id=strategy_id)
        cb_key = f"{asset_id}:{strategy_id}"

        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT cb_consecutive_losses FROM dim_risk_state WHERE state_id = 1"
                )
            ).fetchone()

        if row is None:
            return False

        cb_losses: dict = json.loads(row[0] or "{}")

        current_count = cb_losses.get(cb_key, 0)

        is_loss = realized_pnl < Decimal(str(limits.cb_loss_threshold_pct))

        if is_loss:
            new_count = current_count + 1
            cb_losses[cb_key] = new_count
            logger.debug(
                "Circuit breaker: key=%s count=%d -> %d",
                cb_key,
                current_count,
                new_count,
            )
        else:
            # Profit resets the counter
            if current_count > 0:
                logger.debug(
                    "Circuit breaker: key=%s profit resets count from %d to 0",
                    cb_key,
                    current_count,
                )
            cb_losses[cb_key] = 0
            new_count = 0

        # Persist updated counter
        with self._engine.connect() as conn:
            conn.execute(
                text(
                    """
                UPDATE dim_risk_state
                SET cb_consecutive_losses = :cb_losses, updated_at = now()
                WHERE state_id = 1
                """
                ),
                {"cb_losses": json.dumps(cb_losses)},
            )
            conn.commit()

        # Trip if N consecutive losses reached
        if is_loss and new_count >= limits.cb_consecutive_losses_n:
            logger.warning(
                "Circuit breaker tripped: key=%s reached %d consecutive losses (N=%d)",
                cb_key,
                new_count,
                limits.cb_consecutive_losses_n,
            )
            # Record trip timestamp
            with self._engine.connect() as conn:
                tripped_row = conn.execute(
                    text(
                        "SELECT cb_breaker_tripped_at FROM dim_risk_state WHERE state_id = 1"
                    )
                ).fetchone()
                cb_tripped: dict = json.loads(tripped_row[0] or "{}")
                cb_tripped[cb_key] = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    text(
                        """
                    UPDATE dim_risk_state
                    SET cb_breaker_tripped_at = :cb_tripped, updated_at = now()
                    WHERE state_id = 1
                    """
                    ),
                    {"cb_tripped": json.dumps(cb_tripped)},
                )
                conn.commit()

            self._log_event(
                event_type="circuit_breaker_tripped",
                trigger_source="circuit_breaker",
                reason=(
                    f"Circuit breaker tripped for key={cb_key}: "
                    f"{new_count} consecutive losses >= N={limits.cb_consecutive_losses_n}"
                ),
                asset_id=asset_id,
                strategy_id=strategy_id,
                metadata={
                    "consecutive_losses": new_count,
                    "n_threshold": limits.cb_consecutive_losses_n,
                    "realized_pnl": str(realized_pnl),
                },
            )
            return True

        return False

    def reset_circuit_breaker(
        self,
        strategy_id: int,
        reason: str,
        operator: str,
        asset_id: Optional[int] = None,
    ) -> None:
        """
        Manually reset circuit breaker for a given strategy (and optional asset).

        Args:
            strategy_id: Strategy to reset.
            reason: Human-readable reason for the reset.
            operator: Identity of the operator performing the reset.
            asset_id: Optional asset scope (None = portfolio-level counter).
        """
        cb_key = f"{asset_id}:{strategy_id}"

        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT cb_consecutive_losses, cb_breaker_tripped_at FROM dim_risk_state WHERE state_id = 1"
                )
            ).fetchone()

        if row is None:
            return

        cb_losses: dict = json.loads(row[0] or "{}")
        cb_tripped: dict = json.loads(row[1] or "{}")

        cb_losses[cb_key] = 0
        cb_tripped.pop(cb_key, None)

        with self._engine.connect() as conn:
            conn.execute(
                text(
                    """
                UPDATE dim_risk_state
                SET cb_consecutive_losses = :cb_losses,
                    cb_breaker_tripped_at = :cb_tripped,
                    updated_at = now()
                WHERE state_id = 1
                """
                ),
                {
                    "cb_losses": json.dumps(cb_losses),
                    "cb_tripped": json.dumps(cb_tripped),
                },
            )
            conn.commit()

        self._log_event(
            event_type="circuit_breaker_reset",
            trigger_source="manual",
            reason=reason,
            operator=operator,
            asset_id=asset_id,
            strategy_id=strategy_id,
        )
        logger.info("Circuit breaker reset for key=%s by operator=%s", cb_key, operator)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _is_halted(self) -> bool:
        """Return True if kill switch is active (trading_state = 'halted')."""
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT trading_state FROM dim_risk_state WHERE state_id = 1")
            ).fetchone()
        if row is None:
            logger.warning("dim_risk_state has no row -- treating as halted for safety")
            return True
        return row[0] == "halted"

    def _is_circuit_breaker_tripped(
        self,
        cb_key: str,
        asset_id: Optional[int] = None,
        strategy_id: Optional[int] = None,
    ) -> bool:
        """
        Return True if circuit breaker is currently tripped for this key.

        Auto-resets breaker if cooldown_hours have elapsed since it was tripped.
        """
        limits = self._load_limits(asset_id=asset_id, strategy_id=strategy_id)

        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT cb_breaker_tripped_at FROM dim_risk_state WHERE state_id = 1"
                )
            ).fetchone()

        if row is None:
            return False

        cb_tripped: dict = json.loads(row[0] or "{}")
        tripped_at_str = cb_tripped.get(cb_key)

        if tripped_at_str is None:
            return False

        tripped_at = datetime.fromisoformat(tripped_at_str)
        now = datetime.now(timezone.utc)

        elapsed_hours = (now - tripped_at).total_seconds() / 3600.0

        if elapsed_hours >= limits.cb_cooldown_hours:
            # Auto-reset after cooldown
            logger.info(
                "Circuit breaker auto-reset for key=%s: %.1f hours elapsed >= cooldown=%.1f hours",
                cb_key,
                elapsed_hours,
                limits.cb_cooldown_hours,
            )
            cb_tripped.pop(cb_key, None)
            with self._engine.connect() as conn:
                # Also reset loss count
                losses_row = conn.execute(
                    text(
                        "SELECT cb_consecutive_losses FROM dim_risk_state WHERE state_id = 1"
                    )
                ).fetchone()
                cb_losses: dict = json.loads(losses_row[0] or "{}")
                cb_losses[cb_key] = 0

                conn.execute(
                    text(
                        """
                    UPDATE dim_risk_state
                    SET cb_breaker_tripped_at = :cb_tripped,
                        cb_consecutive_losses = :cb_losses,
                        updated_at = now()
                    WHERE state_id = 1
                    """
                    ),
                    {
                        "cb_tripped": json.dumps(cb_tripped),
                        "cb_losses": json.dumps(cb_losses),
                    },
                )
                conn.commit()
            return False

        return True

    def _load_limits(
        self,
        asset_id: Optional[int] = None,
        strategy_id: Optional[int] = None,
    ) -> RiskLimits:
        """
        Load risk limits from dim_risk_limits with specificity ordering.

        Specificity order (most to least specific):
          1. Exact asset_id + strategy_id match
          2. asset_id match with NULL strategy_id
          3. NULL asset_id with strategy_id match
          4. Portfolio-wide defaults (both NULL)

        Returns the most specific matching row, or hardcoded defaults if no DB row found.
        """
        rows = []
        with self._engine.connect() as conn:
            result = conn.execute(
                text(
                    """
                SELECT
                    max_position_pct,
                    max_portfolio_pct,
                    daily_loss_pct_threshold,
                    cb_consecutive_losses_n,
                    cb_loss_threshold_pct,
                    cb_cooldown_hours,
                    allow_overrides,
                    asset_id,
                    strategy_id
                FROM dim_risk_limits
                WHERE
                    (asset_id = :asset_id OR asset_id IS NULL)
                    AND (strategy_id = :strategy_id OR strategy_id IS NULL)
                ORDER BY
                    (CASE WHEN asset_id IS NOT NULL THEN 1 ELSE 0 END) +
                    (CASE WHEN strategy_id IS NOT NULL THEN 1 ELSE 0 END) DESC
                LIMIT 1
                """
                ),
                {"asset_id": asset_id, "strategy_id": strategy_id},
            )
            rows = result.fetchall()

        if not rows:
            logger.debug("No dim_risk_limits row found -- using hardcoded defaults")
            return RiskLimits()

        row = rows[0]
        return RiskLimits(
            max_position_pct=float(row[0]),
            max_portfolio_pct=float(row[1]),
            daily_loss_pct_threshold=float(row[2]),
            cb_consecutive_losses_n=int(row[3]),
            cb_loss_threshold_pct=float(row[4]),
            cb_cooldown_hours=float(row[5]),
            allow_overrides=bool(row[6]),
        )

    def _compute_portfolio_value(self) -> Optional[Decimal]:
        """
        Compute current portfolio value from cmc_positions (if the table exists).

        Returns None if unable to compute (table not found, no rows, etc.).
        """
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    text(
                        """
                    SELECT COALESCE(SUM(current_value), 0)
                    FROM cmc_positions
                    WHERE status = 'open'
                    """
                    )
                ).fetchone()
            if row and row[0] is not None:
                return Decimal(str(row[0]))
        except Exception as exc:
            logger.debug(
                "Could not compute portfolio value from cmc_positions: %s", exc
            )
        return None

    def _log_event(
        self,
        event_type: str,
        trigger_source: str,
        reason: str,
        operator: Optional[str] = None,
        asset_id: Optional[int] = None,
        strategy_id: Optional[int] = None,
        order_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Insert an immutable risk event into cmc_risk_events.

        Failures are logged but never propagated -- the risk check result takes precedence.
        """
        try:
            with self._engine.connect() as conn:
                conn.execute(
                    text(
                        """
                    INSERT INTO cmc_risk_events (
                        event_type, trigger_source, reason, operator,
                        asset_id, strategy_id, order_id, metadata
                    ) VALUES (
                        :event_type, :trigger_source, :reason, :operator,
                        :asset_id, :strategy_id, :order_id, :metadata
                    )
                    """
                    ),
                    {
                        "event_type": event_type,
                        "trigger_source": trigger_source,
                        "reason": reason,
                        "operator": operator,
                        "asset_id": asset_id,
                        "strategy_id": strategy_id,
                        "order_id": order_id,
                        "metadata": json.dumps(metadata) if metadata else None,
                    },
                )
                conn.commit()
        except Exception as exc:
            logger.warning(
                "Failed to log risk event (event_type=%s): %s", event_type, exc
            )
