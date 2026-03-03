"""
RiskEngine: Order-level risk gate for paper trading.

Checks every order through sequential gates before allowing execution:
  1.   Kill switch -- immediate block if trading is halted
  1.5  Tail risk -- block if FLATTEN, halve buy qty if REDUCE
  1.7  Macro gates -- block if macro FLATTEN state, scale buy qty if REDUCE
  2.   Circuit breaker -- block if per-strategy breaker is tripped
  3.   Per-asset position cap -- scale down quantity if it would exceed max_position_pct
  4.   Portfolio utilization cap -- scale down if total exposure would exceed max_portfolio_pct
  1.6  Margin/liquidation check -- block buys when margin utilization is critically low (perps only)
  5.   All pass -- allow with (possibly adjusted) quantity

Limits are hot-reloaded from dim_risk_limits on each check_order() call.
State (kill switch, circuit breaker, tail risk) is read from dim_risk_state.
Macro gate state is read from dim_macro_gate_state via MacroGateEvaluator.

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

To enable macro gates, inject a MacroGateEvaluator::

    from ta_lab2.risk import RiskEngine, MacroGateEvaluator
    evaluator = MacroGateEvaluator(engine)
    re = RiskEngine(engine, macro_gate_evaluator=evaluator)

Without a MacroGateEvaluator (the default), Gate 1.7 is a no-op and all
existing behaviour is preserved (backward compatible).
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
    from ta_lab2.risk.macro_gate_evaluator import MacroGateEvaluator

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

    margin_alert_threshold: float = 1.5
    """Margin utilization ratio at which a liquidation_warning event is logged.

    When margin_utilization <= this value, a warning event is logged but the
    order is NOT blocked (warning is informational only).
    Default matches dim_risk_limits seed value from Phase 51 migration.
    """

    liquidation_kill_threshold: float = 1.1
    """Margin utilization ratio at which buy orders are blocked.

    When margin_utilization <= this value, new buy orders are blocked and a
    liquidation_critical event is logged.  Reducing exposure (sells) is always
    allowed regardless of this threshold.
    Default matches dim_risk_limits seed value from Phase 51 migration.
    """


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

        2c. Gate 1.6 (margin/liquidation) is checked automatically inside check_order()
            for buy orders. Sell orders bypass this gate (reducing exposure is safe).
            Requires cmc_perp_positions table populated by the paper trading executor.

        2d. Gate 1.7 (macro gates) is checked automatically when macro_gate_evaluator
            is injected at construction time. FLATTEN blocks all orders; REDUCE scales
            buy qty by macro size_mult. Tail risk and macro gate multipliers stack
            (worst-of -- both reduce independently). When macro_gate_evaluator is None
            (the default), Gate 1.7 is a no-op.

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

    def __init__(
        self,
        engine: Engine,
        macro_gate_evaluator: Optional["MacroGateEvaluator"] = None,
    ) -> None:
        """
        Initialise RiskEngine.

        Args:
            engine: SQLAlchemy Engine connected to the paper trading database.
            macro_gate_evaluator: Optional MacroGateEvaluator instance for Gate 1.7.
                When None (default), Gate 1.7 is a no-op -- all existing behaviour
                is preserved (backward compatible).
        """
        self._engine = engine
        self._macro_gate_evaluator = macro_gate_evaluator

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
        Run order through all risk gates.

        Gates are checked in priority order. The first blocking gate short-circuits
        the remaining checks. Position/portfolio cap gates scale down quantity rather
        than outright rejecting (unless the position is already exhausted).

        Gate sequence:
          1.   Kill switch
          1.5  Tail risk (FLATTEN blocks; REDUCE scales buy qty by 0.5)
          1.7  Macro gates (FLATTEN blocks; REDUCE scales buy qty by macro_size_mult)
          2.   Circuit breaker
          3.   Per-asset position cap (scales down buy qty)
          4.   Portfolio utilization cap (scales down buy qty)
          1.6  Margin/liquidation check (buy-only, perps only)
          5.   All pass

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

        # Gate 1.7: Macro gates (no-op when macro_gate_evaluator is None)
        macro_state, macro_size_mult = self._check_macro_gates()
        if macro_state == "flatten":
            self._log_event(
                event_type="macro_stress_gate_triggered",
                trigger_source="macro_gate",
                reason="Order blocked by macro gate FLATTEN state",
                asset_id=asset_id,
                strategy_id=strategy_id,
                metadata={"macro_state": "flatten", "order_side": order_side},
            )
            return RiskCheckResult(
                allowed=False,
                blocked_reason="Macro gate: FLATTEN state active -- all new orders blocked",
            )
        if macro_state == "reduce" and order_side.lower() == "buy":
            # Scale buy order quantity by macro size multiplier
            order_qty = (order_qty * Decimal(str(macro_size_mult))).quantize(
                Decimal("0.00000001")
            )
            order_notional = order_qty * fill_price
            logger.info(
                "Macro gate REDUCE: buy order quantity scaled by %.2f to %s",
                macro_size_mult,
                order_qty,
            )

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

            # Gate 1.6: Margin/liquidation check (perps only, buy orders only)
            margin_result = self._check_margin_gate(
                asset_id=asset_id,
                strategy_id=strategy_id,
                order_side=order_side,
                limits=limits,
            )
            if margin_result in ("critical", "buffer"):
                reason = (
                    f"Liquidation critical: margin utilization at or below "
                    f"{limits.liquidation_kill_threshold}x maintenance margin"
                    if margin_result == "critical"
                    else "Margin buffer insufficient: must maintain >= 2x maintenance margin to open new positions"
                )
                return RiskCheckResult(
                    allowed=False,
                    blocked_reason=reason,
                )
            # Note: "warning" result is logged but does NOT block -- order proceeds

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

    def _check_macro_gates(self) -> tuple[str, float]:
        """
        Gate 1.7: Read aggregate macro gate state for per-order checks.

        Delegates to MacroGateEvaluator.check_order_gates() when an evaluator
        is injected. Returns ('normal', 1.0) when no evaluator is present,
        preserving backward compatibility.

        Returns:
            (state, size_multiplier):
              ('normal', 1.0)  -- no macro restriction
              ('reduce', mult) -- scale buy order quantity by mult
              ('flatten', 0.0) -- block all new orders
        """
        if self._macro_gate_evaluator is None:
            return ("normal", 1.0)
        try:
            return self._macro_gate_evaluator.check_order_gates()
        except Exception as exc:
            logger.warning(
                "Gate 1.7: macro gate check failed (returning normal to avoid blocking): %s",
                exc,
            )
            return ("normal", 1.0)

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
        Handles NULL values for new columns (margin_alert_threshold,
        liquidation_kill_threshold) gracefully by falling back to dataclass defaults.
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
                    strategy_id,
                    margin_alert_threshold,
                    liquidation_kill_threshold
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
        # Columns 9 and 10 are the new margin threshold columns (may be NULL on older rows)
        _defaults = RiskLimits()
        margin_alert = (
            float(row[9]) if row[9] is not None else _defaults.margin_alert_threshold
        )
        liq_kill = (
            float(row[10])
            if row[10] is not None
            else _defaults.liquidation_kill_threshold
        )
        return RiskLimits(
            max_position_pct=float(row[0]),
            max_portfolio_pct=float(row[1]),
            daily_loss_pct_threshold=float(row[2]),
            cb_consecutive_losses_n=int(row[3]),
            cb_loss_threshold_pct=float(row[4]),
            cb_cooldown_hours=float(row[5]),
            allow_overrides=bool(row[6]),
            margin_alert_threshold=margin_alert,
            liquidation_kill_threshold=liq_kill,
        )

    def _check_margin_gate(
        self,
        asset_id: int,
        strategy_id: int,
        order_side: str,
        limits: RiskLimits,
    ) -> Optional[str]:
        """
        Gate 1.6: Margin/liquidation check for perpetual futures positions.

        Only applies to buy orders. Sell orders (reduces exposure) always bypass
        this gate -- closing or reducing a position is always allowed.

        Threshold check order (most severe to least severe to avoid dead code):
          1. Critical (<=1.1x maintenance margin) -- blocks order
          2. Warning  (<=1.5x maintenance margin) -- logs event only, does NOT block
          3. Buffer   (<=2.0x maintenance margin) -- blocks order
          4. Safe     (>2.0x)                     -- returns None (gate passes)

        Args:
            asset_id:    Asset ID (unused for perp query; reserved for future filtering).
            strategy_id: Strategy ID for position lookup.
            order_side:  "buy" or "sell".
            limits:      Loaded RiskLimits (contains threshold values).

        Returns:
            "critical" -- blocks order (margin <= liquidation_kill_threshold)
            "warning"  -- logs event only, does NOT block (margin <= margin_alert_threshold)
            "buffer"   -- blocks order (margin <= 2.0x but above warning threshold)
            None       -- gate passes (no perp position or margin is safe)
        """
        # Sells/closes always allowed -- reducing exposure is safe
        if order_side.lower() == "sell":
            return None

        # Query cmc_perp_positions for any active position for this strategy
        try:
            with self._engine.connect() as conn:
                pos_row = conn.execute(
                    text(
                        """
                    SELECT
                        venue,
                        symbol,
                        allocated_margin,
                        leverage,
                        margin_mode,
                        side,
                        mark_price,
                        quantity,
                        avg_entry_price
                    FROM cmc_perp_positions
                    WHERE strategy_id = :strategy_id
                      AND side != 'flat'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                    ),
                    {"strategy_id": strategy_id},
                ).fetchone()
        except Exception as exc:
            logger.debug(
                "Gate 1.6: cmc_perp_positions query failed (table may not exist): %s",
                exc,
            )
            return None

        if pos_row is None:
            # No perp position -- gate passes (spot-only or no active position)
            return None

        (
            venue,
            symbol,
            allocated_margin,
            leverage,
            margin_mode,
            side,
            mark_price,
            quantity,
            avg_entry_price,
        ) = pos_row  # noqa: E501

        if allocated_margin is None or mark_price is None or quantity is None:
            logger.debug(
                "Gate 1.6: incomplete margin data for venue=%s symbol=%s -- skipping",
                venue,
                symbol,
            )
            return None

        from decimal import Decimal as _Decimal

        allocated_margin = _Decimal(str(allocated_margin))
        leverage = _Decimal(str(leverage)) if leverage is not None else _Decimal("1")
        mark_price = _Decimal(str(mark_price))
        quantity = _Decimal(str(abs(float(quantity))))
        position_value = mark_price * quantity

        # Load margin tiers from cmc_margin_config
        from ta_lab2.risk.margin_monitor import (
            compute_margin_utilization,
            load_margin_tiers,
        )

        tiers = load_margin_tiers(self._engine, venue=venue, symbol=symbol)

        entry_price = (
            _Decimal(str(avg_entry_price)) if avg_entry_price is not None else None
        )
        margin_state = compute_margin_utilization(
            position_value=position_value,
            allocated_margin=allocated_margin,
            leverage=leverage,
            tiers=tiers,
            margin_mode=margin_mode or "isolated",
            venue=venue,
            symbol=symbol,
            side=side or "long",
            entry_price=entry_price,
        )

        util = margin_state.margin_utilization
        liq_kill = _Decimal(str(limits.liquidation_kill_threshold))  # default 1.1
        alert_thresh = _Decimal(str(limits.margin_alert_threshold))  # default 1.5
        buffer_thresh = _Decimal("2.0")

        # Check from most severe to least severe (avoids dead code)

        # 1. Critical: margin <= 1.1x -- blocks buy order
        if util <= liq_kill:
            self._log_event(
                event_type="liquidation_critical",
                trigger_source="margin_monitor",
                reason=(
                    f"Margin utilization {float(util):.4f} at or below "
                    f"critical threshold {float(liq_kill):.1f}x for "
                    f"venue={venue} symbol={symbol}"
                ),
                asset_id=asset_id,
                strategy_id=strategy_id,
                metadata={
                    "margin_utilization": float(util),
                    "liquidation_kill_threshold": float(liq_kill),
                    "venue": venue,
                    "symbol": symbol,
                },
            )
            return "critical"

        # 2. Warning: margin <= 1.5x -- logs event but does NOT block
        if util <= alert_thresh:
            self._log_event(
                event_type="liquidation_warning",
                trigger_source="margin_monitor",
                reason=(
                    f"Margin utilization {float(util):.4f} at or below "
                    f"warning threshold {float(alert_thresh):.1f}x for "
                    f"venue={venue} symbol={symbol} (order NOT blocked)"
                ),
                asset_id=asset_id,
                strategy_id=strategy_id,
                metadata={
                    "margin_utilization": float(util),
                    "margin_alert_threshold": float(alert_thresh),
                    "venue": venue,
                    "symbol": symbol,
                },
            )
            return "warning"

        # 3. Buffer: margin <= 2.0x -- blocks buy order (proactive buffer)
        if util <= buffer_thresh:
            self._log_event(
                event_type="margin_alert",
                trigger_source="margin_monitor",
                reason=(
                    f"Margin utilization {float(util):.4f} below 2x buffer for "
                    f"venue={venue} symbol={symbol} -- must maintain >= 2x to open new positions"
                ),
                asset_id=asset_id,
                strategy_id=strategy_id,
                metadata={
                    "margin_utilization": float(util),
                    "buffer_threshold": 2.0,
                    "venue": venue,
                    "symbol": symbol,
                },
            )
            return "buffer"

        # 4. Safe: > 2.0x
        return None

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
