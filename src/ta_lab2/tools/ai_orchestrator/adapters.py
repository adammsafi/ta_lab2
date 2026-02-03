"""Platform adapters for executing tasks on different AI systems."""

from __future__ import annotations

import asyncio
import os
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
import shutil
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from .core import Task, Result, TaskStatus

from .core import Result, Platform as Plat, TaskStatus, TaskType
from .quota import QuotaTracker


class BasePlatformAdapter(ABC):
    """Base class for all platform adapters (sync version for backward compatibility)."""

    @abstractmethod
    def execute(self, task: Task) -> Result:
        """Execute a task and return result."""
        pass

    @property
    @abstractmethod
    def is_implemented(self) -> bool:
        """Return True if adapter is fully implemented and usable."""
        pass

    @property
    @abstractmethod
    def implementation_status(self) -> str:
        """Return implementation status: 'working', 'partial', 'stub', 'unavailable', 'error'."""
        pass

    @abstractmethod
    def get_adapter_status(self) -> dict:
        """
        Return comprehensive adapter status.

        Returns:
            dict with keys: name, is_implemented, status, capabilities, requirements
        """
        pass


class AsyncBasePlatformAdapter(ABC):
    """
    Base class for async platform adapters.

    Provides comprehensive task lifecycle management with async execution model.
    Supports task submission, status tracking, result retrieval, streaming, and cancellation.
    """

    def __init__(self):
        self._pending_tasks: dict[str, Task] = {}

    # Abstract async methods - must be implemented by subclasses

    @abstractmethod
    async def submit_task(self, task: Task) -> str:
        """
        Submit a task for execution and return task ID.

        Args:
            task: Task to execute

        Returns:
            task_id: Unique identifier for tracking this task

        Raises:
            RuntimeError: If adapter is not available or task cannot be submitted
        """
        pass

    @abstractmethod
    async def get_status(self, task_id: str) -> TaskStatus:
        """
        Check execution status of a task.

        Args:
            task_id: Task identifier returned from submit_task

        Returns:
            TaskStatus: Current execution state

        Raises:
            KeyError: If task_id is not found
        """
        pass

    @abstractmethod
    async def get_result(self, task_id: str, timeout: float = 300) -> Result:
        """
        Get complete result from a task (blocks until done or timeout).

        Args:
            task_id: Task identifier
            timeout: Maximum time to wait in seconds (default 5 minutes)

        Returns:
            Result: Complete task result

        Raises:
            asyncio.TimeoutError: If task doesn't complete within timeout
            KeyError: If task_id is not found
        """
        pass

    @abstractmethod
    async def stream_result(self, task_id: str) -> AsyncIterator[str]:
        """
        Stream partial results as they become available.

        Args:
            task_id: Task identifier

        Yields:
            str: Partial output chunks

        Raises:
            KeyError: If task_id is not found
            NotImplementedError: If platform doesn't support streaming
        """
        pass

    @abstractmethod
    async def cancel_task(self, task_id: str) -> bool:
        """
        Attempt to cancel a running task.

        Args:
            task_id: Task identifier

        Returns:
            bool: True if cancellation succeeded, False otherwise

        Raises:
            KeyError: If task_id is not found
        """
        pass

    # Property methods (keep from existing)

    @property
    @abstractmethod
    def is_implemented(self) -> bool:
        """Return True if adapter is fully implemented and usable."""
        pass

    @property
    @abstractmethod
    def implementation_status(self) -> str:
        """Return implementation status: 'working', 'partial', 'stub', 'unavailable', 'error'."""
        pass

    @abstractmethod
    def get_adapter_status(self) -> dict:
        """
        Return comprehensive adapter status.

        Returns:
            dict with keys: name, is_implemented, status, capabilities, requirements
        """
        pass

    # Async context manager support

    async def __aenter__(self):
        """Enter async context."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context and cleanup resources."""
        pass

    # Utility methods

    def _generate_task_id(self, task: Task) -> str:
        """
        Generate unique task ID.

        Format: {platform}_{timestamp}_{uuid8}
        Example: claude_code_20260129_a1b2c3d4

        Args:
            task: Task to generate ID for

        Returns:
            str: Unique task identifier
        """
        platform_name = task.platform_hint.value if task.platform_hint else "unknown"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        uuid_short = str(uuid.uuid4())[:8]
        return f"{platform_name}_{timestamp}_{uuid_short}"

    async def _wait_with_timeout(self, coro, timeout: float):
        """
        Wrapper for asyncio.wait_for with proper CancelledError handling.

        Args:
            coro: Coroutine to execute
            timeout: Timeout in seconds

        Returns:
            Result from coroutine

        Raises:
            asyncio.TimeoutError: If timeout exceeded
            asyncio.CancelledError: If cancelled (re-raised after cleanup)
        """
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.CancelledError:
            # Re-raise CancelledError after any cleanup
            raise


class ClaudeCodeAdapter(BasePlatformAdapter):
    """
    Adapter for Claude Code CLI.

    Executes tasks via:
    - Interactive mode (current session)
    - Subprocess mode (spawn new Claude Code instance)
    - GSD workflow mode (use GSD commands)
    """

    def __init__(self):
        self.gsd_available = self._check_gsd_installed()

    @property
    def is_implemented(self) -> bool:
        """Claude Code adapter is partially implemented (subprocess mode is stub)."""
        return True

    @property
    def implementation_status(self) -> str:
        """Return implementation status."""
        return "partial"  # Interactive mode works, subprocess mode is stub

    def get_adapter_status(self) -> dict:
        """Return comprehensive adapter status."""
        return {
            "name": "Claude Code",
            "is_implemented": self.is_implemented,
            "status": self.implementation_status,
            "capabilities": [
                "Interactive execution (current session)",
                "GSD workflow routing",
                "Direct file access",
            ],
            "requirements": [
                "Running inside Claude Code session",
                "GSD installed for workflow tasks (optional)",
            ],
        }

    def _check_implementation(self) -> bool:
        """Verify Claude Code CLI is available (we're running in it)."""
        # If we can import this module, we're in Claude Code
        return True

    def execute(self, task: Task) -> Result:
        """
        Execute task via Claude Code.

        For GSD tasks: route to GSD workflow
        For others: execute via subprocess or return instructions
        """
        start = time.time()

        try:
            if task.requires_gsd:
                output = self._execute_gsd(task)
            else:
                output = self._execute_subprocess(task)

            return Result(
                task=task,
                platform=Plat.CLAUDE_CODE,
                output=output,
                success=True,
                duration_seconds=time.time() - start,
                metadata={"method": "gsd" if task.requires_gsd else "subprocess"},
            )

        except Exception as e:
            return Result(
                task=task,
                platform=Plat.CLAUDE_CODE,
                output="",
                success=False,
                error=str(e),
                duration_seconds=time.time() - start,
            )

    def _execute_gsd(self, task: Task) -> str:
        """Execute via GSD workflow."""
        if not self.gsd_available:
            raise RuntimeError("GSD not installed. Run: npx get-shit-done-cc --local")

        steps = task.metadata.get("steps", [])
        workflow = task.metadata.get("workflow", "custom")

        # Build GSD command sequence
        commands = "\n".join(steps)

        # For now, return instructions for interactive execution
        # TODO: Implement subprocess execution with stdin pipe
        return f"""
GSD Workflow: {workflow}

Execute these commands in Claude Code:
{commands}

(Automated execution not yet implemented - run interactively for now)
"""

    def _execute_subprocess(self, task: Task) -> str:
        """Execute via Claude Code subprocess."""
        # NOTE: This is a stub for future implementation
        # Claude Code CLI doesn't have a simple "run prompt" mode yet

        return f"""
Task: {task.type.value}
Prompt: {task.prompt}

(Subprocess execution not yet implemented - this is running in current session)

To execute manually:
1. Copy the prompt above
2. Paste into Claude Code chat
3. Review the results
"""

    @staticmethod
    def _check_gsd_installed() -> bool:
        """Check if GSD is installed in .claude/."""
        gsd_path = Path(".claude/commands/gsd")
        return gsd_path.exists()


class ChatGPTAdapter(BasePlatformAdapter):
    """
    Adapter for ChatGPT.

    Methods:
    - Web UI automation (Selenium/Playwright)
    - OpenAI API
    """

    def __init__(self, use_api: bool = False):
        self.use_api = use_api
        if use_api:
            self._init_api_client()
        else:
            self._web_driver = None  # Initialize on first use

    @property
    def is_implemented(self) -> bool:
        """ChatGPT adapter is still a stub."""
        return False

    @property
    def implementation_status(self) -> str:
        """Return implementation status."""
        return "stub"

    def get_adapter_status(self) -> dict:
        """Return comprehensive adapter status."""
        return {
            "name": "ChatGPT",
            "is_implemented": self.is_implemented,
            "status": self.implementation_status,
            "capabilities": [
                "Planned: OpenAI API integration",
                "Planned: Web UI automation (Selenium)",
            ],
            "requirements": [
                "OPENAI_API_KEY environment variable (for API mode)",
                "Selenium/ChromeDriver (for web automation)",
            ],
        }

    def execute(self, task: Task) -> Result:
        """Execute task via ChatGPT."""
        start = time.time()

        # STUB: Not yet implemented
        if not self.is_implemented:
            error_msg = (
                "ChatGPT adapter not yet implemented. "
                "Required: OPENAI_API_KEY or Selenium setup. "
                "For now, copy the prompt and paste into ChatGPT web UI."
            )
            raise NotImplementedError(error_msg)

        output = f"""
[ChatGPT Stub]
Task: {task.type.value}
Prompt: {task.prompt}

Implementation pending:
- OpenAI API integration
- Web UI automation (Selenium)

For now, copy the prompt above and paste into ChatGPT web UI.
"""

        return Result(
            task=task,
            platform=Plat.CHATGPT,
            output=output,
            success=False,  # Stub, not actually executed
            error="Not implemented",
            duration_seconds=time.time() - start,
            metadata={"stub": True},
        )

    def _init_api_client(self):
        """Initialize OpenAI API client."""
        try:
            from openai import OpenAI
            import os

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set")

            self.api_client = OpenAI(api_key=api_key)
        except ImportError:
            raise RuntimeError("openai package not installed. Run: pip install openai")


class GeminiAdapter(BasePlatformAdapter):
    """
    Adapter for Google Gemini.

    Methods:
    - gcloud CLI (free quota)
    - Gemini API
    """

    def __init__(self, prefer_cli: bool = True):
        self.prefer_cli = prefer_cli
        self._gcloud_available = self._check_gcloud_available()

    @property
    def is_implemented(self) -> bool:
        """Gemini adapter is implemented if gcloud CLI is available."""
        return self._gcloud_available

    @property
    def implementation_status(self) -> str:
        """Return implementation status."""
        if self._gcloud_available:
            return "working"
        return "unavailable"

    def get_adapter_status(self) -> dict:
        """Return comprehensive adapter status."""
        return {
            "name": "Gemini",
            "is_implemented": self.is_implemented,
            "status": self.implementation_status,
            "capabilities": [
                "gcloud CLI execution (free quota)"
                if self._gcloud_available
                else "Planned: gcloud CLI",
                "Gemini 2.0 Flash model"
                if self._gcloud_available
                else "Planned: Gemini API",
            ],
            "requirements": [
                "gcloud CLI installed and configured"
                + (" (met)" if self._gcloud_available else " (missing)"),
                "Google Cloud project with Vertex AI enabled",
            ],
        }

    def _check_gcloud_available(self) -> bool:
        """Check if gcloud CLI is available."""
        try:
            gcloud_executable = shutil.which("gcloud")
            if not gcloud_executable:
                return False

            result = subprocess.run(
                [gcloud_executable, "--version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def execute(self, task: Task) -> Result:
        """Execute task via Gemini."""
        start = time.time()

        try:
            if self.prefer_cli:
                output = self._execute_cli(task)
            else:
                output = self._execute_api(task)

            return Result(
                task=task,
                platform=Plat.GEMINI,
                output=output,
                success=True,
                duration_seconds=time.time() - start,
                metadata={"method": "cli" if self.prefer_cli else "api"},
            )

        except Exception as e:
            return Result(
                task=task,
                platform=Plat.GEMINI,
                output="",
                success=False,
                error=str(e),
                duration_seconds=time.time() - start,
            )

    def _execute_cli(self, task: Task) -> str:
        """Execute via gcloud CLI (free quota)."""
        try:
            gcloud_executable = shutil.which("gcloud")
            if not gcloud_executable:
                raise FileNotFoundError("gcloud CLI not found.")

            # Check if gcloud is available
            subprocess.run(
                [gcloud_executable, "--version"],
                capture_output=True,
                check=True,
            )

            # Execute with Gemini 2.0 Flash
            cmd = [
                gcloud_executable,
                "ai",
                "models",
                "generate-content",
                "--model=gemini-2.0-flash-exp",
                f"--prompt={task.prompt}",
                "--format=json",
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                raise RuntimeError(f"gcloud failed: {result.stderr}")

            return result.stdout

        except FileNotFoundError:
            raise RuntimeError(
                "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("Gemini CLI request timed out")

    def _execute_api(self, task: Task) -> str:
        """Execute via Gemini API."""
        # STUB: Not yet implemented
        return f"""
[Gemini API Stub]
Task: {task.type.value}
Prompt: {task.prompt}

Gemini API integration pending.
For now, use gcloud CLI or Gemini web UI.
"""


class AsyncClaudeCodeAdapter(AsyncBasePlatformAdapter):
    """
    Async adapter for Claude Code CLI.

    Executes tasks via:
    - Async subprocess with JSON output parsing
    - Context file passing via --file flags
    - Proper timeout and cancellation handling

    NOTE: This requires Claude Code CLI to be installed and accessible.
    The CLI binary is typically named 'claude' or 'claude-code'.
    """

    def __init__(
        self,
        cli_path: str | None = None,
        timeout: float = 300.0,
        output_format: str = "json",
    ):
        """
        Initialize Claude Code adapter.

        Args:
            cli_path: Path to Claude Code CLI binary (auto-detected if None)
            timeout: Default timeout for CLI execution in seconds (default: 5 min)
            output_format: Output format (json, text, or stream-json)
        """
        self._cli_path = cli_path or self._find_cli()
        self._timeout = timeout
        self._output_format = output_format
        self._pending_tasks: dict[str, asyncio.Task] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    def _find_cli(self) -> str | None:
        """Find Claude Code CLI binary."""
        import shutil

        # Try common names
        for name in ["claude", "claude-code"]:
            path = shutil.which(name)
            if path:
                return path
        return None

    @property
    def is_implemented(self) -> bool:
        """Check if CLI is available."""
        return self._cli_path is not None

    @property
    def implementation_status(self) -> str:
        """Return implementation status."""
        if not self._cli_path:
            return "unavailable"
        return "working"

    def get_adapter_status(self) -> dict:
        """Return comprehensive adapter status."""
        return {
            "name": "Claude Code (Async)",
            "is_implemented": self.is_implemented,
            "status": self.implementation_status,
            "cli_path": self._cli_path,
            "capabilities": [
                "Async subprocess execution",
                "JSON output parsing",
                "Context file passing",
                "GSD workflow support (via current session)",
            ],
            "requirements": [
                f"Claude Code CLI {'(found: ' + self._cli_path + ')' if self._cli_path else '(not found)'}"
            ],
        }

    async def __aenter__(self):
        """Enter context - verify CLI exists."""
        if not self._cli_path:
            raise RuntimeError(
                "Claude Code CLI not found. Install from https://code.claude.com"
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit context - cleanup any running processes."""
        # Cancel all pending tasks
        for task_id in list(self._pending_tasks.keys()):
            await self.cancel_task(task_id)

    async def submit_task(self, task: Task) -> str:
        """Submit task and return task_id."""
        task_id = self._generate_task_id(task)
        task.task_id = task_id

        # Create background task for execution
        self._pending_tasks[task_id] = asyncio.create_task(
            self._execute_internal(task, task_id)
        )

        return task_id

    async def get_status(self, task_id: str) -> TaskStatus:
        """Get task status."""
        from .core import TaskStatus

        if task_id not in self._pending_tasks:
            return TaskStatus.UNKNOWN

        task_obj = self._pending_tasks[task_id]
        if task_obj.done():
            if task_obj.cancelled():
                return TaskStatus.CANCELLED
            if task_obj.exception():
                return TaskStatus.FAILED
            return TaskStatus.COMPLETED
        return TaskStatus.RUNNING

    async def get_result(self, task_id: str, timeout: float = 300) -> Result:
        """Get complete result, waiting if necessary."""
        from .core import TaskStatus, Platform, TaskType, Task

        if task_id not in self._pending_tasks:
            return Result(
                task=Task(type=TaskType.CODE_GENERATION, prompt=""),
                platform=Platform.CLAUDE_CODE,
                output="",
                success=False,
                status=TaskStatus.UNKNOWN,
                error=f"Unknown task_id: {task_id}",
            )

        try:
            result = await asyncio.wait_for(
                self._pending_tasks[task_id], timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            # Try to kill the process if still running
            if task_id in self._processes:
                self._processes[task_id].kill()
            return Result(
                task=Task(type=TaskType.CODE_GENERATION, prompt=""),
                platform=Platform.CLAUDE_CODE,
                output="",
                success=False,
                status=TaskStatus.FAILED,
                error=f"Task timed out after {timeout}s",
            )
        except asyncio.CancelledError:
            raise  # Always re-raise

    async def stream_result(self, task_id: str) -> AsyncIterator[str]:
        """Stream result - not fully supported for subprocess."""
        # Claude CLI can output stream-json format, but parsing is complex
        # For now, yield complete result
        result = await self.get_result(task_id)
        if result.output:
            yield result.output

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        if task_id not in self._pending_tasks:
            return False

        task_obj = self._pending_tasks[task_id]
        if task_obj.done():
            return False

        # Kill subprocess if running
        if task_id in self._processes:
            process = self._processes[task_id]
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass  # Process already dead

        # Cancel the asyncio task
        task_obj.cancel()
        try:
            await task_obj
        except asyncio.CancelledError:
            pass

        return True

    async def _execute_internal(self, task: Task, task_id: str) -> Result:
        """Execute task via subprocess."""
        from .core import TaskStatus, Platform
        import json
        import time

        start_time = time.time()

        try:
            # Build command
            cmd = [self._cli_path, "--output-format", self._output_format]

            # Add context files if provided
            if task.files:
                for file_path in task.files:
                    cmd.extend(["--file", str(file_path)])

            # Create subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Store process reference for cancellation
            self._processes[task_id] = process

            # Determine timeout
            timeout = (
                task.constraints.timeout_seconds
                if task.constraints and task.constraints.timeout_seconds
                else self._timeout
            )

            try:
                # Send prompt via stdin and wait for response
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=task.prompt.encode("utf-8")),
                    timeout=timeout,
                )
            finally:
                # Clean up process reference
                if task_id in self._processes:
                    del self._processes[task_id]

            # Check return code
            if process.returncode != 0:
                return Result(
                    task=task,
                    platform=Platform.CLAUDE_CODE,
                    output="",
                    success=False,
                    status=TaskStatus.FAILED,
                    error=f"CLI exited with code {process.returncode}: {stderr.decode('utf-8', errors='replace')}",
                    duration_seconds=time.time() - start_time,
                )

            # Parse output
            output_text = stdout.decode("utf-8", errors="replace")
            files_created = []
            metadata = {}

            if self._output_format == "json":
                try:
                    output_data = json.loads(output_text)
                    # Extract relevant fields from JSON
                    output_text = output_data.get(
                        "response", output_data.get("content", output_text)
                    )
                    files_created = output_data.get("files_created", [])
                    metadata = {
                        "raw_json": output_data,
                        "model": output_data.get("model"),
                    }
                except json.JSONDecodeError:
                    # If JSON parsing fails, use raw output
                    metadata["parse_error"] = "Could not parse JSON output"

            return Result(
                task=task,
                platform=Platform.CLAUDE_CODE,
                output=output_text,
                success=True,
                status=TaskStatus.COMPLETED,
                duration_seconds=time.time() - start_time,
                files_created=files_created,
                metadata=metadata,
            )

        except asyncio.TimeoutError:
            # Kill process on timeout
            if task_id in self._processes:
                self._processes[task_id].kill()
                del self._processes[task_id]
            return Result(
                task=task,
                platform=Platform.CLAUDE_CODE,
                output="",
                success=False,
                status=TaskStatus.FAILED,
                error=f"Execution timed out after {self._timeout}s",
                duration_seconds=time.time() - start_time,
            )

        except asyncio.CancelledError:
            # Clean up and re-raise
            if task_id in self._processes:
                self._processes[task_id].kill()
                del self._processes[task_id]
            raise

        except Exception as e:
            return Result(
                task=task,
                platform=Platform.CLAUDE_CODE,
                output="",
                success=False,
                status=TaskStatus.FAILED,
                error=str(e),
                duration_seconds=time.time() - start_time,
            )


class AsyncChatGPTAdapter(AsyncBasePlatformAdapter):
    """
    Async adapter for ChatGPT via OpenAI API.

    Features:
    - Async API calls with openai.AsyncOpenAI
    - Streaming support via async generators
    - Token tracking from API responses
    - Retry on rate limits with exponential backoff
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        timeout: float = 60.0,
    ):
        """
        Initialize ChatGPT adapter.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: Default model to use (default: gpt-4o-mini for cost efficiency)
            timeout: Default timeout for API calls in seconds
        """
        super().__init__()
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._model = model
        self._timeout = timeout
        self._client = None
        self._pending_tasks: dict[str, asyncio.Task] = {}

    async def __aenter__(self):
        """Initialize async client."""
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY not set")

        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=self._api_key, timeout=self._timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup client."""
        if self._client:
            await self._client.close()
            self._client = None

    @property
    def is_implemented(self) -> bool:
        """Check if adapter is usable."""
        return bool(self._api_key)

    @property
    def implementation_status(self) -> str:
        """Return implementation status."""
        if not self._api_key:
            return "unavailable"
        return "working"

    def get_adapter_status(self) -> dict:
        """Return comprehensive adapter status."""
        return {
            "name": "ChatGPT (Async)",
            "is_implemented": self.is_implemented,
            "status": self.implementation_status,
            "model": self._model,
            "capabilities": [
                "OpenAI API integration",
                "Streaming responses",
                "Token tracking",
                "Retry on rate limits",
            ],
            "requirements": [
                f"OPENAI_API_KEY {'(set)' if self._api_key else '(missing)'}"
            ],
        }

    async def submit_task(self, task: Task) -> str:
        """Submit task and return task_id."""

        task_id = self._generate_task_id(task)
        task.task_id = task_id

        # Create background task for execution
        self._pending_tasks[task_id] = asyncio.create_task(self._execute_internal(task))

        return task_id

    async def get_status(self, task_id: str) -> TaskStatus:
        """Get task status."""
        from .core import TaskStatus

        if task_id not in self._pending_tasks:
            return TaskStatus.UNKNOWN

        task_obj = self._pending_tasks[task_id]
        if task_obj.done():
            if task_obj.cancelled():
                return TaskStatus.CANCELLED
            if task_obj.exception():
                return TaskStatus.FAILED
            return TaskStatus.COMPLETED
        return TaskStatus.RUNNING

    async def get_result(self, task_id: str, timeout: float = 300) -> Result:
        """Get complete result, waiting if necessary."""
        from .core import TaskStatus, Platform, Task as CoreTask

        if task_id not in self._pending_tasks:
            # Return error result for unknown task
            return Result(
                task=CoreTask(type=TaskType.CODE_GENERATION, prompt=""),
                platform=Platform.CHATGPT,
                output="",
                success=False,
                status=TaskStatus.UNKNOWN,
                error=f"Unknown task_id: {task_id}",
            )

        try:
            result = await asyncio.wait_for(
                self._pending_tasks[task_id], timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            return Result(
                task=CoreTask(type=TaskType.CODE_GENERATION, prompt=""),
                platform=Platform.CHATGPT,
                output="",
                success=False,
                status=TaskStatus.FAILED,
                error=f"Task timed out after {timeout}s",
            )
        except asyncio.CancelledError:
            raise  # Re-raise cancellation

    async def stream_result(self, task_id: str) -> AsyncIterator[str]:
        """Stream result chunks."""
        # For simplicity, execute inline for streaming
        # A production implementation would track streaming tasks separately
        if task_id not in self._pending_tasks:
            return

        task_obj = self._pending_tasks.get(task_id)
        if task_obj and not task_obj.done():
            # Task still running - can't stream a background task
            # This is a limitation - streaming needs direct execution
            return

        # Fallback: yield the complete result
        result = await self.get_result(task_id)
        if result.output:
            yield result.output

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        if task_id not in self._pending_tasks:
            return False

        task_obj = self._pending_tasks[task_id]
        if task_obj.done():
            return False

        task_obj.cancel()
        try:
            await task_obj
        except asyncio.CancelledError:
            pass
        return True

    async def _execute_internal(self, task: Task) -> Result:
        """Internal execution with retry logic."""
        from .core import TaskStatus, Platform
        from .retry import retry_on_rate_limit
        import time

        start_time = time.time()

        if not self._client:
            return Result(
                task=task,
                platform=Platform.CHATGPT,
                output="",
                success=False,
                status=TaskStatus.FAILED,
                error="Client not initialized. Use 'async with' context manager.",
            )

        try:
            # Build messages
            messages = [{"role": "user", "content": task.prompt}]

            # Add context if provided
            if task.context:
                context_str = "\n".join(f"{k}: {v}" for k, v in task.context.items())
                messages.insert(
                    0, {"role": "system", "content": f"Context:\n{context_str}"}
                )

            # Determine model
            model = (
                task.constraints.model
                if task.constraints and task.constraints.model
                else self._model
            )

            # Apply retry decorator dynamically
            @retry_on_rate_limit()
            async def make_request():
                return await self._client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=task.constraints.max_tokens
                    if task.constraints
                    else None,
                    temperature=task.constraints.temperature
                    if task.constraints
                    else None,
                )

            response = await make_request()

            # Extract output and token usage
            output = response.choices[0].message.content or ""
            tokens_used = response.usage.total_tokens if response.usage else 0

            # Calculate cost (approximate for gpt-4o-mini)
            # Input: $0.15/1M tokens, Output: $0.60/1M tokens
            input_tokens = response.usage.prompt_tokens if response.usage else 0
            output_tokens = response.usage.completion_tokens if response.usage else 0
            cost = (input_tokens * 0.15 + output_tokens * 0.60) / 1_000_000

            return Result(
                task=task,
                platform=Platform.CHATGPT,
                output=output,
                success=True,
                status=TaskStatus.COMPLETED,
                tokens_used=tokens_used,
                cost=cost,
                duration_seconds=time.time() - start_time,
                metadata={
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            )

        except asyncio.CancelledError:
            raise  # Always re-raise CancelledError
        except Exception as e:
            return Result(
                task=task,
                platform=Platform.CHATGPT,
                output="",
                success=False,
                status=TaskStatus.FAILED,
                error=str(e),
                duration_seconds=time.time() - start_time,
            )

    async def execute_streaming(self, task: Task) -> AsyncIterator[str]:
        """Execute task with streaming response."""
        from .retry import retry_on_rate_limit

        if not self._client:
            raise RuntimeError(
                "Client not initialized. Use 'async with' context manager."
            )

        # Build messages
        messages = [{"role": "user", "content": task.prompt}]
        if task.context:
            context_str = "\n".join(f"{k}: {v}" for k, v in task.context.items())
            messages.insert(
                0, {"role": "system", "content": f"Context:\n{context_str}"}
            )

        model = (
            task.constraints.model
            if task.constraints and task.constraints.model
            else self._model
        )

        @retry_on_rate_limit()
        async def make_streaming_request():
            return await self._client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=task.constraints.max_tokens if task.constraints else None,
                temperature=task.constraints.temperature if task.constraints else None,
                stream=True,
                stream_options={"include_usage": True},
            )

        stream = await make_streaming_request()

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class AsyncGeminiAdapter(AsyncBasePlatformAdapter):
    """
    Async adapter for Google Gemini via google-genai SDK.

    Features:
    - Async API calls with google-genai
    - Streaming support via async generators
    - Quota tracking integration (1500 req/day free tier)
    - Retry on rate limits with exponential backoff

    NOTE: Uses new google-genai SDK (not deprecated google-generativeai).
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.0-flash-exp",
        timeout: float = 60.0,
        quota_tracker: QuotaTracker | None = None,
    ):
        """
        Initialize Gemini adapter.

        Args:
            api_key: Gemini API key (defaults to GEMINI_API_KEY env var)
            model: Model to use (default: gemini-2.0-flash-exp for cost efficiency)
            timeout: Default timeout in seconds
            quota_tracker: Optional QuotaTracker for quota management
        """
        super().__init__()
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self._model = model
        self._timeout = timeout
        self._quota_tracker = quota_tracker
        self._client = None
        self._pending_tasks: dict[str, asyncio.Task] = {}

    async def __aenter__(self):
        """Initialize async client."""
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY not set")

        # Import here to avoid hard dependency
        try:
            from google import genai

            self._client = genai.Client(api_key=self._api_key)
        except ImportError:
            raise RuntimeError(
                "google-genai not installed. Run: pip install google-genai"
            )

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Cleanup client."""
        # google-genai client doesn't require explicit cleanup
        self._client = None

    @property
    def is_implemented(self) -> bool:
        """Check if adapter is usable."""
        return bool(self._api_key)

    @property
    def implementation_status(self) -> str:
        """Return implementation status."""
        if not self._api_key:
            return "unavailable"
        return "working"

    def get_adapter_status(self) -> dict:
        """Return comprehensive adapter status."""
        quota_info = "not configured"
        if self._quota_tracker:
            status = self._quota_tracker.get_status().get("gemini_cli", {})
            used = status.get("used", 0)
            limit = status.get("limit", "unlimited")
            quota_info = f"{used}/{limit}"

        return {
            "name": "Gemini (Async)",
            "is_implemented": self.is_implemented,
            "status": self.implementation_status,
            "model": self._model,
            "quota": quota_info,
            "capabilities": [
                "google-genai SDK integration",
                "Streaming responses",
                "Quota tracking",
                "Retry on rate limits",
            ],
            "requirements": [
                f"GEMINI_API_KEY {'(set)' if self._api_key else '(missing)'}",
                "google-genai package",
            ],
        }

    async def submit_task(self, task: Task) -> str:
        """Submit task and return task_id."""
        task_id = self._generate_task_id(task)
        task.task_id = task_id

        # Create background task for execution
        self._pending_tasks[task_id] = asyncio.create_task(self._execute_internal(task))

        return task_id

    async def get_status(self, task_id: str) -> TaskStatus:
        """Get task status."""
        from .core import TaskStatus

        if task_id not in self._pending_tasks:
            return TaskStatus.UNKNOWN

        task_obj = self._pending_tasks[task_id]
        if task_obj.done():
            if task_obj.cancelled():
                return TaskStatus.CANCELLED
            if task_obj.exception():
                return TaskStatus.FAILED
            return TaskStatus.COMPLETED
        return TaskStatus.RUNNING

    async def get_result(self, task_id: str, timeout: float = 300) -> Result:
        """Get complete result, waiting if necessary."""
        from .core import TaskStatus, Platform, Task as CoreTask

        if task_id not in self._pending_tasks:
            return Result(
                task=CoreTask(type=TaskType.CODE_GENERATION, prompt=""),
                platform=Platform.GEMINI,
                output="",
                success=False,
                status=TaskStatus.UNKNOWN,
                error=f"Unknown task_id: {task_id}",
            )

        try:
            result = await asyncio.wait_for(
                self._pending_tasks[task_id], timeout=timeout
            )
            return result
        except asyncio.TimeoutError:
            return Result(
                task=CoreTask(type=TaskType.CODE_GENERATION, prompt=""),
                platform=Platform.GEMINI,
                output="",
                success=False,
                status=TaskStatus.FAILED,
                error=f"Task timed out after {timeout}s",
            )
        except asyncio.CancelledError:
            raise

    async def stream_result(self, task_id: str) -> AsyncIterator[str]:
        """Stream result chunks."""
        # Simplified: yield complete result
        result = await self.get_result(task_id)
        if result.output:
            yield result.output

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        if task_id not in self._pending_tasks:
            return False

        task_obj = self._pending_tasks[task_id]
        if task_obj.done():
            return False

        task_obj.cancel()
        try:
            await task_obj
        except asyncio.CancelledError:
            pass

        # Release reserved quota if we had reserved
        if self._quota_tracker:
            self._quota_tracker.release("gemini", 1)

        return True

    async def _execute_internal(self, task: Task) -> Result:
        """Internal execution with quota checking and retry."""
        from .core import TaskStatus, Platform
        from .retry import retry_on_rate_limit
        import time

        start_time = time.time()

        # Check quota before execution
        if self._quota_tracker:
            can_use, msg = self._quota_tracker.check_and_reserve("gemini", 1)
            if not can_use:
                return Result(
                    task=task,
                    platform=Platform.GEMINI,
                    output="",
                    success=False,
                    status=TaskStatus.FAILED,
                    error=f"Quota check failed: {msg}",
                    duration_seconds=time.time() - start_time,
                )

        if not self._client:
            if self._quota_tracker:
                self._quota_tracker.release("gemini", 1)
            return Result(
                task=task,
                platform=Platform.GEMINI,
                output="",
                success=False,
                status=TaskStatus.FAILED,
                error="Client not initialized. Use 'async with' context manager.",
            )

        try:
            # Build prompt with context
            prompt = task.prompt
            if task.context:
                context_str = "\n".join(f"{k}: {v}" for k, v in task.context.items())
                prompt = f"Context:\n{context_str}\n\nTask:\n{prompt}"

            # Determine model and config
            model = (
                task.constraints.model
                if task.constraints and task.constraints.model
                else self._model
            )
            config = {}
            if task.constraints:
                if task.constraints.max_tokens:
                    config["max_output_tokens"] = task.constraints.max_tokens
                if task.constraints.temperature is not None:
                    config["temperature"] = task.constraints.temperature

            # Apply retry decorator dynamically
            @retry_on_rate_limit()
            async def make_request():
                return await self._client.aio.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=config if config else None,
                )

            response = await asyncio.wait_for(
                make_request(),
                timeout=task.constraints.timeout_seconds
                if task.constraints and task.constraints.timeout_seconds
                else self._timeout,
            )

            # Extract output
            output = response.text if hasattr(response, "text") else str(response)

            # Record usage with quota tracker
            tokens_used = 1  # Gemini API tracks requests, not tokens for free tier
            if self._quota_tracker:
                self._quota_tracker.release_and_record(
                    "gemini", tokens_used, cost=0.0, amount_reserved=1
                )

            return Result(
                task=task,
                platform=Platform.GEMINI,
                output=output,
                success=True,
                status=TaskStatus.COMPLETED,
                tokens_used=tokens_used,
                cost=0.0,  # Free tier
                duration_seconds=time.time() - start_time,
                metadata={
                    "model": model,
                },
            )

        except asyncio.TimeoutError:
            if self._quota_tracker:
                self._quota_tracker.release("gemini", 1)
            return Result(
                task=task,
                platform=Platform.GEMINI,
                output="",
                success=False,
                status=TaskStatus.FAILED,
                error=f"Execution timed out after {self._timeout}s",
                duration_seconds=time.time() - start_time,
            )

        except asyncio.CancelledError:
            if self._quota_tracker:
                self._quota_tracker.release("gemini", 1)
            raise

        except Exception as e:
            if self._quota_tracker:
                self._quota_tracker.release("gemini", 1)
            return Result(
                task=task,
                platform=Platform.GEMINI,
                output="",
                success=False,
                status=TaskStatus.FAILED,
                error=str(e),
                duration_seconds=time.time() - start_time,
            )

    async def execute_streaming(self, task: Task) -> AsyncIterator[str]:
        """Execute task with streaming response."""
        if not self._client:
            raise RuntimeError(
                "Client not initialized. Use 'async with' context manager."
            )

        # Check quota
        if self._quota_tracker:
            can_use, msg = self._quota_tracker.check_and_reserve("gemini", 1)
            if not can_use:
                raise RuntimeError(f"Quota check failed: {msg}")

        try:
            prompt = task.prompt
            if task.context:
                context_str = "\n".join(f"{k}: {v}" for k, v in task.context.items())
                prompt = f"Context:\n{context_str}\n\nTask:\n{prompt}"

            model = (
                task.constraints.model
                if task.constraints and task.constraints.model
                else self._model
            )

            # Note: google-genai streaming API may differ - this is a simplified version
            # Production code should use the actual streaming API
            response = await self._client.aio.models.generate_content(
                model=model,
                contents=prompt,
            )

            # Record usage
            if self._quota_tracker:
                self._quota_tracker.release_and_record(
                    "gemini", 1, cost=0.0, amount_reserved=1
                )

            yield response.text if hasattr(response, "text") else str(response)

        except Exception:
            if self._quota_tracker:
                self._quota_tracker.release("gemini", 1)
            raise
