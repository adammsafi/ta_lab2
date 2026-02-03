"""
Metrics collection module with PostgreSQL storage.

Provides:
- Metric dataclass for metric data
- MetricsCollector for recording and querying metrics
- counter(), gauge(), histogram() convenience methods

Metrics are stored in observability.metrics table (partitioned by month).

Usage:
    from ta_lab2.observability.metrics import MetricsCollector

    collector = MetricsCollector(engine)

    # Counter: cumulative count (tasks completed, errors, etc.)
    collector.counter("tasks_completed", value=1, task_type="ema_refresh")

    # Gauge: point-in-time value (memory usage, queue depth, etc.)
    collector.gauge("memory_usage_mb", value=512.5)

    # Histogram: distribution of values (latency, payload size, etc.)
    collector.histogram("task_duration_ms", value=1234, task_type="backtest")

    # Query metrics
    recent = collector.query("task_duration_ms", hours=24)
    p95 = collector.get_percentile("task_duration_ms", percentile=0.95, hours=24)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import Engine, text

logger = logging.getLogger(__name__)


# =============================================================================
# Metric Data Classes
# =============================================================================


@dataclass
class Metric:
    """
    Metric data point.

    Attributes:
        name: Metric name (e.g., "task_duration_ms")
        value: Metric value (numeric)
        metric_type: Type - 'counter', 'gauge', or 'histogram'
        timestamp: When metric was recorded (defaults to now)
        labels: Optional dict of labels for filtering/grouping
    """

    name: str
    value: float
    metric_type: str  # 'counter', 'gauge', 'histogram'
    timestamp: datetime = field(default_factory=datetime.utcnow)
    labels: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate metric type."""
        valid_types = {"counter", "gauge", "histogram"}
        if self.metric_type not in valid_types:
            raise ValueError(
                f"metric_type must be one of {valid_types}, got {self.metric_type}"
            )


# =============================================================================
# Metrics Collector
# =============================================================================


class MetricsCollector:
    """
    Collects and stores metrics in PostgreSQL.

    Metrics types:
    - Counter: Cumulative count (tasks_completed, errors_total)
    - Gauge: Point-in-time value (memory_usage_mb, queue_depth)
    - Histogram: Distribution of values (task_duration_ms, payload_size_bytes)

    All metrics stored in observability.metrics table with labels for filtering.
    """

    def __init__(self, engine: Engine):
        """
        Initialize metrics collector.

        Args:
            engine: SQLAlchemy engine
        """
        self.engine = engine
        self._ensure_table()

    def _ensure_table(self) -> None:
        """
        Verify observability.metrics table exists.

        Logs warning if table doesn't exist but doesn't fail.
        Table should be created via ensure_observability_tables().
        """
        query = text(
            """
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'observability'
                AND table_name = 'metrics'
            )
        """
        )

        try:
            with self.engine.connect() as conn:
                exists = conn.execute(query).scalar()

                if not exists:
                    logger.warning(
                        "observability.metrics table doesn't exist - "
                        "run ensure_observability_tables() first"
                    )
        except Exception as e:
            logger.warning(f"Could not verify metrics table: {e}")

    def record(self, metric: Metric) -> None:
        """
        Record a metric to database.

        Args:
            metric: Metric to record

        Raises:
            Exception: If database insert fails
        """
        query = text(
            """
            INSERT INTO observability.metrics
                (metric_name, metric_value, metric_type, recorded_at, labels)
            VALUES
                (:metric_name, :metric_value, :metric_type, :recorded_at, :labels)
        """
        )

        params = {
            "metric_name": metric.name,
            "metric_value": metric.value,
            "metric_type": metric.metric_type,
            "recorded_at": metric.timestamp,
            "labels": metric.labels if metric.labels else None,
        }

        try:
            with self.engine.begin() as conn:
                conn.execute(query, params)

            logger.debug(
                f"Recorded {metric.metric_type} metric: {metric.name}={metric.value}"
            )
        except Exception as e:
            logger.error(f"Failed to record metric {metric.name}: {e}")
            raise

    def counter(self, name: str, value: float = 1.0, **labels: Any) -> None:
        """
        Record counter metric.

        Counters are cumulative - they only go up.
        Use for: tasks_completed, requests_total, errors_count

        Args:
            name: Metric name
            value: Increment value (default 1.0)
            **labels: Label key-value pairs
        """
        metric = Metric(
            name=name,
            value=value,
            metric_type="counter",
            labels=labels,
        )
        self.record(metric)

    def gauge(self, name: str, value: float, **labels: Any) -> None:
        """
        Record gauge metric.

        Gauges are point-in-time values that can go up or down.
        Use for: memory_usage_mb, queue_depth, active_connections

        Args:
            name: Metric name
            value: Current value
            **labels: Label key-value pairs
        """
        metric = Metric(
            name=name,
            value=value,
            metric_type="gauge",
            labels=labels,
        )
        self.record(metric)

    def histogram(self, name: str, value: float, **labels: Any) -> None:
        """
        Record histogram metric.

        Histograms track distribution of values.
        Use for: task_duration_ms, payload_size_bytes, batch_size

        Args:
            name: Metric name
            value: Observed value
            **labels: Label key-value pairs
        """
        metric = Metric(
            name=name,
            value=value,
            metric_type="histogram",
            labels=labels,
        )
        self.record(metric)

    def query(
        self,
        name: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        labels: Optional[dict[str, Any]] = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """
        Query metrics by name and time range.

        Args:
            name: Metric name
            start_time: Start time (None = no lower bound)
            end_time: End time (None = no upper bound)
            labels: Optional label filters (must match exactly)
            limit: Maximum results (default 1000)

        Returns:
            List of metric dicts with keys: value, recorded_at, labels
        """
        # Build WHERE clause dynamically
        conditions = ["metric_name = :name"]
        params: dict[str, Any] = {"name": name, "limit": limit}

        if start_time:
            conditions.append("recorded_at >= :start_time")
            params["start_time"] = start_time

        if end_time:
            conditions.append("recorded_at <= :end_time")
            params["end_time"] = end_time

        if labels:
            conditions.append("labels @> :labels::jsonb")
            params["labels"] = labels

        where_clause = " AND ".join(conditions)

        query = text(
            f"""
            SELECT metric_value, recorded_at, labels
            FROM observability.metrics
            WHERE {where_clause}
            ORDER BY recorded_at DESC
            LIMIT :limit
        """
        )

        results = []

        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, params)

                for row in result:
                    results.append(
                        {
                            "value": float(row[0]),
                            "recorded_at": row[1],
                            "labels": row[2] or {},
                        }
                    )
        except Exception as e:
            logger.error(f"Failed to query metrics for {name}: {e}")

        return results

    def get_percentile(
        self,
        name: str,
        percentile: float = 0.5,
        hours: int = 24,
        labels: Optional[dict[str, Any]] = None,
    ) -> Optional[float]:
        """
        Calculate percentile for histogram metric over recent time window.

        Args:
            name: Metric name
            percentile: Percentile to calculate (0.0-1.0, default 0.5 = median)
            hours: Time window in hours (default 24)
            labels: Optional label filters

        Returns:
            Percentile value or None if no data

        Example:
            p50 = collector.get_percentile("task_duration_ms", percentile=0.5)
            p95 = collector.get_percentile("task_duration_ms", percentile=0.95)
            p99 = collector.get_percentile("task_duration_ms", percentile=0.99)
        """
        start_time = datetime.utcnow() - timedelta(hours=hours)

        # Build WHERE clause
        conditions = [
            "metric_name = :name",
            "recorded_at >= :start_time",
        ]
        params: dict[str, Any] = {
            "name": name,
            "start_time": start_time,
            "percentile": percentile,
        }

        if labels:
            conditions.append("labels @> :labels::jsonb")
            params["labels"] = labels

        where_clause = " AND ".join(conditions)

        query = text(
            f"""
            SELECT PERCENTILE_CONT(:percentile) WITHIN GROUP (ORDER BY metric_value)
            FROM observability.metrics
            WHERE {where_clause}
        """
        )

        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, params)
                row = result.fetchone()

                if row and row[0] is not None:
                    return float(row[0])

        except Exception as e:
            logger.error(f"Failed to calculate percentile for {name}: {e}")

        return None
