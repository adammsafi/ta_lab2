"""
Kill switch operations for the paper trading risk system.

Provides atomic halt/re-enable/status operations. The kill switch state is
stored in dim_risk_state (single-row, state_id=1 enforced by DB CHECK constraint).

Key design invariants:
  - activate_kill_switch() is atomic: state update + order cancellation + audit log
    all happen within a single connection; Telegram alert is best-effort after commit
  - re_enable_trading() requires an explicit reason and operator -- never automatic
  - get_kill_switch_status() is read-only and always safe to call

Usage:
    from sqlalchemy import create_engine
    from ta_lab2.risk.kill_switch import (
        activate_kill_switch, re_enable_trading, get_kill_switch_status
    )

    engine = create_engine(db_url)
    activate_kill_switch(engine, reason="Manual safety halt", trigger_source="manual")
    re_enable_trading(engine, reason="Issue resolved", operator="trader_1")
    status = get_kill_switch_status(engine)
    print(status.trading_state)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine

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
class KillSwitchStatus:
    """Current kill switch state as read from dim_risk_state."""

    trading_state: str
    """'active' or 'halted'."""

    halted_at: Optional[datetime]
    """UTC timestamp when trading was halted (None if currently active)."""

    halted_reason: Optional[str]
    """Human-readable reason for the halt (None if currently active)."""

    halted_by: Optional[str]
    """Identity of who/what triggered the halt (None if currently active)."""


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def activate_kill_switch(
    engine: Engine,
    reason: str,
    trigger_source: str,
    operator: Optional[str] = None,
) -> None:
    """
    Atomically halt all trading.

    Sequence (within a single connection):
      1. UPDATE dim_risk_state: trading_state='halted', record timestamp/reason/source
      2. UPDATE orders: cancel all pending orders (status IN ('created', 'submitted'))
      3. INSERT into risk_events: audit record

    After commit, sends a Telegram critical alert (best-effort, failure does not raise).

    If trading is already halted, logs a warning and returns without re-halting.

    Args:
        engine: SQLAlchemy Engine.
        reason: Human-readable reason for the halt.
        trigger_source: One of 'manual', 'daily_loss_stop', 'circuit_breaker', 'system'.
        operator: Identity of caller (CLI user, script name). Optional.
    """
    with engine.connect() as conn:
        # Check current state first
        state_row = conn.execute(
            text("SELECT trading_state FROM dim_risk_state WHERE state_id = 1")
        ).fetchone()

        if state_row is None:
            logger.error("dim_risk_state has no row -- cannot activate kill switch")
            return

        if state_row[0] == "halted":
            logger.warning(
                "Kill switch already active -- ignoring duplicate activate request"
            )
            return

        # Step 1: Flip state to halted
        now_utc = datetime.now(timezone.utc)
        halted_by = operator or trigger_source
        conn.execute(
            text(
                """
            UPDATE dim_risk_state
            SET trading_state = 'halted',
                halted_at      = :halted_at,
                halted_reason  = :halted_reason,
                halted_by      = :halted_by,
                updated_at     = :halted_at
            WHERE state_id = 1
            """
            ),
            {
                "halted_at": now_utc,
                "halted_reason": reason,
                "halted_by": halted_by,
            },
        )

        # Step 2: Cancel all pending orders
        cancel_result = conn.execute(
            text(
                """
            UPDATE orders
            SET status     = 'cancelled',
                updated_at = now()
            WHERE status IN ('created', 'submitted')
            """
            )
        )
        cancelled_count = cancel_result.rowcount

        # Step 3: Insert audit event
        conn.execute(
            text(
                """
            INSERT INTO risk_events (
                event_type, trigger_source, reason, operator
            ) VALUES (
                'kill_switch_activated', :trigger_source, :reason, :operator
            )
            """
            ),
            {
                "trigger_source": trigger_source,
                "reason": reason,
                "operator": operator,
            },
        )

        conn.commit()

    logger.warning(
        "Kill switch ACTIVATED: reason=%r trigger=%s cancelled_orders=%d",
        reason,
        trigger_source,
        cancelled_count,
    )

    # Best-effort Telegram alert (outside transaction)
    if _TELEGRAM_AVAILABLE and _send_critical_alert is not None:
        try:
            _send_critical_alert(
                error_type="kill_switch",
                error_message=f"Kill switch activated by {trigger_source}: {reason}",
                context={
                    "trigger_source": trigger_source,
                    "operator": operator,
                    "cancelled_orders": cancelled_count,
                },
            )
        except Exception as exc:
            logger.warning(
                "Telegram alert failed after kill switch activation: %s", exc
            )


def re_enable_trading(
    engine: Engine,
    reason: str,
    operator: str,
) -> None:
    """
    Re-enable trading after a kill switch halt.

    This operation is NEVER automatic. It always requires a human reason and operator.
    If trading is already active, logs a warning and returns without error.

    Sequence:
      1. Verify current state is 'halted'
      2. UPDATE dim_risk_state: trading_state='active', clear halt columns
      3. INSERT into risk_events: audit record

    Args:
        engine: SQLAlchemy Engine.
        reason: Human-readable reason for re-enabling.
        operator: Identity of the operator authorising the re-enable.

    Raises:
        ValueError: If reason or operator are empty strings.
    """
    if not reason or not reason.strip():
        raise ValueError("reason must be a non-empty string")
    if not operator or not operator.strip():
        raise ValueError("operator must be a non-empty string")

    with engine.connect() as conn:
        state_row = conn.execute(
            text("SELECT trading_state FROM dim_risk_state WHERE state_id = 1")
        ).fetchone()

        if state_row is None:
            logger.error("dim_risk_state has no row -- cannot re-enable trading")
            return

        if state_row[0] == "active":
            logger.warning("Trading already active -- ignoring re-enable request")
            return

        # Step 1: Flip state back to active
        conn.execute(
            text(
                """
            UPDATE dim_risk_state
            SET trading_state = 'active',
                halted_at     = NULL,
                halted_reason = NULL,
                halted_by     = NULL,
                updated_at    = now()
            WHERE state_id = 1
            """
            )
        )

        # Step 2: Insert audit event
        conn.execute(
            text(
                """
            INSERT INTO risk_events (
                event_type, trigger_source, reason, operator
            ) VALUES (
                'kill_switch_disabled', 'manual', :reason, :operator
            )
            """
            ),
            {"reason": reason, "operator": operator},
        )

        conn.commit()

    logger.info("Trading RE-ENABLED by operator=%s reason=%r", operator, reason)


def get_kill_switch_status(engine: Engine) -> KillSwitchStatus:
    """
    Read and return the current kill switch state from dim_risk_state.

    Args:
        engine: SQLAlchemy Engine.

    Returns:
        KillSwitchStatus with current state values.

    Raises:
        RuntimeError: If dim_risk_state has no row (should never happen after migration seed).
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
            SELECT trading_state, halted_at, halted_reason, halted_by
            FROM dim_risk_state
            WHERE state_id = 1
            """
            )
        ).fetchone()

    if row is None:
        raise RuntimeError(
            "dim_risk_state has no row -- database not properly initialised"
        )

    return KillSwitchStatus(
        trading_state=row[0],
        halted_at=row[1],
        halted_reason=row[2],
        halted_by=row[3],
    )


def print_kill_switch_status(engine: Engine) -> None:
    """
    Pretty-print kill switch status to stdout.

    Args:
        engine: SQLAlchemy Engine.
    """
    try:
        status = get_kill_switch_status(engine)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return

    separator = "-" * 40
    print(separator)
    print(f"Trading state : {status.trading_state.upper()}")
    if status.trading_state == "halted":
        print(f"Halted at     : {status.halted_at}")
        print(f"Halted by     : {status.halted_by}")
        print(f"Reason        : {status.halted_reason}")
    print(separator)
