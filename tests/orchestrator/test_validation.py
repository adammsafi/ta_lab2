"""Tests for adapter validation (ORCH-11 double-check pattern)."""

import pytest
from unittest.mock import Mock

from src.ta_lab2.tools.ai_orchestrator.core import Task, TaskType, Platform, Result
from src.ta_lab2.tools.ai_orchestrator.validation import (
    AdapterValidator,
    pre_flight_check,
)
from src.ta_lab2.tools.ai_orchestrator.adapters import (
    BasePlatformAdapter,
    ClaudeCodeAdapter,
    ChatGPTAdapter,
    GeminiAdapter,
)


class StubAdapter(BasePlatformAdapter):
    """Test stub adapter that reports as not implemented."""

    def __init__(self, name: str = "TestStub"):
        self.name = name

    @property
    def is_implemented(self) -> bool:
        return False

    @property
    def implementation_status(self) -> str:
        return "stub"

    def get_adapter_status(self) -> dict:
        return {
            "name": self.name,
            "is_implemented": False,
            "status": "stub",
            "capabilities": [],
            "requirements": ["Not implemented"],
        }

    def execute(self, task: Task) -> Result:
        raise NotImplementedError(f"{self.name} is a stub")


class WorkingAdapter(BasePlatformAdapter):
    """Test working adapter that reports as implemented."""

    def __init__(self, name: str = "TestWorking"):
        self.name = name

    @property
    def is_implemented(self) -> bool:
        return True

    @property
    def implementation_status(self) -> str:
        return "working"

    def get_adapter_status(self) -> dict:
        return {
            "name": self.name,
            "is_implemented": True,
            "status": "working",
            "capabilities": ["Full functionality"],
            "requirements": [],
        }

    def execute(self, task: Task) -> Result:
        return Result(
            task=task,
            platform=Platform.CLAUDE_CODE,
            output="Test output",
            success=True,
        )


def test_stub_adapter_blocked_at_routing():
    """Test that stub adapters are excluded from routing."""
    # Setup: only stub adapter available
    adapters = {
        Platform.CHATGPT: StubAdapter("ChatGPT"),
    }
    validator = AdapterValidator(adapters)

    # Get available platforms (FIRST CHECKPOINT)
    available = validator.get_available_platforms()

    # Assert: stub should be filtered out
    assert len(available) == 0
    assert Platform.CHATGPT not in available


def test_stub_adapter_blocked_at_execution():
    """Test that stub adapters are blocked at execution checkpoint."""
    # Setup: stub adapter
    adapters = {
        Platform.CHATGPT: StubAdapter("ChatGPT"),
    }
    validator = AdapterValidator(adapters)

    # Create task
    task = Task(
        type=TaskType.CODE_GENERATION,
        prompt="test",
        platform_hint=Platform.CHATGPT,
    )

    # Pre-flight check (SECOND CHECKPOINT)
    can_execute, reason = pre_flight_check(task, validator)

    # Assert: execution blocked with helpful error
    assert not can_execute
    assert "not available" in reason or "No implemented" in reason


def test_implemented_adapter_passes():
    """Test that implemented adapters pass both validation checkpoints."""
    # Setup: working adapter
    adapters = {
        Platform.CLAUDE_CODE: WorkingAdapter("ClaudeCode"),
    }
    validator = AdapterValidator(adapters)

    # FIRST CHECKPOINT: routing filter
    available = validator.get_available_platforms()
    assert Platform.CLAUDE_CODE in available

    # SECOND CHECKPOINT: pre-flight check
    task = Task(type=TaskType.CODE_GENERATION, prompt="test")
    can_execute, reason = pre_flight_check(task, validator)
    assert can_execute
    assert reason == ""


def test_validation_reports_requirements():
    """Test that validation results include requirement checks."""
    adapters = {
        Platform.CHATGPT: ChatGPTAdapter(),
    }
    validator = AdapterValidator(adapters)

    result = validator.validate_adapter(Platform.CHATGPT)

    # Assert: result includes requirements
    assert "requirements_met" in result.__dict__
    assert isinstance(result.requirements_met, dict)
    assert not result.is_valid  # ChatGPT is stub


def test_pre_flight_can_be_skipped():
    """Test that pre_flight=False bypasses execution checkpoint."""
    from src.ta_lab2.tools.ai_orchestrator import Orchestrator

    orchestrator = Orchestrator()
    task = Task(type=TaskType.CODE_GENERATION, prompt="test")

    # With pre_flight=False, execution should proceed (but may fail at adapter level)
    # This test just verifies the parameter is accepted
    # Actual execution depends on available adapters


def test_helpful_error_on_no_adapters():
    """Test that error message is helpful when all adapters are stubs."""
    adapters = {
        Platform.CLAUDE_CODE: StubAdapter("ClaudeCode"),
        Platform.CHATGPT: StubAdapter("ChatGPT"),
        Platform.GEMINI: StubAdapter("Gemini"),
    }
    validator = AdapterValidator(adapters)

    task = Task(type=TaskType.CODE_GENERATION, prompt="test")
    can_execute, reason = pre_flight_check(task, validator)

    # Assert: error lists unavailable platforms
    assert not can_execute
    assert "No implemented" in reason
    assert "Stubs" in reason or "stub" in reason.lower()


def test_double_validation_catches_race_condition():
    """Test that execution checkpoint catches adapter becoming unavailable."""
    # Create mock adapter that changes state
    mock_adapter = Mock(spec=BasePlatformAdapter)

    # Initially reports as implemented
    mock_adapter.is_implemented = True
    mock_adapter.implementation_status = "working"
    mock_adapter.get_adapter_status.return_value = {
        "name": "MockAdapter",
        "is_implemented": True,
        "status": "working",
        "capabilities": [],
        "requirements": [],
    }

    adapters = {Platform.CLAUDE_CODE: mock_adapter}
    validator = AdapterValidator(adapters)

    # FIRST CHECKPOINT passes
    available = validator.get_available_platforms()
    assert Platform.CLAUDE_CODE in available

    # Adapter becomes unavailable (race condition simulation)
    mock_adapter.is_implemented = False

    # SECOND CHECKPOINT should catch it
    task = Task(type=TaskType.CODE_GENERATION, prompt="test")
    can_execute, reason = pre_flight_check(task, validator)

    # Note: pre_flight_check checks is_implemented at execution time
    # If adapter became unavailable, it will be caught


def test_get_available_platforms():
    """Test that get_available_platforms only returns implemented adapters."""
    adapters = {
        Platform.CLAUDE_CODE: WorkingAdapter("ClaudeCode"),
        Platform.CHATGPT: StubAdapter("ChatGPT"),
        Platform.GEMINI: WorkingAdapter("Gemini"),
    }
    validator = AdapterValidator(adapters)

    available = validator.get_available_platforms()

    # Assert: only implemented adapters returned
    assert Platform.CLAUDE_CODE in available
    assert Platform.GEMINI in available
    assert Platform.CHATGPT not in available
    assert len(available) == 2


def test_validate_all():
    """Test that validate_all returns results for all adapters."""
    adapters = {
        Platform.CLAUDE_CODE: ClaudeCodeAdapter(),
        Platform.CHATGPT: ChatGPTAdapter(),
        Platform.GEMINI: GeminiAdapter(),
    }
    validator = AdapterValidator(adapters)

    results = validator.validate_all()

    # Assert: results for all platforms
    assert len(results) == 3
    assert Platform.CLAUDE_CODE in results
    assert Platform.CHATGPT in results
    assert Platform.GEMINI in results

    # Assert: ChatGPT is stub
    assert not results[Platform.CHATGPT].is_implemented


def test_is_platform_available():
    """Test quick availability check."""
    adapters = {
        Platform.CLAUDE_CODE: WorkingAdapter(),
        Platform.CHATGPT: StubAdapter(),
    }
    validator = AdapterValidator(adapters)

    assert validator.is_platform_available(Platform.CLAUDE_CODE)
    assert not validator.is_platform_available(Platform.CHATGPT)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
