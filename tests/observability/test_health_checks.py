"""Tests for health check probes."""

import pytest
from unittest.mock import MagicMock
from datetime import datetime


@pytest.mark.observability
@pytest.mark.mocked_deps
class TestHealthChecker:
    """Tests for HealthChecker class."""

    def test_liveness_always_healthy(self, mocker):
        """Test liveness probe always returns healthy (process alive)."""
        from ta_lab2.observability.health import HealthChecker

        mock_engine = mocker.MagicMock()
        checker = HealthChecker(mock_engine)

        status = checker.liveness()

        assert status.healthy is True
        assert "alive" in status.message.lower()

    def test_readiness_checks_database(self, mocker):
        """Test readiness probe checks database connection."""
        from ta_lab2.observability.health import HealthChecker

        mock_engine = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = 1

        checker = HealthChecker(mock_engine)
        status = checker.readiness()

        assert status.healthy is True
        assert "checks" in status.details
        assert "database" in status.details["checks"]
        assert status.details["checks"]["database"]["healthy"] is True

    def test_readiness_fails_on_db_error(self, mocker):
        """Test readiness fails when database unavailable."""
        from ta_lab2.observability.health import HealthChecker

        mock_engine = mocker.MagicMock()
        mock_engine.connect.side_effect = Exception("Connection refused")

        checker = HealthChecker(mock_engine)
        status = checker.readiness()

        assert status.healthy is False
        assert "checks" in status.details
        assert "database" in status.details["checks"]
        assert status.details["checks"]["database"]["healthy"] is False

    def test_readiness_checks_memory_if_configured(self, mocker):
        """Test readiness checks memory service when configured."""
        from ta_lab2.observability.health import HealthChecker

        mock_engine = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.scalar.return_value = 1

        mock_memory = mocker.MagicMock()
        mock_memory.health_check.return_value = True  # Boolean, not dict

        checker = HealthChecker(mock_engine, memory_client=mock_memory)
        status = checker.readiness()

        assert status.healthy is True
        assert "checks" in status.details
        assert "memory" in status.details["checks"]
        assert status.details["checks"]["memory"]["healthy"] is True

    def test_startup_checks_data_loaded(self, mocker):
        """Test startup probe checks if initial data loaded."""
        from ta_lab2.observability.health import HealthChecker

        mock_engine = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_result = mocker.MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value = mock_result
        # Both dim_timeframe and dim_sessions have rows
        mock_result.scalar.return_value = 199

        checker = HealthChecker(mock_engine)
        status = checker.startup()

        assert status.healthy is True
        # Note: startup_complete is NOT automatically set by startup() method
        # The caller must set it manually if they want to mark startup as complete

    def test_startup_fails_when_no_data(self, mocker):
        """Test startup fails when initial data not loaded."""
        from ta_lab2.observability.health import HealthChecker

        mock_engine = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_result = mocker.MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value = mock_result
        # dim_timeframe empty
        mock_result.scalar.return_value = 0

        checker = HealthChecker(mock_engine)
        status = checker.startup()

        assert status.healthy is False
        assert checker.startup_complete is False  # Should still be False (initialized to False)

    def test_health_status_dataclass(self):
        """Test HealthStatus dataclass structure."""
        from ta_lab2.observability.health import HealthStatus

        status = HealthStatus(
            healthy=True,
            message="All systems operational",
            checked_at=datetime.utcnow(),
            details={"db": True, "memory": True}
        )

        assert status.healthy is True
        assert status.details["db"] is True
