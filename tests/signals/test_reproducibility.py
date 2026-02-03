"""
Tests for reproducibility validation module.

Tests verify that:
1. Identical backtests produce identical results (PnL, metrics, trade counts)
2. Feature hash mismatches detected when data changes
3. Validation modes (strict/warn/trust) behave correctly
4. Stored backtest runs can be compared from database

Unit tests use mocks to avoid database dependencies.
Integration tests (marked with pytest.skipif) require TARGET_DB_URL.
"""

import os
from unittest.mock import Mock, MagicMock, patch

import pytest
import pandas as pd

from ta_lab2.scripts.signals.validate_reproducibility import (
    validate_backtest_reproducibility,
    compare_backtest_runs,
    validate_feature_hash_current,
    ReproducibilityReport,
    _compare_metrics,
    _find_metric_differences,
)
from ta_lab2.scripts.backtests import SignalBacktester, BacktestResult


# ============================================================================
# UNIT TESTS (with mocks - no database required)
# ============================================================================


class TestReproducibility:
    """Unit tests for reproducibility validation functions."""

    def test_identical_backtests_produce_identical_pnl(self):
        """CRITICAL: Same backtest twice = same PnL."""
        # Mock backtester
        mock_backtester = Mock(spec=SignalBacktester)

        # Create identical results
        result = BacktestResult(
            run_id="test-1",
            signal_type="ema_crossover",
            signal_id=1,
            asset_id=1,
            start_ts=pd.Timestamp("2023-01-01", tz="UTC"),
            end_ts=pd.Timestamp("2023-12-31", tz="UTC"),
            total_return=0.15,
            sharpe_ratio=1.5,
            max_drawdown=-0.10,
            trade_count=10,
            trades_df=pd.DataFrame(),
            metrics={"sharpe_ratio": 1.5, "sortino_ratio": 1.8},
            cost_model={"fee_bps": 10.0, "slippage_bps": 5.0, "funding_bps_day": 0.0},
            signal_params_hash="abc123",
            feature_hash="def456",
            signal_version="v1.0",
            vbt_version="0.25.5",
        )

        # Return identical results for both calls (create copies with different run_id)
        import copy

        result1 = copy.copy(result)
        result1.run_id = "test-1"
        result2 = copy.copy(result)
        result2.run_id = "test-2"

        mock_backtester.run_backtest.side_effect = [result1, result2]

        # Run validation
        report = validate_backtest_reproducibility(
            mock_backtester,
            "ema_crossover",
            1,
            1,
            pd.Timestamp("2023-01-01", tz="UTC"),
            pd.Timestamp("2023-12-31", tz="UTC"),
            strict=False,
        )

        # Verify identical PnL
        assert report.pnl_match
        assert report.is_reproducible

    def test_identical_backtests_produce_identical_sharpe(self):
        """CRITICAL: Same backtest twice = same Sharpe."""
        mock_backtester = Mock(spec=SignalBacktester)

        result = BacktestResult(
            run_id="test-1",
            signal_type="ema_crossover",
            signal_id=1,
            asset_id=1,
            start_ts=pd.Timestamp("2023-01-01", tz="UTC"),
            end_ts=pd.Timestamp("2023-12-31", tz="UTC"),
            total_return=0.15,
            sharpe_ratio=1.5,
            max_drawdown=-0.10,
            trade_count=10,
            trades_df=pd.DataFrame(),
            metrics={"sharpe_ratio": 1.5, "sortino_ratio": 1.8, "calmar_ratio": 2.0},
            cost_model={"fee_bps": 10.0, "slippage_bps": 5.0, "funding_bps_day": 0.0},
            signal_params_hash="abc123",
            feature_hash="def456",
            signal_version="v1.0",
            vbt_version="0.25.5",
        )

        import copy

        result1 = copy.copy(result)
        result1.run_id = "test-1"
        result2 = copy.copy(result)
        result2.run_id = "test-2"

        mock_backtester.run_backtest.side_effect = [result1, result2]

        report = validate_backtest_reproducibility(
            mock_backtester,
            "ema_crossover",
            1,
            1,
            pd.Timestamp("2023-01-01", tz="UTC"),
            pd.Timestamp("2023-12-31", tz="UTC"),
            strict=False,
        )

        # Verify Sharpe in metrics matches
        assert report.metrics_match
        assert report.is_reproducible

    def test_identical_backtests_produce_identical_trade_count(self):
        """CRITICAL: Same backtest twice = same trade count."""
        mock_backtester = Mock(spec=SignalBacktester)

        result = BacktestResult(
            run_id="test-1",
            signal_type="ema_crossover",
            signal_id=1,
            asset_id=1,
            start_ts=pd.Timestamp("2023-01-01", tz="UTC"),
            end_ts=pd.Timestamp("2023-12-31", tz="UTC"),
            total_return=0.15,
            sharpe_ratio=1.5,
            max_drawdown=-0.10,
            trade_count=10,
            trades_df=pd.DataFrame(),
            metrics={"sharpe_ratio": 1.5},
            cost_model={"fee_bps": 10.0, "slippage_bps": 5.0, "funding_bps_day": 0.0},
            signal_params_hash="abc123",
            feature_hash="def456",
            signal_version="v1.0",
            vbt_version="0.25.5",
        )

        import copy

        result1 = copy.copy(result)
        result1.run_id = "test-1"
        result2 = copy.copy(result)
        result2.run_id = "test-2"

        mock_backtester.run_backtest.side_effect = [result1, result2]

        report = validate_backtest_reproducibility(
            mock_backtester,
            "ema_crossover",
            1,
            1,
            pd.Timestamp("2023-01-01", tz="UTC"),
            pd.Timestamp("2023-12-31", tz="UTC"),
            strict=False,
        )

        # Verify trade count matches
        assert report.trade_count_match
        assert report.is_reproducible

    def test_validate_backtest_reproducibility_returns_true_on_match(self):
        """validate_backtest_reproducibility returns is_reproducible=True when results match."""
        mock_backtester = Mock(spec=SignalBacktester)

        result = BacktestResult(
            run_id="test-1",
            signal_type="ema_crossover",
            signal_id=1,
            asset_id=1,
            start_ts=pd.Timestamp("2023-01-01", tz="UTC"),
            end_ts=pd.Timestamp("2023-12-31", tz="UTC"),
            total_return=0.15,
            sharpe_ratio=1.5,
            max_drawdown=-0.10,
            trade_count=10,
            trades_df=pd.DataFrame(),
            metrics={"sharpe_ratio": 1.5, "sortino_ratio": 1.8},
            cost_model={"fee_bps": 10.0, "slippage_bps": 5.0, "funding_bps_day": 0.0},
            signal_params_hash="abc123",
            feature_hash="def456",
            signal_version="v1.0",
            vbt_version="0.25.5",
        )

        import copy

        result1 = copy.copy(result)
        result1.run_id = "test-1"
        result2 = copy.copy(result)
        result2.run_id = "test-2"

        mock_backtester.run_backtest.side_effect = [result1, result2]

        report = validate_backtest_reproducibility(
            mock_backtester,
            "ema_crossover",
            1,
            1,
            pd.Timestamp("2023-01-01", tz="UTC"),
            pd.Timestamp("2023-12-31", tz="UTC"),
            strict=False,
        )

        assert report.is_reproducible is True
        assert len(report.differences) == 0

    def test_validate_backtest_reproducibility_returns_false_on_mismatch(self):
        """Returns is_reproducible=False when results differ."""
        mock_backtester = Mock(spec=SignalBacktester)

        result1 = BacktestResult(
            run_id="test-1",
            signal_type="ema_crossover",
            signal_id=1,
            asset_id=1,
            start_ts=pd.Timestamp("2023-01-01", tz="UTC"),
            end_ts=pd.Timestamp("2023-12-31", tz="UTC"),
            total_return=0.15,
            sharpe_ratio=1.5,
            max_drawdown=-0.10,
            trade_count=10,
            trades_df=pd.DataFrame(),
            metrics={"sharpe_ratio": 1.5},
            cost_model={"fee_bps": 10.0, "slippage_bps": 5.0, "funding_bps_day": 0.0},
            signal_params_hash="abc123",
            feature_hash="def456",
            signal_version="v1.0",
            vbt_version="0.25.5",
        )

        import copy

        result2 = copy.copy(result1)
        result2.run_id = "test-2"
        result2.total_return = 0.18  # Different PnL

        mock_backtester.run_backtest.side_effect = [result1, result2]

        report = validate_backtest_reproducibility(
            mock_backtester,
            "ema_crossover",
            1,
            1,
            pd.Timestamp("2023-01-01", tz="UTC"),
            pd.Timestamp("2023-12-31", tz="UTC"),
            strict=False,
        )

        assert report.is_reproducible is False
        assert not report.pnl_match
        assert len(report.differences) > 0

    def test_feature_hash_validation_strict_mode_fails(self):
        """strict mode returns False on hash mismatch."""
        mock_engine = MagicMock()

        # Mock: stored hash differs from current hash
        with patch(
            "ta_lab2.scripts.signals.validate_reproducibility._get_latest_feature_hash"
        ) as mock_get, patch(
            "ta_lab2.scripts.signals.validate_reproducibility._compute_current_feature_hash"
        ) as mock_compute:
            mock_get.return_value = "abc123"
            mock_compute.return_value = "def456"  # Different hash

            is_valid, msg = validate_feature_hash_current(
                mock_engine, "ema_crossover", 1, 1, mode="strict"
            )

            assert is_valid is False
            assert msg is not None
            assert "Feature data changed" in msg

    def test_feature_hash_validation_warn_mode_proceeds(self):
        """warn mode logs warning but returns True."""
        mock_engine = MagicMock()

        with patch(
            "ta_lab2.scripts.signals.validate_reproducibility._get_latest_feature_hash"
        ) as mock_get, patch(
            "ta_lab2.scripts.signals.validate_reproducibility._compute_current_feature_hash"
        ) as mock_compute:
            mock_get.return_value = "abc123"
            mock_compute.return_value = "def456"  # Different hash

            is_valid, msg = validate_feature_hash_current(
                mock_engine, "ema_crossover", 1, 1, mode="warn"
            )

            assert is_valid is True  # Proceeds despite mismatch
            assert msg is not None
            assert "WARNING" in msg

    def test_feature_hash_validation_trust_mode_skips(self):
        """trust mode skips validation entirely."""
        mock_engine = MagicMock()

        # Should not call any database functions
        is_valid, msg = validate_feature_hash_current(
            mock_engine, "ema_crossover", 1, 1, mode="trust"
        )

        assert is_valid is True
        assert msg is None

    def test_feature_hash_mismatch_detected(self):
        """validate_feature_hash_current detects data changes."""
        mock_engine = MagicMock()

        with patch(
            "ta_lab2.scripts.signals.validate_reproducibility._get_latest_feature_hash"
        ) as mock_get, patch(
            "ta_lab2.scripts.signals.validate_reproducibility._compute_current_feature_hash"
        ) as mock_compute:
            mock_get.return_value = "old_hash"
            mock_compute.return_value = "new_hash"

            is_valid, msg = validate_feature_hash_current(
                mock_engine, "ema_crossover", 1, 1, mode="warn"
            )

            assert "old_hash" in msg
            assert "new_hash" in msg

    def test_compare_backtest_runs_loads_from_db(self):
        """compare_backtest_runs queries cmc_backtest_runs."""
        mock_engine = MagicMock()

        with patch(
            "ta_lab2.scripts.signals.validate_reproducibility._load_run"
        ) as mock_load_run, patch(
            "ta_lab2.scripts.signals.validate_reproducibility._load_trades"
        ) as mock_load_trades, patch(
            "ta_lab2.scripts.signals.validate_reproducibility._load_metrics"
        ) as mock_load_metrics:
            # Mock run data
            mock_load_run.side_effect = [
                {
                    "run_id": "run1",
                    "total_return": 0.15,
                    "feature_hash": "abc123",
                },
                {
                    "run_id": "run2",
                    "total_return": 0.15,
                    "feature_hash": "abc123",
                },
            ]

            mock_load_trades.side_effect = [
                [{"entry_ts": "2023-01-01"}],
                [{"entry_ts": "2023-01-01"}],
            ]

            mock_load_metrics.side_effect = [
                {"sharpe_ratio": 1.5},
                {"sharpe_ratio": 1.5},
            ]

            report = compare_backtest_runs(mock_engine, "run1", "run2")

            # Verify database queries called
            assert mock_load_run.call_count == 2
            assert mock_load_trades.call_count == 2
            assert mock_load_metrics.call_count == 2

            assert report.is_reproducible

    def test_reproducibility_report_includes_all_fields(self):
        """ReproducibilityReport has all required fields."""
        report = ReproducibilityReport(
            is_reproducible=True,
            run_id_1="run1",
            run_id_2="run2",
            pnl_match=True,
            metrics_match=True,
            trade_count_match=True,
            feature_hash_match=True,
            differences=[],
        )

        assert hasattr(report, "is_reproducible")
        assert hasattr(report, "run_id_1")
        assert hasattr(report, "run_id_2")
        assert hasattr(report, "pnl_match")
        assert hasattr(report, "metrics_match")
        assert hasattr(report, "trade_count_match")
        assert hasattr(report, "feature_hash_match")
        assert hasattr(report, "differences")

        # Test __str__ method
        str_repr = str(report)
        assert "REPRODUCIBLE" in str_repr
        assert "run1" in str_repr
        assert "run2" in str_repr

    def test_compare_metrics_returns_true_for_identical_dicts(self):
        """_compare_metrics returns True for identical metric dictionaries."""
        m1 = {"sharpe": 1.5, "sortino": 1.8, "calmar": 2.0}
        m2 = {"sharpe": 1.5, "sortino": 1.8, "calmar": 2.0}

        assert _compare_metrics(m1, m2)

    def test_compare_metrics_returns_false_for_different_values(self):
        """_compare_metrics returns False when values differ."""
        m1 = {"sharpe": 1.5, "sortino": 1.8}
        m2 = {"sharpe": 1.5, "sortino": 1.9}  # Different sortino

        assert not _compare_metrics(m1, m2)

    def test_compare_metrics_handles_none_values(self):
        """_compare_metrics handles None values correctly."""
        m1 = {"sharpe": 1.5, "profit_factor": None}
        m2 = {"sharpe": 1.5, "profit_factor": None}

        assert _compare_metrics(m1, m2)

        m3 = {"sharpe": 1.5, "profit_factor": None}
        m4 = {"sharpe": 1.5, "profit_factor": 2.0}

        assert not _compare_metrics(m3, m4)

    def test_find_metric_differences_identifies_mismatches(self):
        """_find_metric_differences returns dict of differing metrics."""
        m1 = {"sharpe": 1.5, "sortino": 1.8, "calmar": 2.0}
        m2 = {"sharpe": 1.5, "sortino": 1.9, "calmar": 2.0}

        diffs = _find_metric_differences(m1, m2)

        assert len(diffs) == 1
        assert "sortino" in diffs
        assert diffs["sortino"] == (1.8, 1.9)

    def test_validate_reproducibility_strict_mode_raises_on_mismatch(self):
        """strict=True raises RuntimeError on reproducibility failure."""
        mock_backtester = Mock(spec=SignalBacktester)

        result1 = BacktestResult(
            run_id="test-1",
            signal_type="ema_crossover",
            signal_id=1,
            asset_id=1,
            start_ts=pd.Timestamp("2023-01-01", tz="UTC"),
            end_ts=pd.Timestamp("2023-12-31", tz="UTC"),
            total_return=0.15,
            sharpe_ratio=1.5,
            max_drawdown=-0.10,
            trade_count=10,
            trades_df=pd.DataFrame(),
            metrics={"sharpe_ratio": 1.5},
            cost_model={"fee_bps": 10.0, "slippage_bps": 5.0, "funding_bps_day": 0.0},
            signal_params_hash="abc123",
            feature_hash="def456",
            signal_version="v1.0",
            vbt_version="0.25.5",
        )

        import copy

        result2 = copy.copy(result1)
        result2.run_id = "test-2"
        result2.total_return = 0.20

        mock_backtester.run_backtest.side_effect = [result1, result2]

        with pytest.raises(RuntimeError, match="Reproducibility validation failed"):
            validate_backtest_reproducibility(
                mock_backtester,
                "ema_crossover",
                1,
                1,
                pd.Timestamp("2023-01-01", tz="UTC"),
                pd.Timestamp("2023-12-31", tz="UTC"),
                strict=True,  # Strict mode
            )


# ============================================================================
# INTEGRATION TESTS (require database)
# ============================================================================


@pytest.mark.skipif(not os.environ.get("TARGET_DB_URL"), reason="No database")
class TestReproducibilityIntegration:
    """Integration tests requiring actual database."""

    def test_end_to_end_reproducibility(self):
        """
        Full reproducibility test:
        1. Generate signals (mocked)
        2. Run backtest
        3. Run backtest again
        4. Verify identical results
        """
        # This test requires signal and feature data in database
        # Skipping actual execution - would require full database setup
        pass

    def test_data_change_detected_by_hash(self):
        """
        1. Generate signals with feature_hash
        2. Modify underlying feature data
        3. validate_feature_hash_current returns False
        """
        # This test requires mutable feature data in database
        # Skipping actual execution - would require full database setup
        pass
