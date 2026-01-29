"""Tests for AsyncClaudeCodeAdapter."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import json

from ta_lab2.tools.ai_orchestrator.adapters import AsyncClaudeCodeAdapter
from ta_lab2.tools.ai_orchestrator.core import Task, TaskType, TaskStatus, TaskConstraints


@pytest.fixture
def mock_process():
    """Create mock asyncio process."""
    process = AsyncMock()
    process.returncode = 0
    process.communicate = AsyncMock(return_value=(
        json.dumps({"response": "Test output from Claude"}).encode(),
        b""
    ))
    process.kill = MagicMock()
    process.wait = AsyncMock()
    return process


@pytest.fixture
def sample_task():
    """Create sample task for testing."""
    return Task(
        type=TaskType.CODE_GENERATION,
        prompt="Write a hello world function",
    )


class TestAsyncClaudeCodeAdapterInit:
    """Test adapter initialization."""

    def test_init_with_cli_path(self):
        """Test initialization with explicit CLI path."""
        adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude")
        assert adapter._cli_path == "/usr/bin/claude"
        assert adapter.is_implemented is True

    def test_init_auto_detect_cli(self):
        """Test CLI auto-detection."""
        with patch("shutil.which", return_value="/usr/bin/claude"):
            adapter = AsyncClaudeCodeAdapter()
            assert adapter._cli_path == "/usr/bin/claude"
            assert adapter.is_implemented is True

    def test_init_cli_not_found(self):
        """Test when CLI is not found."""
        with patch("shutil.which", return_value=None):
            adapter = AsyncClaudeCodeAdapter()
            assert adapter._cli_path is None
            assert adapter.is_implemented is False
            assert adapter.implementation_status == "unavailable"

    def test_get_adapter_status(self):
        """Test adapter status reporting."""
        adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude")
        status = adapter.get_adapter_status()

        assert status["name"] == "Claude Code (Async)"
        assert "cli_path" in status
        assert "Async subprocess execution" in status["capabilities"]


class TestAsyncClaudeCodeAdapterExecution:
    """Test task execution."""

    @pytest.mark.asyncio
    async def test_submit_task_returns_task_id(self, mock_process, sample_task):
        """Test that submit_task returns a valid task_id."""
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude")
            task_id = await adapter.submit_task(sample_task)

            assert task_id is not None
            assert "_" in task_id

    @pytest.mark.asyncio
    async def test_get_result_success(self, mock_process, sample_task):
        """Test successful result retrieval."""
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude")
            task_id = await adapter.submit_task(sample_task)
            result = await adapter.get_result(task_id, timeout=5.0)

            assert result.success is True
            assert result.status == TaskStatus.COMPLETED
            assert "Test output from Claude" in result.output

    @pytest.mark.asyncio
    async def test_get_result_cli_failure(self, sample_task):
        """Test handling of CLI failure."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"Error: something went wrong"))
        mock_proc.kill = MagicMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude")
            task_id = await adapter.submit_task(sample_task)
            result = await adapter.get_result(task_id, timeout=5.0)

            assert result.success is False
            assert "exited with code 1" in result.error

    @pytest.mark.asyncio
    async def test_get_result_timeout(self, sample_task):
        """Test timeout handling."""
        mock_proc = AsyncMock()
        # Simulate hanging process
        async def slow_communicate(input=None):
            await asyncio.sleep(10)
            return b"", b""

        mock_proc.communicate = slow_communicate
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude", timeout=0.1)
            task_id = await adapter.submit_task(sample_task)
            result = await adapter.get_result(task_id, timeout=0.1)

            assert result.success is False
            assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_cancel_task(self, sample_task):
        """Test task cancellation."""
        mock_proc = AsyncMock()
        async def slow_communicate(input=None):
            await asyncio.sleep(10)
            return b"", b""

        mock_proc.communicate = slow_communicate
        mock_proc.kill = MagicMock()
        mock_proc.wait = AsyncMock()

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude")
            task_id = await adapter.submit_task(sample_task)
            await asyncio.sleep(0.01)  # Let task start

            cancelled = await adapter.cancel_task(task_id)
            assert cancelled is True

            # Verify process was killed
            mock_proc.kill.assert_called()


class TestAsyncClaudeCodeAdapterContextManager:
    """Test async context manager."""

    @pytest.mark.asyncio
    async def test_context_manager_success(self):
        """Test successful context manager usage."""
        adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude")
        async with adapter as a:
            assert a is adapter

    @pytest.mark.asyncio
    async def test_context_manager_raises_without_cli(self):
        """Test context manager raises if CLI not found."""
        with patch("shutil.which", return_value=None):
            adapter = AsyncClaudeCodeAdapter()
            with pytest.raises(RuntimeError, match="CLI not found"):
                async with adapter:
                    pass

    @pytest.mark.asyncio
    async def test_context_manager_cleanup(self, mock_process, sample_task):
        """Test that context manager cancels pending tasks."""
        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude")

            async with adapter:
                # Submit a task
                task_id = await adapter.submit_task(sample_task)
                # Don't wait for it

            # After exiting context, task should be cancelled
            status = await adapter.get_status(task_id)
            # Status could be COMPLETED (fast) or CANCELLED
            assert status in [TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.UNKNOWN]


class TestFileHandling:
    """Test context file handling."""

    @pytest.mark.asyncio
    async def test_files_passed_to_cli(self, mock_process):
        """Test that files are passed as --file flags."""
        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
            adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude")

            task = Task(
                type=TaskType.CODE_GENERATION,
                prompt="Analyze this file",
                files=["src/main.py", "src/utils.py"],
            )

            task_id = await adapter.submit_task(task)
            await adapter.get_result(task_id, timeout=5.0)

            # Check command includes file flags
            call_args = mock_exec.call_args[0]
            assert "--file" in call_args
            assert "src/main.py" in call_args
            assert "src/utils.py" in call_args


class TestJSONParsing:
    """Test JSON output parsing."""

    @pytest.mark.asyncio
    async def test_json_output_parsed(self, sample_task):
        """Test that JSON output is properly parsed."""
        json_response = {
            "response": "Parsed response content",
            "model": "claude-3-sonnet",
            "files_created": ["output.py"],
        }

        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(
            json.dumps(json_response).encode(),
            b""
        ))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude")
            task_id = await adapter.submit_task(sample_task)
            result = await adapter.get_result(task_id, timeout=5.0)

            assert result.success is True
            assert result.output == "Parsed response content"
            assert result.files_created == ["output.py"]
            assert result.metadata.get("model") == "claude-3-sonnet"

    @pytest.mark.asyncio
    async def test_invalid_json_handled(self, sample_task):
        """Test that invalid JSON is handled gracefully."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(
            b"Not valid JSON output",
            b""
        ))

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude")
            task_id = await adapter.submit_task(sample_task)
            result = await adapter.get_result(task_id, timeout=5.0)

            # Should still succeed with raw output
            assert result.success is True
            assert "Not valid JSON" in result.output
            assert "parse_error" in result.metadata


class TestUnknownTask:
    """Test handling of unknown tasks."""

    @pytest.mark.asyncio
    async def test_get_status_unknown(self):
        """Test status for unknown task_id."""
        adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude")
        status = await adapter.get_status("nonexistent-task-id")
        assert status == TaskStatus.UNKNOWN

    @pytest.mark.asyncio
    async def test_cancel_unknown_task(self):
        """Test cancelling unknown task returns False."""
        adapter = AsyncClaudeCodeAdapter(cli_path="/usr/bin/claude")
        result = await adapter.cancel_task("nonexistent-task-id")
        assert result is False
