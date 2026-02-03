"""Tests for workflow state tracking."""

import pytest
import uuid


@pytest.mark.observability
@pytest.mark.mocked_deps
class TestWorkflowStateTracker:
    """Tests for WorkflowStateTracker class."""

    def test_create_workflow(self, mocker):
        """Test creating new workflow state."""
        from ta_lab2.observability.storage import WorkflowStateTracker

        mock_engine = mocker.MagicMock()
        tracker = WorkflowStateTracker(mock_engine)

        workflow_id = str(uuid.uuid4())
        correlation_id = "a" * 32
        tracker.create_workflow(workflow_id, correlation_id, "orchestrator_task")

        mock_engine.begin.assert_called()

    def test_transition_updates_state(self, mocker):
        """Test transitioning workflow to new phase."""
        from ta_lab2.observability.storage import WorkflowStateTracker

        mock_engine = mocker.MagicMock()
        tracker = WorkflowStateTracker(mock_engine)

        workflow_id = str(uuid.uuid4())
        tracker.transition(workflow_id, "executing", "running")

        mock_engine.begin.assert_called()

    def test_transition_with_metadata(self, mocker):
        """Test transition with metadata."""
        from ta_lab2.observability.storage import WorkflowStateTracker

        mock_engine = mocker.MagicMock()
        tracker = WorkflowStateTracker(mock_engine)

        workflow_id = str(uuid.uuid4())
        metadata = {"task_id": "test-123", "platform": "gemini"}
        tracker.transition(workflow_id, "completed", "completed", metadata=metadata)

        mock_engine.begin.assert_called()

    def test_get_workflow(self, mocker):
        """Test retrieving workflow state."""
        from ta_lab2.observability.storage import WorkflowStateTracker
        from datetime import datetime

        mock_engine = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value.fetchone.return_value = (
            "wf-123",
            "corr-456",
            "orchestrator_task",
            "executing",
            "running",
            datetime.utcnow(),
            datetime.utcnow(),
            {},
        )

        tracker = WorkflowStateTracker(mock_engine)
        result = tracker.get_workflow("wf-123")

        assert result is not None
        assert result["workflow_id"] == "wf-123"
        assert result["correlation_id"] == "corr-456"

    def test_list_workflows(self, mocker):
        """Test listing workflows by status."""
        from ta_lab2.observability.storage import WorkflowStateTracker
        from datetime import datetime

        mock_engine = mocker.MagicMock()
        mock_conn = mocker.MagicMock()
        mock_result = mocker.MagicMock()
        mock_engine.connect.return_value.__enter__.return_value = mock_conn
        mock_conn.execute.return_value = mock_result

        # Mock the result iteration with complete rows (8 columns)
        now = datetime.utcnow()
        mock_result.__iter__ = lambda self: iter(
            [
                ("wf-1", "corr-1", "task", "executing", "running", now, now, {}),
                ("wf-2", "corr-2", "task", "executing", "running", now, now, {}),
            ]
        )

        tracker = WorkflowStateTracker(mock_engine)
        results = tracker.list_workflows(status="running", limit=10)

        assert len(results) == 2
        assert results[0]["workflow_id"] == "wf-1"
        assert results[1]["workflow_id"] == "wf-2"

    def test_workflow_lifecycle(self, mocker):
        """Test complete workflow lifecycle: create -> transition -> complete."""
        from ta_lab2.observability.storage import WorkflowStateTracker

        mock_engine = mocker.MagicMock()
        tracker = WorkflowStateTracker(mock_engine)

        workflow_id = str(uuid.uuid4())
        correlation_id = "b" * 32

        # Create
        tracker.create_workflow(workflow_id, correlation_id, "feature_refresh")

        # Transitions
        tracker.transition(workflow_id, "routing", "running")
        tracker.transition(workflow_id, "executing", "running")
        tracker.transition(workflow_id, "completed", "completed")

        # Verify 4 database calls (create + 3 transitions)
        assert mock_engine.begin.call_count == 4
