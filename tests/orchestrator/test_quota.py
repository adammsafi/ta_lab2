"""Comprehensive tests for quota tracking system."""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ta_lab2.tools.ai_orchestrator.quota import QuotaAlert, QuotaLimit, QuotaTracker
from ta_lab2.tools.ai_orchestrator.persistence import QuotaPersistence, QuotaState


@pytest.fixture
def temp_storage_path():
    """Create temporary storage path for isolated tests."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_path = f.name

    yield temp_path

    # Cleanup
    Path(temp_path).unlink(missing_ok=True)
    Path(temp_path).with_suffix('.tmp').unlink(missing_ok=True)


@pytest.fixture
def clean_quota(temp_storage_path):
    """Create fresh QuotaTracker with temp storage."""
    return QuotaTracker(persistence_path=temp_storage_path)


# =============================================================================
# UTC Midnight Reset Tests
# =============================================================================

def test_quota_resets_at_utc_midnight(temp_storage_path):
    """Verify quota resets at UTC midnight."""
    tracker = QuotaTracker(persistence_path=temp_storage_path)

    # Record some usage
    tracker.record_usage("gemini", tokens=500)
    assert tracker.limits["gemini_cli"].used == 500

    # Mock time to be past reset time
    future_time = tracker.limits["gemini_cli"].resets_at + timedelta(hours=1)

    with patch('ta_lab2.tools.ai_orchestrator.quota.datetime') as mock_datetime:
        mock_datetime.now.return_value = future_time
        mock_datetime.fromisoformat = datetime.fromisoformat

        # Check quota (should trigger reset)
        result = tracker.can_use("gemini")

        assert result is True
        assert tracker.limits["gemini_cli"].used == 0


def test_quota_does_not_reset_before_midnight(clean_quota):
    """Verify no premature reset before midnight."""
    tracker = clean_quota

    # Record usage
    tracker.record_usage("gemini", tokens=500)
    assert tracker.limits["gemini_cli"].used == 500

    # Check quota (same day, should not reset)
    result = tracker.can_use("gemini")

    assert result is True
    assert tracker.limits["gemini_cli"].used == 500


def test_quota_persists_after_reset(temp_storage_path):
    """Verify new day starts fresh with persistence."""
    tracker = QuotaTracker(persistence_path=temp_storage_path)

    # Record usage
    tracker.record_usage("gemini", tokens=1000)
    assert tracker.limits["gemini_cli"].used == 1000

    # Simulate next day
    future_time = tracker.limits["gemini_cli"].resets_at + timedelta(hours=1)

    with patch('ta_lab2.tools.ai_orchestrator.quota.datetime') as mock_datetime:
        mock_datetime.now.return_value = future_time
        mock_datetime.fromisoformat = datetime.fromisoformat

        # Trigger reset
        tracker.can_use("gemini")

    # Create new tracker (simulates restart)
    new_tracker = QuotaTracker(persistence_path=temp_storage_path)

    # Should have reset state
    assert new_tracker.limits["gemini_cli"].used == 0


# =============================================================================
# Threshold Alert Tests
# =============================================================================

def test_alert_at_50_percent(temp_storage_path):
    """Verify callback fires at 50% threshold."""
    alerts = []

    def capture_alert(alert: QuotaAlert):
        alerts.append(alert)

    tracker = QuotaTracker(
        alert_thresholds=[50, 80, 90],
        on_alert=capture_alert,
        persistence_path=temp_storage_path
    )

    # Use 750 requests (50% of 1500)
    tracker.record_usage("gemini", tokens=750)

    assert len(alerts) == 1
    assert alerts[0].threshold == 50
    assert alerts[0].platform == "gemini_cli"
    assert alerts[0].current_usage == 750


def test_alert_at_80_percent(temp_storage_path):
    """Verify callback fires at 80% threshold."""
    alerts = []

    def capture_alert(alert: QuotaAlert):
        alerts.append(alert)

    tracker = QuotaTracker(
        alert_thresholds=[50, 80, 90],
        on_alert=capture_alert,
        persistence_path=temp_storage_path
    )

    # Use 1200 requests (80% of 1500)
    tracker.record_usage("gemini", tokens=1200)

    # Should trigger both 50% and 80%
    assert len(alerts) == 2
    thresholds = [a.threshold for a in alerts]
    assert 50 in thresholds
    assert 80 in thresholds


def test_alert_at_90_percent(temp_storage_path):
    """Verify callback fires at 90% threshold."""
    alerts = []

    def capture_alert(alert: QuotaAlert):
        alerts.append(alert)

    tracker = QuotaTracker(
        alert_thresholds=[50, 80, 90],
        on_alert=capture_alert,
        persistence_path=temp_storage_path
    )

    # Use 1350 requests (90% of 1500)
    tracker.record_usage("gemini", tokens=1350)

    # Should trigger all three thresholds
    assert len(alerts) == 3
    thresholds = [a.threshold for a in alerts]
    assert 50 in thresholds
    assert 80 in thresholds
    assert 90 in thresholds


def test_no_duplicate_alerts(temp_storage_path):
    """Same threshold doesn't alert twice."""
    alerts = []

    def capture_alert(alert: QuotaAlert):
        alerts.append(alert)

    tracker = QuotaTracker(
        alert_thresholds=[50, 80, 90],
        on_alert=capture_alert,
        persistence_path=temp_storage_path
    )

    # Cross 50% threshold
    tracker.record_usage("gemini", tokens=750)
    assert len(alerts) == 1

    # Use more, but stay in 50-80% range
    tracker.record_usage("gemini", tokens=100)
    assert len(alerts) == 1  # No new alert


# =============================================================================
# Persistence Tests
# =============================================================================

def test_quota_persists_across_restart(temp_storage_path):
    """Save, recreate, verify state persists."""
    # First tracker
    tracker1 = QuotaTracker(persistence_path=temp_storage_path)
    tracker1.record_usage("gemini", tokens=800)

    assert tracker1.limits["gemini_cli"].used == 800

    # Create new tracker (simulates restart)
    tracker2 = QuotaTracker(persistence_path=temp_storage_path)

    # Should load previous state
    assert tracker2.limits["gemini_cli"].used == 800


def test_corrupted_file_handled(temp_storage_path):
    """Bad JSON doesn't crash."""
    # Write corrupted JSON
    with open(temp_storage_path, 'w') as f:
        f.write("{ invalid json }")

    # Should not crash, should start fresh
    tracker = QuotaTracker(persistence_path=temp_storage_path)

    assert tracker.limits["gemini_cli"].used == 0


def test_missing_file_handled(temp_storage_path):
    """No file = fresh state."""
    # Ensure file doesn't exist
    Path(temp_storage_path).unlink(missing_ok=True)

    tracker = QuotaTracker(persistence_path=temp_storage_path)

    assert tracker.limits["gemini_cli"].used == 0


# =============================================================================
# Reservation Tests
# =============================================================================

def test_reserve_blocks_quota(clean_quota):
    """Reserved quota not available."""
    tracker = clean_quota

    # Reserve 500 requests
    result = tracker.reserve("gemini", amount=500)
    assert result is True

    # Should have 500 reserved
    assert tracker.limits["gemini_cli"].reserved == 500

    # Try to use 1100 more (total would be 1100 + 500 = 1600, exceeds 1500)
    result = tracker.can_use("gemini", amount=1100)
    assert result is False


def test_release_frees_quota(clean_quota):
    """Released quota becomes available."""
    tracker = clean_quota

    # Reserve 500
    tracker.reserve("gemini", amount=500)
    assert tracker.limits["gemini_cli"].reserved == 500

    # Release 300
    tracker.release("gemini", amount=300)
    assert tracker.limits["gemini_cli"].reserved == 200


def test_record_usage_releases_reservation(clean_quota):
    """Using reserved quota works correctly."""
    tracker = clean_quota

    # Reserve 500
    tracker.reserve("gemini", amount=500)
    assert tracker.limits["gemini_cli"].reserved == 500

    # Use 300 (should release 300 from reservation)
    tracker.record_usage("gemini", tokens=300)

    assert tracker.limits["gemini_cli"].used == 300
    assert tracker.limits["gemini_cli"].reserved == 200


def test_cannot_reserve_beyond_limit(clean_quota):
    """Reservation respects limits."""
    tracker = clean_quota

    # Try to reserve 2000 (exceeds 1500 limit)
    result = tracker.reserve("gemini", amount=2000)
    assert result is False

    # Should have no reservation
    assert tracker.limits["gemini_cli"].reserved == 0


# =============================================================================
# Daily Summary Tests
# =============================================================================

def test_daily_summary_format(clean_quota):
    """Verify summary structure."""
    tracker = clean_quota
    summary = tracker.get_daily_summary()

    # Check structure
    assert "gemini_cli" in summary
    assert "used" in summary["gemini_cli"]
    assert "limit" in summary["gemini_cli"]
    assert "remaining" in summary["gemini_cli"]
    assert "percent_used" in summary["gemini_cli"]
    assert "alerts_triggered" in summary["gemini_cli"]


def test_daily_summary_after_usage(temp_storage_path):
    """Accurate counts in summary."""
    alerts = []
    tracker = QuotaTracker(
        on_alert=lambda a: alerts.append(a),
        persistence_path=temp_storage_path
    )

    # Use 800 requests (53.3%, triggers 50% alert)
    tracker.record_usage("gemini", tokens=800)

    summary = tracker.get_daily_summary()

    assert summary["gemini_cli"]["used"] == 800
    assert summary["gemini_cli"]["limit"] == 1500
    assert summary["gemini_cli"]["remaining"] == 700
    assert summary["gemini_cli"]["percent_used"] == pytest.approx(53.3, abs=0.1)
    assert 50 in summary["gemini_cli"]["alerts_triggered"]


# =============================================================================
# Integration Tests
# =============================================================================

def test_full_quota_lifecycle(temp_storage_path):
    """Test complete quota lifecycle: reserve, use, alert, persist, reset."""
    alerts = []

    def capture_alert(alert: QuotaAlert):
        alerts.append(alert)

    # Create tracker
    tracker = QuotaTracker(
        alert_thresholds=[50, 80, 90],
        on_alert=capture_alert,
        persistence_path=temp_storage_path
    )

    # Reserve some quota
    assert tracker.reserve("gemini", amount=200) is True

    # Use quota (triggers release of reservation)
    tracker.record_usage("gemini", tokens=500)

    # Check state
    assert tracker.limits["gemini_cli"].used == 500
    assert tracker.limits["gemini_cli"].reserved == 0  # 200 released, 300 not reserved

    # Use more (triggers 50% alert)
    tracker.record_usage("gemini", tokens=300)

    assert len(alerts) == 1
    assert alerts[0].threshold == 50

    # Verify persistence
    new_tracker = QuotaTracker(persistence_path=temp_storage_path)
    assert new_tracker.limits["gemini_cli"].used == 800


def test_display_status_output(clean_quota):
    """Verify display_status produces formatted output."""
    tracker = clean_quota
    tracker.record_usage("gemini", tokens=750)

    output = tracker.display_status()

    # Basic checks
    assert "Quota Status" in output
    assert "gemini_cli" in output
    assert "750/1500" in output
    assert "█" in output  # Progress bar filled section
    assert "░" in output  # Progress bar unfilled section
    assert "Resets in:" in output
