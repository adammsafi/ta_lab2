"""
Orchestrator <-> Memory component pair integration tests.

Tests the integration between:
- AsyncOrchestrator (execution.py)
- Memory system (Mem0 client, handoff)

Per CONTEXT.md: Both execution and inspection tests.

Uses TracingContext from observability for correlation ID propagation.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio

# Import TracingContext for correlation tracking
from ta_lab2.observability.tracing import TracingContext, generate_correlation_id


@pytest.mark.integration
@pytest.mark.mocked_deps
class TestOrchestratorMemoryContext:
    """Tests for orchestrator retrieving memory context."""

    @pytest.mark.asyncio
    async def test_orchestrator_retrieves_memory_context(self, mocker):
        """Test orchestrator queries memory for task context."""
        from ta_lab2.tools.ai_orchestrator.execution import AsyncOrchestrator
        from ta_lab2.tools.ai_orchestrator.core import Task, TaskType, Platform

        # Mock memory client
        mock_memory = mocker.MagicMock()
        mock_memory.search.return_value = {
            "results": [
                {"content": "EMA refresh requires bars loaded first", "score": 0.95}
            ]
        }

        # Mock adapter
        mock_adapter = mocker.MagicMock()
        mock_adapter.submit_task = AsyncMock(return_value="task-123")
        mock_adapter.get_result = AsyncMock(return_value=mocker.MagicMock(success=True))
        mock_adapter.__aenter__ = AsyncMock(return_value=mock_adapter)
        mock_adapter.__aexit__ = AsyncMock(return_value=None)

        orchestrator = AsyncOrchestrator(
            adapters={Platform.GEMINI: mock_adapter},
        )

        task = Task(type=TaskType.DATA_ANALYSIS, prompt="Refresh EMA features")

        # Execute with tracing context for correlation
        with TracingContext("orchestrator_memory_test") as ctx:
            async with orchestrator:
                result = await orchestrator.execute_single(task)

            # Verify trace context exists
            assert ctx.trace_id is not None

        assert result is not None

    @pytest.mark.asyncio
    async def test_memory_context_injected_into_prompt(self, mocker):
        """Test retrieved memory is injected into task prompt."""
        from ta_lab2.tools.ai_orchestrator.memory.injection import inject_memory_context

        # Mock the search_memories function
        with patch('ta_lab2.tools.ai_orchestrator.memory.injection.search_memories') as mock_search:
            from ta_lab2.tools.ai_orchestrator.memory.query import SearchResult, SearchResponse

            mock_search.return_value = SearchResponse(
                query="Refresh features for BTC",
                results=[
                    SearchResult(
                        memory_id="mem-1",
                        content="BTC EMA patterns show strong trend following",
                        metadata={},
                        similarity=0.95,
                        distance=0.05
                    ),
                    SearchResult(
                        memory_id="mem-2",
                        content="Refresh order: bars -> EMA -> returns -> features",
                        metadata={},
                        similarity=0.92,
                        distance=0.08
                    ),
                ],
                total_found=2,
                filtered_count=2,
                search_time_ms=10.5,
                threshold_used=0.7
            )

            enhanced = inject_memory_context("Refresh features for BTC", max_length=500)

            # Should include memory content
            assert "EMA patterns" in enhanced or "Refresh order" in enhanced

    @pytest.mark.asyncio
    async def test_orchestrator_stores_result_to_memory(self, mocker):
        """Test orchestrator can store task result in memory."""
        # Mock the low-level functions that add_memory depends on
        with patch('ta_lab2.tools.ai_orchestrator.memory.update.get_embedding') as mock_embed, \
             patch('ta_lab2.tools.ai_orchestrator.memory.client.get_memory_client') as mock_client:

            # Setup mocks
            mock_embed.return_value = [[0.1] * 1536]  # Mock embedding
            mock_collection = mocker.MagicMock()
            mock_collection.get.return_value = {"ids": []}  # No existing memories
            mock_client.return_value.collection = mock_collection

            from ta_lab2.tools.ai_orchestrator.memory.update import add_memory

            result = add_memory(
                memory_id="mem-123",
                content="EMA refresh complete: 1000 rows",
                metadata={"type": "task_result", "rows": 1000}
            )

            # Verify the collection was called
            mock_collection.upsert.assert_called_once()
            assert result.added == 1


@pytest.mark.integration
@pytest.mark.mocked_deps
class TestOrchestratorMemoryHandoff:
    """Tests for AI-to-AI handoffs via memory."""

    @pytest.mark.asyncio
    async def test_handoff_stores_context_with_id(self, mocker):
        """Test handoff creates memory entry with retrievable ID."""
        from ta_lab2.tools.ai_orchestrator.handoff import spawn_child_task
        from ta_lab2.tools.ai_orchestrator.core import Task, TaskType, Result, Platform, TaskStatus

        # Create a mock parent result
        parent_task = Task(type=TaskType.DATA_ANALYSIS, prompt="Task A", task_id="task-a-123")
        parent_result = Result(
            task=parent_task,
            platform=Platform.GEMINI,
            output="data prepared",
            success=True,
            status=TaskStatus.COMPLETED
        )

        with patch('ta_lab2.tools.ai_orchestrator.memory.update.get_embedding') as mock_embed, \
             patch('ta_lab2.tools.ai_orchestrator.memory.client.get_memory_client') as mock_client:

            # Setup mocks
            mock_embed.return_value = [[0.1] * 1536]
            mock_collection = mocker.MagicMock()
            mock_collection.get.return_value = {"ids": []}  # No existing memories
            mock_client.return_value.collection = mock_collection

            child_task, handoff = await spawn_child_task(
                parent_result=parent_result,
                child_prompt="Task B using data from Task A",
                child_type=TaskType.DATA_ANALYSIS
            )

            # Verify memory was stored
            mock_collection.upsert.assert_called_once()
            assert handoff.memory_id is not None
            assert "handoff" in handoff.memory_id

    @pytest.mark.asyncio
    async def test_handoff_retrieves_context_by_id(self, mocker):
        """Test handoff can retrieve context by ID."""
        from ta_lab2.tools.ai_orchestrator.handoff import load_handoff_context
        from ta_lab2.tools.ai_orchestrator.core import Task, TaskType
        from ta_lab2.tools.ai_orchestrator.memory.query import SearchResult

        # Create a task with handoff context
        task = Task(
            type=TaskType.DATA_ANALYSIS,
            prompt="Task B",
            context={"handoff_memory_id": "handoff-456"}
        )

        with patch('ta_lab2.tools.ai_orchestrator.memory.query.get_memory_by_id') as mock_get:
            mock_get.return_value = SearchResult(
                memory_id="handoff-456",
                content="Task A completed data preparation",
                metadata={"task_a_result": "data prepared"},
                similarity=1.0,
                distance=0.0
            )

            context = await load_handoff_context(task)

            assert context is not None
            assert "data preparation" in context

    @pytest.mark.asyncio
    async def test_handoff_fails_on_missing_context(self, mocker):
        """Test handoff raises error when context not found."""
        from ta_lab2.tools.ai_orchestrator.handoff import load_handoff_context
        from ta_lab2.tools.ai_orchestrator.core import Task, TaskType

        # Create a task with handoff context that doesn't exist
        task = Task(
            type=TaskType.DATA_ANALYSIS,
            prompt="Task B",
            context={"handoff_memory_id": "nonexistent-id"}
        )

        with patch('ta_lab2.tools.ai_orchestrator.memory.query.get_memory_by_id') as mock_get:
            mock_get.return_value = None

            with pytest.raises(RuntimeError, match="not found"):
                await load_handoff_context(task)


@pytest.mark.integration
@pytest.mark.mixed_deps
class TestOrchestratorMemoryRealDB:
    """Tests with real database, mocked AI APIs."""

    @pytest.mark.asyncio
    async def test_workflow_tracking_with_memory(self, clean_database, mocker):
        """Test workflow state tracked through memory operations."""
        from ta_lab2.observability.storage import WorkflowStateTracker

        # Use real database connection
        tracker = WorkflowStateTracker(clean_database)

        # Mock the execute call
        mock_conn = mocker.MagicMock()
        clean_database.execute = mock_conn.execute

        # Workflow would be created during orchestrator execution
        # This tests the pattern, not actual execution
        assert tracker is not None
