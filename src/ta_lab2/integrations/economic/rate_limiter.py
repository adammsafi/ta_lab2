"""Rate limiting for economic data API calls.

Provides token bucket rate limiting to prevent exceeding API limits.
FRED API allows 120 requests per minute by default.
"""
import threading
import time
from typing import Optional


class RateLimiter:
    """Token bucket rate limiter for API calls.

    Implements a token bucket algorithm that refills tokens at a steady
    rate. Callers can acquire tokens (blocking or non-blocking) before
    making API requests.

    Attributes:
        max_tokens: Maximum tokens in bucket (burst capacity)
        refill_rate: Tokens added per second
        tokens: Current available tokens

    Example:
        >>> limiter = RateLimiter(max_tokens=120, refill_period=60)
        >>> limiter.acquire()  # Blocks if rate limit exceeded
        >>> # Make API call...
    """

    def __init__(
        self,
        max_tokens: int = 120,
        refill_period: float = 60.0,
    ):
        """Initialize rate limiter.

        Args:
            max_tokens: Maximum tokens (requests) allowed in the bucket.
                        Default 120 for FRED API.
            refill_period: Seconds to refill all tokens. Default 60 seconds.
        """
        self.max_tokens = max_tokens
        self.refill_rate = max_tokens / refill_period  # tokens per second
        self._tokens = float(max_tokens)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.max_tokens, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now

    def acquire(
        self, tokens: int = 1, blocking: bool = True, timeout: Optional[float] = None
    ) -> bool:
        """Acquire tokens from the bucket.

        Args:
            tokens: Number of tokens to acquire (usually 1 per API call)
            blocking: If True, wait for tokens to become available
            timeout: Maximum seconds to wait (None = wait forever)

        Returns:
            True if tokens acquired, False if timed out or non-blocking fail

        Example:
            >>> if limiter.acquire(blocking=False):
            ...     # Make API call
            ... else:
            ...     print("Rate limited, try later")
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            with self._lock:
                self._refill()

                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True

                if not blocking:
                    return False

                # Calculate wait time for enough tokens
                tokens_needed = tokens - self._tokens
                wait_time = tokens_needed / self.refill_rate

            # Check timeout
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait_time = min(wait_time, remaining)

            time.sleep(min(wait_time, 0.1))  # Sleep in small increments

    @property
    def available_tokens(self) -> float:
        """Current available tokens."""
        with self._lock:
            self._refill()
            return self._tokens

    def reset(self) -> None:
        """Reset to full capacity."""
        with self._lock:
            self._tokens = float(self.max_tokens)
            self._last_refill = time.monotonic()


# Default FRED rate limiter (120 requests per minute)
_fred_limiter: Optional[RateLimiter] = None


def get_fred_rate_limiter() -> RateLimiter:
    """Get or create the global FRED rate limiter.

    Returns a singleton rate limiter configured for FRED API limits
    (120 requests per minute).

    Returns:
        RateLimiter instance
    """
    global _fred_limiter
    if _fred_limiter is None:
        _fred_limiter = RateLimiter(max_tokens=120, refill_period=60.0)
    return _fred_limiter
