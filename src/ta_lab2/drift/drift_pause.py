"""
Drift pause operations for the paper trading risk system.

Implements a tiered graduated response to drift threshold breaches:
  - Tier 1 WARNING: send Telegram alert when tracking error exceeds 75% of threshold
  - Tier 2 PAUSE: set drift_paused=TRUE on dim_risk_state when threshold is breached
  - Tier 3 ESCALATE: activate kill switch when drift pause persists beyond escalation window

Key design invariants:
  - activate_drift_pause() is atomic: state update + audit log in one transaction
  - Telegram alerts are best-effort (failure does not raise) -- same pattern as kill_switch.py
  - disable_drift_pause() requires explicit reason and operator -- never automatic
  - check_drift_escalation() triggers kill switch via activate_kill_switch() from Phase 46

Usage:
    from sqlalchemy import create_engine
    from ta_lab2.drift.drift_pause import (
        activate_drift_pause, disable_drift_pause,
        check_drift_threshold, check_drift_escalation,
    )

    engine = create_engine(db_url)
    metrics = ...  # DriftMetrics from drift_metrics.py
    if check_drift_threshold(engine, metrics):
        # drift pause was activated; new signal processing is blocked
        pass
    check_drift_escalation(engine)  # escalates to kill switch if expired
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.risk.kill_switch import activate_kill_switch

if TYPE_CHECKING:
    from ta_lab2.drift.drift_metrics import DriftMetrics

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional Telegram import -- gracefully degrade if not configured
# ---------------------------------------------------------------------------
try:
    from ta_lab2.notifications.telegram import (
        send_critical_alert as _send_critical_alert,
    )
    from ta_lab2.notifications.telegram import send_alert as _send_alert

    _TELEGRAM_AVAILABLE = True
except ImportError:
    _send_critical_alert = None  # type: ignore[assignment]
    _send_alert = None  # type: ignore[assignment]
    _TELEGRAM_AVAILABLE = False


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def activate_drift_pause(
    engine: Engine,
    reason: str,
    tracking_error: float,
    config_id: int,
) -> None:
    """
    Atomically activate drift pause state.

    Sequence (within a single transaction):
      1. UPDATE dim_risk_state: drift_paused=TRUE, drift_paused_at=now(), drift_paused_reason
      2. INSERT into cmc_risk_events: audit record with tracking_error and config_id

    After commit, sends a Telegram critical alert (best-effort, failure does not raise).

    Args:
        engine: SQLAlchemy Engine.
        reason: Human-readable reason for the drift pause.
        tracking_error: The tracking error value that triggered the pause.
        config_id: Executor config ID that triggered the breach.
    """
    now_utc = datetime.now(timezone.utc)

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE dim_risk_state
                SET drift_paused        = TRUE,
                    drift_paused_at     = :paused_at,
                    drift_paused_reason = :reason,
                    updated_at          = :paused_at
                WHERE state_id = 1
                """
            ),
            {"paused_at": now_utc, "reason": reason},
        )

        conn.execute(
            text(
                """
                INSERT INTO cmc_risk_events (
                    event_type, trigger_source, reason, metadata
                ) VALUES (
                    'drift_pause_activated', 'drift_monitor', :reason, :metadata
                )
                """
            ),
            {
                "reason": reason,
                "metadata": json.dumps(
                    {"tracking_error_pct": tracking_error, "config_id": config_id}
                ),
            },
        )

    logger.warning(
        "Drift pause ACTIVATED: reason=%r tracking_error=%.4f config_id=%d",
        reason,
        tracking_error,
        config_id,
    )

    # Best-effort Telegram alert (outside transaction)
    if _TELEGRAM_AVAILABLE and _send_critical_alert is not None:
        try:
            _send_critical_alert(
                error_type="drift_pause",
                error_message=f"Drift pause activated: {reason}",
                context={
                    "tracking_error": tracking_error,
                    "config_id": config_id,
                },
            )
        except Exception as exc:
            logger.warning(
                "Telegram alert failed after drift pause activation: %s", exc
            )


def disable_drift_pause(
    engine: Engine,
    reason: str,
    operator: str,
) -> None:
    """
    Disable drift pause state.

    This operation is NEVER automatic. It always requires a human reason and operator.

    Sequence (within a single transaction):
      1. UPDATE dim_risk_state: drift_paused=FALSE, clear drift_paused_at/reason
      2. INSERT into cmc_risk_events: audit record

    Args:
        engine: SQLAlchemy Engine.
        reason: Human-readable reason for disabling the pause.
        operator: Identity of the operator authorising the disable.

    Raises:
        ValueError: If reason or operator are empty strings.
    """
    if not reason or not reason.strip():
        raise ValueError("reason must be a non-empty string")
    if not operator or not operator.strip():
        raise ValueError("operator must be a non-empty string")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE dim_risk_state
                SET drift_paused        = FALSE,
                    drift_paused_at     = NULL,
                    drift_paused_reason = NULL,
                    updated_at          = now()
                WHERE state_id = 1
                """
            )
        )

        conn.execute(
            text(
                """
                INSERT INTO cmc_risk_events (
                    event_type, trigger_source, reason, operator
                ) VALUES (
                    'drift_pause_disabled', 'manual', :reason, :operator
                )
                """
            ),
            {"reason": reason, "operator": operator},
        )

    logger.info(
        "Drift pause DISABLED by operator=%s reason=%r",
        operator,
        reason,
    )


def check_drift_threshold(
    engine: Engine,
    metrics: "DriftMetrics",
) -> bool:
    """
    Check drift metrics against configured thresholds and trigger graduated response.

    Loads thresholds from dim_risk_limits (hotload pattern -- always reads live values).

    Tier 1 WARNING (>= 75% of threshold): sends Telegram warning alert.
    Tier 2 PAUSE (>= 100% of threshold): calls activate_drift_pause(). Returns True.

    Args:
        engine: SQLAlchemy Engine.
        metrics: DriftMetrics from the current monitoring run.

    Returns:
        True if drift pause was activated (threshold breached), False otherwise.
    """
    if metrics.tracking_error_5d is None:
        logger.debug(
            "check_drift_threshold: tracking_error_5d is None (insufficient history) "
            "for config_id=%d asset_id=%d",
            metrics.config_id,
            metrics.asset_id,
        )
        return False

    # Hotload thresholds from dim_risk_limits
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    COALESCE(drift_tracking_error_threshold_5d,  0.015) AS threshold_5d,
                    COALESCE(drift_tracking_error_threshold_30d, 0.005) AS threshold_30d,
                    COALESCE(drift_window_days, 5)                      AS window_days
                FROM dim_risk_limits
                WHERE asset_id IS NULL
                  AND strategy_id IS NULL
                LIMIT 1
                """
            )
        ).fetchone()

    if row is None:
        # Fallback defaults when no global risk limits row exists
        threshold_5d = 0.015
        logger.warning(
            "check_drift_threshold: no global row in dim_risk_limits -- "
            "using default threshold_5d=%.3f",
            threshold_5d,
        )
    else:
        threshold_5d = float(row[0])

    te = metrics.tracking_error_5d
    warning_level = threshold_5d * 0.75

    if te >= threshold_5d:
        # Tier 2: breach -- activate drift pause
        reason = (
            f"Tracking error {te:.4f} exceeds threshold {threshold_5d:.4f} "
            f"for config_id={metrics.config_id} asset_id={metrics.asset_id}"
        )
        activate_drift_pause(
            engine,
            reason=reason,
            tracking_error=te,
            config_id=metrics.config_id,
        )
        return True

    if te >= warning_level:
        # Tier 1: warning zone -- alert only, do not pause
        pct = te / threshold_5d * 100
        message = (
            f"Tracking error {te:.4f} is {pct:.1f}% of threshold {threshold_5d:.4f}. "
            f"config_id={metrics.config_id} asset_id={metrics.asset_id}. "
            f"No pause activated yet."
        )
        logger.warning(
            "Drift WARNING: tracking_error=%.4f is %.1f%% of threshold config_id=%d",
            te,
            pct,
            metrics.config_id,
        )
        if _TELEGRAM_AVAILABLE and _send_alert is not None:
            try:
                _send_alert(
                    "Drift Approaching Threshold",
                    message,
                    severity="warning",
                )
            except Exception as exc:
                logger.warning("Telegram warning alert failed: %s", exc)

    return False


def check_drift_escalation(engine: Engine) -> bool:
    """
    Check whether a drift pause has been active long enough to escalate to kill switch.

    Reads dim_risk_state and compares drift_paused_at + drift_auto_escalate_after_days
    against the current UTC time. If expired, activates kill switch.

    Args:
        engine: SQLAlchemy Engine.

    Returns:
        True if escalation to kill switch was triggered, False otherwise.
    """
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT drift_paused, drift_paused_at, drift_auto_escalate_after_days
                FROM dim_risk_state
                WHERE state_id = 1
                """
            )
        ).fetchone()

    if row is None:
        logger.error("check_drift_escalation: dim_risk_state has no row")
        return False

    drift_paused = row[0]
    drift_paused_at = row[1]
    escalate_after_days = row[2]

    if not drift_paused:
        return False

    if drift_paused_at is None or escalate_after_days is None:
        logger.warning(
            "check_drift_escalation: drift_paused=True but drift_paused_at or "
            "drift_auto_escalate_after_days is NULL -- skipping escalation check"
        )
        return False

    now_utc = datetime.now(timezone.utc)

    # Ensure drift_paused_at is tz-aware for comparison
    if hasattr(drift_paused_at, "tzinfo") and drift_paused_at.tzinfo is None:
        drift_paused_at = drift_paused_at.replace(tzinfo=timezone.utc)

    from datetime import timedelta

    escalation_deadline = drift_paused_at + timedelta(days=float(escalate_after_days))

    if now_utc >= escalation_deadline:
        days_str = f"{escalate_after_days}"
        reason = (
            f"Drift pause escalated after {days_str} days without manual resolution"
        )

        logger.warning(
            "Drift ESCALATION: drift paused for > %s days -- activating kill switch",
            days_str,
        )

        # Activate kill switch
        activate_kill_switch(engine, reason=reason, trigger_source="drift_monitor")

        # Log separate escalation event
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO cmc_risk_events (
                        event_type, trigger_source, reason
                    ) VALUES (
                        'drift_escalated', 'drift_monitor', :reason
                    )
                    """
                ),
                {"reason": reason},
            )

        return True

    return False
