"""Core orchestrator classes and task definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from datetime import datetime


class TaskType(Enum):
    """Types of tasks that can be routed to AI platforms."""

    CODE_GENERATION = "code_generation"
    REFACTORING = "refactoring"
    RESEARCH = "research"
    DATA_ANALYSIS = "data_analysis"
    DOCUMENTATION = "documentation"
    CODE_REVIEW = "code_review"
    SQL_DB_WORK = "sql_db_work"
    TESTING = "testing"
    DEBUGGING = "debugging"
    PLANNING = "planning"


class Platform(Enum):
    """Available AI platforms."""

    CLAUDE_CODE = "claude_code"
    CHATGPT = "chatgpt"
    GEMINI = "gemini"


class TaskStatus(Enum):
    """Execution status for async task lifecycle."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


@dataclass
class TaskConstraints:
    """Execution constraints for tasks.

    Attributes:
        max_tokens: Token limit for task execution
        timeout_seconds: Maximum execution time (default 300s / 5 minutes)
        temperature: Model temperature for response randomness
        model: Specific model to use (platform-specific)
    """

    max_tokens: Optional[int] = None
    timeout_seconds: float = 300.0
    temperature: Optional[float] = None
    model: Optional[str] = None


@dataclass
class Task:
    """
    Represents a task to be executed by an AI platform.

    Attributes:
        type: Type of task (code_generation, research, etc.)
        prompt: The actual instruction/question for the AI
        context: Memory context, previous task outputs, additional data
        platform_hint: Optional hint for which platform to use
        priority: Task priority (0=highest, 10=lowest)
        requires_gsd: Whether this task needs GSD workflow
        metadata: Additional task-specific data
        created_at: When task was created
        files: File paths for Claude Code operations or file attachments
        constraints: Execution constraints (tokens, timeout, temperature, model)
        task_id: Unique identifier assigned when submitted (UUID format)
    """

    type: TaskType
    prompt: str
    context: dict[str, Any] = field(default_factory=dict)
    platform_hint: Optional[Platform] = None
    priority: int = 5
    requires_gsd: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    files: list[str] = field(default_factory=list)
    constraints: Optional[TaskConstraints] = None
    task_id: Optional[str] = None


@dataclass
class Result:
    """
    Result from executing a task on an AI platform.

    Attributes:
        task: The original task
        platform: Which platform executed it
        output: The AI's response/output
        success: Whether the task completed successfully
        error: Error message if failed
        cost: Estimated cost in USD (0 for free tier)
        tokens_used: Approximate tokens consumed
        duration_seconds: How long the task took
        metadata: Platform-specific result data
        completed_at: When task execution finished
        status: Execution state (for async lifecycle)
        files_created: Output files generated during execution
        partial_output: Partial results for streaming or cancellation
    """

    task: Task
    platform: Platform
    output: str
    success: bool
    error: Optional[str] = None
    cost: float = 0.0
    tokens_used: int = 0
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    completed_at: datetime = field(default_factory=datetime.utcnow)
    status: TaskStatus = TaskStatus.COMPLETED
    files_created: list[str] = field(default_factory=list)
    partial_output: Optional[str] = None


class Orchestrator:
    """
    Main orchestrator that routes tasks to optimal AI platforms.

    Manages:
    - Task routing based on type and platform strengths
    - Quota tracking for free tiers
    - Cost optimization
    - Parallel execution
    - GSD workflow integration
    """

    def __init__(self):
        from .routing import TaskRouter
        from .quota import QuotaTracker
        from .adapters import ClaudeCodeAdapter, ChatGPTAdapter, GeminiAdapter
        from .validation import AdapterValidator

        self.quota_tracker = QuotaTracker()
        self.adapters = {
            Platform.CLAUDE_CODE: ClaudeCodeAdapter(),
            Platform.CHATGPT: ChatGPTAdapter(),
            Platform.GEMINI: GeminiAdapter(),
        }
        self.validator = AdapterValidator(self.adapters)
        self.router = TaskRouter(validator=self.validator)

    def execute(self, task: Task, pre_flight: bool = True) -> Result:
        """
        Execute a single task on the optimal platform.

        Args:
            task: Task to execute
            pre_flight: If True, run pre-flight validation (SECOND CHECKPOINT)

        Returns:
            Result object with output and metadata
        """
        # SECOND CHECKPOINT: Pre-flight safety check
        if pre_flight:
            from .validation import pre_flight_check

            can_execute, reason = pre_flight_check(task, self.validator)
            if not can_execute:
                available = self.validator.get_available_platforms()
                return Result(
                    task=task,
                    platform=Platform.CLAUDE_CODE,  # Placeholder
                    output="",
                    success=False,
                    error=f"Cannot execute: {reason}. Available platforms: {[p.value for p in available]}",
                )

        # Route to best platform (FIRST CHECKPOINT already applied in router)
        platform = self.router.route(task, self.quota_tracker)

        # Execute on chosen platform
        adapter = self.adapters[platform]
        result = adapter.execute(task)

        # Update quota tracking
        self.quota_tracker.record_usage(
            platform=platform.value, tokens=result.tokens_used, cost=result.cost
        )

        return result

    def execute_parallel(self, tasks: list[Task]) -> list[Result]:
        """
        Execute multiple tasks in parallel across all platforms.

        Args:
            tasks: List of tasks to execute

        Returns:
            List of results in same order as tasks
        """
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=len(Platform)) as executor:
            futures = [executor.submit(self.execute, task) for task in tasks]
            results = [f.result() for f in futures]

        return results

    def execute_gsd_workflow(
        self, workflow: str, steps: list[str], interactive: bool = False
    ) -> Result:
        """
        Execute a GSD workflow through Claude Code.

        Args:
            workflow: Name of workflow (new-feature, refactor, debug, etc.)
            steps: List of GSD commands to execute in sequence
            interactive: If True, wait for user confirmation between steps

        Returns:
            Consolidated result from all workflow steps
        """
        adapter = self.adapters[Platform.CLAUDE_CODE]

        # Build task with GSD commands
        task = Task(
            type=TaskType.PLANNING,
            prompt=f"Execute GSD workflow: {workflow}",
            requires_gsd=True,
            metadata={
                "workflow": workflow,
                "steps": steps,
                "interactive": interactive,
            },
        )

        return adapter.execute(task)

    def execute_batch(
        self, tasks: list[Task], optimize_cost: bool = True, max_parallel: int = 10
    ) -> list[Result]:
        """
        Execute a batch of tasks with cost optimization.

        Args:
            tasks: Tasks to execute
            optimize_cost: If True, prefer free tiers
            max_parallel: Max concurrent tasks

        Returns:
            List of results
        """
        # Sort by priority (lower number = higher priority)
        sorted_tasks = sorted(tasks, key=lambda t: t.priority)

        # Execute in chunks to respect max_parallel
        results = []
        for i in range(0, len(sorted_tasks), max_parallel):
            chunk = sorted_tasks[i : i + max_parallel]
            chunk_results = self.execute_parallel(chunk)
            results.extend(chunk_results)

        return results

    def validate_environment(self) -> dict[Platform, dict]:
        """
        Validate all adapters and return status.

        Useful for CLI status display and debugging.

        Returns:
            Dict mapping Platform to validation status dict
        """
        validation_results = self.validator.validate_all()
        return {
            platform: {
                "name": result.adapter_name,
                "is_valid": result.is_valid,
                "is_implemented": result.is_implemented,
                "status": result.status,
                "message": result.message,
                "requirements_met": result.requirements_met,
            }
            for platform, result in validation_results.items()
        }
