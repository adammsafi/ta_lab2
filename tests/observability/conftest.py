"""
Observability test fixtures.

Provides fixtures for testing metrics, health checks, and tracing infrastructure.
"""

import pytest


@pytest.fixture
def metrics_collector(mocker):
    """
    MetricsCollector with mocked database.

    Returns a MetricsCollector instance with mocked engine for testing
    metrics collection without database writes.
    """
    from ta_lab2.observability.metrics import MetricsCollector

    mock_engine = mocker.MagicMock()
    return MetricsCollector(mock_engine)


@pytest.fixture
def health_checker(mocker):
    """
    HealthChecker with mocked dependencies.

    Returns a HealthChecker instance with mocked engine and external
    service checks for testing health check logic.
    """
    from ta_lab2.observability.health import HealthChecker

    mock_engine = mocker.MagicMock()
    return HealthChecker(mock_engine)


@pytest.fixture
def tracing_context():
    """
    TracingContext for testing spans and distributed tracing.

    Returns a TracingContext for testing trace propagation and span creation.
    """
    from ta_lab2.observability.tracing import TracingContext

    return TracingContext(operation_name="test_operation")
