"""Circuit breaker for API resilience.

Implements the circuit breaker pattern to prevent cascade failures
when external APIs are down or overloaded.
"""
import threading
import time
from enum import Enum
from typing import Optional, Callable, Any
from dataclasses import dataclass


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, rejecting requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitStats:
    """Circuit breaker statistics."""
    state: CircuitState
    failure_count: int
    success_count: int
    last_failure_time: Optional[float]
    last_success_time: Optional[float]


class CircuitBreaker:
    """Circuit breaker for external service calls.

    Prevents cascade failures by tracking failures and temporarily
    stopping requests when a service is down.

    States:
        CLOSED: Normal operation, requests pass through
        OPEN: Service failing, requests rejected immediately
        HALF_OPEN: Testing if service recovered

    Attributes:
        failure_threshold: Failures before opening circuit
        recovery_timeout: Seconds before trying half-open
        success_threshold: Successes in half-open to close

    Example:
        >>> breaker = CircuitBreaker(failure_threshold=5)
        >>> def call_api():
        ...     # Make API call
        ...     pass
        >>> result = breaker.call(call_api)
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        success_threshold: int = 2,
    ):
        """Initialize circuit breaker.

        Args:
            failure_threshold: Failures before opening (default 5)
            recovery_timeout: Seconds before half-open (default 60)
            success_threshold: Successes to close from half-open (default 2)
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[float] = None
        self._last_success_time: Optional[float] = None
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        """Current circuit state."""
        with self._lock:
            self._check_state_transition()
            return self._state

    def _check_state_transition(self) -> None:
        """Check if state should transition based on time."""
        if self._state == CircuitState.OPEN:
            if self._last_failure_time is not None:
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._success_count = 0

    def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            self._last_success_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.success_threshold:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
            elif self._state == CircuitState.CLOSED:
                # Reset failure count on success
                self._failure_count = max(0, self._failure_count - 1)

    def record_failure(self) -> None:
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                # Any failure in half-open goes back to open
                self._state = CircuitState.OPEN
            elif self._state == CircuitState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN

    def is_call_permitted(self) -> bool:
        """Check if a call is currently permitted.

        Returns:
            True if call should proceed, False if circuit is open
        """
        with self._lock:
            self._check_state_transition()
            return self._state != CircuitState.OPEN

    def call(
        self,
        func: Callable[..., Any],
        *args,
        fallback: Optional[Callable[..., Any]] = None,
        **kwargs
    ) -> Any:
        """Execute a function through the circuit breaker.

        Args:
            func: Function to call
            *args: Positional arguments for func
            fallback: Optional fallback function if circuit is open
            **kwargs: Keyword arguments for func

        Returns:
            Result of func or fallback

        Raises:
            CircuitOpenError: If circuit is open and no fallback provided
        """
        if not self.is_call_permitted():
            if fallback is not None:
                return fallback(*args, **kwargs)
            raise CircuitOpenError(
                f"Circuit is open. Service failing. "
                f"Recovery in {self._time_until_half_open():.1f}s"
            )

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise

    def _time_until_half_open(self) -> float:
        """Time in seconds until circuit goes to half-open."""
        if self._last_failure_time is None:
            return 0.0
        elapsed = time.time() - self._last_failure_time
        return max(0.0, self.recovery_timeout - elapsed)

    def reset(self) -> None:
        """Reset circuit breaker to closed state."""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._last_failure_time = None

    def stats(self) -> CircuitStats:
        """Get circuit breaker statistics."""
        with self._lock:
            self._check_state_transition()
            return CircuitStats(
                state=self._state,
                failure_count=self._failure_count,
                success_count=self._success_count,
                last_failure_time=self._last_failure_time,
                last_success_time=self._last_success_time,
            )


class CircuitOpenError(Exception):
    """Raised when circuit breaker is open."""
    pass
