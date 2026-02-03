"""
Observability infrastructure for ta_lab2.

Provides:
- Distributed tracing with OpenTelemetry
- Metrics collection (counter, gauge, histogram)
- Health checks (liveness, readiness, startup)
- Workflow state tracking
- Alert threshold checking and delivery

Usage:
    from ta_lab2.observability import (
        TracingContext,
        MetricsCollector,
        HealthChecker,
        WorkflowStateTracker,
        AlertThresholdChecker,
        HealthStatus,
    )

    # Tracing
    with TracingContext("my_operation") as ctx:
        ctx.add_event("processing_started")
        # ... do work ...
        print(f"Trace ID: {ctx.trace_id}")

    # Metrics
    metrics = MetricsCollector(engine)
    metrics.counter("tasks_completed", value=1, task_type="ema_refresh")
    metrics.gauge("memory_usage_mb", value=512.5)
    metrics.histogram("task_duration_ms", value=1234)

    # Health checks
    health = HealthChecker(engine, memory_client=mem_client)
    liveness = health.liveness()  # Simple process check
    readiness = health.readiness()  # Database + dependencies
    startup = health.startup()  # Initial data loaded

    # Workflow tracking
    tracker = WorkflowStateTracker(engine)
    tracker.create_workflow(
        workflow_id=uuid4(),
        correlation_id="abc123",
        workflow_type="ema_refresh"
    )
    tracker.transition(workflow_id, "running", "success")

    # Alerts
    checker = AlertThresholdChecker(engine)
    alert = checker.check_integration_failure("component", "error message", 1)
    if alert:
        print(f"Alert: {alert.message}")
"""

from __future__ import annotations

from ta_lab2.observability.alerts import (
    Alert,
    AlertSeverity,
    AlertThresholdChecker,
    AlertType,
    check_all_thresholds,
)
from ta_lab2.observability.health import HealthChecker, HealthStatus
from ta_lab2.observability.metrics import Metric, MetricsCollector
from ta_lab2.observability.storage import (
    WorkflowStateTracker,
    ensure_observability_tables,
)
from ta_lab2.observability.tracing import (
    TracingContext,
    generate_correlation_id,
    get_tracer,
    setup_tracing,
)

__all__ = [
    # Tracing
    "TracingContext",
    "setup_tracing",
    "get_tracer",
    "generate_correlation_id",
    # Metrics
    "MetricsCollector",
    "Metric",
    # Health
    "HealthChecker",
    "HealthStatus",
    # Storage
    "WorkflowStateTracker",
    "ensure_observability_tables",
    # Alerts
    "Alert",
    "AlertType",
    "AlertSeverity",
    "AlertThresholdChecker",
    "check_all_thresholds",
]
