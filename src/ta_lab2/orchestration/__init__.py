# -*- coding: utf-8 -*-
"""
Multiprocessing orchestration utilities.

Provides generic orchestration for ETL/builder tasks with:
- Parallel/serial execution
- Result aggregation
- Error resilience
- Progress tracking

Usage:
    from ta_lab2.orchestration import (
        MultiprocessingOrchestrator,
        OrchestratorConfig,
        ProgressTracker,
        create_resilient_worker,
    )

    # Configure orchestrator
    config = OrchestratorConfig(num_processes=6, maxtasksperchild=50)
    progress = ProgressTracker(total=len(tasks))

    # Create orchestrator
    orchestrator = MultiprocessingOrchestrator(
        worker_fn=my_worker_function,
        config=config,
        progress_callback=progress.update,
    )

    # Execute tasks
    state_updates, stats = orchestrator.execute(
        tasks,
        stats_template={"upserted": 0, "errors": 0}
    )
"""

from .multiprocessing_orchestrator import (
    MultiprocessingOrchestrator,
    create_resilient_worker,
    ProgressTracker,
)
from .types import (
    OrchestratorConfig,
    WorkerFunction,
    ProgressCallback,
)

__all__ = [
    "MultiprocessingOrchestrator",
    "OrchestratorConfig",
    "ProgressTracker",
    "create_resilient_worker",
    "WorkerFunction",
    "ProgressCallback",
]
