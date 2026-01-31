"""Tests for OpenTelemetry tracing integration."""

import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.observability
@pytest.mark.mocked_deps
class TestTracingModule:
    """Tests for tracing.py functionality."""

    def test_generate_correlation_id_format(self):
        """Test correlation ID is 32-char hex string."""
        from ta_lab2.observability.tracing import generate_correlation_id

        cid = generate_correlation_id()

        assert len(cid) == 32, f"Expected 32 chars, got {len(cid)}"
        assert all(c in '0123456789abcdef' for c in cid), "Expected hex chars only"

    def test_generate_correlation_id_unique(self):
        """Test correlation IDs are unique."""
        from ta_lab2.observability.tracing import generate_correlation_id

        ids = [generate_correlation_id() for _ in range(100)]
        assert len(set(ids)) == 100, "Expected unique IDs"

    def test_tracing_context_creates_span(self, mocker):
        """Test TracingContext creates and ends span."""
        from ta_lab2.observability.tracing import TracingContext

        with TracingContext("test_operation") as ctx:
            assert ctx.trace_id is not None
            assert len(ctx.trace_id) == 32

    def test_tracing_context_attributes(self, mocker):
        """Test TracingContext can set attributes."""
        from ta_lab2.observability.tracing import TracingContext

        with TracingContext("test_operation") as ctx:
            ctx.set_attribute("test_key", "test_value")
            # Should not raise

    def test_tracing_context_events(self, mocker):
        """Test TracingContext can add events."""
        from ta_lab2.observability.tracing import TracingContext

        with TracingContext("test_operation") as ctx:
            ctx.add_event("test_event", {"key": "value"})
            # Should not raise

    def test_tracing_context_exception_handling(self):
        """Test TracingContext records exceptions."""
        from ta_lab2.observability.tracing import TracingContext

        with pytest.raises(ValueError):
            with TracingContext("failing_operation"):
                raise ValueError("Test error")

    def test_setup_tracing_returns_tracer(self, mocker):
        """Test setup_tracing returns a tracer."""
        from ta_lab2.observability.tracing import setup_tracing

        mock_engine = mocker.MagicMock()
        tracer = setup_tracing("test_service", engine=mock_engine)

        assert tracer is not None
