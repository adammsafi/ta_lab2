"""Async orchestrator for parallel task execution."""

from __future__ import annotations

import asyncio
from asyncio import Semaphore, TaskGroup
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Set

if TYPE_CHECKING:
    from .adapters import AsyncBasePlatformAdapter
    from .core import Task, Result, Platform

from .core import Task, Result, Platform, TaskStatus
from .routing import TaskRouter
from .quota import QuotaTracker


# Error handling constants
MAX_RETRIES = 3
RETRY_BASE_DELAY = 1.0  # seconds


@dataclass
class AggregatedResult:
    """Combined results from parallel task execution."""

    results: List[Result]
    total_cost: float
    total_tokens: int
    total_duration: float
    success_count: int
    failure_count: int
    by_platform: Dict[str, List[Result]] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

    @property
    def all_succeeded(self) -> bool:
        return self.failure_count == 0


def aggregate_results(results: List[Result]) -> AggregatedResult:
    """Aggregate results from parallel execution."""
    by_platform: Dict[str, List[Result]] = {}

    for result in results:
        platform = result.platform.value
        if platform not in by_platform:
            by_platform[platform] = []
        by_platform[platform].append(result)

    return AggregatedResult(
        results=results,
        total_cost=sum(r.cost for r in results),
        total_tokens=sum(r.tokens_used for r in results),
        total_duration=sum(r.duration_seconds for r in results),
        success_count=sum(1 for r in results if r.success),
        failure_count=sum(1 for r in results if not r.success),
        by_platform=by_platform,
    )


class AsyncOrchestrator:
    """
    Async orchestrator for parallel task execution across platforms.

    Features:
    - TaskGroup-based parallel execution with fail-independent semantics
    - Semaphore-controlled concurrency to prevent quota exhaustion
    - Adaptive concurrency based on remaining quota
    - Result aggregation with success/failure tracking
    """

    def __init__(
        self,
        adapters: Dict[Platform, AsyncBasePlatformAdapter] = None,
        router: TaskRouter = None,
        quota_tracker: QuotaTracker = None,
        max_concurrent: int = 10,
    ):
        """
        Initialize orchestrator.

        Args:
            adapters: Dict of Platform -> adapter instance
            router: TaskRouter instance (created if not provided)
            quota_tracker: QuotaTracker instance (created if not provided)
            max_concurrent: Base concurrent task limit (default: 10)
        """
        self._adapters = adapters or {}
        self._router = router or TaskRouter()
        self._quota = quota_tracker or QuotaTracker()
        self._max_concurrent = max_concurrent
        self._semaphore: Optional[Semaphore] = None

    async def __aenter__(self):
        """Enter async context - initialize adapters."""
        for adapter in self._adapters.values():
            await adapter.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context - cleanup adapters."""
        for adapter in self._adapters.values():
            await adapter.__aexit__(exc_type, exc_val, exc_tb)

    async def execute_single(self, task: Task) -> Result:
        """Execute a single task on the best platform."""
        # Route to best platform
        platform = self._router.route_cost_optimized(task, self._quota)
        adapter = self._adapters.get(platform)

        if not adapter:
            return Result(
                task=task,
                platform=platform,
                output="",
                success=False,
                status=TaskStatus.FAILED,
                error=f"No adapter for platform: {platform.value}",
            )

        # Execute via adapter
        task_id = await adapter.submit_task(task)
        timeout = task.constraints.timeout_seconds if task.constraints else 300
        result = await adapter.get_result(task_id, timeout=timeout)

        return result

    async def execute_parallel(
        self,
        tasks: List[Task],
        max_concurrent: Optional[int] = None,
    ) -> AggregatedResult:
        """
        Execute tasks in parallel with fail-independent semantics.

        All tasks run concurrently (up to semaphore limit). Failures in one
        task do not cancel others. Results collected for all tasks.

        Args:
            tasks: List of tasks to execute
            max_concurrent: Override concurrent limit for this batch

        Returns:
            AggregatedResult with all results and aggregated metrics
        """
        limit = max_concurrent or self._max_concurrent
        semaphore = Semaphore(limit)

        results: Dict[int, Result] = {}
        errors: Dict[int, Exception] = {}

        async def execute_one(idx: int, task: Task):
            """Execute single task with semaphore control."""
            async with semaphore:
                try:
                    result = await self.execute_single(task)
                    results[idx] = result
                except Exception as e:
                    errors[idx] = e

        # Fail-independent: catch ExceptionGroup, results already collected
        try:
            async with TaskGroup() as tg:
                for idx, task in enumerate(tasks):
                    tg.create_task(execute_one(idx, task))
        except* Exception:
            # TaskGroup raises ExceptionGroup on failures
            # Results/errors already collected in dicts
            pass

        # Build ordered results list
        ordered_results = []
        for i in range(len(tasks)):
            if i in results:
                ordered_results.append(results[i])
            elif i in errors:
                ordered_results.append(self._error_result(tasks[i], errors[i]))
            else:
                ordered_results.append(
                    self._error_result(tasks[i], RuntimeError("Unknown error"))
                )

        return aggregate_results(ordered_results)

    def _error_result(self, task: Task, error: Exception) -> Result:
        """Create error Result from exception."""
        return Result(
            task=task,
            platform=task.platform_hint or Platform.CLAUDE_CODE,
            output="",
            success=False,
            status=TaskStatus.FAILED,
            error=str(error),
        )

    def get_adaptive_concurrency(self, platform: Platform) -> int:
        """
        Calculate adaptive concurrency limit based on remaining quota.

        Per CONTEXT.md: Scale concurrent tasks based on available quota.

        Returns:
            Recommended concurrency limit (min 1, max self._max_concurrent)
        """
        status = self._quota.get_status()
        quota_key = self._quota._platform_to_quota_key(platform.value)
        platform_status = status.get(quota_key, {})

        available = platform_status.get("available", "unlimited")

        if available == "unlimited":
            return self._max_concurrent

        # Don't exceed 50% of remaining quota in one batch
        return max(1, min(self._max_concurrent, available // 2))

    async def execute_with_fallback(
        self,
        task: Task,
        max_retries: int = MAX_RETRIES,
        exclude_platforms: Optional[Set[Platform]] = None,
    ) -> Result:
        """
        Execute task with retry logic and fallback routing.

        Per ORCH-08: Retry failed tasks and route to fallback platforms.

        Strategy:
        1. Route to best platform via cost-optimized routing
        2. On failure, retry with exponential backoff (up to max_retries)
        3. If retries exhausted, try next platform in cost priority order
        4. If all platforms fail, return error result

        Args:
            task: Task to execute
            max_retries: Max retries per platform (default: 3)
            exclude_platforms: Platforms to skip (e.g., already tried)

        Returns:
            Result from successful execution or final error
        """
        exclude = exclude_platforms or set()
        attempted_platforms: List[Platform] = []
        last_error: Optional[str] = None

        # Get all available platforms in cost order
        platforms = self._get_platforms_by_cost(exclude)

        for platform in platforms:
            if platform in exclude:
                continue

            attempted_platforms.append(platform)
            adapter = self._adapters.get(platform)

            if not adapter:
                last_error = f"No adapter for {platform.value}"
                continue

            # Try this platform with retries
            result = await self._execute_with_retries(
                task, adapter, platform, max_retries
            )

            if result.success:
                return result

            # Platform failed after retries, try next
            last_error = result.error

        # All platforms failed
        return Result(
            task=task,
            platform=attempted_platforms[-1]
            if attempted_platforms
            else Platform.CLAUDE_CODE,
            output="",
            success=False,
            status=TaskStatus.FAILED,
            error=f"All platforms failed. Last error: {last_error}. Tried: {[p.value for p in attempted_platforms]}",
        )

    async def _execute_with_retries(
        self,
        task: Task,
        adapter: AsyncBasePlatformAdapter,
        platform: Platform,
        max_retries: int,
    ) -> Result:
        """
        Execute task on single platform with exponential backoff retries.

        Args:
            task: Task to execute
            adapter: Adapter instance
            platform: Platform being used
            max_retries: Max retry attempts

        Returns:
            Result from execution (success or final failure)
        """
        last_result: Optional[Result] = None

        for attempt in range(max_retries + 1):  # +1 for initial attempt
            try:
                # Submit and wait for result
                task_id = await adapter.submit_task(task)
                timeout = task.constraints.timeout_seconds if task.constraints else 300
                result = await adapter.get_result(task_id, timeout=timeout)

                if result.success:
                    return result

                last_result = result

                # Check if error is retryable
                if not self._is_retryable_error(result.error):
                    return result

                # Exponential backoff before retry
                if attempt < max_retries:
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    await asyncio.sleep(delay)

            except asyncio.CancelledError:
                raise  # Always propagate cancellation
            except asyncio.TimeoutError:
                last_result = Result(
                    task=task,
                    platform=platform,
                    output="",
                    success=False,
                    status=TaskStatus.FAILED,
                    error=f"Timeout on attempt {attempt + 1}",
                )
                if attempt < max_retries:
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    await asyncio.sleep(delay)
            except Exception as e:
                last_result = Result(
                    task=task,
                    platform=platform,
                    output="",
                    success=False,
                    status=TaskStatus.FAILED,
                    error=str(e),
                )
                if attempt < max_retries:
                    delay = RETRY_BASE_DELAY * (2**attempt)
                    await asyncio.sleep(delay)

        return last_result or self._error_result(
            task, RuntimeError("No result after retries")
        )

    def _is_retryable_error(self, error: Optional[str]) -> bool:
        """
        Check if error is retryable.

        Retryable: rate limits, timeouts, transient server errors
        Not retryable: auth errors, invalid requests, quota exhausted
        """
        if not error:
            return False

        error_lower = error.lower()

        # Retryable patterns
        retryable_patterns = [
            "rate limit",
            "timeout",
            "timed out",
            "503",
            "502",
            "500",
            "server error",
            "connection error",
            "temporarily unavailable",
        ]

        for pattern in retryable_patterns:
            if pattern in error_lower:
                return True

        # Non-retryable patterns
        non_retryable_patterns = [
            "quota exhausted",
            "quota exceeded",
            "unauthorized",
            "invalid api key",
            "authentication",
            "permission denied",
            "invalid request",
        ]

        for pattern in non_retryable_patterns:
            if pattern in error_lower:
                return False

        # Default: retry unknown errors
        return True

    def _get_platforms_by_cost(self, exclude: Set[Platform] = None) -> List[Platform]:
        """
        Get platforms ordered by cost priority.

        Per ORCH-04: Gemini free first, then subscriptions, then paid.
        """
        from .routing import COST_TIERS

        exclude = exclude or set()
        platforms = []
        seen = set()

        for tier in sorted(COST_TIERS, key=lambda t: t["priority"]):
            platform = tier["platform"]
            if platform not in seen and platform not in exclude:
                # Check if we have an adapter for this platform
                if platform in self._adapters:
                    platforms.append(platform)
                    seen.add(platform)

        return platforms

    async def execute_parallel_with_fallback(
        self,
        tasks: List[Task],
        max_retries: int = MAX_RETRIES,
        max_concurrent: Optional[int] = None,
    ) -> AggregatedResult:
        """
        Execute tasks in parallel with per-task fallback routing.

        Combines parallel execution with individual task retry/fallback.
        """
        limit = max_concurrent or self._max_concurrent
        semaphore = Semaphore(limit)

        results: Dict[int, Result] = {}

        async def execute_one(idx: int, task: Task):
            async with semaphore:
                result = await self.execute_with_fallback(task, max_retries)
                results[idx] = result

        try:
            async with TaskGroup() as tg:
                for idx, task in enumerate(tasks):
                    tg.create_task(execute_one(idx, task))
        except* Exception:
            pass  # Results already collected

        ordered = [
            results.get(i, self._error_result(tasks[i], RuntimeError("Unknown")))
            for i in range(len(tasks))
        ]

        return aggregate_results(ordered)
