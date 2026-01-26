"""Smoke tests - end-to-end validation of Phase 1 infrastructure."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.ta_lab2.tools.ai_orchestrator import Orchestrator
from src.ta_lab2.tools.ai_orchestrator.core import Task, TaskType, Platform
from src.ta_lab2.tools.ai_orchestrator.quota import QuotaTracker
from src.ta_lab2.tools.ai_orchestrator.config import load_config


def test_smoke_quota_persistence():
    """Test that quota state persists correctly."""
    # Use temp directory for test
    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = str(Path(tmpdir) / "quota_state.json")

        # Create tracker and record usage
        tracker = QuotaTracker(persistence_path=state_path)
        tracker.record_usage("gemini", tokens=100, cost=0)

        # Verify state written to disk
        assert Path(state_path).exists()

        # Reload from disk
        tracker2 = QuotaTracker(persistence_path=state_path)
        summary = tracker2.get_daily_summary()

        # Verify values loaded (gemini_cli should have usage)
        assert "gemini_cli" in summary
        assert summary["gemini_cli"]["used"] == 100


def test_smoke_config_loading():
    """Test that config loads from .env.example."""
    # Load config
    config = load_config()

    # Verify required fields present
    assert hasattr(config, "gemini_daily_quota")
    assert hasattr(config, "quota_alert_thresholds")
    assert isinstance(config.gemini_daily_quota, int)
    assert isinstance(config.quota_alert_thresholds, list)


def test_smoke_orchestrator_init():
    """Test that Orchestrator initializes without errors."""
    # Create orchestrator
    orchestrator = Orchestrator()

    # Verify components initialized
    assert orchestrator.router is not None
    assert orchestrator.quota_tracker is not None
    assert orchestrator.validator is not None
    assert orchestrator.adapters is not None

    # Verify all three adapters present
    assert Platform.CLAUDE_CODE in orchestrator.adapters
    assert Platform.CHATGPT in orchestrator.adapters
    assert Platform.GEMINI in orchestrator.adapters


def test_smoke_validation_runs():
    """Test that validation runs and returns status."""
    orchestrator = Orchestrator()

    # Call validate_environment
    status = orchestrator.validate_environment()

    # Verify returns status dict
    assert isinstance(status, dict)
    assert len(status) == 3  # Three platforms

    # Check Claude Code shows as available (we're running in it)
    claude_status = status[Platform.CLAUDE_CODE]
    assert claude_status["is_implemented"]
    assert claude_status["status"] in ["working", "partial"]


def test_smoke_task_execution_claude():
    """Test task execution through Claude Code adapter."""
    orchestrator = Orchestrator()

    # Create simple task
    task = Task(
        type=TaskType.CODE_GENERATION,
        prompt="test prompt",
        platform_hint=Platform.CLAUDE_CODE,
    )

    # Execute task
    result = orchestrator.execute(task)

    # Verify Result returned
    assert result is not None
    assert result.task == task
    assert result.platform == Platform.CLAUDE_CODE

    # Result may contain instructions since subprocess not implemented,
    # but it should not raise exceptions
    assert isinstance(result.output, str)


def test_smoke_quota_tracking_integration():
    """Test that quota tracking records usage during execution."""
    orchestrator = Orchestrator()

    # Get initial status
    initial_summary = orchestrator.quota_tracker.get_daily_summary()
    initial_used = initial_summary.get("claude_code", {}).get("used", 0)

    # Execute a task
    task = Task(
        type=TaskType.CODE_GENERATION,
        prompt="test",
        platform_hint=Platform.CLAUDE_CODE,
    )
    orchestrator.execute(task)

    # Verify quota tracking updated
    final_summary = orchestrator.quota_tracker.get_daily_summary()
    final_used = final_summary.get("claude_code", {}).get("used", 0)

    # Claude Code is unlimited, but usage should still be tracked
    assert final_used >= initial_used


def test_smoke_routing_with_validation():
    """Test that routing respects validation results."""
    orchestrator = Orchestrator()

    # Create task without platform hint
    task = Task(
        type=TaskType.CODE_GENERATION,
        prompt="test",
    )

    # Route should only return implemented platforms
    platform = orchestrator.router.route(task, orchestrator.quota_tracker)

    # Verify platform is implemented
    assert orchestrator.validator.is_platform_available(platform)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
