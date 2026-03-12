# src/ta_lab2/notifications/macro_alerts.py
"""
MacroAlertManager: Telegram alerting for macro regime transitions.

Detects dimension-level and composite regime-key changes in macro_regimes,
sends throttled Telegram alerts, and logs all alert activity to macro_alert_log
for audit and dashboard visibility.

Key design decisions:
- Throttle window defaults to 6 hours (macro regimes are sticky -- change ~1-3x/month).
- Risk-off (risk_appetite -> RiskOff) and carry unwind (carry -> Unwind) escalate to "critical".
- Composite alert fires in addition to per-dimension alerts when regime_key changes.
- Gracefully degrades when Telegram is not configured (logs warning, still writes to DB).
- macro_alert_log may not yet exist if Plan 01 Alembic migration hasn't run;
  catches OperationalError/ProgrammingError on insert and logs a warning.

Phase 72, Plan 02.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, ProgrammingError

from ta_lab2.notifications import telegram

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DIMENSIONS = ["monetary_policy", "liquidity", "risk_appetite", "carry"]

# Dimension labels that escalate alert to "critical"
_CRITICAL_LABELS: dict[str, set[str]] = {
    "risk_appetite": {"RiskOff"},
    "carry": {"Unwind"},
}

# Composite macro_state values that escalate to "critical"
_CRITICAL_STATES = {"cautious", "adverse"}

# Alert type constants
_TYPE_DIMENSION = "dimension_change"
_TYPE_COMPOSITE = "composite_change"


# ---------------------------------------------------------------------------
# MacroAlertManager
# ---------------------------------------------------------------------------


class MacroAlertManager:
    """
    Detect macro regime transitions and dispatch throttled Telegram alerts.

    Usage::

        manager = MacroAlertManager(engine, cooldown_hours=6)
        transitions = manager.check_and_alert(profile="default")
    """

    def __init__(self, engine: Engine, cooldown_hours: int = 6) -> None:
        self._engine = engine
        self._cooldown_hours = cooldown_hours

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_alert(self, profile: str = "default") -> list[dict[str, Any]]:
        """
        Detect transitions in macro_regimes and send Telegram alerts.

        Returns:
            List of dicts describing each transition detected (for caller logging).
            Each dict has keys: type, dimension, old_label, new_label,
            old_regime_key, new_regime_key, throttled, sent.
        """
        latest, previous = self._load_latest_two_rows(profile)
        if latest is None or previous is None:
            logger.info(
                "Fewer than 2 regime rows for profile=%s -- no comparison possible",
                profile,
            )
            return []

        transitions: list[dict[str, Any]] = []

        # Per-dimension change detection
        for dim in _DIMENSIONS:
            old_label = previous.get(dim)
            new_label = latest.get(dim)
            if old_label != new_label:
                logger.info(
                    "Dimension %s changed: %s -> %s (profile=%s)",
                    dim,
                    old_label,
                    new_label,
                    profile,
                )
                result = self._send_dimension_alert(dim, old_label, new_label, latest)
                transitions.append(
                    {
                        "type": _TYPE_DIMENSION,
                        "dimension": dim,
                        "old_label": old_label,
                        "new_label": new_label,
                        "old_regime_key": previous.get("regime_key"),
                        "new_regime_key": latest.get("regime_key"),
                        "throttled": result.get("throttled", False),
                        "sent": result.get("sent", False),
                    }
                )

        # Composite regime_key change detection
        old_key = previous.get("regime_key")
        new_key = latest.get("regime_key")
        if old_key != new_key:
            logger.info(
                "Composite regime_key changed: %s -> %s (profile=%s)",
                old_key,
                new_key,
                profile,
            )
            result = self._send_composite_alert(
                old_key=old_key,
                new_key=new_key,
                old_state=previous.get("macro_state"),
                new_state=latest.get("macro_state"),
                current_row=latest,
            )
            transitions.append(
                {
                    "type": _TYPE_COMPOSITE,
                    "dimension": None,
                    "old_label": old_key,
                    "new_label": new_key,
                    "old_regime_key": old_key,
                    "new_regime_key": new_key,
                    "throttled": result.get("throttled", False),
                    "sent": result.get("sent", False),
                }
            )

        if not transitions:
            logger.info("No macro regime transitions detected for profile=%s", profile)

        return transitions

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_latest_two_rows(
        self, profile: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Return (latest_row, previous_row) as dicts, or (None, None)."""
        sql = text("""
            SELECT date, monetary_policy, liquidity, risk_appetite, carry,
                   regime_key, macro_state
            FROM macro_regimes
            WHERE profile = :profile
            ORDER BY date DESC
            LIMIT 2
        """)
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(sql, {"profile": profile}).fetchall()
        except Exception as exc:
            logger.error("Failed to query macro_regimes: %s", exc)
            return None, None

        if len(rows) < 2:
            return None, None

        latest = dict(rows[0]._mapping)
        previous = dict(rows[1]._mapping)
        return latest, previous

    def _load_key_metrics(self) -> dict[str, Any]:
        """
        Load most recent key FRED metrics for alert enrichment.

        Returns dict with vixcls, hy_oas_level, dff, net_liquidity_365d_zscore.
        Returns "N/A" for any metric that fails to load.
        """
        defaults: dict[str, Any] = {
            "vixcls": "N/A",
            "hy_oas_level": "N/A",
            "dff": "N/A",
            "net_liquidity_365d_zscore": "N/A",
        }
        sql = text("""
            SELECT vixcls, hy_oas_level, dff, net_liquidity_365d_zscore
            FROM fred.fred_macro_features
            ORDER BY date DESC
            LIMIT 1
        """)
        try:
            with self._engine.connect() as conn:
                row = conn.execute(sql).fetchone()
            if row:
                mapping = dict(row._mapping)
                for key in defaults:
                    val = mapping.get(key)
                    if val is not None:
                        try:
                            defaults[key] = f"{float(val):.2f}"
                        except (TypeError, ValueError):
                            defaults[key] = str(val)
        except Exception as exc:
            logger.warning(
                "Could not load key metrics from fred.fred_macro_features: %s", exc
            )
        return defaults

    def _is_throttled(self, alert_type: str, dimension: str | None) -> bool:
        """
        Return True if an un-throttled alert of this type/dimension was sent
        within the cooldown window.
        """
        sql = text("""
            SELECT 1
            FROM macro_alert_log
            WHERE alert_type = :alert_type
              AND (dimension = :dimension OR (:dimension IS NULL AND dimension IS NULL))
              AND sent_at > NOW() - (INTERVAL '1 hour' * :hours)
              AND throttled = FALSE
            LIMIT 1
        """)
        try:
            with self._engine.connect() as conn:
                row = conn.execute(
                    sql,
                    {
                        "alert_type": alert_type,
                        "dimension": dimension,
                        "hours": self._cooldown_hours,
                    },
                ).fetchone()
            return row is not None
        except (OperationalError, ProgrammingError) as exc:
            # Table may not exist yet if Alembic migration hasn't run
            logger.warning(
                "macro_alert_log not accessible (migration pending?): %s", exc
            )
            return False
        except Exception as exc:
            logger.error("Error checking throttle state: %s", exc)
            return False

    def _log_alert(
        self,
        alert_type: str,
        dimension: str | None,
        old_label: str | None,
        new_label: str | None,
        regime_key: str | None,
        macro_state: str | None,
        throttled: bool,
    ) -> None:
        """Persist alert record to macro_alert_log."""
        sql = text("""
            INSERT INTO macro_alert_log
                (alert_type, dimension, old_label, new_label, regime_key, macro_state, throttled)
            VALUES
                (:alert_type, :dimension, :old_label, :new_label, :regime_key, :macro_state, :throttled)
        """)
        try:
            with self._engine.begin() as conn:
                conn.execute(
                    sql,
                    {
                        "alert_type": alert_type,
                        "dimension": dimension,
                        "old_label": old_label,
                        "new_label": new_label,
                        "regime_key": regime_key,
                        "macro_state": macro_state,
                        "throttled": throttled,
                    },
                )
        except (OperationalError, ProgrammingError) as exc:
            logger.warning(
                "Could not write to macro_alert_log (migration pending?): %s", exc
            )
        except Exception as exc:
            logger.error("Failed to log alert to macro_alert_log: %s", exc)

    def _send_dimension_alert(
        self,
        dimension: str,
        old_label: str | None,
        new_label: str | None,
        current_row: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Send a per-dimension regime change alert.

        Returns dict with keys: throttled, sent.
        """
        if self._is_throttled(_TYPE_DIMENSION, dimension):
            logger.info(
                "Alert throttled: dimension=%s within %d-hour cooldown",
                dimension,
                self._cooldown_hours,
            )
            self._log_alert(
                alert_type=_TYPE_DIMENSION,
                dimension=dimension,
                old_label=str(old_label),
                new_label=str(new_label),
                regime_key=current_row.get("regime_key"),
                macro_state=current_row.get("macro_state"),
                throttled=True,
            )
            return {"throttled": True, "sent": False}

        metrics = self._load_key_metrics()
        regime_key = current_row.get("regime_key", "N/A")
        macro_state = current_row.get("macro_state", "N/A")

        title = f"Macro Regime Change: {dimension}"
        message = (
            f"{old_label} -&gt; {new_label}\n\n"
            f"Current regime: {regime_key}\n"
            f"Macro state: {macro_state}\n\n"
            f"Key metrics:\n"
            f"- VIX: {metrics['vixcls']}\n"
            f"- HY OAS: {metrics['hy_oas_level']}\n"
            f"- Fed Funds: {metrics['dff']}\n"
            f"- Net Liquidity Z: {metrics['net_liquidity_365d_zscore']}"
        )

        # Escalate to critical for risk-off / carry-unwind transitions
        critical_new_labels = _CRITICAL_LABELS.get(dimension, set())
        severity = "critical" if new_label in critical_new_labels else "warning"

        sent = False
        if not telegram.is_configured():
            logger.warning(
                "Telegram not configured -- skipping send for dimension alert: %s %s->%s",
                dimension,
                old_label,
                new_label,
            )
        else:
            try:
                sent = telegram.send_alert(title, message, severity=severity)
            except Exception as exc:
                logger.error("Telegram send failed for dimension alert: %s", exc)

        self._log_alert(
            alert_type=_TYPE_DIMENSION,
            dimension=dimension,
            old_label=str(old_label),
            new_label=str(new_label),
            regime_key=regime_key,
            macro_state=macro_state,
            throttled=False,
        )
        return {"throttled": False, "sent": sent}

    def _send_composite_alert(
        self,
        old_key: str | None,
        new_key: str | None,
        old_state: str | None,
        new_state: str | None,
        current_row: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Send a composite regime_key transition alert.

        Returns dict with keys: throttled, sent.
        """
        if self._is_throttled(_TYPE_COMPOSITE, None):
            logger.info(
                "Alert throttled: composite_change within %d-hour cooldown",
                self._cooldown_hours,
            )
            self._log_alert(
                alert_type=_TYPE_COMPOSITE,
                dimension=None,
                old_label=str(old_key),
                new_label=str(new_key),
                regime_key=new_key,
                macro_state=new_state,
                throttled=True,
            )
            return {"throttled": True, "sent": False}

        metrics = self._load_key_metrics()
        monetary = current_row.get("monetary_policy", "N/A")
        liquidity = current_row.get("liquidity", "N/A")
        risk_appetite = current_row.get("risk_appetite", "N/A")
        carry = current_row.get("carry", "N/A")

        title = "Macro Regime Transition"
        message = (
            f"{old_key} -&gt; {new_key}\n\n"
            f"New macro state: {new_state}\n\n"
            f"Dimensions:\n"
            f"- Monetary: {monetary}\n"
            f"- Liquidity: {liquidity}\n"
            f"- Risk Appetite: {risk_appetite}\n"
            f"- Carry: {carry}\n\n"
            f"Key metrics:\n"
            f"- VIX: {metrics['vixcls']}\n"
            f"- HY OAS: {metrics['hy_oas_level']}\n"
            f"- Fed Funds: {metrics['dff']}\n"
            f"- Net Liquidity Z: {metrics['net_liquidity_365d_zscore']}"
        )

        severity = "critical" if new_state in _CRITICAL_STATES else "warning"

        sent = False
        if not telegram.is_configured():
            logger.warning(
                "Telegram not configured -- skipping send for composite alert: %s->%s",
                old_key,
                new_key,
            )
        else:
            try:
                sent = telegram.send_alert(title, message, severity=severity)
            except Exception as exc:
                logger.error("Telegram send failed for composite alert: %s", exc)

        self._log_alert(
            alert_type=_TYPE_COMPOSITE,
            dimension=None,
            old_label=str(old_key),
            new_label=str(new_key),
            regime_key=new_key,
            macro_state=new_state,
            throttled=False,
        )
        return {"throttled": False, "sent": sent}


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------


def check_and_alert_transitions(
    engine: Engine,
    profile: str = "default",
    cooldown_hours: int = 6,
) -> list[dict[str, Any]]:
    """
    Convenience wrapper -- create manager and run check.

    Args:
        engine: SQLAlchemy engine connected to the ta_lab2 database.
        profile: Macro regime profile to check (default "default").
        cooldown_hours: Throttle window in hours (default 6).

    Returns:
        List of dicts describing all transitions found.
    """
    manager = MacroAlertManager(engine, cooldown_hours=cooldown_hours)
    return manager.check_and_alert(profile=profile)
