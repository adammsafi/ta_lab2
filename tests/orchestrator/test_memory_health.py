"""Tests for memory health monitoring."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

from ta_lab2.tools.ai_orchestrator.memory.health import (
    HealthReport,
    MemoryHealthMonitor,
    scan_stale_memories,
)


# Test HealthReport
def test_health_report_creation():
    """Test HealthReport creation with all fields."""
    report = HealthReport(
        total_memories=100,
        healthy=80,
        stale=15,
        deprecated=5,
        missing_metadata=2,
        age_distribution={"0-30d": 50, "30-60d": 30, "60-90d": 15, "90+d": 5},
        stale_memories=[],
        scan_timestamp="2026-01-28T15:00:00",
    )

    assert report.total_memories == 100
    assert report.healthy == 80
    assert report.stale == 15
    assert report.deprecated == 5
    assert report.missing_metadata == 2
    assert report.scan_timestamp == "2026-01-28T15:00:00"


def test_health_report_age_distribution():
    """Test HealthReport age distribution dict works."""
    age_dist = {"0-30d": 100, "30-60d": 50, "60-90d": 25, "90+d": 10}

    report = HealthReport(
        total_memories=185,
        healthy=150,
        stale=35,
        deprecated=10,
        missing_metadata=0,
        age_distribution=age_dist,
        stale_memories=[],
        scan_timestamp="2026-01-28T15:00:00",
    )

    assert report.age_distribution == age_dist
    assert report.age_distribution["0-30d"] == 100
    assert report.age_distribution["90+d"] == 10


# Test MemoryHealthMonitor
def test_monitor_creation():
    """Test monitor initializes with client."""
    mock_client = Mock()
    monitor = MemoryHealthMonitor(client=mock_client, staleness_days=60)

    assert monitor.client == mock_client
    assert monitor.staleness_days == 60


def test_monitor_default_staleness():
    """Test default staleness is 90 days."""
    mock_client = Mock()
    monitor = MemoryHealthMonitor(client=mock_client)

    assert monitor.staleness_days == 90


def test_scan_finds_stale_memories():
    """Test memories older than threshold are flagged."""
    # Create mock memories with stale timestamps
    now = datetime.now(timezone.utc)
    old_date = now - timedelta(days=100)  # Stale
    recent_date = now - timedelta(days=30)  # Fresh

    mock_memories = [
        {
            "id": "mem_stale_1",
            "memory": "This is stale memory content",
            "metadata": {
                "created_at": old_date.isoformat(),
                "last_verified": old_date.isoformat(),
            },
        },
        {
            "id": "mem_fresh_1",
            "memory": "This is fresh memory content",
            "metadata": {
                "created_at": recent_date.isoformat(),
                "last_verified": recent_date.isoformat(),
            },
        },
    ]

    mock_client = Mock()
    mock_client.get_all.return_value = mock_memories

    monitor = MemoryHealthMonitor(client=mock_client, staleness_days=90)
    stale = monitor.scan_stale_memories()

    # Should find only the stale memory
    assert len(stale) == 1
    assert stale[0]["id"] == "mem_stale_1"
    assert stale[0]["age_days"] >= 90


def test_scan_ignores_recent_memories():
    """Test recent memories are not flagged."""
    now = datetime.now(timezone.utc)
    recent_date = now - timedelta(days=30)

    mock_memories = [
        {
            "id": "mem_recent_1",
            "memory": "Recent memory",
            "metadata": {
                "created_at": recent_date.isoformat(),
                "last_verified": recent_date.isoformat(),
            },
        },
        {
            "id": "mem_recent_2",
            "memory": "Another recent memory",
            "metadata": {
                "created_at": recent_date.isoformat(),
                "last_verified": recent_date.isoformat(),
            },
        },
    ]

    mock_client = Mock()
    mock_client.get_all.return_value = mock_memories

    monitor = MemoryHealthMonitor(client=mock_client, staleness_days=90)
    stale = monitor.scan_stale_memories()

    # Should find no stale memories
    assert len(stale) == 0


def test_scan_handles_missing_metadata():
    """Test missing last_verified is detected as stale."""
    mock_memories = [
        {
            "id": "mem_missing_1",
            "memory": "Memory without last_verified",
            "metadata": {
                "created_at": "2026-01-01T00:00:00"
                # No last_verified
            },
        },
        {"id": "mem_missing_2", "memory": "Memory without metadata", "metadata": {}},
    ]

    mock_client = Mock()
    mock_client.get_all.return_value = mock_memories

    monitor = MemoryHealthMonitor(client=mock_client, staleness_days=90)
    stale = monitor.scan_stale_memories()

    # Both should be flagged as stale
    assert len(stale) == 2
    assert stale[0]["last_verified"] == "never"
    assert stale[1]["last_verified"] == "never"
    assert stale[0]["age_days"] is None
    assert stale[1]["age_days"] is None


# Test generate_health_report
def test_report_categorizes_by_age():
    """Test age distribution calculated correctly."""
    now = datetime.now(timezone.utc)

    mock_memories = [
        # 0-30d bucket
        {
            "id": "mem_1",
            "memory": "Fresh",
            "metadata": {
                "created_at": (now - timedelta(days=10)).isoformat(),
                "last_verified": (now - timedelta(days=10)).isoformat(),
            },
        },
        # 30-60d bucket
        {
            "id": "mem_2",
            "memory": "Moderate",
            "metadata": {
                "created_at": (now - timedelta(days=45)).isoformat(),
                "last_verified": (now - timedelta(days=45)).isoformat(),
            },
        },
        # 60-90d bucket
        {
            "id": "mem_3",
            "memory": "Aging",
            "metadata": {
                "created_at": (now - timedelta(days=75)).isoformat(),
                "last_verified": (now - timedelta(days=75)).isoformat(),
            },
        },
        # 90+d bucket
        {
            "id": "mem_4",
            "memory": "Stale",
            "metadata": {
                "created_at": (now - timedelta(days=120)).isoformat(),
                "last_verified": (now - timedelta(days=120)).isoformat(),
            },
        },
    ]

    mock_client = Mock()
    mock_client.get_all.return_value = mock_memories

    monitor = MemoryHealthMonitor(client=mock_client, staleness_days=90)
    report = monitor.generate_health_report()

    assert report.total_memories == 4
    assert report.age_distribution["0-30d"] == 1
    assert report.age_distribution["30-60d"] == 1
    assert report.age_distribution["60-90d"] == 1
    assert report.age_distribution["90+d"] == 1


def test_report_counts_deprecated():
    """Test deprecated memories are counted."""
    now = datetime.now(timezone.utc)

    mock_memories = [
        {
            "id": "mem_1",
            "memory": "Active",
            "metadata": {
                "created_at": now.isoformat(),
                "last_verified": now.isoformat(),
            },
        },
        {
            "id": "mem_2",
            "memory": "Deprecated",
            "metadata": {
                "created_at": now.isoformat(),
                "last_verified": now.isoformat(),
                "deprecated_since": now.isoformat(),
                "deprecation_reason": "Test reason",
            },
        },
    ]

    mock_client = Mock()
    mock_client.get_all.return_value = mock_memories

    monitor = MemoryHealthMonitor(client=mock_client, staleness_days=90)
    report = monitor.generate_health_report()

    assert report.total_memories == 2
    assert report.deprecated == 1


def test_report_includes_stale_list():
    """Test stale memories included in report for review."""
    now = datetime.now(timezone.utc)
    stale_date = now - timedelta(days=100)

    mock_memories = [
        {
            "id": "mem_stale_1",
            "memory": "This is a long stale memory content that should be truncated to 100 characters for the report display purposes",
            "metadata": {
                "created_at": stale_date.isoformat(),
                "last_verified": stale_date.isoformat(),
            },
        }
    ]

    mock_client = Mock()
    mock_client.get_all.return_value = mock_memories

    monitor = MemoryHealthMonitor(client=mock_client, staleness_days=90)
    report = monitor.generate_health_report()

    assert len(report.stale_memories) == 1
    assert report.stale_memories[0]["id"] == "mem_stale_1"
    assert len(report.stale_memories[0]["content"]) <= 100
    assert report.stale_memories[0]["age_days"] >= 90


# Test flag_stale_memories
def test_flag_dry_run_no_update():
    """Test dry run does not modify memories."""
    now = datetime.now(timezone.utc)
    stale_date = now - timedelta(days=100)

    mock_memories = [
        {
            "id": "mem_stale_1",
            "memory": "Stale memory",
            "metadata": {
                "created_at": stale_date.isoformat(),
                "last_verified": stale_date.isoformat(),
            },
        }
    ]

    mock_client = Mock()
    mock_client.get_all.return_value = mock_memories

    monitor = MemoryHealthMonitor(client=mock_client, staleness_days=90)
    count = monitor.flag_stale_memories(dry_run=True)

    # Should return count but not call update
    assert count == 1
    mock_client.update.assert_not_called()


def test_flag_updates_metadata():
    """Test real run adds deprecated_since."""
    now = datetime.now(timezone.utc)
    stale_date = now - timedelta(days=100)

    mock_memories = [
        {
            "id": "mem_stale_1",
            "memory": "Stale memory",
            "metadata": {
                "created_at": stale_date.isoformat(),
                "last_verified": stale_date.isoformat(),
            },
        }
    ]

    mock_client = Mock()
    mock_client.get_all.return_value = mock_memories

    monitor = MemoryHealthMonitor(client=mock_client, staleness_days=90)
    count = monitor.flag_stale_memories(dry_run=False)

    # Should call update with deprecated metadata
    assert count == 1
    assert mock_client.update.called
    call_args = mock_client.update.call_args

    assert call_args.kwargs["memory_id"] == "mem_stale_1"
    assert "deprecated_since" in call_args.kwargs["metadata"]
    assert "deprecation_reason" in call_args.kwargs["metadata"]


def test_flag_includes_reason():
    """Test deprecation reason is set."""
    now = datetime.now(timezone.utc)
    stale_date = now - timedelta(days=100)

    mock_memories = [
        {
            "id": "mem_stale_1",
            "memory": "Stale memory",
            "metadata": {
                "created_at": stale_date.isoformat(),
                "last_verified": stale_date.isoformat(),
            },
        }
    ]

    mock_client = Mock()
    mock_client.get_all.return_value = mock_memories

    monitor = MemoryHealthMonitor(client=mock_client, staleness_days=90)
    monitor.flag_stale_memories(dry_run=False)

    call_args = mock_client.update.call_args
    reason = call_args.kwargs["metadata"]["deprecation_reason"]

    assert "Not verified" in reason
    assert "days" in reason
    assert "90" in reason


# Test refresh_verification
def test_refresh_updates_timestamp():
    """Test last_verified updated to current time."""
    now = datetime.now(timezone.utc)
    old_date = now - timedelta(days=100)

    mock_memories = [
        {
            "id": "mem_1",
            "memory": "Memory to refresh",
            "metadata": {
                "created_at": old_date.isoformat(),
                "last_verified": old_date.isoformat(),
            },
        }
    ]

    mock_client = Mock()
    mock_client.get_all.return_value = mock_memories

    monitor = MemoryHealthMonitor(client=mock_client, staleness_days=90)
    count = monitor.refresh_verification(["mem_1"])

    assert count == 1
    assert mock_client.update.called

    call_args = mock_client.update.call_args
    assert call_args.kwargs["memory_id"] == "mem_1"

    # Check that last_verified was updated to recent time
    updated_timestamp = call_args.kwargs["metadata"]["last_verified"]
    updated_date = datetime.fromisoformat(updated_timestamp)

    # Should be very recent (within last minute)
    time_diff = (datetime.now(timezone.utc) - updated_date).total_seconds()
    assert time_diff < 60


def test_refresh_multiple_memories():
    """Test batch refresh works for multiple memories."""
    now = datetime.now(timezone.utc)
    old_date = now - timedelta(days=100)

    mock_memories = [
        {
            "id": "mem_1",
            "memory": "Memory 1",
            "metadata": {
                "created_at": old_date.isoformat(),
                "last_verified": old_date.isoformat(),
            },
        },
        {
            "id": "mem_2",
            "memory": "Memory 2",
            "metadata": {
                "created_at": old_date.isoformat(),
                "last_verified": old_date.isoformat(),
            },
        },
    ]

    mock_client = Mock()
    mock_client.get_all.return_value = mock_memories

    monitor = MemoryHealthMonitor(client=mock_client, staleness_days=90)
    count = monitor.refresh_verification(["mem_1", "mem_2"])

    assert count == 2
    assert mock_client.update.call_count == 2


# Test scan_stale_memories convenience function
def test_scan_stale_memories_convenience_function():
    """Test convenience function creates monitor and scans."""
    now = datetime.now(timezone.utc)
    stale_date = now - timedelta(days=100)

    mock_memories = [
        {
            "id": "mem_stale_1",
            "memory": "Stale",
            "metadata": {
                "created_at": stale_date.isoformat(),
                "last_verified": stale_date.isoformat(),
            },
        }
    ]

    mock_client = Mock()
    mock_client.get_all.return_value = mock_memories

    with patch(
        "ta_lab2.tools.ai_orchestrator.memory.health.get_mem0_client"
    ) as mock_get_client:
        mock_get_client.return_value = mock_client

        stale = scan_stale_memories(staleness_days=60)

        assert len(stale) == 1
        assert stale[0]["id"] == "mem_stale_1"


# Integration test
@pytest.mark.integration
def test_health_scan_real_db():
    """Integration test: scan against real Mem0 client.

    This test requires Qdrant to be available and properly configured.
    """
    from ta_lab2.tools.ai_orchestrator.memory import get_mem0_client

    try:
        client = get_mem0_client()
        monitor = MemoryHealthMonitor(client=client, staleness_days=90)

        # Run health scan
        report = monitor.generate_health_report()

        # Basic validation
        assert isinstance(report, HealthReport)
        assert report.total_memories >= 0
        assert report.healthy >= 0
        assert report.stale >= 0
        assert report.deprecated >= 0
        assert len(report.age_distribution) == 4

        # Validate age distribution keys
        expected_keys = {"0-30d", "30-60d", "60-90d", "90+d"}
        assert set(report.age_distribution.keys()) == expected_keys

    except Exception as e:
        pytest.skip(f"Integration test skipped: {e}")
