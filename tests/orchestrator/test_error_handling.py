"""Tests for error handling, retries, and fallback routing."""
import pytest
from unittest.mock import AsyncMock, Mock, patch

from ta_lab2.tools.ai_orchestrator.execution import (
    AsyncOrchestrator,
)
from ta_lab2.tools.ai_orchestrator.core import Task, Result, TaskType, Platform


class TestRetryLogic:
    """Test retry with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retries_on_transient_error(self):
        """Retries when error is retryable."""
        mock_adapter = AsyncMock()

        # First two calls fail, third succeeds
        mock_adapter.submit_task.return_value = "task_123"
        mock_adapter.get_result.side_effect = [
            Result(
                task=Mock(),
                platform=Platform.GEMINI,
                output="",
                success=False,
                error="rate limit",
            ),
            Result(
                task=Mock(),
                platform=Platform.GEMINI,
                output="",
                success=False,
                error="timeout",
            ),
            Result(
                task=Mock(), platform=Platform.GEMINI, output="Success!", success=True
            ),
        ]

        orch = AsyncOrchestrator(
            adapters={Platform.GEMINI: mock_adapter},
            max_concurrent=1,
        )

        task = Task(type=TaskType.CODE_GENERATION, prompt="Test")

        with patch.object(orch, "_router") as mock_router:
            mock_router.route_cost_optimized.return_value = Platform.GEMINI

            result = await orch._execute_with_retries(
                task, mock_adapter, Platform.GEMINI, 3
            )

        assert result.success is True
        assert mock_adapter.get_result.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_auth_error(self):
        """Does not retry authentication errors."""
        mock_adapter = AsyncMock()
        mock_adapter.submit_task.return_value = "task_123"
        mock_adapter.get_result.return_value = Result(
            task=Mock(),
            platform=Platform.GEMINI,
            output="",
            success=False,
            error="Invalid API key",
        )

        orch = AsyncOrchestrator(adapters={Platform.GEMINI: mock_adapter})
        task = Task(type=TaskType.CODE_GENERATION, prompt="Test")

        result = await orch._execute_with_retries(
            task, mock_adapter, Platform.GEMINI, 3
        )

        assert result.success is False
        assert mock_adapter.get_result.call_count == 1  # No retries


class TestFallbackRouting:
    """Test fallback to alternative platforms."""

    @pytest.mark.asyncio
    async def test_falls_back_on_platform_failure(self):
        """Tries next platform when first fails."""
        gemini_adapter = AsyncMock()
        gemini_adapter.submit_task.return_value = "g_task"
        gemini_adapter.get_result.return_value = Result(
            task=Mock(),
            platform=Platform.GEMINI,
            output="",
            success=False,
            error="Quota exhausted",
        )

        claude_adapter = AsyncMock()
        claude_adapter.submit_task.return_value = "c_task"
        claude_adapter.get_result.return_value = Result(
            task=Mock(), platform=Platform.CLAUDE_CODE, output="Success", success=True
        )

        orch = AsyncOrchestrator(
            adapters={
                Platform.GEMINI: gemini_adapter,
                Platform.CLAUDE_CODE: claude_adapter,
            },
        )

        task = Task(type=TaskType.CODE_GENERATION, prompt="Test")

        with patch.object(
            orch,
            "_get_platforms_by_cost",
            return_value=[Platform.GEMINI, Platform.CLAUDE_CODE],
        ):
            result = await orch.execute_with_fallback(task, max_retries=0)

        assert result.success is True
        assert result.platform == Platform.CLAUDE_CODE

    @pytest.mark.asyncio
    async def test_returns_error_when_all_fail(self):
        """Returns error result when all platforms fail."""
        mock_adapter = AsyncMock()
        mock_adapter.submit_task.return_value = "task_123"
        mock_adapter.get_result.return_value = Result(
            task=Mock(),
            platform=Platform.GEMINI,
            output="",
            success=False,
            error="Permanent failure",
        )

        orch = AsyncOrchestrator(adapters={Platform.GEMINI: mock_adapter})
        task = Task(type=TaskType.CODE_GENERATION, prompt="Test")

        with patch.object(
            orch, "_get_platforms_by_cost", return_value=[Platform.GEMINI]
        ):
            result = await orch.execute_with_fallback(task, max_retries=1)

        assert result.success is False
        assert "All platforms failed" in result.error


class TestIsRetryableError:
    """Test error classification."""

    def test_rate_limit_is_retryable(self):
        """Rate limit errors are retryable."""
        orch = AsyncOrchestrator()
        assert orch._is_retryable_error("Rate limit exceeded") is True

    def test_timeout_is_retryable(self):
        """Timeout errors are retryable."""
        orch = AsyncOrchestrator()
        assert orch._is_retryable_error("Request timed out") is True

    def test_auth_error_not_retryable(self):
        """Auth errors are not retryable."""
        orch = AsyncOrchestrator()
        assert orch._is_retryable_error("Invalid API key") is False

    def test_quota_exhausted_not_retryable(self):
        """Quota exhaustion is not retryable (should fallback instead)."""
        orch = AsyncOrchestrator()
        assert orch._is_retryable_error("Quota exhausted") is False


class TestGetPlatformsByCost:
    """Test cost-ordered platform list."""

    def test_returns_available_platforms(self):
        """Returns only platforms with adapters."""
        mock_adapter = Mock()
        orch = AsyncOrchestrator(adapters={Platform.GEMINI: mock_adapter})

        with patch(
            "ta_lab2.tools.ai_orchestrator.routing.COST_TIERS",
            [
                {"platform": Platform.GEMINI, "priority": 1},
                {"platform": Platform.CLAUDE_CODE, "priority": 2},
            ],
        ):
            platforms = orch._get_platforms_by_cost()

        assert Platform.GEMINI in platforms
        assert Platform.CLAUDE_CODE not in platforms  # No adapter

    def test_respects_exclude_set(self):
        """Excludes specified platforms."""
        orch = AsyncOrchestrator(
            adapters={
                Platform.GEMINI: Mock(),
                Platform.CLAUDE_CODE: Mock(),
            }
        )

        with patch(
            "ta_lab2.tools.ai_orchestrator.routing.COST_TIERS",
            [
                {"platform": Platform.GEMINI, "priority": 1},
                {"platform": Platform.CLAUDE_CODE, "priority": 2},
            ],
        ):
            platforms = orch._get_platforms_by_cost(exclude={Platform.GEMINI})

        assert Platform.GEMINI not in platforms
        assert Platform.CLAUDE_CODE in platforms
