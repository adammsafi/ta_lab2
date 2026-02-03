"""Tests for async execution engine."""
import asyncio
import pytest
from unittest.mock import AsyncMock, Mock

from ta_lab2.tools.ai_orchestrator.execution import (
    AsyncOrchestrator,
    AggregatedResult,
    aggregate_results,
)
from ta_lab2.tools.ai_orchestrator.core import (
    Task,
    Result,
    TaskType,
    Platform,
    TaskStatus,
)


class TestAggregatedResult:
    """Test AggregatedResult dataclass."""

    def test_success_rate_all_successful(self):
        """100% success rate when all succeed."""
        result = AggregatedResult(
            results=[],
            total_cost=0.0,
            total_tokens=0,
            total_duration=0.0,
            success_count=5,
            failure_count=0,
        )
        assert result.success_rate == 1.0

    def test_success_rate_some_failures(self):
        """Correct rate with mixed results."""
        result = AggregatedResult(
            results=[],
            total_cost=0.0,
            total_tokens=0,
            total_duration=0.0,
            success_count=7,
            failure_count=3,
        )
        assert result.success_rate == 0.7

    def test_success_rate_empty(self):
        """0% when no results."""
        result = AggregatedResult(
            results=[],
            total_cost=0.0,
            total_tokens=0,
            total_duration=0.0,
            success_count=0,
            failure_count=0,
        )
        assert result.success_rate == 0.0

    def test_all_succeeded_property(self):
        """all_succeeded is True when no failures."""
        result_success = AggregatedResult(
            results=[],
            total_cost=0.0,
            total_tokens=0,
            total_duration=0.0,
            success_count=5,
            failure_count=0,
        )
        assert result_success.all_succeeded is True

        result_failure = AggregatedResult(
            results=[],
            total_cost=0.0,
            total_tokens=0,
            total_duration=0.0,
            success_count=5,
            failure_count=2,
        )
        assert result_failure.all_succeeded is False


class TestAggregateResults:
    """Test aggregate_results function."""

    def test_aggregates_costs(self):
        """Total cost is sum of all result costs."""
        task = Task(type=TaskType.CODE_GENERATION, prompt="test")
        results = [
            Result(
                task=task, platform=Platform.GEMINI, output="", success=True, cost=0.5
            ),
            Result(
                task=task, platform=Platform.CHATGPT, output="", success=True, cost=1.2
            ),
            Result(
                task=task,
                platform=Platform.CLAUDE_CODE,
                output="",
                success=True,
                cost=0.0,
            ),
        ]

        agg = aggregate_results(results)
        assert agg.total_cost == 1.7

    def test_aggregates_tokens(self):
        """Total tokens is sum of all tokens."""
        task = Task(type=TaskType.CODE_GENERATION, prompt="test")
        results = [
            Result(
                task=task,
                platform=Platform.GEMINI,
                output="",
                success=True,
                tokens_used=100,
            ),
            Result(
                task=task,
                platform=Platform.CHATGPT,
                output="",
                success=True,
                tokens_used=250,
            ),
            Result(
                task=task,
                platform=Platform.CLAUDE_CODE,
                output="",
                success=True,
                tokens_used=50,
            ),
        ]

        agg = aggregate_results(results)
        assert agg.total_tokens == 400

    def test_groups_by_platform(self):
        """Results grouped by platform in by_platform dict."""
        task = Task(type=TaskType.CODE_GENERATION, prompt="test")
        results = [
            Result(task=task, platform=Platform.GEMINI, output="a", success=True),
            Result(task=task, platform=Platform.CHATGPT, output="b", success=True),
            Result(task=task, platform=Platform.GEMINI, output="c", success=True),
        ]

        agg = aggregate_results(results)
        assert "gemini" in agg.by_platform
        assert "chatgpt" in agg.by_platform
        assert len(agg.by_platform["gemini"]) == 2
        assert len(agg.by_platform["chatgpt"]) == 1
        assert agg.by_platform["gemini"][0].output == "a"
        assert agg.by_platform["gemini"][1].output == "c"

    def test_counts_success_and_failure(self):
        """Success and failure counts are correct."""
        task = Task(type=TaskType.CODE_GENERATION, prompt="test")
        results = [
            Result(task=task, platform=Platform.GEMINI, output="", success=True),
            Result(task=task, platform=Platform.CHATGPT, output="", success=False),
            Result(task=task, platform=Platform.GEMINI, output="", success=True),
            Result(task=task, platform=Platform.CLAUDE_CODE, output="", success=False),
        ]

        agg = aggregate_results(results)
        assert agg.success_count == 2
        assert agg.failure_count == 2
        assert agg.success_rate == 0.5


class TestAsyncOrchestrator:
    """Test AsyncOrchestrator class."""

    @pytest.mark.asyncio
    async def test_execute_single_routes_to_adapter(self):
        """execute_single uses router and adapter correctly."""
        task = Task(type=TaskType.CODE_GENERATION, prompt="test code gen")

        # Mock adapter
        mock_adapter = AsyncMock()
        mock_adapter.submit_task = AsyncMock(return_value="task-123")
        mock_adapter.get_result = AsyncMock(
            return_value=Result(
                task=task,
                platform=Platform.GEMINI,
                output="Generated code",
                success=True,
            )
        )

        # Mock router
        mock_router = Mock()
        mock_router.route_cost_optimized = Mock(return_value=Platform.GEMINI)

        # Create orchestrator
        orchestrator = AsyncOrchestrator(
            adapters={Platform.GEMINI: mock_adapter},
            router=mock_router,
        )

        # Execute
        result = await orchestrator.execute_single(task)

        # Verify routing and execution
        mock_router.route_cost_optimized.assert_called_once()
        mock_adapter.submit_task.assert_called_once_with(task)
        mock_adapter.get_result.assert_called_once_with("task-123", timeout=300)
        assert result.success is True
        assert result.output == "Generated code"

    @pytest.mark.asyncio
    async def test_execute_parallel_runs_concurrently(self):
        """Tasks run in parallel, not sequentially."""
        tasks = [
            Task(type=TaskType.CODE_GENERATION, prompt=f"task {i}") for i in range(3)
        ]

        # Mock adapter with delay to measure parallelism
        async def mock_execute(task_id, timeout=300):
            await asyncio.sleep(0.1)  # Simulate work
            return Result(
                task=tasks[0],
                platform=Platform.GEMINI,
                output=f"result-{task_id}",
                success=True,
            )

        mock_adapter = AsyncMock()
        mock_adapter.submit_task = AsyncMock(
            side_effect=lambda t: f"task-{tasks.index(t)}"
        )
        mock_adapter.get_result = AsyncMock(side_effect=mock_execute)

        mock_router = Mock()
        mock_router.route_cost_optimized = Mock(return_value=Platform.GEMINI)

        orchestrator = AsyncOrchestrator(
            adapters={Platform.GEMINI: mock_adapter},
            router=mock_router,
            max_concurrent=10,
        )

        # Measure execution time
        import time

        start = time.time()
        agg_result = await orchestrator.execute_parallel(tasks)
        duration = time.time() - start

        # Verify parallel execution (should take ~0.1s, not ~0.3s)
        assert duration < 0.25, f"Expected parallel execution, took {duration}s"
        assert agg_result.success_count == 3
        assert len(agg_result.results) == 3

    @pytest.mark.asyncio
    async def test_execute_parallel_fail_independent(self):
        """One failure doesn't cancel other tasks."""
        tasks = [
            Task(type=TaskType.CODE_GENERATION, prompt="task 0"),
            Task(type=TaskType.CODE_GENERATION, prompt="task 1 - will fail"),
            Task(type=TaskType.CODE_GENERATION, prompt="task 2"),
        ]

        # Mock adapter - task 1 fails
        async def mock_execute(task_id, timeout=300):
            await asyncio.sleep(0.05)
            if task_id == "task-1":
                raise RuntimeError("Task 1 failed")
            return Result(
                task=tasks[0],
                platform=Platform.GEMINI,
                output=f"result-{task_id}",
                success=True,
            )

        mock_adapter = AsyncMock()
        mock_adapter.submit_task = AsyncMock(
            side_effect=lambda t: f"task-{tasks.index(t)}"
        )
        mock_adapter.get_result = AsyncMock(side_effect=mock_execute)

        mock_router = Mock()
        mock_router.route_cost_optimized = Mock(return_value=Platform.GEMINI)

        orchestrator = AsyncOrchestrator(
            adapters={Platform.GEMINI: mock_adapter},
            router=mock_router,
        )

        # Execute
        agg_result = await orchestrator.execute_parallel(tasks)

        # Verify: task 1 failed but tasks 0 and 2 succeeded
        assert len(agg_result.results) == 3
        assert agg_result.success_count == 2
        assert agg_result.failure_count == 1
        assert agg_result.results[0].success is True
        assert agg_result.results[1].success is False
        assert agg_result.results[2].success is True

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """Semaphore prevents more than max_concurrent tasks."""
        tasks = [
            Task(type=TaskType.CODE_GENERATION, prompt=f"task {i}") for i in range(10)
        ]

        # Track concurrent execution count
        concurrent_count = 0
        max_concurrent_observed = 0
        lock = asyncio.Lock()

        async def mock_execute(task_id, timeout=300):
            nonlocal concurrent_count, max_concurrent_observed
            async with lock:
                concurrent_count += 1
                max_concurrent_observed = max(max_concurrent_observed, concurrent_count)

            await asyncio.sleep(0.05)  # Simulate work

            async with lock:
                concurrent_count -= 1

            return Result(
                task=tasks[0],
                platform=Platform.GEMINI,
                output=f"result-{task_id}",
                success=True,
            )

        mock_adapter = AsyncMock()
        mock_adapter.submit_task = AsyncMock(
            side_effect=lambda t: f"task-{tasks.index(t)}"
        )
        mock_adapter.get_result = AsyncMock(side_effect=mock_execute)

        mock_router = Mock()
        mock_router.route_cost_optimized = Mock(return_value=Platform.GEMINI)

        orchestrator = AsyncOrchestrator(
            adapters={Platform.GEMINI: mock_adapter},
            router=mock_router,
            max_concurrent=3,  # Limit to 3 concurrent
        )

        # Execute
        agg_result = await orchestrator.execute_parallel(tasks)

        # Verify semaphore worked
        assert (
            max_concurrent_observed <= 3
        ), f"Exceeded concurrency limit: {max_concurrent_observed}"
        assert agg_result.success_count == 10

    @pytest.mark.asyncio
    async def test_results_in_original_order(self):
        """Results returned in same order as input tasks."""
        tasks = [
            Task(type=TaskType.CODE_GENERATION, prompt=f"task {i}") for i in range(5)
        ]

        # Mock adapter with varying delays
        async def mock_execute(task_id, timeout=300):
            # Task 4 completes first, task 0 completes last
            delays = {
                "task-0": 0.20,
                "task-1": 0.15,
                "task-2": 0.10,
                "task-3": 0.05,
                "task-4": 0.01,
            }
            await asyncio.sleep(delays.get(task_id, 0.05))
            return Result(
                task=tasks[0],
                platform=Platform.GEMINI,
                output=task_id,
                success=True,
            )

        mock_adapter = AsyncMock()
        mock_adapter.submit_task = AsyncMock(
            side_effect=lambda t: f"task-{tasks.index(t)}"
        )
        mock_adapter.get_result = AsyncMock(side_effect=mock_execute)

        mock_router = Mock()
        mock_router.route_cost_optimized = Mock(return_value=Platform.GEMINI)

        orchestrator = AsyncOrchestrator(
            adapters={Platform.GEMINI: mock_adapter},
            router=mock_router,
        )

        # Execute
        agg_result = await orchestrator.execute_parallel(tasks)

        # Verify order preserved despite different completion times
        assert len(agg_result.results) == 5
        assert agg_result.results[0].output == "task-0"
        assert agg_result.results[1].output == "task-1"
        assert agg_result.results[2].output == "task-2"
        assert agg_result.results[3].output == "task-3"
        assert agg_result.results[4].output == "task-4"

    @pytest.mark.asyncio
    async def test_error_results_for_failed_tasks(self):
        """Failed tasks get error Result objects."""
        tasks = [
            Task(type=TaskType.CODE_GENERATION, prompt="task 0"),
        ]

        # Mock adapter that raises exception
        mock_adapter = AsyncMock()
        mock_adapter.submit_task = AsyncMock(
            side_effect=RuntimeError("Adapter unavailable")
        )

        mock_router = Mock()
        mock_router.route_cost_optimized = Mock(return_value=Platform.GEMINI)

        orchestrator = AsyncOrchestrator(
            adapters={Platform.GEMINI: mock_adapter},
            router=mock_router,
        )

        # Execute
        agg_result = await orchestrator.execute_parallel(tasks)

        # Verify error result created
        assert len(agg_result.results) == 1
        assert agg_result.results[0].success is False
        assert agg_result.results[0].status == TaskStatus.FAILED
        assert "Adapter unavailable" in agg_result.results[0].error


class TestAdaptiveConcurrency:
    """Test adaptive concurrency calculation."""

    def test_unlimited_quota_uses_max(self):
        """When quota unlimited, use max_concurrent."""
        from ta_lab2.tools.ai_orchestrator.quota import QuotaTracker

        quota_tracker = QuotaTracker()
        orchestrator = AsyncOrchestrator(
            quota_tracker=quota_tracker,
            max_concurrent=10,
        )

        # Claude Code has unlimited quota
        limit = orchestrator.get_adaptive_concurrency(Platform.CLAUDE_CODE)
        assert limit == 10

    def test_limited_quota_scales_down(self):
        """When quota limited, scale to 50% of remaining."""
        from ta_lab2.tools.ai_orchestrator.quota import QuotaTracker

        quota_tracker = QuotaTracker()
        # Simulate Gemini with 100 requests remaining
        quota_tracker.limits[
            "gemini_cli"
        ].used = 1400  # 1500 limit - 1400 used = 100 remaining

        orchestrator = AsyncOrchestrator(
            quota_tracker=quota_tracker,
            max_concurrent=100,
        )

        # Should scale to 50% of 100 remaining = 50
        limit = orchestrator.get_adaptive_concurrency(Platform.GEMINI)
        assert limit == 50

    def test_minimum_one_concurrent(self):
        """Never return less than 1."""
        from ta_lab2.tools.ai_orchestrator.quota import QuotaTracker

        quota_tracker = QuotaTracker()
        # Simulate Gemini with 1 request remaining
        quota_tracker.limits["gemini_cli"].used = 1499

        orchestrator = AsyncOrchestrator(
            quota_tracker=quota_tracker,
            max_concurrent=100,
        )

        # Should return at least 1
        limit = orchestrator.get_adaptive_concurrency(Platform.GEMINI)
        assert limit >= 1
