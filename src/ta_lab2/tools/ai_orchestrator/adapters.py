"""Platform adapters for executing tasks on different AI systems."""

from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
from pathlib import Path
import shutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Task, Result, Platform

from .core import Result, Platform as Plat


class BasePlatformAdapter(ABC):
    """Base class for all platform adapters."""

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
                "Direct file access"
            ],
            "requirements": [
                "Running inside Claude Code session",
                "GSD installed for workflow tasks (optional)"
            ]
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
                metadata={"method": "gsd" if task.requires_gsd else "subprocess"}
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
                "Planned: Web UI automation (Selenium)"
            ],
            "requirements": [
                "OPENAI_API_KEY environment variable (for API mode)",
                "Selenium/ChromeDriver (for web automation)"
            ]
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
            metadata={"stub": True}
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
                "gcloud CLI execution (free quota)" if self._gcloud_available else "Planned: gcloud CLI",
                "Gemini 2.0 Flash model" if self._gcloud_available else "Planned: Gemini API"
            ],
            "requirements": [
                "gcloud CLI installed and configured" + (" (met)" if self._gcloud_available else " (missing)"),
                "Google Cloud project with Vertex AI enabled"
            ]
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
                metadata={"method": "cli" if self.prefer_cli else "api"}
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
                gcloud_executable, "ai", "models", "generate-content",
                "--model=gemini-2.0-flash-exp",
                f"--prompt={task.prompt}",
                "--format=json"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                raise RuntimeError(f"gcloud failed: {result.stderr}")

            return result.stdout

        except FileNotFoundError:
            raise RuntimeError("gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install")
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
