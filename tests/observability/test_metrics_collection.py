"""Tests for metrics collection module."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime


@pytest.mark.observability
@pytest.mark.mocked_deps
class TestMetricsCollector:
    """Tests for MetricsCollector class."""

    def test_counter_increment(self, mocker):
        """Test counter increments value."""
        from ta_lab2.observability.metrics import MetricsCollector

        mock_engine = mocker.MagicMock()
        collector = MetricsCollector(mock_engine)

        collector.counter("test_counter", value=1, service="test")

        # Verify insert was called
        mock_engine.begin.assert_called()

    def test_gauge_set_value(self, mocker):
        """Test gauge sets absolute value."""
        from ta_lab2.observability.metrics import MetricsCollector

        mock_engine = mocker.MagicMock()
        collector = MetricsCollector(mock_engine)

        collector.gauge("test_gauge", value=42.5, service="test")

        mock_engine.begin.assert_called()

    def test_histogram_with_labels(self, mocker):
        """Test histogram records with labels."""
        from ta_lab2.observability.metrics import MetricsCollector

        mock_engine = mocker.MagicMock()
        collector = MetricsCollector(mock_engine)

        collector.histogram("request_duration", value=0.125, endpoint="/api/test")

        mock_engine.begin.assert_called()

    def test_metric_dataclass(self):
        """Test Metric dataclass structure."""
        from ta_lab2.observability.metrics import Metric

        metric = Metric(
            name="test_metric",
            value=1.0,
            metric_type="counter",
            timestamp=datetime.utcnow(),
            labels={"env": "test"}
        )

        assert metric.name == "test_metric"
        assert metric.metric_type == "counter"
        assert "env" in metric.labels

    def test_record_metric(self, mocker):
        """Test record() stores metric to database."""
        from ta_lab2.observability.metrics import MetricsCollector, Metric

        mock_engine = mocker.MagicMock()
        collector = MetricsCollector(mock_engine)

        metric = Metric(
            name="test",
            value=1.0,
            metric_type="counter",
            timestamp=datetime.utcnow(),
            labels={}
        )

        collector.record(metric)
        mock_engine.begin.assert_called()
