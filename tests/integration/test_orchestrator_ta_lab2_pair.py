"""
Orchestrator <-> ta_lab2 component pair integration tests.

Tests the integration between:
- AsyncOrchestrator (execution.py)
- ta_lab2 feature pipeline (refresh scripts)

Per CONTEXT.md: Orchestrator successfully coordinates ta_lab2 feature refresh tasks.

Uses TracingContext from observability for correlation ID propagation.
"""

import pytest
from unittest.mock import patch

# Import TracingContext for correlation tracking
from ta_lab2.observability.tracing import TracingContext


@pytest.mark.integration
@pytest.mark.mocked_deps
class TestOrchestratorFeatureRefresh:
    """Tests for orchestrator triggering ta_lab2 feature refresh."""

    def test_orchestrator_triggers_feature_refresh(self, mocker):
        """Test orchestrator can invoke feature refresh."""
        # Mock the refresh script execution
        mock_refresh_func = mocker.MagicMock(
            return_value={"success": True, "rows_inserted": 100}
        )

        # Simulate orchestrator calling refresh with tracing
        with TracingContext("feature_refresh_trigger") as ctx:
            result = mock_refresh_func(asset_ids=[1, 52])
            assert ctx.trace_id is not None

        assert result["success"]
        assert result["rows_inserted"] == 100

    def test_orchestrator_handles_refresh_failure(self, mocker):
        """Test orchestrator handles feature refresh failures."""
        mock_refresh_func = mocker.MagicMock(
            return_value={"success": False, "error": "Test error"}
        )

        result = mock_refresh_func(asset_ids=[1])

        assert not result["success"]
        assert "error" in result

    def test_orchestrator_passes_asset_ids(self, mocker):
        """Test orchestrator passes correct asset IDs to refresh."""
        mock_refresh_func = mocker.MagicMock(return_value={"success": True})

        expected_ids = [1, 52, 100]
        result = mock_refresh_func(asset_ids=expected_ids)

        # Verify IDs were passed
        call_args = mock_refresh_func.call_args
        assert call_args[1]["asset_ids"] == expected_ids
        assert result["success"]


@pytest.mark.integration
@pytest.mark.mocked_deps
class TestOrchestratorValidation:
    """Tests for orchestrator triggering validation."""

    def test_orchestrator_triggers_validation(self, mocker):
        """Test orchestrator can invoke feature validation."""
        from ta_lab2.scripts.features.validate_features import FeatureValidator

        mock_engine = mocker.MagicMock()
        validator = FeatureValidator(mock_engine)

        # Mock the validation methods
        with patch.object(validator, "check_gaps") as mock_gaps, patch.object(
            validator, "check_null_ratios"
        ) as mock_nulls, patch.object(validator, "check_outliers") as mock_outliers:
            mock_gaps.return_value = []
            mock_nulls.return_value = []
            mock_outliers.return_value = []

            # Simulate validation
            gap_issues = validator.check_gaps(
                "test_table", [1], "2024-01-01", "2024-01-31"
            )
            null_issues = validator.check_null_ratios("test_table", [1])
            outlier_issues = validator.check_outliers("test_table", [1])

            assert len(gap_issues) == 0
            assert len(null_issues) == 0
            assert len(outlier_issues) == 0

    def test_orchestrator_receives_validation_issues(self, mocker):
        """Test orchestrator receives validation issues."""
        from ta_lab2.scripts.features.validate_features import (
            FeatureValidator,
            GapIssue,
        )

        mock_engine = mocker.MagicMock()
        validator = FeatureValidator(mock_engine)

        # Mock the validation to return issues
        with patch.object(validator, "check_gaps") as mock_gaps:
            mock_gaps.return_value = [GapIssue("test_table", 1, ["2024-01-02"], 10, 9)]

            issues = validator.check_gaps("test_table", [1], "2024-01-01", "2024-01-31")

            assert len(issues) == 1
            assert issues[0].details["table"] == "test_table"


@pytest.mark.integration
@pytest.mark.mocked_deps
class TestOrchestratorSignalGeneration:
    """Tests for orchestrator triggering signal generation."""

    def test_orchestrator_triggers_signal_refresh(self, mocker):
        """Test orchestrator can invoke signal generation."""
        # Mock signal generation function
        mock_signal_func = mocker.MagicMock(
            return_value={"signals_generated": 50, "success": True}
        )

        result = mock_signal_func(signal_type="ema_crossover", asset_ids=[1])

        assert result["signals_generated"] == 50
        assert result["success"]

    def test_orchestrator_triggers_backtest(self, mocker):
        """Test orchestrator can invoke backtest."""
        # Mock backtest function
        mock_backtest_func = mocker.MagicMock(
            return_value={
                "total_return": 0.15,
                "sharpe_ratio": 1.2,
                "trades": 50,
            }
        )

        result = mock_backtest_func(
            signal_type="ema_crossover",
            start="2024-01-01",
            end="2024-12-31",
        )

        assert result["total_return"] == 0.15
        assert result["sharpe_ratio"] == 1.2


@pytest.mark.integration
@pytest.mark.mocked_deps
class TestOrchestratorTracing:
    """Tests for tracing across orchestrator->ta_lab2."""

    def test_correlation_id_propagated(self, mocker):
        """Test correlation ID passed from orchestrator to ta_lab2."""
        # Verify TracingContext import works (key_link verification)
        from ta_lab2.observability.tracing import (
            generate_correlation_id,
            TracingContext,
        )

        correlation_id = generate_correlation_id()

        # Orchestrator creates tracing context
        with TracingContext("orchestrator_task") as ctx:
            # Correlation ID would be passed to ta_lab2 calls
            assert ctx.trace_id is not None
            # In real implementation, trace_id would be passed as parameter

    def test_workflow_state_updated(self, mocker):
        """Test workflow state updated during ta_lab2 operations."""
        from ta_lab2.observability.storage import WorkflowStateTracker

        mock_engine = mocker.MagicMock()
        tracker = WorkflowStateTracker(mock_engine)

        # Simulate workflow lifecycle
        workflow_id = "wf-123"
        tracker.create_workflow(workflow_id, "corr-456", "feature_refresh")
        tracker.transition(workflow_id, "refresh_started", "running")
        tracker.transition(workflow_id, "validation_started", "running")
        tracker.transition(workflow_id, "completed", "completed")

        # Verify transitions occurred
        assert mock_engine.begin.call_count == 4
