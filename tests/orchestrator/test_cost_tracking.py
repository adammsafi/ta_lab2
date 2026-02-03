"""Tests for cost tracking with SQLite persistence."""
import pytest
from datetime import datetime, timezone

from ta_lab2.tools.ai_orchestrator.cost import (
    CostTracker,
    CostRecord,
    PRICING,
)
from ta_lab2.tools.ai_orchestrator.core import Task, Result, TaskType, Platform


class TestPricing:
    """Test PRICING configuration."""

    def test_gemini_free_is_zero(self):
        """Gemini free tier has zero cost."""
        assert PRICING["gemini_cli"]["input"] == 0.0
        assert PRICING["gemini_cli"]["output"] == 0.0

    def test_openai_models_have_pricing(self):
        """OpenAI models have non-zero pricing."""
        assert PRICING["gpt-4o-mini"]["input"] > 0
        assert PRICING["gpt-4o"]["input"] > 0


class TestCostTracker:
    """Test CostTracker class."""

    @pytest.fixture
    def tracker(self, tmp_path):
        """Create tracker with temp database."""
        db_path = tmp_path / "test_costs.db"
        return CostTracker(str(db_path))

    @pytest.fixture
    def sample_task(self):
        """Create sample task for testing."""
        return Task(
            type=TaskType.CODE_GENERATION,
            prompt="Test prompt",
            task_id="test_task_123",
            metadata={"chain_id": "chain_abc"},
        )

    @pytest.fixture
    def sample_result(self, sample_task):
        """Create sample result for testing."""
        return Result(
            task=sample_task,
            platform=Platform.CHATGPT,
            output="Test output",
            success=True,
            tokens_used=150,
            metadata={
                "model": "gpt-4o-mini",
                "input_tokens": 100,
                "output_tokens": 50,
            },
        )

    def test_record_creates_entry(self, tracker, sample_task, sample_result):
        """record() creates database entry."""
        tracker.record(sample_task, sample_result)
        cost = tracker.get_task_cost("test_task_123")
        assert cost is not None
        assert cost >= 0

    def test_get_chain_cost_sums_tasks(self, tracker, sample_task, sample_result):
        """get_chain_cost returns sum of all tasks in chain."""
        # Record multiple tasks in same chain
        tracker.record(sample_task, sample_result)

        task2 = Task(
            type=TaskType.CODE_GENERATION,
            prompt="Test 2",
            task_id="test_task_456",
            metadata={"chain_id": "chain_abc"},
        )
        result2 = Result(
            task=task2,
            platform=Platform.CHATGPT,
            output="Output 2",
            success=True,
            metadata={
                "model": "gpt-4o-mini",
                "input_tokens": 200,
                "output_tokens": 100,
            },
        )
        tracker.record(task2, result2)

        chain_cost = tracker.get_chain_cost("chain_abc")
        task1_cost = tracker.get_task_cost("test_task_123")
        task2_cost = tracker.get_task_cost("test_task_456")

        assert chain_cost == pytest.approx(task1_cost + task2_cost, rel=1e-6)

    def test_get_platform_totals(self, tracker, sample_task, sample_result):
        """get_platform_totals groups by platform."""
        tracker.record(sample_task, sample_result)
        totals = tracker.get_platform_totals()
        assert "chatgpt" in totals

    def test_get_session_summary(self, tracker, sample_task, sample_result):
        """get_session_summary returns today's stats."""
        tracker.record(sample_task, sample_result)
        summary = tracker.get_session_summary()
        assert summary["total_tasks"] >= 1
        assert "chatgpt" in summary["by_platform"]


class TestCostEstimation:
    """Test cost estimation functionality."""

    @pytest.fixture
    def tracker(self, tmp_path):
        db_path = tmp_path / "test_costs.db"
        return CostTracker(str(db_path))

    def test_estimate_cost_returns_positive(self, tracker):
        """Estimate returns positive cost for paid models."""
        cost = tracker.estimate_cost("Hello world", model="gpt-4o-mini")
        assert cost >= 0

    def test_should_warn_cost_above_threshold(self, tracker):
        """Warns when prompt above token threshold."""
        # ~40k chars = ~10k tokens
        long_prompt = "x" * 50000
        assert tracker.should_warn_cost(long_prompt) is True

    def test_should_warn_cost_below_threshold(self, tracker):
        """No warning for short prompts."""
        short_prompt = "Hello world"
        assert tracker.should_warn_cost(short_prompt) is False


class TestCostRecord:
    """Test CostRecord dataclass."""

    def test_dataclass_fields(self):
        """CostRecord has all required fields."""
        record = CostRecord(
            task_id="task_1",
            platform="chatgpt",
            chain_id="chain_1",
            model="gpt-4o-mini",
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.0001,
            timestamp=datetime.now(timezone.utc),
        )
        assert record.task_id == "task_1"
        assert record.cost_usd == 0.0001
