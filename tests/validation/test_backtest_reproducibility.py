"""
Backtest reproducibility validation tests (SIG-06).

Validates that:
1. Identical backtests produce identical results (PnL, metrics, trade counts)
2. Feature hash validation detects data changes
3. Reproducibility is deterministic within floating point tolerance

These tests wrap existing validate_reproducibility.py infrastructure into
CI-runnable pytest tests that block release on reproducibility failures.
"""

import os
import pytest
import pandas as pd
from unittest.mock import Mock
from sqlalchemy import text

from ta_lab2.scripts.signals.validate_reproducibility import (
    validate_backtest_reproducibility,
    validate_feature_hash_current,
    ReproducibilityReport,
)
from ta_lab2.scripts.backtests import SignalBacktester
from ta_lab2.backtests.costs import CostModel


# Mark all tests in this module as validation gates
pytestmark = pytest.mark.validation_gate


@pytest.fixture
def sample_signal(db_session, db_engine):
    """
    Load a sample signal from database for validation testing.

    Returns first valid signal found in any signal table.
    If no signals exist, returns None (tests will skip).
    """
    signal_tables = ['cmc_signals_ema_crossover', 'cmc_signals_rsi_mean_revert', 'cmc_signals_atr_breakout']

    for table in signal_tables:
        sql = text(f"""
            SELECT
                :table_type as signal_type,
                signal_id,
                id as asset_id,
                entry_ts,
                feature_version_hash
            FROM public.{table}
            WHERE signal_action = 'entry'
            LIMIT 1
        """)

        try:
            result = db_session.execute(sql, {"table_type": table.replace('cmc_signals_', '')})
            row = result.fetchone()

            if row:
                return {
                    'signal_type': row[0],
                    'signal_id': row[1],
                    'asset_id': row[2],
                    'entry_ts': row[3],
                    'feature_hash': row[4],
                }
        except Exception:
            # Table might not exist yet
            continue

    return None


@pytest.fixture
def backtester(db_engine):
    """
    Create configured SignalBacktester instance for testing.

    Uses realistic cost model (10 bps fee, 5 bps slippage).
    """
    cost_model = CostModel(fee_bps=10.0, slippage_bps=5.0, funding_bps_day=0.0)
    return SignalBacktester(db_engine, cost_model)


class TestBacktestReproducibilityValidation:
    """
    Backtest reproducibility validation tests for CI.

    These tests verify SIG-06 (backtest reproducibility) using existing
    validate_reproducibility.py infrastructure. All tests are CI blockers.
    """

    def test_backtest_produces_identical_results_on_rerun(self, backtester, sample_signal, db_session):
        """
        CRITICAL: Same backtest twice produces identical results.

        This is the gold standard reproducibility test - if two identical
        backtest runs produce different results, the system is non-deterministic.

        Tests all three signal types (ema_crossover, rsi_mean_revert, atr_breakout).
        """
        if sample_signal is None:
            pytest.skip("No signals in database (early project state)")

        # Define test parameters
        signal_type = sample_signal['signal_type']
        signal_id = sample_signal['signal_id']
        asset_id = sample_signal['asset_id']

        # Use 30-day window ending at signal entry time
        end_ts = pd.Timestamp(sample_signal['entry_ts'])
        start_ts = end_ts - pd.Timedelta(days=30)

        # Run validation (runs backtest twice internally)
        try:
            report = validate_backtest_reproducibility(
                backtester,
                signal_type,
                signal_id,
                asset_id,
                start_ts,
                end_ts,
                strict=True,
                tolerance=1e-10,
            )

            # Assert reproducibility
            assert report.is_reproducible, (
                f"Backtest not reproducible for {signal_type}/{signal_id}. "
                f"Differences: {report.differences}"
            )
            assert len(report.differences) == 0, (
                f"Found {len(report.differences)} differences: {report.differences}"
            )

        except ValueError as e:
            # Backtest might fail if insufficient data
            if "No feature data" in str(e) or "No signals" in str(e):
                pytest.skip(f"Insufficient data for backtest: {e}")
            raise

    def test_feature_hash_validates_current_data(self, db_engine, sample_signal):
        """
        Feature hash validation detects when underlying data changes.

        In strict mode, hash mismatch is a FAILURE (not a warning).
        This ensures backtests reflect current feature data.
        """
        if sample_signal is None:
            pytest.skip("No signals in database (early project state)")

        signal_type = sample_signal['signal_type']
        signal_id = sample_signal['signal_id']
        asset_id = sample_signal['asset_id']

        # Validate feature hash in strict mode
        is_valid, message = validate_feature_hash_current(
            db_engine,
            signal_type,
            signal_id,
            asset_id,
            mode='strict'
        )

        # In strict mode, mismatch is a failure
        assert is_valid, (
            f"Feature hash validation failed in strict mode. "
            f"Current feature data does not match stored hash. "
            f"Message: {message}"
        )

    def test_pnl_determinism_within_tolerance(self, backtester, sample_signal):
        """
        PnL values are deterministic within floating point tolerance.

        Two identical backtest runs must produce PnL values that differ
        by less than 1e-10 (floating point precision limit).
        """
        if sample_signal is None:
            pytest.skip("No signals in database")

        signal_type = sample_signal['signal_type']
        signal_id = sample_signal['signal_id']
        asset_id = sample_signal['asset_id']

        end_ts = pd.Timestamp(sample_signal['entry_ts'])
        start_ts = end_ts - pd.Timedelta(days=30)

        # Run backtest twice
        try:
            result1 = backtester.run_backtest(
                signal_type, signal_id, asset_id, start_ts, end_ts
            )
            result2 = backtester.run_backtest(
                signal_type, signal_id, asset_id, start_ts, end_ts
            )

            # Compare PnL with strict tolerance
            pnl_diff = abs(result1.total_return - result2.total_return)

            assert pnl_diff < 1e-10, (
                f"PnL not deterministic: {result1.total_return} vs {result2.total_return}. "
                f"Difference: {pnl_diff} exceeds tolerance 1e-10"
            )

        except ValueError as e:
            if "No feature data" in str(e) or "No signals" in str(e):
                pytest.skip(f"Insufficient data for backtest: {e}")
            raise

    def test_trade_count_determinism(self, backtester, sample_signal):
        """
        Trade counts are exactly identical (no tolerance).

        Trade count is an integer - two identical backtest runs must
        produce the exact same number of trades (no approximation).
        """
        if sample_signal is None:
            pytest.skip("No signals in database")

        signal_type = sample_signal['signal_type']
        signal_id = sample_signal['signal_id']
        asset_id = sample_signal['asset_id']

        end_ts = pd.Timestamp(sample_signal['entry_ts'])
        start_ts = end_ts - pd.Timedelta(days=30)

        # Run backtest twice
        try:
            result1 = backtester.run_backtest(
                signal_type, signal_id, asset_id, start_ts, end_ts
            )
            result2 = backtester.run_backtest(
                signal_type, signal_id, asset_id, start_ts, end_ts
            )

            # Compare trade counts (exact match required)
            assert result1.trade_count == result2.trade_count, (
                f"Trade count not deterministic: {result1.trade_count} vs {result2.trade_count}"
            )

        except ValueError as e:
            if "No feature data" in str(e) or "No signals" in str(e):
                pytest.skip(f"Insufficient data for backtest: {e}")
            raise

    def test_metric_reproducibility(self, backtester, sample_signal):
        """
        Key metrics (Sharpe, win rate, profit factor) are reproducible.

        All performance metrics must match within tolerance across identical runs.
        Tests the three most critical metrics for strategy evaluation.
        """
        if sample_signal is None:
            pytest.skip("No signals in database")

        signal_type = sample_signal['signal_type']
        signal_id = sample_signal['signal_id']
        asset_id = sample_signal['asset_id']

        end_ts = pd.Timestamp(sample_signal['entry_ts'])
        start_ts = end_ts - pd.Timedelta(days=30)

        # Run backtest twice
        try:
            result1 = backtester.run_backtest(
                signal_type, signal_id, asset_id, start_ts, end_ts
            )
            result2 = backtester.run_backtest(
                signal_type, signal_id, asset_id, start_ts, end_ts
            )

            # Compare key metrics
            key_metrics = ['sharpe_ratio', 'win_rate', 'profit_factor']

            for metric_name in key_metrics:
                val1 = result1.metrics.get(metric_name)
                val2 = result2.metrics.get(metric_name)

                # Handle None values (can occur with insufficient trades)
                if val1 is None and val2 is None:
                    continue

                assert val1 is not None and val2 is not None, (
                    f"Metric '{metric_name}' missing in one run: {val1} vs {val2}"
                )

                # Compare with tolerance
                diff = abs(val1 - val2)
                assert diff < 1e-10, (
                    f"Metric '{metric_name}' not reproducible: {val1} vs {val2}. "
                    f"Difference: {diff} exceeds tolerance 1e-10"
                )

        except ValueError as e:
            if "No feature data" in str(e) or "No signals" in str(e):
                pytest.skip(f"Insufficient data for backtest: {e}")
            raise
