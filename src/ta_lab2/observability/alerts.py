"""
Alert threshold checking and delivery.

Per CONTEXT.md requirements:
- Integration failures: Alert when orchestrator -> memory or orchestrator -> ta_lab2 breaks
- Performance degradation: Alert when task execution >2x baseline duration
- Data quality issues: Alert on gap detection, alignment failures, reproducibility mismatches
- Resource exhaustion: Alert on quota limits, memory usage, database connections

Delivery: Telegram (existing) + database logging.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any, List

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)


class AlertType(Enum):
    """Alert type categories."""
    INTEGRATION_FAILURE = "integration_failure"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    DATA_QUALITY = "data_quality"
    RESOURCE_EXHAUSTION = "resource_exhaustion"


class AlertSeverity(Enum):
    """Alert severity levels."""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Alert:
    """Alert data structure."""
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    triggered_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = field(default_factory=dict)
    alert_id: Optional[int] = None


class AlertThresholdChecker:
    """
    Check metrics against thresholds and deliver alerts.

    Uses baseline + percentage approach for dynamic thresholds:
    - Calculate baseline (p50 over last 7 days for latency, 30 days for data quality)
    - Alert when current value exceeds baseline by configured percentage
    """

    def __init__(
        self,
        engine: Engine,
        baseline_days: int = 7,
        degradation_threshold: float = 2.0,  # 2x baseline
    ):
        """
        Initialize threshold checker.

        Args:
            engine: SQLAlchemy engine for metrics/alerts
            baseline_days: Days of history for baseline calculation
            degradation_threshold: Multiplier for degradation alerts (default 2x)
        """
        self.engine = engine
        self.baseline_days = baseline_days
        self.degradation_threshold = degradation_threshold

    def check_performance_degradation(
        self,
        metric_name: str,
        current_value: float,
        baseline: Optional[float] = None,
    ) -> Optional[Alert]:
        """
        Check if metric shows performance degradation.

        Args:
            metric_name: Name of metric to check
            current_value: Current metric value
            baseline: Optional pre-calculated baseline (queries DB if not provided)

        Returns:
            Alert if degradation detected, None otherwise
        """
        if baseline is None:
            baseline = self._calculate_baseline(metric_name)

        if baseline is None or baseline == 0:
            logger.debug(f"No baseline available for {metric_name}")
            return None

        ratio = current_value / baseline

        if ratio > self.degradation_threshold:
            return Alert(
                alert_type=AlertType.PERFORMANCE_DEGRADATION,
                severity=AlertSeverity.WARNING,
                title=f"Performance Degradation: {metric_name}",
                message=(
                    f"{metric_name}: {current_value:.2f} "
                    f"(baseline: {baseline:.2f}, +{(ratio - 1) * 100:.0f}%)"
                ),
                metadata={
                    "metric_name": metric_name,
                    "current_value": current_value,
                    "baseline": baseline,
                    "ratio": ratio,
                }
            )

        return None

    def check_integration_failure(
        self,
        component: str,
        error_message: str,
        error_count: int = 1,
    ) -> Alert:
        """
        Create alert for integration failure.

        Args:
            component: Component that failed (memory, ta_lab2, orchestrator)
            error_message: Error details
            error_count: Number of consecutive failures

        Returns:
            Alert for integration failure
        """
        severity = AlertSeverity.CRITICAL if error_count > 3 else AlertSeverity.WARNING

        return Alert(
            alert_type=AlertType.INTEGRATION_FAILURE,
            severity=severity,
            title=f"Integration Failure: {component}",
            message=f"{component} failed: {error_message}",
            metadata={
                "component": component,
                "error_message": error_message,
                "error_count": error_count,
            }
        )

    def check_data_quality(
        self,
        check_type: str,
        issue_count: int,
        details: Dict[str, Any],
    ) -> Optional[Alert]:
        """
        Create alert for data quality issues.

        Args:
            check_type: Type of check (gap, alignment, rowcount)
            issue_count: Number of issues found
            details: Issue details

        Returns:
            Alert if issues found, None otherwise
        """
        if issue_count == 0:
            return None

        severity = AlertSeverity.CRITICAL if issue_count > 10 else AlertSeverity.WARNING

        return Alert(
            alert_type=AlertType.DATA_QUALITY,
            severity=severity,
            title=f"Data Quality: {check_type}",
            message=f"Found {issue_count} {check_type} issues",
            metadata={
                "check_type": check_type,
                "issue_count": issue_count,
                **details,
            }
        )

    def check_resource_exhaustion(
        self,
        resource: str,
        usage_percent: float,
        threshold_percent: float = 90.0,
    ) -> Optional[Alert]:
        """
        Create alert for resource exhaustion.

        Args:
            resource: Resource name (quota, memory, connections)
            usage_percent: Current usage percentage
            threshold_percent: Alert threshold (default 90%)

        Returns:
            Alert if threshold exceeded, None otherwise
        """
        if usage_percent < threshold_percent:
            return None

        severity = AlertSeverity.CRITICAL if usage_percent >= 95 else AlertSeverity.WARNING

        return Alert(
            alert_type=AlertType.RESOURCE_EXHAUSTION,
            severity=severity,
            title=f"Resource Exhaustion: {resource}",
            message=f"{resource} at {usage_percent:.1f}% (threshold: {threshold_percent:.0f}%)",
            metadata={
                "resource": resource,
                "usage_percent": usage_percent,
                "threshold_percent": threshold_percent,
            }
        )

    def _calculate_baseline(self, metric_name: str) -> Optional[float]:
        """Calculate p50 baseline from historical data."""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY metric_value)
                    FROM observability.metrics
                    WHERE metric_name = :name
                      AND recorded_at >= NOW() - INTERVAL ':days days'
                """), {"name": metric_name, "days": self.baseline_days})
                return result.scalar()
        except Exception as e:
            logger.warning(f"Failed to calculate baseline for {metric_name}: {e}")
            return None

    def deliver_alert(self, alert: Alert) -> bool:
        """
        Deliver alert via Telegram and log to database.

        Args:
            alert: Alert to deliver

        Returns:
            True if delivery succeeded, False otherwise
        """
        success = True

        # 1. Send via Telegram (if configured)
        try:
            from ta_lab2.notifications.telegram import send_alert as telegram_send

            telegram_success = telegram_send(
                title=alert.title,
                message=alert.message,
                severity=alert.severity.value,
            )

            if not telegram_success:
                logger.warning("Telegram alert delivery failed")
                success = False
        except ImportError:
            logger.debug("Telegram not available")
        except Exception as e:
            logger.error(f"Telegram alert failed: {e}")
            success = False

        # 2. Log to database (always)
        try:
            self._log_alert_to_db(alert)
        except Exception as e:
            logger.error(f"Failed to log alert to database: {e}")
            success = False

        return success

    def _log_alert_to_db(self, alert: Alert) -> int:
        """Log alert to observability.alerts table."""
        import json

        with self.engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO observability.alerts
                (alert_type, severity, title, message, triggered_at, metadata)
                VALUES (:type, :severity, :title, :message, :triggered_at, :metadata::jsonb)
                RETURNING id
            """), {
                "type": alert.alert_type.value,
                "severity": alert.severity.value,
                "title": alert.title,
                "message": alert.message,
                "triggered_at": alert.triggered_at,
                "metadata": json.dumps(alert.metadata),
            })
            alert_id = result.scalar()
            alert.alert_id = alert_id
            return alert_id

    def get_recent_alerts(
        self,
        alert_type: Optional[AlertType] = None,
        severity: Optional[AlertSeverity] = None,
        hours: int = 24,
        limit: int = 100,
    ) -> List[Alert]:
        """
        Query recent alerts from database.

        Args:
            alert_type: Filter by type (optional)
            severity: Filter by severity (optional)
            hours: Lookback hours (default 24)
            limit: Max alerts to return

        Returns:
            List of recent alerts
        """
        query_parts = [
            "SELECT id, alert_type, severity, title, message, triggered_at, metadata",
            "FROM observability.alerts",
            "WHERE triggered_at >= NOW() - INTERVAL ':hours hours'",
        ]
        params = {"hours": hours, "limit": limit}

        if alert_type:
            query_parts.append("AND alert_type = :type")
            params["type"] = alert_type.value

        if severity:
            query_parts.append("AND severity = :severity")
            params["severity"] = severity.value

        query_parts.append("ORDER BY triggered_at DESC LIMIT :limit")

        query = " ".join(query_parts)

        alerts = []
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query), params)
                for row in result:
                    alerts.append(Alert(
                        alert_id=row[0],
                        alert_type=AlertType(row[1]),
                        severity=AlertSeverity(row[2]),
                        title=row[3],
                        message=row[4],
                        triggered_at=row[5],
                        metadata=row[6] or {},
                    ))
        except Exception as e:
            logger.error(f"Failed to query alerts: {e}")

        return alerts


def check_all_thresholds(engine: Engine, metrics: Dict[str, float]) -> List[Alert]:
    """
    Convenience function to check all threshold types.

    Args:
        engine: SQLAlchemy engine
        metrics: Dict of metric_name -> current_value

    Returns:
        List of triggered alerts
    """
    checker = AlertThresholdChecker(engine)
    alerts = []

    for name, value in metrics.items():
        alert = checker.check_performance_degradation(name, value)
        if alert:
            alerts.append(alert)
            checker.deliver_alert(alert)

    return alerts
