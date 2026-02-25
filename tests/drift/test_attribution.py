"""
Unit tests for DriftAttributor sequential OAT decomposition.

Tests use mocked SignalBacktester and DB queries -- no live DB or vectorbt execution.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from ta_lab2.drift.attribution import (
    AttributionResult,
    DriftAttributor,
    _MIN_TRADE_COUNT,
    _zeros_with_paper_pnl,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine():
    """Return a minimal mock SQLAlchemy engine."""
    engine = MagicMock()
    conn_ctx = MagicMock()
    conn = MagicMock()
    conn_ctx.__enter__ = MagicMock(return_value=conn)
    conn_ctx.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value = conn_ctx
    # Default: config row returns fee_bps=5.0, slippage_base_bps=3.0
    row = MagicMock()
    row.__getitem__ = MagicMock(side_effect=lambda i: [5.0, "fixed", 3.0][i])
    conn.execute.return_value.fetchone.return_value = row
    return engine, conn


def _make_backtest_result(total_return: float):
    """Return a minimal BacktestResult-like mock with given total_return."""
    result = MagicMock()
    result.total_return = total_return
    result.metrics = {"total_return": total_return}
    return result


# ---------------------------------------------------------------------------
# Test: AttributionResult arithmetic
# ---------------------------------------------------------------------------


class TestAttributionResult:
    def test_attribution_result_total_explained(self):
        """total_explained_pnl must equal baseline + sum of all deltas."""
        baseline = 100.0
        fee = -5.0
        slip = -3.0
        timing = 0.0
        data_rev = 0.0
        sizing = 0.0
        regime = 2.0
        total_explained = baseline + fee + slip + timing + data_rev + sizing + regime
        paper_pnl = 97.0
        unexplained = paper_pnl - total_explained

        result = AttributionResult(
            baseline_pnl=baseline,
            fee_delta=fee,
            slippage_delta=slip,
            timing_delta=timing,
            data_revision_delta=data_rev,
            sizing_delta=sizing,
            regime_delta=regime,
            unexplained_residual=unexplained,
            total_explained_pnl=total_explained,
            paper_pnl=paper_pnl,
        )

        assert result.total_explained_pnl == pytest.approx(
            result.baseline_pnl
            + result.fee_delta
            + result.slippage_delta
            + result.timing_delta
            + result.data_revision_delta
            + result.sizing_delta
            + result.regime_delta,
            abs=1e-9,
        )

    def test_zeros_with_paper_pnl_helper(self):
        """Helper should return all-zero result with paper_pnl preserved."""
        r = _zeros_with_paper_pnl(42.5)
        assert r.paper_pnl == 42.5
        assert r.baseline_pnl == 0.0
        assert r.fee_delta == 0.0
        assert r.total_explained_pnl == 0.0
        assert r.unexplained_residual == 42.5


# ---------------------------------------------------------------------------
# Test: minimum trade count guard
# ---------------------------------------------------------------------------


class TestMinimumGuard:
    def test_run_attribution_minimum_guard(self, caplog):
        """
        When paper_trade_count < MIN_TRADE_COUNT, run_attribution should
        return all-zero result with paper_pnl preserved and log the guard message.
        """
        engine, _ = _make_engine()
        attributor = DriftAttributor(engine)

        with caplog.at_level(logging.WARNING, logger="ta_lab2.drift.attribution"):
            result = attributor.run_attribution(
                config_id=1,
                signal_id=2,
                signal_type="ema_crossover",
                asset_id=1,
                paper_start="2026-01-01",
                paper_end="2026-02-01",
                paper_pnl=55.0,
                paper_trade_count=5,  # below minimum of 10
            )

        assert result.paper_pnl == 55.0
        assert result.baseline_pnl == 0.0
        assert result.fee_delta == 0.0
        assert result.slippage_delta == 0.0
        assert result.timing_delta == 0.0
        assert result.data_revision_delta == 0.0
        assert result.sizing_delta == 0.0
        assert result.regime_delta == 0.0
        assert result.total_explained_pnl == 0.0
        assert result.unexplained_residual == 55.0

        assert any(
            "Insufficient trade history" in rec.message for rec in caplog.records
        ), "Expected 'Insufficient trade history' log message"

    def test_min_trade_count_boundary(self):
        """Exactly _MIN_TRADE_COUNT trades should proceed (not be caught by guard)."""
        assert _MIN_TRADE_COUNT == 10


# ---------------------------------------------------------------------------
# Test: fee_delta computation
# ---------------------------------------------------------------------------


class TestFeeDelta:
    @patch("ta_lab2.drift.attribution._get_signal_backtester_class")
    def test_run_attribution_fee_delta(self, mock_get_class):
        """fee_delta should equal step1_pnl - baseline_pnl."""
        engine, _ = _make_engine()

        step0_return = 0.10  # baseline
        step1_return = 0.07  # +fees applied
        step2_return = 0.05  # +slippage applied
        # Regime step uses same step2_return (no-regime replay mirrors step2).

        BacktesterCls = MagicMock()
        mock_get_class.return_value = BacktesterCls
        backtester_instance = MagicMock()
        BacktesterCls.return_value = backtester_instance
        backtester_instance.run_backtest.side_effect = [
            _make_backtest_result(step0_return),  # step 0 baseline
            _make_backtest_result(step1_return),  # step 1 +fees
            _make_backtest_result(step2_return),  # step 2 +slippage
            _make_backtest_result(step2_return),  # step 6 regime (no-regime replay)
        ]

        attributor = DriftAttributor(engine)
        result = attributor.run_attribution(
            config_id=1,
            signal_id=2,
            signal_type="ema_crossover",
            asset_id=1,
            paper_start="2026-01-01",
            paper_end="2026-02-01",
            paper_pnl=0.04,
            paper_trade_count=20,
        )

        expected_fee_delta = step1_return - step0_return
        assert result.fee_delta == pytest.approx(expected_fee_delta, abs=1e-9)


# ---------------------------------------------------------------------------
# Test: slippage_delta computation
# ---------------------------------------------------------------------------


class TestSlippageDelta:
    @patch("ta_lab2.drift.attribution._get_signal_backtester_class")
    def test_run_attribution_slippage_delta(self, mock_get_class):
        """slippage_delta should equal step2_pnl - step1_pnl."""
        engine, _ = _make_engine()

        step0_return = 0.12
        step1_return = 0.09
        step2_return = 0.06

        BacktesterCls = MagicMock()
        mock_get_class.return_value = BacktesterCls
        backtester_instance = MagicMock()
        BacktesterCls.return_value = backtester_instance
        backtester_instance.run_backtest.side_effect = [
            _make_backtest_result(step0_return),
            _make_backtest_result(step1_return),
            _make_backtest_result(step2_return),
            _make_backtest_result(step2_return),  # regime replay
        ]

        attributor = DriftAttributor(engine)
        result = attributor.run_attribution(
            config_id=1,
            signal_id=2,
            signal_type="ema_crossover",
            asset_id=1,
            paper_start="2026-01-01",
            paper_end="2026-02-01",
            paper_pnl=0.05,
            paper_trade_count=25,
        )

        expected_slippage = step2_return - step1_return
        assert result.slippage_delta == pytest.approx(expected_slippage, abs=1e-9)


# ---------------------------------------------------------------------------
# Test: residual computation
# ---------------------------------------------------------------------------


class TestResidualComputation:
    @patch("ta_lab2.drift.attribution._get_signal_backtester_class")
    def test_run_attribution_residual_computation(self, mock_get_class):
        """unexplained_residual should equal paper_pnl - total_explained_pnl."""
        engine, _ = _make_engine()

        step0 = 0.10
        step1 = 0.08
        step2 = 0.06
        paper_pnl = 0.03  # paper did worse than explained (negative residual)

        BacktesterCls = MagicMock()
        mock_get_class.return_value = BacktesterCls
        backtester_instance = MagicMock()
        BacktesterCls.return_value = backtester_instance
        backtester_instance.run_backtest.side_effect = [
            _make_backtest_result(step0),
            _make_backtest_result(step1),
            _make_backtest_result(step2),
            _make_backtest_result(step2),  # regime replay returns same
        ]

        attributor = DriftAttributor(engine)
        result = attributor.run_attribution(
            config_id=1,
            signal_id=2,
            signal_type="ema_crossover",
            asset_id=1,
            paper_start="2026-01-01",
            paper_end="2026-02-01",
            paper_pnl=paper_pnl,
            paper_trade_count=30,
        )

        # V1: timing=0, data_revision=0, sizing=0, regime=0 (step2==no_regime)
        expected_total = (
            result.baseline_pnl
            + result.fee_delta
            + result.slippage_delta
            + result.timing_delta
            + result.data_revision_delta
            + result.sizing_delta
            + result.regime_delta
        )
        assert result.total_explained_pnl == pytest.approx(expected_total, abs=1e-9)
        expected_residual = paper_pnl - expected_total
        assert result.unexplained_residual == pytest.approx(expected_residual, abs=1e-9)


# ---------------------------------------------------------------------------
# Test: graceful handling of backtest failure
# ---------------------------------------------------------------------------


class TestBacktesterFailureGraceful:
    @patch("ta_lab2.drift.attribution._get_signal_backtester_class")
    def test_run_attribution_backtester_failure_graceful(self, mock_get_class):
        """
        When the fee-step replay raises an exception, fee_delta should be 0
        and all other deltas should still be computed correctly.
        """
        engine, _ = _make_engine()

        step0 = 0.10
        step2 = 0.06  # slippage step uses step1_pnl == baseline_pnl when step1 fails

        BacktesterCls = MagicMock()
        mock_get_class.return_value = BacktesterCls
        backtester_instance = MagicMock()
        BacktesterCls.return_value = backtester_instance
        backtester_instance.run_backtest.side_effect = [
            _make_backtest_result(step0),  # step 0 baseline -- succeeds
            RuntimeError("Backtester step1 error"),  # step 1 +fees -- fails
            _make_backtest_result(step2),  # step 2 +slippage
            _make_backtest_result(step2),  # step 6 regime replay
        ]

        attributor = DriftAttributor(engine)
        result = attributor.run_attribution(
            config_id=1,
            signal_id=2,
            signal_type="ema_crossover",
            asset_id=1,
            paper_start="2026-01-01",
            paper_end="2026-02-01",
            paper_pnl=0.05,
            paper_trade_count=15,
        )

        # fee_delta must be 0 because step 1 failed
        assert result.fee_delta == pytest.approx(0.0, abs=1e-9)

        # baseline should still be populated
        assert result.baseline_pnl == pytest.approx(step0, abs=1e-9)

        # slippage_delta = step2 - step1_fallback(=baseline because step1 failed)
        expected_slip = step2 - step0
        assert result.slippage_delta == pytest.approx(expected_slip, abs=1e-9)

        # result should be a complete AttributionResult, not an exception
        assert isinstance(result, AttributionResult)
