"""
Unit tests for ParityChecker.

All tests use mock data and mock DB connections — no live database required.
Tests cover:
1. exact match zero slippage -> pass
2. trade count mismatch -> fail
3. price divergence below threshold -> pass
4. price divergence above threshold -> fail
5. lognormal high correlation -> pass
6. lognormal low correlation -> fail
7. format report pass output
8. format report fail output
9. empty trades -> fail
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ta_lab2.executor.parity_checker import ParityChecker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_checker() -> ParityChecker:
    """Create a ParityChecker with a mock engine (no real DB)."""
    engine = MagicMock()
    return ParityChecker(engine)


def _make_bt_trades(
    n: int,
    base_price: float = 50_000.0,
    pnl_values: list[float] | None = None,
) -> list[dict]:
    """Build n synthetic backtest trade dicts."""
    trades = []
    for i in range(n):
        pnl = pnl_values[i] if pnl_values else float(i * 100)
        trades.append(
            {
                "entry_ts": f"2024-01-{i + 1:02d}T00:00:00Z",
                "exit_ts": f"2024-01-{i + 1:02d}T12:00:00Z",
                "entry_price": base_price + i * 100.0,
                "exit_price": base_price + i * 100.0 + 500.0,
                "direction": "long",
                "pnl": pnl,
                "pnl_pct": pnl / (base_price + i * 100.0) * 100,
            }
        )
    return trades


def _make_exec_fills(
    n: int,
    base_price: float = 50_000.0,
    price_offset: float = 0.0,
) -> list[dict]:
    """Build n synthetic executor fill dicts."""
    fills = []
    for i in range(n):
        fills.append(
            {
                "filled_at": f"2024-01-{i + 1:02d}T00:00:01Z",
                "fill_price": base_price + i * 100.0 + price_offset,
                "fill_qty": 0.1,
                "side": "buy",
                "asset_id": 1,
                "signal_id": 1,
            }
        )
    return fills


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParityCheckerZeroSlippage:
    """Zero-slippage mode tests (exact match expected)."""

    def test_exact_match_zero_slippage_pass(self):
        """Test 1: Exact match in zero-slippage mode -> parity_pass=True."""
        checker = _make_checker()
        bt_trades = _make_bt_trades(5, base_price=50_000.0)
        exec_fills = _make_exec_fills(5, base_price=50_000.0, price_offset=0.0)

        with (
            patch.object(checker, "_load_backtest_trades", return_value=bt_trades),
            patch.object(checker, "_load_executor_fills", return_value=exec_fills),
        ):
            report = checker.check(
                config_id=1,
                signal_id=1,
                start_date="2024-01-01",
                end_date="2024-12-31",
                slippage_mode="zero",
            )

        assert report["parity_pass"] is True
        assert report["trade_count_match"] is True
        assert report["max_price_divergence_bps"] == 0.0
        assert report["backtest_trade_count"] == 5
        assert report["executor_fill_count"] == 5

    def test_trade_count_mismatch_fail(self):
        """Test 2: Trade count mismatch -> parity_pass=False."""
        checker = _make_checker()
        bt_trades = _make_bt_trades(47, base_price=50_000.0)
        exec_fills = _make_exec_fills(45, base_price=50_000.0)

        with (
            patch.object(checker, "_load_backtest_trades", return_value=bt_trades),
            patch.object(checker, "_load_executor_fills", return_value=exec_fills),
        ):
            report = checker.check(
                config_id=1,
                signal_id=1,
                start_date="2024-01-01",
                end_date="2024-12-31",
                slippage_mode="zero",
            )

        assert report["parity_pass"] is False
        assert report["trade_count_match"] is False
        assert report["backtest_trade_count"] == 47
        assert report["executor_fill_count"] == 45
        # No price divergence computed when counts mismatch
        assert report["max_price_divergence_bps"] is None

    def test_price_divergence_below_threshold_pass(self):
        """Test 3: Max price divergence < 1 bps -> parity_pass=True (zero mode)."""
        checker = _make_checker()
        base = 50_000.0
        # 0.5 bps offset: 50000 * 0.5 / 10000 = 2.5
        offset = base * 0.5 / 10_000
        bt_trades = _make_bt_trades(3, base_price=base)
        exec_fills = _make_exec_fills(3, base_price=base, price_offset=offset)

        with (
            patch.object(checker, "_load_backtest_trades", return_value=bt_trades),
            patch.object(checker, "_load_executor_fills", return_value=exec_fills),
        ):
            report = checker.check(
                config_id=1,
                signal_id=1,
                start_date="2024-01-01",
                end_date="2024-12-31",
                slippage_mode="zero",
            )

        assert report["trade_count_match"] is True
        assert report["max_price_divergence_bps"] < 1.0
        assert report["parity_pass"] is True

    def test_price_divergence_above_threshold_fail(self):
        """Test 4: Max price divergence >= 1 bps -> parity_pass=False (zero mode)."""
        checker = _make_checker()
        base = 50_000.0
        # 5 bps offset: 50000 * 5 / 10000 = 25.0
        offset = base * 5.0 / 10_000
        bt_trades = _make_bt_trades(3, base_price=base)
        exec_fills = _make_exec_fills(3, base_price=base, price_offset=offset)

        with (
            patch.object(checker, "_load_backtest_trades", return_value=bt_trades),
            patch.object(checker, "_load_executor_fills", return_value=exec_fills),
        ):
            report = checker.check(
                config_id=1,
                signal_id=1,
                start_date="2024-01-01",
                end_date="2024-12-31",
                slippage_mode="zero",
            )

        assert report["trade_count_match"] is True
        assert report["max_price_divergence_bps"] >= 1.0
        assert report["parity_pass"] is False


class TestParityCheckerLognormalMode:
    """Lognormal / fixed slippage mode tests (statistical match)."""

    def test_lognormal_high_correlation_pass(self):
        """Test 5: P&L correlation = 0.995 -> parity_pass=True (lognormal)."""
        checker = _make_checker()

        # Build pnl arrays that are highly correlated
        rng = np.random.default_rng(42)
        true_pnl = rng.normal(loc=100.0, scale=20.0, size=30).tolist()
        # Fill prices = true_pnl * scale so corrcoef is ~1.0
        fill_prices = [p * 1.001 + 0.01 for p in true_pnl]

        bt_trades = []
        exec_fills = []
        for i, (pnl, fp) in enumerate(zip(true_pnl, fill_prices)):
            bt_trades.append(
                {
                    "entry_ts": f"2024-01-{i % 28 + 1:02d}T00:00:00Z",
                    "entry_price": 50_000.0,
                    "exit_price": 50_500.0,
                    "pnl": pnl,
                    "pnl_pct": pnl / 50_000.0 * 100,
                }
            )
            exec_fills.append(
                {
                    "filled_at": f"2024-01-{i % 28 + 1:02d}T00:00:01Z",
                    "fill_price": fp,
                    "fill_qty": 0.1,
                    "side": "buy",
                    "asset_id": 1,
                    "signal_id": 1,
                }
            )

        with (
            patch.object(checker, "_load_backtest_trades", return_value=bt_trades),
            patch.object(checker, "_load_executor_fills", return_value=exec_fills),
        ):
            report = checker.check(
                config_id=1,
                signal_id=1,
                start_date="2024-01-01",
                end_date="2024-12-31",
                slippage_mode="lognormal",
            )

        assert report["pnl_correlation"] is not None
        assert report["pnl_correlation"] >= 0.99
        assert report["parity_pass"] is True

    def test_lognormal_low_correlation_fail(self):
        """Test 6: P&L correlation = 0.90 -> parity_pass=False (lognormal)."""
        checker = _make_checker()

        # Build two uncorrelated pnl arrays
        rng = np.random.default_rng(99)
        true_pnl = rng.normal(loc=100.0, scale=20.0, size=20).tolist()
        # Fill prices from an independent distribution
        fill_prices = rng.normal(loc=200.0, scale=50.0, size=20).tolist()

        bt_trades = []
        exec_fills = []
        for i, (pnl, fp) in enumerate(zip(true_pnl, fill_prices)):
            bt_trades.append(
                {
                    "entry_ts": f"2024-01-{i % 28 + 1:02d}T00:00:00Z",
                    "entry_price": 50_000.0,
                    "exit_price": 50_500.0,
                    "pnl": pnl,
                    "pnl_pct": pnl / 50_000.0 * 100,
                }
            )
            exec_fills.append(
                {
                    "filled_at": f"2024-01-{i % 28 + 1:02d}T00:00:01Z",
                    "fill_price": fp,
                    "fill_qty": 0.1,
                    "side": "buy",
                    "asset_id": 1,
                    "signal_id": 1,
                }
            )

        with (
            patch.object(checker, "_load_backtest_trades", return_value=bt_trades),
            patch.object(checker, "_load_executor_fills", return_value=exec_fills),
        ):
            report = checker.check(
                config_id=1,
                signal_id=1,
                start_date="2024-01-01",
                end_date="2024-12-31",
                slippage_mode="lognormal",
            )

        # Correlation should be far below 0.99 for independent arrays
        assert report["pnl_correlation"] is not None
        assert report["pnl_correlation"] < 0.99
        assert report["parity_pass"] is False


class TestParityCheckerFormatReport:
    """Format report string output tests."""

    def test_format_report_pass(self):
        """Test 7: format_report on passing report contains 'PASS'."""
        checker = _make_checker()
        report = {
            "config_id": 1,
            "signal_id": 1,
            "date_range": "2024-01-01 to 2024-12-31",
            "slippage_mode": "zero",
            "backtest_trade_count": 10,
            "executor_fill_count": 10,
            "trade_count_match": True,
            "max_price_divergence_bps": 0.05,
            "pnl_correlation": 0.9999,
            "tracking_error_pct": 0.1,
            "parity_pass": True,
        }

        output = checker.format_report(report)

        assert "PASS" in output
        assert "=== BACKTEST PARITY REPORT ===" in output
        assert "MATCH" in output
        assert "0.05" in output  # divergence bps
        assert "0.9999" in output  # correlation

    def test_format_report_fail(self):
        """Test 8: format_report on failing report contains 'FAIL'."""
        checker = _make_checker()
        report = {
            "config_id": None,
            "signal_id": 2,
            "date_range": "2024-01-01 to 2024-12-31",
            "slippage_mode": "zero",
            "backtest_trade_count": 47,
            "executor_fill_count": 45,
            "trade_count_match": False,
            "max_price_divergence_bps": None,
            "pnl_correlation": None,
            "tracking_error_pct": None,
            "parity_pass": False,
        }

        output = checker.format_report(report)

        assert "FAIL" in output
        assert "MISMATCH" in output
        assert "N/A" in output  # divergence and correlation N/A


class TestParityCheckerEdgeCases:
    """Edge case and boundary condition tests."""

    def test_empty_backtest_trades_fail(self):
        """Test 9: No backtest trades -> parity_pass=False with zero counts."""
        checker = _make_checker()

        with (
            patch.object(checker, "_load_backtest_trades", return_value=[]),
            patch.object(checker, "_load_executor_fills", return_value=[]),
        ):
            report = checker.check(
                config_id=None,
                signal_id=99,
                start_date="2024-01-01",
                end_date="2024-12-31",
                slippage_mode="zero",
            )

        assert report["parity_pass"] is False
        assert report["backtest_trade_count"] == 0
        assert report["executor_fill_count"] == 0
        # trade_count_match is True (0 == 0) but still fails on empty check
        assert report["max_price_divergence_bps"] is None
        assert report["pnl_correlation"] is None

    def test_report_contains_required_keys(self):
        """Verify report always contains all required parity report keys."""
        checker = _make_checker()
        bt_trades = _make_bt_trades(2)
        exec_fills = _make_exec_fills(2)

        with (
            patch.object(checker, "_load_backtest_trades", return_value=bt_trades),
            patch.object(checker, "_load_executor_fills", return_value=exec_fills),
        ):
            report = checker.check(
                config_id=1,
                signal_id=1,
                start_date="2024-01-01",
                end_date="2024-12-31",
            )

        required_keys = {
            "config_id",
            "signal_id",
            "date_range",
            "slippage_mode",
            "backtest_trade_count",
            "executor_fill_count",
            "trade_count_match",
            "max_price_divergence_bps",
            "pnl_correlation",
            "tracking_error_pct",
            "parity_pass",
        }
        assert required_keys.issubset(report.keys())

    def test_fixed_mode_high_correlation_pass(self):
        """Test fixed slippage mode behaves same as lognormal (correlation >= 0.99)."""
        checker = _make_checker()

        rng = np.random.default_rng(7)
        pnl = rng.normal(100.0, 10.0, 10).tolist()
        fill_prices = [p * 1.0001 for p in pnl]

        bt_trades = [
            {"entry_price": 50_000.0, "exit_price": 50_500.0, "pnl": p, "pnl_pct": 1.0}
            for p in pnl
        ]
        exec_fills = [
            {
                "filled_at": "2024-01-01T00:00:00Z",
                "fill_price": fp,
                "fill_qty": 0.1,
                "side": "buy",
                "asset_id": 1,
                "signal_id": 1,
            }
            for fp in fill_prices
        ]

        with (
            patch.object(checker, "_load_backtest_trades", return_value=bt_trades),
            patch.object(checker, "_load_executor_fills", return_value=exec_fills),
        ):
            report = checker.check(
                config_id=None,
                signal_id=1,
                start_date="2024-01-01",
                end_date="2024-12-31",
                slippage_mode="fixed",
            )

        assert report["parity_pass"] is True
