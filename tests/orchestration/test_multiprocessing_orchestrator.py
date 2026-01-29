# -*- coding: utf-8 -*-
"""
Unit tests for MultiprocessingOrchestrator.

Tests cover:
- Serial execution mode
- Parallel execution mode
- Error handling with resilient worker
- Result aggregation
- Stats accumulation
- Progress tracking
"""

import pytest
from typing import List, Dict
from ta_lab2.orchestration import (
    MultiprocessingOrchestrator,
    OrchestratorConfig,
    create_resilient_worker,
    ProgressTracker,
)


# Test fixtures and workers
def simple_worker(task: tuple[int, str]) -> tuple[List[Dict], Dict[str, int]]:
    """Simple worker that processes (id, data) tuples."""
    task_id, data = task
    state_update = {"id": task_id, "result": data.upper()}
    stats = {"upserted": 1, "errors": 0}
    return ([state_update], stats)


def failing_worker(task: tuple[int, str]) -> tuple[List[Dict], Dict[str, int]]:
    """Worker that always fails."""
    raise ValueError("Intentional failure")


def error_prone_worker(task: tuple[int, str]) -> tuple[List[Dict], Dict[str, int]]:
    """Worker that fails for specific IDs."""
    task_id, data = task
    if task_id == 2:
        raise ValueError(f"Task {task_id} failed")

    state_update = {"id": task_id, "result": data.upper()}
    stats = {"upserted": 1, "errors": 0}
    return ([state_update], stats)


class TestOrchestratorConfig:
    """Test OrchestratorConfig validation."""

    def test_default_config(self):
        """Test default configuration values."""
        config = OrchestratorConfig()
        assert config.num_processes is None
        assert config.default_processes == 6
        assert config.maxtasksperchild == 50
        assert config.use_imap_unordered is False

    def test_custom_config(self):
        """Test custom configuration."""
        config = OrchestratorConfig(
            num_processes=4,
            default_processes=8,
            maxtasksperchild=100,
            use_imap_unordered=True,
        )
        assert config.num_processes == 4
        assert config.default_processes == 8
        assert config.maxtasksperchild == 100
        assert config.use_imap_unordered is True

    def test_invalid_default_processes(self):
        """Test that invalid default_processes raises error."""
        with pytest.raises(ValueError, match="default_processes must be > 0"):
            OrchestratorConfig(default_processes=0)

    def test_invalid_maxtasksperchild(self):
        """Test that invalid maxtasksperchild raises error."""
        with pytest.raises(ValueError, match="maxtasksperchild must be > 0"):
            OrchestratorConfig(maxtasksperchild=-1)


class TestMultiprocessingOrchestrator:
    """Test MultiprocessingOrchestrator execution."""

    def test_serial_execution(self):
        """Test serial execution mode."""
        orchestrator = MultiprocessingOrchestrator(
            worker_fn=simple_worker,
            config=OrchestratorConfig(num_processes=1),
        )

        tasks = [(1, "hello"), (2, "world"), (3, "test")]
        stats_template = {"upserted": 0, "errors": 0}

        state_updates, stats = orchestrator.execute(
            tasks,
            stats_template=stats_template,
            serial_mode=True,
        )

        assert len(state_updates) == 3
        assert stats["upserted"] == 3
        assert stats["errors"] == 0
        assert state_updates[0]["result"] == "HELLO"
        assert state_updates[1]["result"] == "WORLD"
        assert state_updates[2]["result"] == "TEST"

    def test_parallel_execution(self):
        """Test parallel execution mode."""
        orchestrator = MultiprocessingOrchestrator(
            worker_fn=simple_worker,
            config=OrchestratorConfig(num_processes=2, maxtasksperchild=10),
        )

        tasks = [(i, f"task{i}") for i in range(10)]
        stats_template = {"upserted": 0, "errors": 0}

        state_updates, stats = orchestrator.execute(
            tasks,
            stats_template=stats_template,
        )

        assert len(state_updates) == 10
        assert stats["upserted"] == 10
        assert stats["errors"] == 0

        # Verify all tasks processed
        ids = sorted([u["id"] for u in state_updates])
        assert ids == list(range(10))

    def test_empty_tasks(self):
        """Test execution with empty task list."""
        orchestrator = MultiprocessingOrchestrator(worker_fn=simple_worker)

        state_updates, stats = orchestrator.execute(
            [],
            stats_template={"upserted": 0, "errors": 0},
        )

        assert state_updates == []
        assert stats == {"upserted": 0, "errors": 0}

    def test_stats_accumulation(self):
        """Test that stats are accumulated correctly."""
        def multi_stats_worker(task: int) -> tuple[List[Dict], Dict[str, int]]:
            return (
                [{"id": task}],
                {"upserted": task, "updated": task * 2, "deleted": 1}
            )

        orchestrator = MultiprocessingOrchestrator(worker_fn=multi_stats_worker)

        tasks = [1, 2, 3]
        stats_template = {"upserted": 0, "updated": 0, "deleted": 0}

        state_updates, stats = orchestrator.execute(
            tasks,
            stats_template=stats_template,
            serial_mode=True,
        )

        assert stats["upserted"] == 6  # 1 + 2 + 3
        assert stats["updated"] == 12  # 2 + 4 + 6
        assert stats["deleted"] == 3   # 1 + 1 + 1

    def test_multiple_state_updates_per_task(self):
        """Test worker returning multiple state updates."""
        def multi_update_worker(task: int) -> tuple[List[Dict], Dict[str, int]]:
            updates = [{"id": task, "seq": i} for i in range(3)]
            return (updates, {"upserted": 3, "errors": 0})

        orchestrator = MultiprocessingOrchestrator(worker_fn=multi_update_worker)

        tasks = [1, 2]
        state_updates, stats = orchestrator.execute(
            tasks,
            stats_template={"upserted": 0, "errors": 0},
            serial_mode=True,
        )

        assert len(state_updates) == 6  # 3 updates × 2 tasks
        assert stats["upserted"] == 6

    def test_progress_callback(self):
        """Test progress callback is called correctly."""
        progress_calls = []

        def progress_callback(completed: int, total: int, stats: dict):
            progress_calls.append((completed, total, stats.copy()))

        orchestrator = MultiprocessingOrchestrator(
            worker_fn=simple_worker,
            progress_callback=progress_callback,
        )

        tasks = [(i, f"task{i}") for i in range(3)]
        orchestrator.execute(
            tasks,
            stats_template={"upserted": 0, "errors": 0},
            serial_mode=True,
        )

        # Should have 3 progress updates
        assert len(progress_calls) == 3
        assert progress_calls[0] == (1, 3, {"upserted": 1, "errors": 0})
        assert progress_calls[1] == (2, 3, {"upserted": 2, "errors": 0})
        assert progress_calls[2] == (3, 3, {"upserted": 3, "errors": 0})


class TestResilientWorker:
    """Test create_resilient_worker error handling."""

    def test_resilient_worker_handles_exceptions(self):
        """Test that resilient worker catches exceptions."""
        stats_template = {"upserted": 0, "errors": 0}
        safe_worker = create_resilient_worker(
            failing_worker,
            stats_template,
        )

        result = safe_worker((1, "test"))
        state_updates, stats = result

        assert state_updates == []
        assert stats["upserted"] == 0
        assert stats["errors"] == 1

    def test_resilient_worker_partial_failures(self):
        """Test orchestrator with resilient worker handles partial failures."""
        stats_template = {"upserted": 0, "errors": 0}
        safe_worker = create_resilient_worker(
            error_prone_worker,
            stats_template,
        )

        orchestrator = MultiprocessingOrchestrator(worker_fn=safe_worker)

        tasks = [(1, "task1"), (2, "task2"), (3, "task3")]
        state_updates, stats = orchestrator.execute(
            tasks,
            stats_template=stats_template,
            serial_mode=True,
        )

        # Task 2 failed, tasks 1 and 3 succeeded
        assert len(state_updates) == 2
        assert stats["upserted"] == 2
        assert stats["errors"] == 1

        # Verify correct tasks succeeded
        ids = sorted([u["id"] for u in state_updates])
        assert ids == [1, 3]

    def test_resilient_worker_with_custom_error_logger(self):
        """Test resilient worker with custom error logger."""
        error_logs = []

        def error_logger(msg: str, exc: Exception):
            error_logs.append((msg, str(exc)))

        stats_template = {"upserted": 0, "errors": 0}
        safe_worker = create_resilient_worker(
            failing_worker,
            stats_template,
            error_logger=error_logger,
        )

        safe_worker((1, "test"))

        assert len(error_logs) == 1
        assert "Worker failed for task: (1, 'test')" in error_logs[0][0]
        assert "Intentional failure" in error_logs[0][1]


class TestProgressTracker:
    """Test ProgressTracker functionality."""

    def test_progress_tracker_initialization(self):
        """Test ProgressTracker initialization."""
        tracker = ProgressTracker(total=100, log_interval=10, prefix="[Test]")
        assert tracker.total == 100
        assert tracker.log_interval == 10
        assert tracker.prefix == "[Test]"
        assert tracker.completed == 0

    def test_progress_tracker_update(self, capsys):
        """Test ProgressTracker logs at correct intervals."""
        tracker = ProgressTracker(total=100, log_interval=25)

        # Should not log (below interval)
        tracker.update(10, 100, {"upserted": 10, "errors": 0})
        captured = capsys.readouterr()
        assert captured.out == ""

        # Should log (at interval)
        tracker.update(25, 100, {"upserted": 25, "errors": 0})
        captured = capsys.readouterr()
        assert "[Progress] 25/100" in captured.out
        assert "25.0%" in captured.out
        assert "upserted=25" in captured.out

        # Should log (completion)
        tracker.update(100, 100, {"upserted": 100, "errors": 5})
        captured = capsys.readouterr()
        assert "[Progress] 100/100" in captured.out
        assert "100.0%" in captured.out
        assert "upserted=100" in captured.out
        assert "errors=5" in captured.out

    def test_progress_tracker_with_orchestrator(self, capsys):
        """Test ProgressTracker integration with orchestrator."""
        tracker = ProgressTracker(total=5, log_interval=2, prefix="[Integration]")

        orchestrator = MultiprocessingOrchestrator(
            worker_fn=simple_worker,
            progress_callback=tracker.update,
        )

        tasks = [(i, f"task{i}") for i in range(5)]
        orchestrator.execute(
            tasks,
            stats_template={"upserted": 0, "errors": 0},
            serial_mode=True,
        )

        captured = capsys.readouterr()
        # Should log at 2, 4, and 5 (completion)
        assert captured.out.count("[Integration]") == 3
        assert "5/5 (100.0%)" in captured.out


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_single_task(self):
        """Test execution with single task."""
        orchestrator = MultiprocessingOrchestrator(worker_fn=simple_worker)

        state_updates, stats = orchestrator.execute(
            [(1, "single")],
            stats_template={"upserted": 0, "errors": 0},
            serial_mode=True,
        )

        assert len(state_updates) == 1
        assert stats["upserted"] == 1

    def test_auto_detect_num_processes(self):
        """Test that num_processes=None auto-detects CPU count."""
        orchestrator = MultiprocessingOrchestrator(
            worker_fn=simple_worker,
            config=OrchestratorConfig(num_processes=None),
        )

        num_processes = orchestrator._resolve_num_processes()
        assert num_processes >= 1  # Should be at least 1
        assert num_processes <= orchestrator.config.default_processes

    def test_force_serial_with_parallel_config(self):
        """Test that serial_mode=True overrides parallel config."""
        orchestrator = MultiprocessingOrchestrator(
            worker_fn=simple_worker,
            config=OrchestratorConfig(num_processes=8),
        )

        tasks = [(i, f"task{i}") for i in range(5)]
        state_updates, stats = orchestrator.execute(
            tasks,
            stats_template={"upserted": 0, "errors": 0},
            serial_mode=True,  # Force serial despite parallel config
        )

        assert len(state_updates) == 5
        assert stats["upserted"] == 5

    def test_worker_returning_empty_state_updates(self):
        """Test worker that returns empty state updates."""
        def empty_worker(task: int) -> tuple[List[Dict], Dict[str, int]]:
            return ([], {"upserted": 0, "errors": 0})

        orchestrator = MultiprocessingOrchestrator(worker_fn=empty_worker)

        state_updates, stats = orchestrator.execute(
            [1, 2, 3],
            stats_template={"upserted": 0, "errors": 0},
            serial_mode=True,
        )

        assert state_updates == []
        assert stats["upserted"] == 0

    def test_no_stats_template(self):
        """Test execution without stats template."""
        orchestrator = MultiprocessingOrchestrator(worker_fn=simple_worker)

        state_updates, stats = orchestrator.execute(
            [(1, "test")],
            serial_mode=True,
        )

        assert len(state_updates) == 1
        assert stats == {}  # Empty dict when no template
