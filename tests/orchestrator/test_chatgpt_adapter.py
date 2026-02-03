"""Tests for AsyncChatGPTAdapter."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from ta_lab2.tools.ai_orchestrator.adapters import AsyncChatGPTAdapter
from ta_lab2.tools.ai_orchestrator.core import (
    Task,
    TaskType,
    TaskStatus,
    TaskConstraints,
)


@pytest.fixture
def mock_openai_response():
    """Create mock OpenAI response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = "Test response from ChatGPT"
    response.usage = MagicMock()
    response.usage.total_tokens = 150
    response.usage.prompt_tokens = 50
    response.usage.completion_tokens = 100
    return response


@pytest.fixture
def mock_openai_client(mock_openai_response):
    """Create mock AsyncOpenAI client."""
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=mock_openai_response)
    client.close = AsyncMock()
    return client


@pytest.fixture
def sample_task():
    """Create sample task for testing."""
    return Task(
        type=TaskType.CODE_GENERATION,
        prompt="Write a hello world function in Python",
    )


class TestAsyncChatGPTAdapterInit:
    """Test adapter initialization."""

    def test_init_with_api_key(self):
        """Test initialization with explicit API key."""
        adapter = AsyncChatGPTAdapter(api_key="test-key")
        assert adapter.is_implemented is True
        assert adapter.implementation_status == "working"

    def test_init_without_api_key(self):
        """Test initialization without API key."""
        with patch.dict("os.environ", {}, clear=True):
            adapter = AsyncChatGPTAdapter(api_key=None)
            # May be True or False depending on env
            assert adapter.implementation_status in ["working", "unavailable"]

    def test_get_adapter_status(self):
        """Test adapter status reporting."""
        adapter = AsyncChatGPTAdapter(api_key="test-key")
        status = adapter.get_adapter_status()

        assert status["name"] == "ChatGPT (Async)"
        assert "capabilities" in status
        assert "Streaming responses" in status["capabilities"]


class TestAsyncChatGPTAdapterExecution:
    """Test task execution."""

    @pytest.mark.asyncio
    async def test_submit_task_returns_task_id(self, mock_openai_client, sample_task):
        """Test that submit_task returns a valid task_id."""
        adapter = AsyncChatGPTAdapter(api_key="test-key")
        adapter._client = mock_openai_client

        task_id = await adapter.submit_task(sample_task)

        assert task_id is not None
        assert "_" in task_id  # Format: platform_timestamp_uuid

    @pytest.mark.asyncio
    async def test_get_status_running(self, mock_openai_client, sample_task):
        """Test status check for running task."""

        # Make the API call hang
        async def slow_call(**kwargs):
            await asyncio.sleep(100)  # Very long sleep
            return MagicMock()

        mock_openai_client.chat.completions.create = slow_call

        adapter = AsyncChatGPTAdapter(api_key="test-key")
        adapter._client = mock_openai_client

        task_id = await adapter.submit_task(sample_task)
        await asyncio.sleep(0.05)  # Let task start

        status = await adapter.get_status(task_id)
        assert status == TaskStatus.RUNNING

        # Cleanup
        await adapter.cancel_task(task_id)

    @pytest.mark.asyncio
    async def test_get_result_success(self, mock_openai_client, sample_task):
        """Test successful result retrieval."""
        adapter = AsyncChatGPTAdapter(api_key="test-key")
        adapter._client = mock_openai_client

        task_id = await adapter.submit_task(sample_task)
        result = await adapter.get_result(task_id, timeout=5.0)

        assert result.success is True
        assert result.status == TaskStatus.COMPLETED
        assert result.output == "Test response from ChatGPT"
        assert result.tokens_used == 150
        assert result.metadata["input_tokens"] == 50
        assert result.metadata["output_tokens"] == 100

    @pytest.mark.asyncio
    async def test_get_result_timeout(self, sample_task):
        """Test timeout handling."""

        # Create adapter with slow mock
        async def slow_call(**kwargs):
            await asyncio.sleep(10)
            return MagicMock()

        adapter = AsyncChatGPTAdapter(api_key="test-key")
        adapter._client = AsyncMock()
        adapter._client.chat.completions.create = slow_call

        task_id = await adapter.submit_task(sample_task)
        result = await adapter.get_result(task_id, timeout=0.1)

        assert result.success is False
        assert "timed out" in result.error

    @pytest.mark.asyncio
    async def test_cancel_task(self, sample_task):
        """Test task cancellation."""
        adapter = AsyncChatGPTAdapter(api_key="test-key")
        adapter._client = AsyncMock()

        # Slow API call
        async def slow_call(**kwargs):
            await asyncio.sleep(10)
            return MagicMock()

        adapter._client.chat.completions.create = slow_call

        task_id = await adapter.submit_task(sample_task)
        await asyncio.sleep(0.01)  # Let task start

        cancelled = await adapter.cancel_task(task_id)
        assert cancelled is True

        status = await adapter.get_status(task_id)
        assert status == TaskStatus.CANCELLED


class TestAsyncChatGPTAdapterContextManager:
    """Test async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_init_close(self):
        """Test context manager initializes and closes client."""
        with patch("openai.AsyncOpenAI") as mock_class:
            mock_instance = AsyncMock()
            mock_class.return_value = mock_instance

            async with AsyncChatGPTAdapter(api_key="test-key") as adapter:
                assert adapter._client is not None

            mock_instance.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager_raises_without_key(self):
        """Test context manager raises if no API key."""
        with patch.dict("os.environ", {}, clear=True):
            adapter = AsyncChatGPTAdapter(api_key=None)
            with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                async with adapter:
                    pass


class TestTaskWithConstraints:
    """Test task constraints handling."""

    @pytest.mark.asyncio
    async def test_constraints_passed_to_api(self, mock_openai_client):
        """Test that constraints are passed to API call."""
        adapter = AsyncChatGPTAdapter(api_key="test-key")
        adapter._client = mock_openai_client

        task = Task(
            type=TaskType.CODE_GENERATION,
            prompt="Test",
            constraints=TaskConstraints(
                max_tokens=100,
                temperature=0.5,
                model="gpt-4",
            ),
        )

        task_id = await adapter.submit_task(task)
        await adapter.get_result(task_id)

        # Check API was called with constraints
        call_kwargs = mock_openai_client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4"
        assert call_kwargs["max_tokens"] == 100
        assert call_kwargs["temperature"] == 0.5


class TestUnknownTask:
    """Test handling of unknown tasks."""

    @pytest.mark.asyncio
    async def test_get_status_unknown(self):
        """Test status for unknown task_id."""
        adapter = AsyncChatGPTAdapter(api_key="test-key")
        status = await adapter.get_status("nonexistent-task-id")
        assert status == TaskStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_get_result_unknown(self):
        """Test result for unknown task_id."""
        adapter = AsyncChatGPTAdapter(api_key="test-key")
        result = await adapter.get_result("nonexistent-task-id")
        assert result.success is False
        assert result.status == TaskStatus.UNKNOWN
