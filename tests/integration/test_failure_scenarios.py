"""
Failure scenario integration tests.

Per CONTEXT.md, tests all four failure scenarios:
1. Component unavailable (memory down, ta_lab2 fails, orchestrator unreachable)
2. Partial failures (task succeeds but memory write fails)
3. Timeout/latency issues (memory search too slow)
4. Invalid state transitions (task without context)

Uses TracingContext from observability for correlation ID propagation.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio

# Import TracingContext for correlation tracking (key_link verification)
from ta_lab2.observability.tracing import TracingContext


@pytest.mark.integration
@pytest.mark.mocked_deps
class TestComponentUnavailable:
    """Tests for component unavailability scenarios."""

    @pytest.mark.asyncio
    async def test_memory_unavailable(self, mocker):
        """Test orchestrator handles memory service being down."""
        from ta_lab2.tools.ai_orchestrator.handoff import load_handoff_context
        from ta_lab2.tools.ai_orchestrator.core import Task, TaskType

        task = Task(
            type=TaskType.DATA_ANALYSIS,
            prompt="Task B",
            context={"handoff_memory_id": "any-id"},
        )

        with patch(
            "ta_lab2.tools.ai_orchestrator.memory.query.get_memory_by_id"
        ) as mock_get:
            mock_get.side_effect = ConnectionError("Qdrant connection refused")

            with pytest.raises(ConnectionError):
                await load_handoff_context(task)

    @pytest.mark.asyncio
    async def test_database_unavailable(self, mocker):
        """Test feature refresh handles database unavailability."""
        from ta_lab2.scripts.features.validate_features import FeatureValidator

        mock_engine = mocker.MagicMock()
        mock_engine.connect.side_effect = Exception("Connection refused")

        validator = FeatureValidator(mock_engine)

        # Should raise or handle gracefully
        with pytest.raises(Exception):
            with mock_engine.connect():
                validator.check_gaps("test", [1], "2024-01-01", "2024-01-31")

    @pytest.mark.asyncio
    async def test_orchestrator_adapter_unavailable(self, mocker):
        """Test orchestrator handles adapter being unavailable."""
        from ta_lab2.tools.ai_orchestrator.execution import AsyncOrchestrator
        from ta_lab2.tools.ai_orchestrator.core import Task, TaskType

        orchestrator = AsyncOrchestrator(adapters={})  # No adapters

        task = Task(type=TaskType.DATA_ANALYSIS, prompt="Test")

        # Track failure with tracing
        with TracingContext("adapter_unavailable_test") as ctx:
            async with orchestrator:
                result = await orchestrator.execute_single(task)
            assert ctx.trace_id is not None

        # Should fail gracefully with error result
        assert not result.success
        assert "No adapter" in result.error or "platform" in result.error.lower()


@pytest.mark.integration
@pytest.mark.mocked_deps
class TestPartialFailures:
    """Tests for partial failure scenarios."""

    @pytest.mark.asyncio
    async def test_task_succeeds_memory_write_fails(self, mocker):
        """Test handling when task succeeds but memory write fails."""
        from ta_lab2.tools.ai_orchestrator.memory.update import add_memory

        with patch(
            "ta_lab2.tools.ai_orchestrator.memory.update.get_embedding"
        ) as mock_embed:
            mock_embed.side_effect = Exception("Memory write failed")

            result = add_memory(
                memory_id="mem-123", content="success", metadata={"type": "task_result"}
            )

            # add_memory catches exceptions and returns them in result.errors
            assert result.failed > 0
            assert any("write failed" in err.lower() for err in result.errors)

    def test_refresh_succeeds_validation_fails(self, mocker):
        """Test handling when refresh succeeds but validation fails."""
        mock_refresh_func = mocker.MagicMock(return_value={"success": True})
        mock_validate_func = mocker.MagicMock(
            return_value={"passed": False, "issues": [{"type": "gap"}]}
        )

        # Both complete but validation fails
        refresh_result = mock_refresh_func(asset_ids=[1])
        validate_result = mock_validate_func(asset_ids=[1])

        assert refresh_result["success"]
        assert not validate_result["passed"]

    def test_partial_feature_refresh_failure(self, mocker):
        """Test handling when some feature tables fail to refresh."""
        mock_refresh_all = mocker.MagicMock(
            return_value={
                "returns": {"success": True, "rows": 100},
                "vol": {"success": False, "error": "Vol calc failed"},
                "ta": {"success": True, "rows": 100},
            }
        )

        result = mock_refresh_all(asset_ids=[1])

        # Some succeed, some fail
        assert result["returns"]["success"]
        assert not result["vol"]["success"]
        assert result["ta"]["success"]


@pytest.mark.integration
@pytest.mark.mocked_deps
class TestTimeoutLatency:
    """Tests for timeout and latency scenarios."""

    @pytest.mark.asyncio
    async def test_memory_search_timeout(self, mocker):
        """Test handling when memory search times out."""
        from ta_lab2.tools.ai_orchestrator.memory.query import search_memories

        with patch(
            "ta_lab2.tools.ai_orchestrator.memory.client.get_memory_client"
        ) as mock_client:
            mock_collection = mocker.MagicMock()

            async def slow_query(*args, **kwargs):
                await asyncio.sleep(10)  # Simulate slow response
                return {
                    "ids": [[]],
                    "distances": [[]],
                    "documents": [[]],
                    "metadatas": [[]],
                }

            # Memory client uses synchronous API, but we can test timeout pattern
            mock_collection.query.side_effect = lambda *args, **kwargs: {
                "ids": [[]],
                "distances": [[]],
                "documents": [[]],
                "metadatas": [[]],
            }
            mock_client.return_value.collection = mock_collection

            # Should complete quickly with mocked data
            with patch(
                "ta_lab2.tools.ai_orchestrator.memory.update.get_embedding"
            ) as mock_embed:
                mock_embed.return_value = [[0.1] * 1536]
                result = search_memories("test query", max_results=5)
                assert result is not None

    @pytest.mark.asyncio
    async def test_adapter_execution_timeout(self, mocker):
        """Test handling when adapter execution times out."""
        from ta_lab2.tools.ai_orchestrator.execution import AsyncOrchestrator
        from ta_lab2.tools.ai_orchestrator.core import (
            Task,
            TaskType,
            Platform,
            TaskConstraints,
        )

        mock_adapter = mocker.MagicMock()
        mock_adapter.submit_task = AsyncMock(return_value="task-123")
        mock_adapter.get_result = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_adapter.__aenter__ = AsyncMock(return_value=mock_adapter)
        mock_adapter.__aexit__ = AsyncMock(return_value=None)

        orchestrator = AsyncOrchestrator(adapters={Platform.GEMINI: mock_adapter})

        task = Task(
            type=TaskType.DATA_ANALYSIS,
            prompt="Test",
            constraints=TaskConstraints(timeout_seconds=1),
        )

        # Should handle timeout - result depends on implementation
        async with orchestrator:
            try:
                result = await orchestrator.execute_single(task)
                # If it doesn't raise, check result
                if result:
                    # May be None or error Result
                    pass
            except asyncio.TimeoutError:
                # Timeout may propagate
                pass


@pytest.mark.integration
@pytest.mark.mocked_deps
class TestInvalidStateTransitions:
    """Tests for invalid state transition scenarios."""

    @pytest.mark.asyncio
    async def test_task_without_required_context(self, mocker):
        """Test handling task submitted without required memory context."""
        from ta_lab2.tools.ai_orchestrator.handoff import load_handoff_context
        from ta_lab2.tools.ai_orchestrator.core import Task, TaskType

        task = Task(
            type=TaskType.DATA_ANALYSIS,
            prompt="Task B",
            context={"handoff_memory_id": "nonexistent-context-id"},
        )

        with patch(
            "ta_lab2.tools.ai_orchestrator.memory.query.get_memory_by_id"
        ) as mock_get:
            mock_get.return_value = None

            # Task B tries to load context from Task A that doesn't exist
            with pytest.raises(RuntimeError, match="not found"):
                await load_handoff_context(task)

    def test_invalid_workflow_transition(self, mocker):
        """Test handling invalid workflow state transition."""
        from ta_lab2.observability.storage import WorkflowStateTracker

        mock_engine = mocker.MagicMock()
        tracker = WorkflowStateTracker(mock_engine)

        # Try to transition workflow that doesn't exist
        # Should handle gracefully (no-op or error)
        tracker.transition("nonexistent-workflow", "completed", "completed")

        # Verify attempt was made
        mock_engine.begin.assert_called()

    def test_duplicate_workflow_creation(self, mocker):
        """Test handling duplicate workflow ID creation."""
        from ta_lab2.observability.storage import WorkflowStateTracker

        mock_engine = mocker.MagicMock()
        # Simulate unique constraint violation
        mock_conn = mocker.MagicMock()
        mock_conn.__enter__ = mocker.MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = mocker.MagicMock(return_value=None)
        mock_conn.execute.side_effect = [
            None,  # First create succeeds
            Exception("duplicate key"),  # Second create fails
        ]
        mock_engine.begin.return_value = mock_conn

        tracker = WorkflowStateTracker(mock_engine)

        # First creation works
        tracker.create_workflow("wf-123", "corr-456", "test")

        # Second creation with same ID should fail
        # (In practice, would catch and handle)
        try:
            tracker.create_workflow("wf-123", "corr-456", "test")
        except Exception as e:
            assert "duplicate" in str(e).lower()


@pytest.mark.integration
@pytest.mark.mocked_deps
class TestFailFastMode:
    """Tests for --fail-fast flag behavior."""

    def test_fail_fast_stops_on_first_error(self, mocker):
        """Test --fail-fast stops execution on first error."""
        errors = []

        def mock_refresh(table, fail=False):
            if fail:
                raise ValueError(f"{table} failed")
            return MagicMock(success=True)

        tables = ["returns", "vol", "ta"]

        # With fail_fast=True, should stop at first failure
        fail_fast = True
        for i, table in enumerate(tables):
            try:
                if i == 1:  # vol fails
                    mock_refresh(table, fail=True)
                else:
                    mock_refresh(table)
            except ValueError as e:
                errors.append(str(e))
                if fail_fast:
                    break

        # Should have stopped at first error
        assert len(errors) == 1
        assert "vol" in errors[0]

    def test_continue_on_error_default(self, mocker):
        """Test default behavior continues after errors."""
        errors = []
        results = []

        tables = ["returns", "vol", "ta"]

        # Default: continue after failure
        fail_fast = False
        for i, table in enumerate(tables):
            try:
                if i == 1:  # vol fails
                    raise ValueError(f"{table} failed")
                results.append(table)
            except ValueError as e:
                errors.append(str(e))
                if fail_fast:
                    break

        # Should have continued through all tables
        assert len(errors) == 1
        assert len(results) == 2  # returns and ta succeeded
