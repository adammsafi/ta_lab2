"""Tests for async base infrastructure."""

import asyncio
import pytest

from src.ta_lab2.tools.ai_orchestrator.core import (
    Task,
    TaskType,
    TaskStatus,
    TaskConstraints,
    Result,
    Platform,
)
from src.ta_lab2.tools.ai_orchestrator.adapters import AsyncBasePlatformAdapter
from src.ta_lab2.tools.ai_orchestrator.streaming import StreamingResult, collect_stream


def test_task_status_enum_values():
    """Verify all TaskStatus values exist."""
    assert TaskStatus.PENDING.value == "pending"
    assert TaskStatus.RUNNING.value == "running"
    assert TaskStatus.COMPLETED.value == "completed"
    assert TaskStatus.FAILED.value == "failed"
    assert TaskStatus.CANCELLED.value == "cancelled"
    assert TaskStatus.UNKNOWN.value == "unknown"


def test_task_constraints_defaults():
    """TaskConstraints has reasonable defaults."""
    constraints = TaskConstraints()

    assert constraints.max_tokens is None
    assert constraints.timeout_seconds == 300.0
    assert constraints.temperature is None
    assert constraints.model is None


def test_task_enhanced_fields():
    """Task has context, files, constraints, task_id."""
    task = Task(
        type=TaskType.CODE_GENERATION,
        prompt="test prompt",
        context={"key": "value"},
        files=["file1.py", "file2.py"],
        constraints=TaskConstraints(max_tokens=1000),
        task_id="test_123",
    )

    assert task.context == {"key": "value"}
    assert task.files == ["file1.py", "file2.py"]
    assert task.constraints.max_tokens == 1000
    assert task.task_id == "test_123"


def test_task_enhanced_fields_defaults():
    """Task enhanced fields have proper defaults."""
    task = Task(
        type=TaskType.CODE_GENERATION,
        prompt="test prompt",
    )

    assert task.context == {}
    assert task.files == []
    assert task.constraints is None
    assert task.task_id is None


def test_result_enhanced_fields():
    """Result has status, files_created, partial_output."""
    task = Task(type=TaskType.CODE_GENERATION, prompt="test")
    result = Result(
        task=task,
        platform=Platform.CLAUDE_CODE,
        output="test output",
        success=True,
        status=TaskStatus.COMPLETED,
        files_created=["output1.py", "output2.py"],
        partial_output="partial",
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.files_created == ["output1.py", "output2.py"]
    assert result.partial_output == "partial"


def test_result_enhanced_fields_defaults():
    """Result enhanced fields have proper defaults."""
    task = Task(type=TaskType.CODE_GENERATION, prompt="test")
    result = Result(
        task=task,
        platform=Platform.CLAUDE_CODE,
        output="test output",
        success=True,
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.files_created == []
    assert result.partial_output is None


def test_streaming_result_accumulation():
    """StreamingResult collects chunks correctly."""
    result = StreamingResult()

    result.add_chunk("Hello ")
    result.add_chunk("World")
    result.add_chunk("!")

    assert result.get_content() == "Hello World!"
    assert len(result.chunks) == 3
    assert result.completed_at is None

    result.complete(tokens=50)

    assert result.completed_at is not None
    assert result.total_tokens == 50
    assert result.duration_seconds >= 0  # May be 0 on fast machines


@pytest.mark.asyncio
async def test_collect_stream_success():
    """collect_stream collects all chunks successfully."""

    async def mock_stream():
        for chunk in ["chunk1", "chunk2", "chunk3"]:
            yield chunk
            await asyncio.sleep(0.01)

    result = await collect_stream(mock_stream(), timeout=5)

    assert result.get_content() == "chunk1chunk2chunk3"
    assert len(result.chunks) == 3
    assert result.completed_at is not None


@pytest.mark.asyncio
async def test_collect_stream_timeout():
    """collect_stream respects timeout."""

    async def slow_stream():
        for i in range(100):
            yield f"chunk{i}"
            await asyncio.sleep(0.5)  # Too slow

    with pytest.raises(asyncio.TimeoutError):
        await collect_stream(slow_stream(), timeout=0.5)


@pytest.mark.asyncio
async def test_collect_stream_cancellation():
    """collect_stream handles cancellation and saves partial results."""

    async def infinite_stream():
        i = 0
        while True:
            yield f"chunk{i}"
            i += 1
            await asyncio.sleep(0.01)

    async def cancel_after_delay():
        task = asyncio.create_task(collect_stream(infinite_stream(), timeout=10))
        await asyncio.sleep(0.05)  # Let it collect a few chunks
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return True
        return False

    cancelled = await cancel_after_delay()
    assert cancelled


def test_async_base_adapter_abstract():
    """Cannot instantiate AsyncBasePlatformAdapter directly."""
    with pytest.raises(TypeError) as exc_info:
        AsyncBasePlatformAdapter()

    assert "Can't instantiate abstract class" in str(exc_info.value)


def test_generate_task_id_format():
    """Task ID follows expected format."""

    # Create a concrete test adapter
    class TestAdapter(AsyncBasePlatformAdapter):
        @property
        def is_implemented(self) -> bool:
            return True

        @property
        def implementation_status(self) -> str:
            return "working"

        def get_adapter_status(self) -> dict:
            return {}

        async def submit_task(self, task):
            return self._generate_task_id(task)

        async def get_status(self, task_id):
            return TaskStatus.PENDING

        async def get_result(self, task_id, timeout=300):
            pass

        async def stream_result(self, task_id):
            yield "test"

        async def cancel_task(self, task_id):
            return False

    adapter = TestAdapter()
    task = Task(
        type=TaskType.CODE_GENERATION,
        prompt="test",
        platform_hint=Platform.CLAUDE_CODE,
    )

    task_id = adapter._generate_task_id(task)

    # Format: platform_yyyymmdd_uuid8
    # Note: platform may contain underscores (claude_code)
    assert "_" in task_id
    parts = task_id.split("_")
    # claude_code_20260129_a1b2c3d4 -> 4 parts
    assert len(parts) >= 3
    # Last part should be UUID (8 chars)
    assert len(parts[-1]) == 8
    # Second to last should be date (8 digits)
    assert len(parts[-2]) == 8
    assert parts[-2].isdigit()


@pytest.mark.asyncio
async def test_async_context_manager():
    """AsyncBasePlatformAdapter supports async context manager."""

    class TestAdapter(AsyncBasePlatformAdapter):
        @property
        def is_implemented(self) -> bool:
            return True

        @property
        def implementation_status(self) -> str:
            return "working"

        def get_adapter_status(self) -> dict:
            return {}

        async def submit_task(self, task):
            return "test_id"

        async def get_status(self, task_id):
            return TaskStatus.PENDING

        async def get_result(self, task_id, timeout=300):
            pass

        async def stream_result(self, task_id):
            yield "test"

        async def cancel_task(self, task_id):
            return False

    async with TestAdapter() as adapter:
        assert adapter is not None
        assert isinstance(adapter, AsyncBasePlatformAdapter)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
