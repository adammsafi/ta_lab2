# -*- coding: utf-8 -*-
"""
Generic multiprocessing orchestrator for ETL/builder tasks.

Extracts the common multiprocessing pattern used across all bar builders:
1. Prepare tasks (with state map optimization)
2. Execute worker function in parallel pool
3. Aggregate results (state updates + stats)
4. Handle errors gracefully
5. Support serial fallback

Usage:
    from ta_lab2.orchestration import MultiprocessingOrchestrator, OrchestratorConfig

    config = OrchestratorConfig(num_processes=6, maxtasksperchild=50)
    orchestrator = MultiprocessingOrchestrator(
        worker_fn=my_worker_function,
        config=config,
    )

    state_updates, stats = orchestrator.execute(tasks, stats_template={"upserted": 0, "errors": 0})
"""

from __future__ import annotations
from typing import Sequence, Callable, Generic
from multiprocessing import Pool, cpu_count
import traceback

from .types import (
    TTask,
    TStateUpdate,
    TStats,
    OrchestratorConfig,
    WorkerFunction,
    ProgressCallback,
)


class MultiprocessingOrchestrator(Generic[TTask, TStateUpdate, TStats]):
    """
    Generic orchestrator for ETL tasks with multiprocessing.

    Handles:
    - Task preparation (state map filtering by ID)
    - Parallel/serial execution with Pool management
    - Result aggregation (state_updates + stats)
    - Error resilience (workers don't crash pool)
    - Progress tracking

    Type Parameters:
    - TTask: Input task type (e.g., tuple of worker args)
    - TStateUpdate: State update record type (e.g., dict)
    - TStats: Stats dictionary type (e.g., dict[str, int])

    Example:
        >>> def my_worker(task):
        ...     id_, data = task
        ...     # Process data...
        ...     return ([{"id": id_, "result": "done"}], {"upserted": 1, "errors": 0})
        ...
        >>> orchestrator = MultiprocessingOrchestrator(my_worker)
        >>> tasks = [(1, "data1"), (2, "data2")]
        >>> state_updates, stats = orchestrator.execute(tasks)
    """

    def __init__(
        self,
        worker_fn: WorkerFunction[TTask, TStateUpdate, TStats],
        config: OrchestratorConfig | None = None,
        progress_callback: ProgressCallback | None = None,
    ):
        """
        Initialize orchestrator.

        Args:
            worker_fn: Function that processes a single task
            config: Orchestrator configuration (defaults to OrchestratorConfig())
            progress_callback: Optional callback for progress updates
        """
        self.worker_fn = worker_fn
        self.config = config or OrchestratorConfig()
        self.progress_callback = progress_callback

    def execute(
        self,
        tasks: Sequence[TTask],
        *,
        stats_template: TStats | None = None,
        serial_mode: bool = False,
    ) -> tuple[list[TStateUpdate], TStats]:
        """
        Execute tasks in parallel (or serial fallback).

        Args:
            tasks: Sequence of tasks to process
            stats_template: Template for stats accumulation (dict keys)
            serial_mode: Force serial execution (for debugging)

        Returns:
            Tuple of (all_state_updates, aggregated_stats)

        Example:
            >>> orchestrator = MultiprocessingOrchestrator(my_worker)
            >>> tasks = [(1, "data"), (2, "data")]
            >>> state_updates, stats = orchestrator.execute(
            ...     tasks,
            ...     stats_template={"upserted": 0, "errors": 0}
            ... )
            >>> print(f"Upserted: {stats['upserted']}, Errors: {stats['errors']}")
        """
        if not tasks:
            return ([], self._init_stats(stats_template))

        num_processes = self._resolve_num_processes()

        if serial_mode or num_processes <= 1:
            return self._execute_serial(tasks, stats_template)
        else:
            return self._execute_parallel(tasks, num_processes, stats_template)

    def _resolve_num_processes(self) -> int:
        """Resolve worker count with sane defaults."""
        n = self.config.num_processes
        if n is None:
            n = self.config.default_processes
        n = max(1, int(n))
        n = min(n, cpu_count() or 1)
        return n

    def _execute_serial(
        self,
        tasks: Sequence[TTask],
        stats_template: TStats | None,
    ) -> tuple[list[TStateUpdate], TStats]:
        """Serial execution fallback (useful for debugging)."""
        all_state_updates: list[TStateUpdate] = []
        totals = self._init_stats(stats_template)

        for i, task in enumerate(tasks):
            try:
                state_updates, stats = self.worker_fn(task)
                all_state_updates.extend(state_updates)
                self._accumulate_stats(totals, stats)

                if self.progress_callback:
                    self.progress_callback(i + 1, len(tasks), totals)
            except Exception as e:
                print(f"[Orchestrator] ERROR in serial execution: {e}")
                traceback.print_exc()
                # Increment error count if stats support it
                if isinstance(totals, dict) and "errors" in totals:
                    totals["errors"] += 1

        return (all_state_updates, totals)

    def _execute_parallel(
        self,
        tasks: Sequence[TTask],
        num_processes: int,
        stats_template: TStats | None,
    ) -> tuple[list[TStateUpdate], TStats]:
        """Parallel execution with Pool."""
        all_state_updates: list[TStateUpdate] = []
        totals = self._init_stats(stats_template)

        with Pool(processes=num_processes, maxtasksperchild=self.config.maxtasksperchild) as pool:
            if self.config.use_imap_unordered:
                # Streaming results (good for long-running tasks)
                completed = 0
                for state_updates, stats in pool.imap_unordered(self.worker_fn, tasks):
                    all_state_updates.extend(state_updates)
                    self._accumulate_stats(totals, stats)
                    completed += 1
                    if self.progress_callback:
                        self.progress_callback(completed, len(tasks), totals)
            else:
                # Batch results (simpler, good for fast tasks)
                results = pool.map(self.worker_fn, tasks)
                for state_updates, stats in results:
                    all_state_updates.extend(state_updates)
                    self._accumulate_stats(totals, stats)

        return (all_state_updates, totals)

    def _init_stats(self, template: TStats | None) -> TStats:
        """Initialize stats accumulator from template."""
        if template is None:
            return {}  # type: ignore
        if isinstance(template, dict):
            return {k: 0 for k in template.keys()}  # type: ignore
        return template

    def _accumulate_stats(self, totals: TStats, stats: TStats) -> None:
        """Accumulate stats (assumes dict-like interface)."""
        if isinstance(totals, dict) and isinstance(stats, dict):
            for k in totals.keys():
                totals[k] += stats.get(k, 0)


def create_resilient_worker(
    inner_worker: Callable[[TTask], tuple[list[TStateUpdate], TStats]],
    stats_template: dict,
    error_logger: Callable[[str, Exception], None] | None = None,
) -> Callable[[TTask], tuple[list[TStateUpdate], TStats]]:
    """
    Wrap a worker function with exception handling.

    Ensures that worker failures don't crash the pool, and
    preserves partial state on error.

    Args:
        inner_worker: The actual worker function
        stats_template: Template stats dict (for error case)
        error_logger: Optional error logging function

    Returns:
        Wrapped worker that never raises

    Example:
        >>> def my_worker(task):
        ...     # May raise exceptions
        ...     return process(task)
        ...
        >>> safe_worker = create_resilient_worker(
        ...     my_worker,
        ...     stats_template={"upserted": 0, "errors": 0},
        ... )
        >>> orchestrator = MultiprocessingOrchestrator(safe_worker)
    """

    def resilient_worker(task: TTask) -> tuple[list[TStateUpdate], TStats]:
        try:
            return inner_worker(task)
        except Exception as e:
            # Log error
            if error_logger:
                error_logger(f"Worker failed for task: {task}", e)
            else:
                print(f"[ERROR] Worker failed: {e}")
                traceback.print_exc()

            # Return empty results with error flag
            empty_state: list[TStateUpdate] = []
            error_stats = {k: 0 for k in stats_template.keys()}
            error_stats["errors"] = 1

            return (empty_state, error_stats)  # type: ignore

    return resilient_worker


class ProgressTracker:
    """
    Track and display progress during parallel execution.

    Example:
        >>> progress = ProgressTracker(total=100, log_interval=10)
        >>> orchestrator = MultiprocessingOrchestrator(
        ...     worker_fn=my_worker,
        ...     progress_callback=progress.update,
        ... )
    """

    def __init__(self, total: int, log_interval: int = 10, prefix: str = "[Progress]"):
        """
        Initialize progress tracker.

        Args:
            total: Total number of tasks
            log_interval: Log every N completions
            prefix: Log message prefix
        """
        self.total = total
        self.log_interval = log_interval
        self.prefix = prefix
        self.completed = 0
        self.last_log = 0

        import time

        self.start_time = time.time()

    def update(self, completed: int, total: int, stats: dict) -> None:
        """Progress callback (called by orchestrator)."""
        import time

        self.completed = completed
        elapsed = time.time() - self.start_time

        # Log every N completions
        if completed - self.last_log >= self.log_interval or completed == total:
            pct = (completed / total) * 100 if total > 0 else 0
            rate = completed / elapsed if elapsed > 0 else 0
            eta = (total - completed) / rate if rate > 0 else 0

            print(
                f"{self.prefix} {completed}/{total} ({pct:.1f}%) | "
                f"Rate: {rate:.1f}/s | ETA: {eta:.0f}s | "
                f"Stats: {self._format_stats(stats)}"
            )
            self.last_log = completed

    def _format_stats(self, stats: dict) -> str:
        """Format stats for display."""
        return ", ".join(f"{k}={v:,}" for k, v in stats.items())
