"""
Alert threshold configuration and testing script.

Usage:
    python -m ta_lab2.scripts.observability.alert_thresholds --test
    python -m ta_lab2.scripts.observability.alert_thresholds --check
    python -m ta_lab2.scripts.observability.alert_thresholds --list-recent
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime

from ta_lab2.config import TARGET_DB_URL

logger = logging.getLogger(__name__)


# Default threshold configuration
DEFAULT_THRESHOLDS = {
    # Performance thresholds (multiplier of baseline)
    "task_execution_duration": 2.0,   # Alert if >2x baseline
    "memory_search_duration": 2.0,
    "feature_refresh_duration": 2.0,

    # Resource thresholds (percentage)
    "gemini_quota_usage": 90.0,       # Alert at 90%
    "database_connections": 80.0,
    "memory_usage": 85.0,

    # Data quality thresholds (counts)
    "gap_threshold": 0,               # 0% tolerance (strict)
    "alignment_threshold": 0,
    "rowcount_tolerance": 0,
}


def configure_alert_thresholds(
    engine,
    thresholds: dict = None,
) -> dict:
    """
    Configure alert thresholds.

    Args:
        engine: SQLAlchemy engine
        thresholds: Custom threshold overrides

    Returns:
        Final threshold configuration
    """
    final_thresholds = DEFAULT_THRESHOLDS.copy()
    if thresholds:
        final_thresholds.update(thresholds)

    logger.info(f"Configured {len(final_thresholds)} alert thresholds")
    return final_thresholds


def test_alert_delivery(engine) -> bool:
    """
    Send test alert to verify delivery works.

    Args:
        engine: SQLAlchemy engine

    Returns:
        True if test alert delivered successfully
    """
    from ta_lab2.observability.alerts import AlertThresholdChecker, Alert, AlertType, AlertSeverity

    checker = AlertThresholdChecker(engine)

    test_alert = Alert(
        alert_type=AlertType.DATA_QUALITY,
        severity=AlertSeverity.INFO,
        title="Test Alert",
        message="This is a test alert to verify delivery is working.",
        metadata={"test": True, "timestamp": datetime.utcnow().isoformat()},
    )

    success = checker.deliver_alert(test_alert)

    if success:
        print("[OK] Test alert delivered successfully")
    else:
        print("[WARN] Test alert delivery had issues (check logs)")

    return success


def check_current_thresholds(engine) -> dict:
    """
    Check current metrics against thresholds.

    Args:
        engine: SQLAlchemy engine

    Returns:
        Dict with check results
    """
    from ta_lab2.observability.alerts import AlertThresholdChecker
    from ta_lab2.tools.ai_orchestrator.quota import QuotaTracker

    checker = AlertThresholdChecker(engine)
    results = {
        "checked_at": datetime.utcnow().isoformat(),
        "alerts_triggered": [],
        "all_ok": True,
    }

    # Check quota usage
    try:
        quota = QuotaTracker()
        status = quota.get_status()

        for platform, data in status.items():
            if data.get("available") != "unlimited":
                used = data.get("used", 0)
                limit = data.get("limit", 1500)
                usage_pct = (used / limit) * 100 if limit > 0 else 0

                alert = checker.check_resource_exhaustion(
                    f"quota_{platform}",
                    usage_pct,
                    threshold_percent=90.0,
                )

                if alert:
                    results["alerts_triggered"].append(alert.title)
                    results["all_ok"] = False
                    checker.deliver_alert(alert)
    except Exception as e:
        logger.warning(f"Quota check failed: {e}")

    print(f"\nThreshold Check Results ({results['checked_at']}):")
    print(f"  All OK: {results['all_ok']}")
    print(f"  Alerts triggered: {len(results['alerts_triggered'])}")

    for alert_title in results["alerts_triggered"]:
        print(f"    - {alert_title}")

    return results


def list_recent_alerts(engine, hours: int = 24) -> None:
    """
    List recent alerts from database.

    Args:
        engine: SQLAlchemy engine
        hours: Lookback hours
    """
    from ta_lab2.observability.alerts import AlertThresholdChecker

    checker = AlertThresholdChecker(engine)
    alerts = checker.get_recent_alerts(hours=hours)

    print(f"\nRecent Alerts (last {hours} hours):")
    print("-" * 60)

    if not alerts:
        print("  No alerts in this period")
        return

    for alert in alerts:
        print(f"  [{alert.severity.value.upper()}] {alert.title}")
        print(f"    Time: {alert.triggered_at}")
        print(f"    Type: {alert.alert_type.value}")
        print(f"    Message: {alert.message[:100]}...")
        print()


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Alert threshold management")
    parser.add_argument("--test", action="store_true", help="Send test alert")
    parser.add_argument("--check", action="store_true", help="Check current thresholds")
    parser.add_argument("--list-recent", action="store_true", help="List recent alerts")
    parser.add_argument("--hours", type=int, default=24, help="Hours for --list-recent")

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(level=logging.INFO)

    # Get database connection
    if not TARGET_DB_URL:
        print("ERROR: No database URL configured")
        return 1

    from sqlalchemy import create_engine
    engine = create_engine(TARGET_DB_URL)

    if args.test:
        test_alert_delivery(engine)
    elif args.check:
        check_current_thresholds(engine)
    elif args.list_recent:
        list_recent_alerts(engine, hours=args.hours)
    else:
        # Default: show thresholds
        thresholds = configure_alert_thresholds(engine)
        print("\nConfigured Thresholds:")
        for name, value in thresholds.items():
            print(f"  {name}: {value}")

    return 0


if __name__ == "__main__":
    exit(main())
