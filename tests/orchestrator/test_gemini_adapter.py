"""Tests for AsyncGeminiAdapter."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from ta_lab2.tools.ai_orchestrator.adapters import AsyncGeminiAdapter
from ta_lab2.tools.ai_orchestrator.quota import QuotaTracker
from ta_lab2.tools.ai_orchestrator.core import Task, TaskType, TaskStatus, TaskConstraints


@pytest.fixture
def mock_genai_response():
    """Create mock Gemini response."""
    response = MagicMock()
    response.text = "Test response from Gemini"
    return response


@pytest.fixture
def mock_genai_client(mock_genai_response):
    """Create mock google-genai client."""
    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = AsyncMock(return_value=mock_genai_response)
    return client


@pytest.fixture
def quota_tracker():
    """Create quota tracker for testing."""
    return QuotaTracker(persistence_path=None)


@pytest.fixture
def sample_task():
    """Create sample task for testing."""
    return Task(
        type=TaskType.RESEARCH,
        prompt="Explain quantum computing",
    )


class TestAsyncGeminiAdapterInit:
    """Test adapter initialization."""

    def test_init_with_api_key(self):
        """Test initialization with explicit API key."""
        adapter = AsyncGeminiAdapter(api_key="test-key")
        assert adapter.is_implemented is True
        assert adapter.implementation_status == "working"

    def test_init_without_api_key(self):
        """Test initialization without API key."""
        with patch.dict("os.environ", {}, clear=True):
            adapter = AsyncGeminiAdapter(api_key=None)
            assert adapter.implementation_status in ["working", "unavailable"]

    def test_init_with_quota_tracker(self, quota_tracker):
        """Test initialization with quota tracker."""
        adapter = AsyncGeminiAdapter(api_key="test-key", quota_tracker=quota_tracker)
        assert adapter._quota_tracker is quota_tracker

    def test_get_adapter_status(self, quota_tracker):
        """Test adapter status includes quota info."""
        adapter = AsyncGeminiAdapter(api_key="test-key", quota_tracker=quota_tracker)
        status = adapter.get_adapter_status()

        assert status["name"] == "Gemini (Async)"
        assert "quota" in status
        assert "Quota tracking" in status["capabilities"]


class TestAsyncGeminiAdapterExecution:
    """Test task execution."""

    @pytest.mark.asyncio
    async def test_submit_task_returns_task_id(self, mock_genai_client, sample_task):
        """Test that submit_task returns a valid task_id."""
        with patch("google.genai.Client", return_value=mock_genai_client):
            adapter = AsyncGeminiAdapter(api_key="test-key")
            adapter._client = mock_genai_client

            task_id = await adapter.submit_task(sample_task)
            assert task_id is not None
            assert "_" in task_id

    @pytest.mark.asyncio
    async def test_get_result_success(self, mock_genai_client, sample_task):
        """Test successful result retrieval."""
        adapter = AsyncGeminiAdapter(api_key="test-key")
        adapter._client = mock_genai_client

        task_id = await adapter.submit_task(sample_task)
        result = await adapter.get_result(task_id, timeout=5.0)

        assert result.success is True
        assert result.status == TaskStatus.COMPLETED
        assert result.output == "Test response from Gemini"

    @pytest.mark.asyncio
    async def test_get_result_timeout(self, sample_task):
        """Test timeout handling."""
        mock_client = MagicMock()

        async def slow_response(**kwargs):
            await asyncio.sleep(10)
            return MagicMock(text="Response")

        mock_client.aio.models.generate_content = slow_response

        adapter = AsyncGeminiAdapter(api_key="test-key")
        adapter._client = mock_client

        task_id = await adapter.submit_task(sample_task)
        result = await adapter.get_result(task_id, timeout=0.1)

        assert result.success is False
        assert "timed out" in result.error.lower()


class TestQuotaIntegration:
    """Test quota tracker integration."""

    @pytest.mark.asyncio
    async def test_quota_checked_before_execution(self, mock_genai_client, sample_task, quota_tracker):
        """Test quota is checked before API call."""
        adapter = AsyncGeminiAdapter(api_key="test-key", quota_tracker=quota_tracker)
        adapter._client = mock_genai_client

        # Get initial quota
        initial_status = quota_tracker.get_status()["gemini_cli"]
        initial_used = initial_status["used"]

        task_id = await adapter.submit_task(sample_task)
        await adapter.get_result(task_id, timeout=5.0)

        # Quota should be recorded
        final_status = quota_tracker.get_status()["gemini_cli"]
        assert final_status["used"] == initial_used + 1

    @pytest.mark.asyncio
    async def test_quota_exhausted_fails_fast(self, sample_task, quota_tracker):
        """Test that exhausted quota fails without API call."""
        # Exhaust quota
        for i in range(1500):
            quota_tracker.record_usage("gemini", 1)

        adapter = AsyncGeminiAdapter(api_key="test-key", quota_tracker=quota_tracker)
        adapter._client = MagicMock()  # Won't be called

        task_id = await adapter.submit_task(sample_task)
        result = await adapter.get_result(task_id, timeout=5.0)

        assert result.success is False
        assert "quota" in result.error.lower()

    @pytest.mark.asyncio
    async def test_quota_released_on_failure(self, sample_task, quota_tracker):
        """Test quota is released when API call fails."""
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("API Error")
        )

        adapter = AsyncGeminiAdapter(api_key="test-key", quota_tracker=quota_tracker)
        adapter._client = mock_client

        initial_reserved = quota_tracker.limits["gemini_cli"].reserved

        task_id = await adapter.submit_task(sample_task)
        await adapter.get_result(task_id, timeout=5.0)

        # Reservation should be released
        final_reserved = quota_tracker.limits["gemini_cli"].reserved
        assert final_reserved == initial_reserved

    @pytest.mark.asyncio
    async def test_quota_released_on_cancellation(self, sample_task, quota_tracker):
        """Test quota is released when task is cancelled."""
        mock_client = MagicMock()

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(10)
            return MagicMock(text="Response")

        mock_client.aio.models.generate_content = slow_call

        adapter = AsyncGeminiAdapter(api_key="test-key", quota_tracker=quota_tracker)
        adapter._client = mock_client

        task_id = await adapter.submit_task(sample_task)
        await asyncio.sleep(0.01)

        cancelled = await adapter.cancel_task(task_id)
        assert cancelled is True

        # Check quota was released (not consumed)
        status = quota_tracker.get_status()["gemini_cli"]
        # Reserved should be 0 after cancellation
        assert quota_tracker.limits["gemini_cli"].reserved == 0


class TestAsyncGeminiAdapterContextManager:
    """Test async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_init(self):
        """Test context manager initializes client."""
        with patch("google.genai.Client") as mock_class:
            mock_instance = MagicMock()
            mock_class.return_value = mock_instance

            async with AsyncGeminiAdapter(api_key="test-key") as adapter:
                assert adapter._client is not None
                mock_class.assert_called_once_with(api_key="test-key")

    @pytest.mark.asyncio
    async def test_context_manager_raises_without_key(self):
        """Test context manager raises if no API key."""
        with patch.dict("os.environ", {}, clear=True):
            adapter = AsyncGeminiAdapter(api_key=None)
            with pytest.raises(ValueError, match="GEMINI_API_KEY"):
                async with adapter:
                    pass


class TestTaskWithConstraints:
    """Test task constraints handling."""

    @pytest.mark.asyncio
    async def test_constraints_passed_to_api(self, mock_genai_client):
        """Test that constraints are passed to API call."""
        adapter = AsyncGeminiAdapter(api_key="test-key")
        adapter._client = mock_genai_client

        task = Task(
            type=TaskType.RESEARCH,
            prompt="Test",
            constraints=TaskConstraints(
                max_tokens=500,
                temperature=0.3,
                model="gemini-1.5-pro",
            ),
        )

        task_id = await adapter.submit_task(task)
        await adapter.get_result(task_id)

        # Check API was called with constraints
        call_kwargs = mock_genai_client.aio.models.generate_content.call_args.kwargs
        assert call_kwargs["model"] == "gemini-1.5-pro"
        config = call_kwargs.get("config", {})
        assert config.get("max_output_tokens") == 500
        assert config.get("temperature") == 0.3


class TestContextHandling:
    """Test context injection."""

    @pytest.mark.asyncio
    async def test_context_added_to_prompt(self, mock_genai_client):
        """Test that context is prepended to prompt."""
        adapter = AsyncGeminiAdapter(api_key="test-key")
        adapter._client = mock_genai_client

        task = Task(
            type=TaskType.RESEARCH,
            prompt="Analyze this data",
            context={"project": "ta_lab2", "domain": "quant trading"},
        )

        task_id = await adapter.submit_task(task)
        await adapter.get_result(task_id)

        # Check prompt includes context
        call_args = mock_genai_client.aio.models.generate_content.call_args
        prompt = call_args.kwargs.get("contents", "")
        assert "project: ta_lab2" in prompt
        assert "domain: quant trading" in prompt


class TestUnknownTask:
    """Test handling of unknown tasks."""

    @pytest.mark.asyncio
    async def test_get_status_unknown(self):
        """Test status for unknown task_id."""
        adapter = AsyncGeminiAdapter(api_key="test-key")
        status = await adapter.get_status("nonexistent-task-id")
        assert status == TaskStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_get_result_unknown(self):
        """Test result for unknown task_id."""
        adapter = AsyncGeminiAdapter(api_key="test-key")
        result = await adapter.get_result("nonexistent-task-id")
        assert result.success is False
        assert result.status == TaskStatus.UNKNOWN
