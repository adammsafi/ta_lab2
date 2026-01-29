# -*- coding: utf-8 -*-
"""
Type definitions and protocols for multiprocessing orchestration.

Provides generic type support for the MultiprocessingOrchestrator.
"""

from __future__ import annotations
from typing import Protocol, TypeVar, runtime_checkable
from dataclasses import dataclass

# Generic type variables for orchestrator
TTask = TypeVar("TTask")
TStateUpdate = TypeVar("TStateUpdate")
TStats = TypeVar("TStats")


@dataclass
class OrchestratorConfig:
    """Configuration for the MultiprocessingOrchestrator."""

    num_processes: int | None = None  # None = auto-detect
    default_processes: int = 6
    maxtasksperchild: int = 50
    use_imap_unordered: bool = False  # If True, stream results with imap_unordered

    def __post_init__(self):
        """Validate configuration."""
        if self.default_processes <= 0:
            raise ValueError("default_processes must be > 0")
        if self.maxtasksperchild <= 0:
            raise ValueError("maxtasksperchild must be > 0")


@runtime_checkable
class WorkerFunction(Protocol[TTask, TStateUpdate, TStats]):
    """Protocol for worker function signature."""

    def __call__(self, task: TTask) -> tuple[list[TStateUpdate], TStats]:
        """
        Process a single task.

        Args:
            task: Task to process (typically a tuple of arguments)

        Returns:
            Tuple of (state_updates, stats) where:
            - state_updates: List of state records to upsert
            - stats: Dictionary of statistics (e.g., {"upserted": 10, "errors": 0})
        """
        ...


@runtime_checkable
class ProgressCallback(Protocol):
    """Protocol for progress callback during execution."""

    def __call__(self, completed: int, total: int, stats: dict) -> None:
        """
        Called after each task completes (or batch of tasks).

        Args:
            completed: Number of tasks completed so far
            total: Total number of tasks
            stats: Aggregated statistics so far
        """
        ...
