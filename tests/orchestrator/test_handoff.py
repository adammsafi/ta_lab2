"""Tests for AI-to-AI handoff mechanism."""
import pytest
from unittest.mock import Mock, patch

from ta_lab2.tools.ai_orchestrator.handoff import (
    HandoffContext,
    TaskChain,
    ChainTracker,
    spawn_child_task,
    load_handoff_context,
    has_handoff_context,
)
from ta_lab2.tools.ai_orchestrator.core import Task, Result, TaskType, Platform


class TestHandoffContext:
    """Test HandoffContext dataclass."""

    def test_to_context_dict(self):
        """Converts to dict with correct keys."""
        ctx = HandoffContext(
            memory_id="mem_123",
            summary="Brief summary",
            parent_task_id="task_abc",
            chain_id="chain_xyz",
        )
        d = ctx.to_context_dict()
        assert d["handoff_memory_id"] == "mem_123"
        assert d["handoff_summary"] == "Brief summary"
        assert d["parent_task_id"] == "task_abc"
        assert d["chain_id"] == "chain_xyz"


class TestTaskChain:
    """Test TaskChain dataclass."""

    def test_add_task_sets_root(self):
        """First task becomes root_task_id."""
        chain = TaskChain(chain_id="chain_1")
        assert chain.root_task_id is None

        chain.add_task("task_a", cost=1.0, tokens=100)
        assert chain.root_task_id == "task_a"

        # Second task doesn't override root
        chain.add_task("task_b", cost=2.0, tokens=200)
        assert chain.root_task_id == "task_a"

    def test_add_task_accumulates_cost(self):
        """Total cost accumulates from all tasks."""
        chain = TaskChain(chain_id="chain_1")

        chain.add_task("task_a", cost=1.5, tokens=100)
        assert chain.total_cost == 1.5
        assert chain.total_tokens == 100

        chain.add_task("task_b", cost=2.5, tokens=200)
        assert chain.total_cost == 4.0
        assert chain.total_tokens == 300

    def test_depth_property(self):
        """Depth returns number of tasks in chain."""
        chain = TaskChain(chain_id="chain_1")
        assert chain.depth == 0

        chain.add_task("task_a")
        assert chain.depth == 1

        chain.add_task("task_b")
        chain.add_task("task_c")
        assert chain.depth == 3


class TestChainTracker:
    """Test ChainTracker class."""

    def test_get_or_create_chain_creates_new(self):
        """Creates new chain if not exists."""
        tracker = ChainTracker()

        chain = tracker.get_or_create_chain("chain_1")
        assert chain is not None
        assert chain.chain_id == "chain_1"
        assert chain.depth == 0

    def test_get_or_create_chain_returns_existing(self):
        """Returns existing chain if exists."""
        tracker = ChainTracker()

        chain1 = tracker.get_or_create_chain("chain_1")
        chain1.add_task("task_a")

        chain2 = tracker.get_or_create_chain("chain_1")
        assert chain2 is chain1
        assert chain2.depth == 1

    def test_record_task_adds_to_chain(self):
        """record_task adds task to chain."""
        tracker = ChainTracker()

        tracker.record_task("chain_1", "task_a", cost=1.0, tokens=100)
        chain = tracker.get_chain("chain_1")

        assert chain.depth == 1
        assert chain.total_cost == 1.0
        assert chain.total_tokens == 100

    def test_get_chain_cost_returns_total(self):
        """get_chain_cost returns accumulated total."""
        tracker = ChainTracker()

        tracker.record_task("chain_1", "task_a", cost=1.5, tokens=100)
        tracker.record_task("chain_1", "task_b", cost=2.5, tokens=200)

        assert tracker.get_chain_cost("chain_1") == 4.0

        # Non-existent chain returns 0
        assert tracker.get_chain_cost("chain_999") == 0.0


class TestSpawnChildTask:
    """Test spawn_child_task function."""

    @pytest.mark.asyncio
    async def test_stores_context_in_memory(self):
        """Full context stored via add_memory."""
        with patch(
            "ta_lab2.tools.ai_orchestrator.memory.update.add_memory"
        ) as mock_add:
            # Create parent result
            parent_task = Task(
                type=TaskType.CODE_GENERATION, prompt="Parent", task_id="parent_123"
            )
            parent_result = Result(
                task=parent_task,
                platform=Platform.CLAUDE_CODE,
                output="Parent output text",
                success=True,
            )

            child_task, handoff = await spawn_child_task(parent_result, "Child prompt")

            mock_add.assert_called_once()
            call_args = mock_add.call_args
            assert "Parent output text" in call_args[1]["content"]
            assert call_args[1]["metadata"]["type"] == "handoff"
            assert call_args[1]["metadata"]["parent_task_id"] == "parent_123"

    @pytest.mark.asyncio
    async def test_truncates_long_summary(self):
        """Summary truncated to max_summary_length."""
        with patch("ta_lab2.tools.ai_orchestrator.memory.update.add_memory"):
            parent_task = Task(
                type=TaskType.CODE_GENERATION, prompt="Parent", task_id="parent_123"
            )
            long_output = "A" * 1000
            parent_result = Result(
                task=parent_task,
                platform=Platform.CLAUDE_CODE,
                output=long_output,
                success=True,
            )

            child_task, handoff = await spawn_child_task(
                parent_result, "Child prompt", max_summary_length=100
            )

            assert len(handoff.summary) == 103  # 100 + "..."
            assert handoff.summary.endswith("...")

    @pytest.mark.asyncio
    async def test_child_task_has_context_pointer(self):
        """Child task.context has handoff_memory_id."""
        with patch("ta_lab2.tools.ai_orchestrator.memory.update.add_memory"):
            parent_task = Task(
                type=TaskType.CODE_GENERATION, prompt="Parent", task_id="parent_123"
            )
            parent_result = Result(
                task=parent_task,
                platform=Platform.CLAUDE_CODE,
                output="Parent output",
                success=True,
            )

            child_task, handoff = await spawn_child_task(parent_result, "Child prompt")

            assert "handoff_memory_id" in child_task.context
            assert child_task.context["handoff_memory_id"] == handoff.memory_id
            assert child_task.context["parent_task_id"] == "parent_123"
            assert child_task.context["chain_id"] == handoff.chain_id

    @pytest.mark.asyncio
    async def test_preserves_chain_id(self):
        """Uses existing chain_id if provided."""
        with patch("ta_lab2.tools.ai_orchestrator.memory.update.add_memory"):
            parent_task = Task(
                type=TaskType.CODE_GENERATION,
                prompt="Parent",
                task_id="parent_123",
                metadata={"chain_id": "existing_chain"},
            )
            parent_result = Result(
                task=parent_task,
                platform=Platform.CLAUDE_CODE,
                output="Parent output",
                success=True,
            )

            # Should use existing chain_id from parent
            child_task, handoff = await spawn_child_task(parent_result, "Child prompt")
            assert handoff.chain_id == "existing_chain"

            # Should use explicitly provided chain_id
            child_task2, handoff2 = await spawn_child_task(
                parent_result, "Child prompt", chain_id="explicit_chain"
            )
            assert handoff2.chain_id == "explicit_chain"


class TestLoadHandoffContext:
    """Test load_handoff_context function."""

    @pytest.mark.asyncio
    async def test_retrieves_from_memory(self):
        """Loads context from memory by ID."""
        with patch(
            "ta_lab2.tools.ai_orchestrator.memory.query.get_memory_by_id"
        ) as mock_get:
            # Mock SearchResult with content attribute
            mock_result = Mock()
            mock_result.content = "Full context"
            mock_get.return_value = mock_result

            task = Task(
                type=TaskType.CODE_GENERATION,
                prompt="Child",
                context={"handoff_memory_id": "mem_123"},
            )

            content = await load_handoff_context(task)
            assert content == "Full context"
            mock_get.assert_called_with("mem_123")

    @pytest.mark.asyncio
    async def test_raises_if_no_memory_id(self):
        """Raises RuntimeError if no handoff_memory_id."""
        task = Task(type=TaskType.CODE_GENERATION, prompt="Child", context={})
        with pytest.raises(RuntimeError, match="no handoff_memory_id"):
            await load_handoff_context(task)

    @pytest.mark.asyncio
    async def test_raises_if_memory_not_found(self):
        """Raises RuntimeError if memory lookup returns None (fail-fast per CONTEXT.md)."""
        with patch(
            "ta_lab2.tools.ai_orchestrator.memory.query.get_memory_by_id"
        ) as mock_get:
            mock_get.return_value = None
            task = Task(
                type=TaskType.CODE_GENERATION,
                prompt="Child",
                context={"handoff_memory_id": "mem_missing"},
            )

            with pytest.raises(RuntimeError, match="not found"):
                await load_handoff_context(task)


class TestHasHandoffContext:
    """Test has_handoff_context helper."""

    def test_returns_true_if_has_memory_id(self):
        """True when handoff_memory_id in context."""
        task = Task(
            type=TaskType.CODE_GENERATION,
            prompt="Child",
            context={"handoff_memory_id": "mem_123"},
        )
        assert has_handoff_context(task) is True

    def test_returns_false_if_no_memory_id(self):
        """False when handoff_memory_id not in context."""
        task = Task(
            type=TaskType.CODE_GENERATION,
            prompt="Child",
            context={},
        )
        assert has_handoff_context(task) is False
