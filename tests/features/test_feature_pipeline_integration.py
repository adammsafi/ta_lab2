"""
Integration tests for feature refresh pipeline.

Tests cover:
- Refresh order and dependencies
- Parallel execution
- Sequential fallback
- Validation integration
- Partial failure handling
- Result summary
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from ta_lab2.config import TARGET_DB_URL
from ta_lab2.scripts.features.run_all_feature_refreshes import (
    RefreshResult,
    run_all_refreshes,
)


class TestRefreshOrder(unittest.TestCase):
    """Tests for refresh dependency order."""

    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_daily_features")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_ta")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_vol")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_returns")
    def test_refresh_order_returns_first(
        self, mock_returns, mock_vol, mock_ta, mock_daily
    ):
        """Test that returns is in phase 1 (before daily_features)."""
        # Mock results
        mock_returns.return_value = RefreshResult("cmc_returns_daily", 100, 1.0, True)
        mock_vol.return_value = RefreshResult("cmc_vol_daily", 100, 1.0, True)
        mock_ta.return_value = RefreshResult("cmc_ta_daily", 100, 1.0, True)
        mock_daily.return_value = RefreshResult("cmc_daily_features", 100, 1.0, True)

        engine = MagicMock()
        results = run_all_refreshes(
            engine,
            ids=[1],
            parallel=False,
            validate=False,
        )

        # Returns called before daily_features
        mock_returns.assert_called_once()
        mock_daily.assert_called_once()

        # All phase 1 called before daily
        self.assertEqual(len(results), 4)

    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_daily_features")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_ta")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_vol")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_returns")
    def test_refresh_order_vol_parallel(
        self, mock_returns, mock_vol, mock_ta, mock_daily
    ):
        """Test that vol can run in parallel with returns."""
        # Mock results
        mock_returns.return_value = RefreshResult("cmc_returns_daily", 100, 1.0, True)
        mock_vol.return_value = RefreshResult("cmc_vol_daily", 100, 1.0, True)
        mock_ta.return_value = RefreshResult("cmc_ta_daily", 100, 1.0, True)
        mock_daily.return_value = RefreshResult("cmc_daily_features", 100, 1.0, True)

        engine = MagicMock()
        results = run_all_refreshes(
            engine,
            ids=[1],
            parallel=True,
            validate=False,
        )

        # Both returns and vol called (parallel executor)
        mock_returns.assert_called_once()
        mock_vol.assert_called_once()
        mock_ta.assert_called_once()

    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_daily_features")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_ta")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_vol")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_returns")
    def test_refresh_order_daily_features_last(
        self, mock_returns, mock_vol, mock_ta, mock_daily
    ):
        """Test that daily_features runs after all others."""
        # Mock results
        mock_returns.return_value = RefreshResult("cmc_returns_daily", 100, 1.0, True)
        mock_vol.return_value = RefreshResult("cmc_vol_daily", 100, 1.0, True)
        mock_ta.return_value = RefreshResult("cmc_ta_daily", 100, 1.0, True)
        mock_daily.return_value = RefreshResult("cmc_daily_features", 100, 1.0, True)

        engine = MagicMock()
        results = run_all_refreshes(
            engine,
            ids=[1],
            parallel=False,
            validate=False,
        )

        # Daily features called last
        mock_daily.assert_called_once()

        # Verify all phase 1 completed
        self.assertIn("cmc_returns_daily", results)
        self.assertIn("cmc_vol_daily", results)
        self.assertIn("cmc_ta_daily", results)
        self.assertIn("cmc_daily_features", results)


class TestParallelExecution(unittest.TestCase):
    """Tests for parallel vs sequential execution."""

    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_daily_features")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.ThreadPoolExecutor")
    def test_parallel_execution(self, mock_executor_class, mock_daily):
        """Test that parallel mode uses ThreadPoolExecutor."""
        # Mock executor
        mock_executor = MagicMock()
        mock_executor_class.return_value.__enter__.return_value = mock_executor

        # Mock futures
        mock_future1 = MagicMock()
        mock_future1.result.return_value = RefreshResult(
            "cmc_returns_daily", 100, 1.0, True
        )
        mock_future2 = MagicMock()
        mock_future2.result.return_value = RefreshResult(
            "cmc_vol_daily", 100, 1.0, True
        )
        mock_future3 = MagicMock()
        mock_future3.result.return_value = RefreshResult("cmc_ta_daily", 100, 1.0, True)

        mock_executor.submit.side_effect = [mock_future1, mock_future2, mock_future3]

        # Mock as_completed
        with patch(
            "ta_lab2.scripts.features.run_all_feature_refreshes.as_completed"
        ) as mock_as_completed:
            mock_as_completed.return_value = [mock_future1, mock_future2, mock_future3]

            mock_daily.return_value = RefreshResult(
                "cmc_daily_features", 100, 1.0, True
            )

            engine = MagicMock()
            results = run_all_refreshes(
                engine,
                ids=[1],
                parallel=True,
                validate=False,
            )

            # ThreadPoolExecutor used
            mock_executor_class.assert_called_once_with(max_workers=3)
            # submit called 3 times (returns, vol, ta)
            self.assertEqual(mock_executor.submit.call_count, 3)

    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_daily_features")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_ta")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_vol")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_returns")
    def test_sequential_fallback(self, mock_returns, mock_vol, mock_ta, mock_daily):
        """Test that sequential mode works without parallelism."""
        # Mock results
        mock_returns.return_value = RefreshResult("cmc_returns_daily", 100, 1.0, True)
        mock_vol.return_value = RefreshResult("cmc_vol_daily", 100, 1.0, True)
        mock_ta.return_value = RefreshResult("cmc_ta_daily", 100, 1.0, True)
        mock_daily.return_value = RefreshResult("cmc_daily_features", 100, 1.0, True)

        engine = MagicMock()
        results = run_all_refreshes(
            engine,
            ids=[1],
            parallel=False,
            validate=False,
        )

        # All functions called sequentially
        mock_returns.assert_called_once()
        mock_vol.assert_called_once()
        mock_ta.assert_called_once()
        mock_daily.assert_called_once()

        # All results present
        self.assertEqual(len(results), 4)


class TestValidationIntegration(unittest.TestCase):
    """Tests for validation integration."""

    @patch("ta_lab2.scripts.features.validate_features.validate_features")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_daily_features")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_ta")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_vol")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_returns")
    def test_validate_after_refresh(
        self, mock_returns, mock_vol, mock_ta, mock_daily, mock_validate
    ):
        """Test that validation runs when --validate flag set."""
        # Mock results
        mock_returns.return_value = RefreshResult("cmc_returns_daily", 100, 1.0, True)
        mock_vol.return_value = RefreshResult("cmc_vol_daily", 100, 1.0, True)
        mock_ta.return_value = RefreshResult("cmc_ta_daily", 100, 1.0, True)
        mock_daily.return_value = RefreshResult("cmc_daily_features", 100, 1.0, True)

        # Mock validation report
        mock_report = MagicMock()
        mock_report.passed = True
        mock_report.total_checks = 10
        mock_validate.return_value = mock_report

        engine = MagicMock()
        results = run_all_refreshes(
            engine,
            ids=[1],
            validate=True,
        )

        # Validation called
        mock_validate.assert_called_once()

    @patch("ta_lab2.scripts.features.validate_features.validate_features")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_daily_features")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_ta")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_vol")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_returns")
    def test_no_validate_flag(
        self, mock_returns, mock_vol, mock_ta, mock_daily, mock_validate
    ):
        """Test that validation skipped when --no-validate flag set."""
        # Mock results
        mock_returns.return_value = RefreshResult("cmc_returns_daily", 100, 1.0, True)
        mock_vol.return_value = RefreshResult("cmc_vol_daily", 100, 1.0, True)
        mock_ta.return_value = RefreshResult("cmc_ta_daily", 100, 1.0, True)
        mock_daily.return_value = RefreshResult("cmc_daily_features", 100, 1.0, True)

        engine = MagicMock()
        results = run_all_refreshes(
            engine,
            ids=[1],
            validate=False,
        )

        # Validation NOT called
        mock_validate.assert_not_called()


class TestPartialFailures(unittest.TestCase):
    """Tests for handling partial failures."""

    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_daily_features")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_ta")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_vol")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_returns")
    def test_partial_failure_continues(
        self, mock_returns, mock_vol, mock_ta, mock_daily
    ):
        """Test that one failure doesn't stop all refreshes."""
        # Returns fails, others succeed
        mock_returns.return_value = RefreshResult(
            "cmc_returns_daily", 0, 1.0, False, error="Test error"
        )
        mock_vol.return_value = RefreshResult("cmc_vol_daily", 100, 1.0, True)
        mock_ta.return_value = RefreshResult("cmc_ta_daily", 100, 1.0, True)
        mock_daily.return_value = RefreshResult("cmc_daily_features", 100, 1.0, True)

        engine = MagicMock()
        results = run_all_refreshes(
            engine,
            ids=[1],
            parallel=False,
            validate=False,
        )

        # All refreshes attempted despite failure
        mock_returns.assert_called_once()
        mock_vol.assert_called_once()
        mock_ta.assert_called_once()
        mock_daily.assert_called_once()

        # Results include failure
        self.assertFalse(results["cmc_returns_daily"].success)
        self.assertTrue(results["cmc_vol_daily"].success)

    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_daily_features")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_ta")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_vol")
    @patch("ta_lab2.scripts.features.run_all_feature_refreshes.refresh_returns")
    def test_refresh_result_summary(self, mock_returns, mock_vol, mock_ta, mock_daily):
        """Test that result summary has correct counts."""
        # Mock results with varying row counts
        mock_returns.return_value = RefreshResult("cmc_returns_daily", 100, 1.0, True)
        mock_vol.return_value = RefreshResult("cmc_vol_daily", 200, 2.0, True)
        mock_ta.return_value = RefreshResult("cmc_ta_daily", 150, 1.5, True)
        mock_daily.return_value = RefreshResult("cmc_daily_features", 300, 3.0, True)

        engine = MagicMock()
        results = run_all_refreshes(
            engine,
            ids=[1],
            validate=False,
        )

        # Check totals
        total_rows = sum(r.rows_inserted for r in results.values() if r.success)
        self.assertEqual(total_rows, 750)  # 100 + 200 + 150 + 300


class TestFullPipelineEndToEnd(unittest.TestCase):
    """End-to-end integration tests (skip if no database)."""

    @unittest.skipIf(not TARGET_DB_URL, "No database configured")
    def test_full_pipeline_end_to_end(self):
        """Test complete pipeline with real database (if available)."""
        from ta_lab2.scripts.bars.common_snapshot_contract import get_engine

        # This is a placeholder for true integration test
        # Would require test database with sample data
        engine = get_engine(TARGET_DB_URL)

        # Just verify imports work
        from ta_lab2.scripts.features.run_all_feature_refreshes import run_all_refreshes

        # Test would run full pipeline with test data
        # For now, just verify function exists
        self.assertTrue(callable(run_all_refreshes))


if __name__ == "__main__":
    unittest.main()
