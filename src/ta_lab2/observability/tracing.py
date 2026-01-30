"""
OpenTelemetry tracing integration for distributed tracing.

Provides:
- setup_tracing(): Initialize OpenTelemetry with service name
- TracingContext: Context manager for creating spans
- generate_correlation_id(): Generate correlation IDs for request tracking
- get_tracer(): Get tracer for current service

Gracefully degrades if opentelemetry-api not installed.

Usage:
    # Setup (once at startup)
    from ta_lab2.observability.tracing import setup_tracing
    tracer = setup_tracing("ta_lab2", engine=engine)

    # Use in code
    from ta_lab2.observability.tracing import TracingContext

    with TracingContext("compute_ema") as ctx:
        ctx.set_attribute("asset_id", 1)
        ctx.add_event("computation_started")
        # ... do work ...
        print(f"Trace ID: {ctx.trace_id}")

    # Generate correlation IDs
    from ta_lab2.observability.tracing import generate_correlation_id
    correlation_id = generate_correlation_id()  # 32-char hex
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Try importing OpenTelemetry - gracefully degrade if not available
try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    OTEL_AVAILABLE = True
except ImportError:
    logger.debug("OpenTelemetry not installed - tracing will be no-op")
    OTEL_AVAILABLE = False
    trace = None  # type: ignore[assignment]


# =============================================================================
# Tracer Setup
# =============================================================================

def setup_tracing(service_name: str, engine: Optional[Any] = None) -> Any:
    """
    Initialize OpenTelemetry tracing for this service.

    Args:
        service_name: Service name for trace attribution (e.g., "ta_lab2")
        engine: Optional SQLAlchemy engine for PostgreSQL span export

    Returns:
        Tracer instance (or no-op if OpenTelemetry not available)

    Example:
        tracer = setup_tracing("ta_lab2", engine=db_engine)
    """
    if not OTEL_AVAILABLE:
        logger.warning("OpenTelemetry not available - returning no-op tracer")
        return NoOpTracer()

    # Create resource with service name
    resource = Resource.create({"service.name": service_name})

    # Create tracer provider
    provider = TracerProvider(resource=resource)

    # Add span processor with PostgreSQL exporter if engine provided
    if engine:
        try:
            from ta_lab2.observability.storage import PostgreSQLSpanExporter
            exporter = PostgreSQLSpanExporter(engine)
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)
            logger.info(f"Tracing configured for {service_name} with PostgreSQL exporter")
        except Exception as e:
            logger.warning(f"Failed to setup PostgreSQL span exporter: {e}")
    else:
        logger.info(f"Tracing configured for {service_name} (no exporter)")

    # Set as global provider
    trace.set_tracer_provider(provider)

    return provider.get_tracer(__name__)


def get_tracer(name: str = __name__) -> Any:
    """
    Get tracer from current provider.

    Args:
        name: Tracer name (typically __name__)

    Returns:
        Tracer instance
    """
    if not OTEL_AVAILABLE:
        return NoOpTracer()

    return trace.get_tracer(name)


# =============================================================================
# Tracing Context
# =============================================================================

class TracingContext:
    """
    Context manager for creating OpenTelemetry spans.

    Automatically starts span on __enter__, ends on __exit__.
    Records exceptions if raised.

    Attributes:
        operation_name: Operation name for this span
        attributes: Optional dict of span attributes
        _span: OpenTelemetry span (or None if not available)

    Example:
        with TracingContext("refresh_ema") as ctx:
            ctx.set_attribute("timeframe", "1D")
            ctx.add_event("started_computation")
            # ... do work ...
            print(f"Trace ID: {ctx.trace_id}")
    """

    def __init__(self, operation_name: str, attributes: Optional[dict[str, Any]] = None):
        """
        Initialize tracing context.

        Args:
            operation_name: Operation name for this span
            attributes: Optional dict of initial span attributes
        """
        self.operation_name = operation_name
        self.attributes = attributes or {}
        self._span: Optional[Any] = None
        self._tracer: Optional[Any] = None

    def __enter__(self) -> TracingContext:
        """
        Start span.

        Returns:
            Self for context manager protocol
        """
        if not OTEL_AVAILABLE:
            logger.debug(f"Tracing not available for operation: {self.operation_name}")
            return self

        self._tracer = get_tracer()
        self._span = self._tracer.start_span(self.operation_name)

        # Set initial attributes
        for key, value in self.attributes.items():
            self._span.set_attribute(key, value)

        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """
        End span, recording exception if raised.

        Args:
            exc_type: Exception type (or None)
            exc_val: Exception value (or None)
            exc_tb: Exception traceback (or None)
        """
        if not self._span:
            return

        # Record exception if raised
        if exc_type is not None:
            self._span.record_exception(exc_val)
            self._span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc_val)))
        else:
            self._span.set_status(trace.Status(trace.StatusCode.OK))

        # End span
        self._span.end()

    @property
    def trace_id(self) -> str:
        """
        Get trace ID as 32-char hex string.

        Returns:
            Trace ID hex string (or empty if span not available)
        """
        if not self._span:
            return ""

        context = self._span.get_span_context()
        return format(context.trace_id, '032x')

    @property
    def span_id(self) -> str:
        """
        Get span ID as 16-char hex string.

        Returns:
            Span ID hex string (or empty if span not available)
        """
        if not self._span:
            return ""

        context = self._span.get_span_context()
        return format(context.span_id, '016x')

    def add_event(self, name: str, attributes: Optional[dict[str, Any]] = None) -> None:
        """
        Add event to current span.

        Args:
            name: Event name
            attributes: Optional event attributes
        """
        if not self._span:
            return

        self._span.add_event(name, attributes=attributes or {})

    def set_attribute(self, key: str, value: Any) -> None:
        """
        Set span attribute.

        Args:
            key: Attribute key
            value: Attribute value
        """
        if not self._span:
            return

        self._span.set_attribute(key, value)


# =============================================================================
# Correlation ID Generation
# =============================================================================

def generate_correlation_id() -> str:
    """
    Generate correlation ID for cross-system request tracing.

    Uses OpenTelemetry trace context if available, else generates UUID.

    Returns:
        32-character hex correlation ID

    Example:
        correlation_id = generate_correlation_id()
        # "a1b2c3d4e5f6789012345678abcdef01"
    """
    if OTEL_AVAILABLE:
        # Try to get current trace context
        try:
            current_span = trace.get_current_span()
            if current_span and current_span.is_recording():
                context = current_span.get_span_context()
                return format(context.trace_id, '032x')
        except Exception:
            pass  # Fall through to UUID generation

    # Fallback: generate new UUID
    return uuid.uuid4().hex


# =============================================================================
# No-op Tracer (when OpenTelemetry not available)
# =============================================================================

class NoOpTracer:
    """
    No-op tracer for when OpenTelemetry not installed.

    Provides same interface but does nothing.
    """

    def start_span(self, name: str, *args: Any, **kwargs: Any) -> NoOpSpan:
        """Start no-op span."""
        return NoOpSpan()

    def get_tracer(self, name: str) -> NoOpTracer:
        """Get no-op tracer."""
        return self


class NoOpSpan:
    """
    No-op span for when OpenTelemetry not installed.
    """

    def set_attribute(self, key: str, value: Any) -> None:
        """No-op set attribute."""
        pass

    def add_event(self, name: str, attributes: Optional[dict[str, Any]] = None) -> None:
        """No-op add event."""
        pass

    def record_exception(self, exception: Exception) -> None:
        """No-op record exception."""
        pass

    def set_status(self, status: Any) -> None:
        """No-op set status."""
        pass

    def end(self) -> None:
        """No-op end span."""
        pass

    def is_recording(self) -> bool:
        """No-op is recording."""
        return False

    def get_span_context(self) -> NoOpSpanContext:
        """Get no-op span context."""
        return NoOpSpanContext()


class NoOpSpanContext:
    """
    No-op span context.
    """

    trace_id: int = 0
    span_id: int = 0
