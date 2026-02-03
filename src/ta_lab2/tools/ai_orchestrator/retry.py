"""Retry logic with exponential backoff for API calls."""
from __future__ import annotations

import logging
from typing import Callable, TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    wait_exponential_jitter,
    stop_after_attempt,
    before_sleep_log,
)

logger = logging.getLogger(__name__)

# Type variable for generic decorator
F = TypeVar("F", bound=Callable)


def retry_on_rate_limit(
    max_attempts: int = 5,
    initial_wait: float = 1.0,
    max_wait: float = 32.0,
    jitter: float = 3.0,
) -> Callable[[F], F]:
    """
    Decorator for retrying API calls on rate limit errors.

    Uses exponential backoff with jitter per AWS/OpenAI best practices.
    Handles OpenAI RateLimitError and APIError.

    Args:
        max_attempts: Maximum retry attempts (default: 5)
        initial_wait: Initial wait in seconds (default: 1.0)
        max_wait: Maximum wait in seconds (default: 32.0)
        jitter: Random jitter range in seconds (default: 3.0)

    Example:
        @retry_on_rate_limit()
        async def call_api():
            return await client.chat.completions.create(...)
    """
    # Import here to avoid hard dependency if openai not installed
    try:
        import openai

        retry_exceptions = (openai.RateLimitError, openai.APIError)
    except ImportError:
        # Fallback to generic exceptions if openai not installed
        retry_exceptions = (Exception,)
        logger.warning("openai not installed, retry decorator using generic Exception")

    return retry(
        retry=retry_if_exception_type(retry_exceptions),
        wait=wait_exponential_jitter(initial=initial_wait, max=max_wait, jitter=jitter),
        stop=stop_after_attempt(max_attempts),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


def retry_on_transient(
    max_attempts: int = 3,
    initial_wait: float = 0.5,
    max_wait: float = 10.0,
) -> Callable[[F], F]:
    """
    Decorator for retrying on transient network errors.

    Lighter retry policy for connection issues.

    Args:
        max_attempts: Maximum retry attempts (default: 3)
        initial_wait: Initial wait in seconds (default: 0.5)
        max_wait: Maximum wait in seconds (default: 10.0)
    """
    import aiohttp

    return retry(
        retry=retry_if_exception_type(
            (
                aiohttp.ClientError,
                ConnectionError,
                TimeoutError,
            )
        ),
        wait=wait_exponential_jitter(initial=initial_wait, max=max_wait, jitter=1.0),
        stop=stop_after_attempt(max_attempts),
        before_sleep=before_sleep_log(logger, logging.INFO),
        reraise=True,
    )


__all__ = ["retry_on_rate_limit", "retry_on_transient"]
