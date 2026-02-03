"""
EMA Computation Orchestrator - Parallel execution with resilient error handling.

Encapsulates multiprocessing pattern for EMA refresh scripts:
- Worker pool management
- Connection limit error detection
- Graceful error handling (one worker failure doesn't crash the pool)
- Progress tracking

Usage:
    from ta_lab2.scripts.emas.ema_computation_orchestrator import (
        EMAComputationOrchestrator,
        WorkerTask,
    )

    def worker_fn(task: WorkerTask) -> int:
        # Compute EMAs for single ID
        return rows_written

    orchestrator = EMAComputationOrchestrator(
        worker_fn=worker_fn,
        num_processes=4,
        logger=logger,
    )

    tasks = [WorkerTask(id_=1, ...), WorkerTask(id_=52, ...)]
    results = orchestrator.execute(tasks)
    total_rows = sum(results)
"""

from __future__ import annotations

from dataclasses import dataclass
from multiprocessing import Pool, cpu_count
from typing import TypeVar, Callable, Sequence, Optional, Any
import logging


# =============================================================================
# Worker Task
# =============================================================================


@dataclass(frozen=True)
class WorkerTask:
    """
    Task for EMA computation worker.

    Encapsulates all parameters needed for a single worker to compute EMAs.

    Attributes:
        id_: Cryptocurrency ID to process
        db_url: Database URL (must include password, not masked)
        periods: List of EMA periods to compute
        start: Start timestamp for incremental refresh
        end: Optional end timestamp for date range filtering
        extra_config: Script-specific configuration (alignment_type, bars_table, etc.)
    """

    id_: int
    db_url: str
    periods: list[int]
    start: str
    end: Optional[str] = None
    extra_config: dict[str, Any] = None

    def __post_init__(self):
        if self.extra_config is None:
            object.__setattr__(self, "extra_config", {})


TTask = TypeVar("TTask")


# =============================================================================
# Orchestrator
# =============================================================================


class EMAComputationOrchestrator:
    """
    Orchestrator for parallel EMA computations.

    Handles:
    - Worker pool creation and disposal
    - Parallel execution with configurable process count
    - Resilient error handling (one worker failure doesn't crash pool)
    - Database connection limit detection
    - Progress tracking and result aggregation

    Example:
        orchestrator = EMAComputationOrchestrator(
            worker_fn=compute_ema_for_id,
            num_processes=4,
            logger=logger,
        )

        tasks = [WorkerTask(id_=1, ...), WorkerTask(id_=52, ...)]
        results = orchestrator.execute(tasks)
        total_rows = sum(results)

    Thread-safety: Safe to use from main thread only.
    """

    def __init__(
        self,
        worker_fn: Callable[[TTask], int],
        num_processes: Optional[int] = None,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize orchestrator.

        Args:
            worker_fn: Worker function that takes a task and returns row count.
                      Should be a module-level function (for pickling).
            num_processes: Number of parallel processes.
                          Default: min(cpu_count(), 4) to avoid connection exhaustion.
            logger: Logger for progress tracking. If None, uses default logger.
        """
        self.worker_fn = worker_fn
        self.num_processes = num_processes or min(cpu_count(), 4)
        self.logger = logger or logging.getLogger(__name__)

    def execute(self, tasks: Sequence[TTask]) -> list[int]:
        """
        Execute tasks in parallel using worker pool.

        Args:
            tasks: Sequence of tasks to execute

        Returns:
            List of row counts from each worker (0 if worker failed)

        Note:
            Worker failures are logged but don't raise exceptions.
            Check returned list for 0 values to detect failures.
        """
        if not tasks:
            self.logger.info("No tasks to execute")
            return []

        self.logger.info(
            f"Executing {len(tasks)} tasks with {self.num_processes} workers"
        )

        try:
            with Pool(processes=self.num_processes) as pool:
                results = pool.map(self._resilient_worker, tasks)

            self.logger.info(f"Completed {len(tasks)} tasks")
            return results

        except Exception as e:
            self.logger.error(f"Pool execution failed: {e}", exc_info=True)
            # Return zeros for all tasks if pool itself fails
            return [0] * len(tasks)

    def _resilient_worker(self, task: TTask) -> int:
        """
        Wrapper that handles worker exceptions gracefully.

        Prevents one worker failure from crashing the entire pool.
        Detects common database issues (connection limits, auth failures).

        Args:
            task: Task to execute

        Returns:
            Number of rows written, or 0 if worker failed
        """
        try:
            return self.worker_fn(task)

        except Exception as e:
            error_msg = str(e).lower()

            # Detect specific error types for better diagnostics
            if "too many clients" in error_msg or "max_connections" in error_msg:
                self.logger.error(
                    f"DATABASE CONNECTION LIMIT REACHED. "
                    f"Solutions: (1) Reduce --num-processes, "
                    f"(2) Increase Postgres max_connections. "
                    f"Error: {e}"
                )
            elif (
                "password authentication failed" in error_msg or "password" in error_msg
            ):
                self.logger.error(
                    f"DATABASE AUTHENTICATION FAILED. "
                    f"Check that db_url includes correct password. "
                    f"IMPORTANT: Use engine.url.render_as_string(hide_password=False) "
                    f"when passing URL to workers. "
                    f"Error: {e}"
                )
            else:
                self.logger.error(f"Worker failed: {e}", exc_info=True)

            return 0

    def __repr__(self) -> str:
        return f"EMAComputationOrchestrator(" f"num_processes={self.num_processes})"
