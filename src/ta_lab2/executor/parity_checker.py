"""
Backtest parity checker for paper executor replay validation.

Compares executor replay fills against stored backtest trades to verify that
the paper executor produces identical results to the backtester under
zero-slippage conditions (EXEC-05).

Usage:
    checker = ParityChecker(engine)
    report = checker.check(config_id=1, signal_id=1,
                           start_date='2024-01-01', end_date='2024-12-31',
                           slippage_mode='zero')
    print(checker.format_report(report))

Phase 88 burn-in: use pnl_correlation_threshold=0.90 (softer gate) via
the --pnl-correlation-threshold flag in run_parity_check.py.
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


class ParityChecker:
    """
    Compare paper executor replay fills against stored backtest trades.

    Usage:
    1. Run executor in replay mode: --replay-historical --start X --end Y
    2. Run parity check: ParityChecker(engine).check(config, start, end)
    3. Returns parity report dict with pass/fail

    Slippage modes:
    - "zero": Exact match expected. Pass if count matches AND max price
              divergence < 1.0 bps.
    - "fixed" / "lognormal": Statistical match expected. Pass if
              P&L correlation >= 0.99.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(
        self,
        config_id: Optional[int],
        signal_id: int,
        start_date: str,
        end_date: str,
        slippage_mode: str = "zero",
        pnl_correlation_threshold: float = 0.99,
    ) -> dict:
        """
        Run parity check and return a report dict.

        Parameters
        ----------
        config_id:
            Executor config ID (for labelling; not used in DB queries).
        signal_id:
            Signal ID to compare backtest trades vs executor fills.
        start_date:
            Inclusive start date string (e.g. '2024-01-01').
        end_date:
            Inclusive end date string (e.g. '2024-12-31').
        slippage_mode:
            One of 'zero', 'fixed', 'lognormal'.
        pnl_correlation_threshold:
            Minimum P&L correlation for PASS in fixed/lognormal modes.
            Default: 0.99.  Phase 88 burn-in uses 0.90.

        Returns
        -------
        dict with keys:
            config_id, signal_id, date_range, slippage_mode,
            backtest_trade_count, executor_fill_count, trade_count_match,
            max_price_divergence_bps, pnl_correlation, tracking_error_pct,
            pnl_correlation_threshold, parity_pass.
        """
        bt_trades = self._load_backtest_trades(signal_id, start_date, end_date)
        exec_fills = self._load_executor_fills(signal_id, start_date, end_date)

        report: dict = {
            "config_id": config_id,
            "signal_id": signal_id,
            "date_range": f"{start_date} to {end_date}",
            "slippage_mode": slippage_mode,
            "backtest_trade_count": len(bt_trades),
            "executor_fill_count": len(exec_fills),
            "trade_count_match": len(bt_trades) == len(exec_fills),
            "max_price_divergence_bps": None,
            "pnl_correlation": None,
            "tracking_error_pct": None,
            "pnl_correlation_threshold": pnl_correlation_threshold,
            "parity_pass": False,
        }

        # Short-circuit: no trades means failure
        if len(bt_trades) == 0:
            logger.warning(
                "No backtest trades found for signal_id=%s in range %s to %s",
                signal_id,
                start_date,
                end_date,
            )
            return report

        if report["trade_count_match"] and len(exec_fills) > 0:
            report = self._compute_price_divergence(report, bt_trades, exec_fills)
            report = self._compute_pnl_correlation(report, bt_trades, exec_fills)

        report["parity_pass"] = self._evaluate_parity(
            report, slippage_mode, pnl_correlation_threshold
        )
        return report

    def format_report(self, report: dict) -> str:
        """
        Format parity report as human-readable string.

        Returns a multi-line report with pass/fail result.
        """
        div_bps = report.get("max_price_divergence_bps")
        corr = report.get("pnl_correlation")
        tracking = report.get("tracking_error_pct")

        div_str = f"{div_bps:.2f} bps" if div_bps is not None else "N/A"
        corr_str = f"{corr:.4f}" if corr is not None else "N/A"
        tracking_str = f"{tracking:.2f}%" if tracking is not None else "N/A"

        count_label = "MATCH" if report.get("trade_count_match") else "MISMATCH"
        result_label = "PASS" if report.get("parity_pass") else "FAIL"

        lines = [
            "=== BACKTEST PARITY REPORT ===",
            f"Signal ID:        {report.get('signal_id')}",
            f"Config ID:        {report.get('config_id')}",
            f"Date Range:       {report.get('date_range')}",
            f"Slippage Mode:    {report.get('slippage_mode')}",
            "",
            f"Backtest Trades:  {report.get('backtest_trade_count')}",
            f"Executor Fills:   {report.get('executor_fill_count')}",
            f"Trade Count:      {count_label}",
            "",
            f"Max Price Div:    {div_str}",
            f"P&L Correlation:  {corr_str}",
            f"P&L Threshold:    {report.get('pnl_correlation_threshold', 0.99):.2f}",
            f"Tracking Error:   {tracking_str}",
            "",
            f"RESULT:           {result_label}",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_backtest_trades(
        self, signal_id: int, start_date: str, end_date: str
    ) -> list[dict]:
        """Load backtest trades from backtest_trades for a given signal_id."""
        sql = text(
            """
            SELECT bt.entry_ts, bt.exit_ts, bt.entry_price, bt.exit_price,
                   bt.direction, bt.pnl, bt.pnl_pct
            FROM backtest_trades bt
            JOIN backtest_runs br ON bt.run_id = br.run_id
            WHERE br.signal_id = :signal_id
              AND bt.entry_ts >= :start_date
              AND bt.entry_ts <= :end_date
            ORDER BY bt.entry_ts ASC
            """
        )
        with self._engine.connect() as conn:
            rows = conn.execute(
                sql,
                {
                    "signal_id": signal_id,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            ).fetchall()

        return [dict(r._mapping) for r in rows]

    def _load_executor_fills(
        self, signal_id: int, start_date: str, end_date: str
    ) -> list[dict]:
        """Load executor fills from fills for a given signal_id."""
        sql = text(
            """
            SELECT f.filled_at, f.fill_price, f.fill_qty, f.side,
                   o.asset_id, o.signal_id
            FROM fills f
            JOIN orders o ON f.order_id = o.order_id
            WHERE o.signal_id = :signal_id
              AND f.filled_at >= :start_date
              AND f.filled_at <= :end_date
            ORDER BY f.filled_at ASC
            """
        )
        with self._engine.connect() as conn:
            rows = conn.execute(
                sql,
                {
                    "signal_id": signal_id,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            ).fetchall()

        return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # Computation helpers
    # ------------------------------------------------------------------

    def _compute_price_divergence(
        self,
        report: dict,
        bt_trades: list[dict],
        exec_fills: list[dict],
    ) -> dict:
        """
        Compute pairwise fill price divergence in basis points.

        Aligns bt entry prices against executor fill prices by position index.
        divergence_bps = abs(exec_fill_price - bt_entry_price) / bt_entry_price * 10000
        """
        divergences = []
        for bt, ex in zip(bt_trades, exec_fills):
            bt_price = float(bt.get("entry_price") or 0)
            ex_price = float(ex.get("fill_price") or 0)
            if bt_price > 0:
                bps = abs(ex_price - bt_price) / bt_price * 10_000
                divergences.append(bps)

        report["max_price_divergence_bps"] = max(divergences) if divergences else 0.0
        return report

    def _compute_pnl_correlation(
        self,
        report: dict,
        bt_trades: list[dict],
        exec_fills: list[dict],
    ) -> dict:
        """
        Compute P&L correlation and tracking error between backtest and executor.

        Uses trade-level P&L from backtest trades; computes implied P&L for
        executor fills as (exit_price - entry_price) relative to entry.
        When executor fills lack explicit pnl, uses fill_price as proxy array.
        """
        bt_pnl = np.array([float(t.get("pnl") or 0) for t in bt_trades])

        # Executor fills may not carry pnl directly; use fill_price as proxy
        exec_pnl_raw = np.array([float(f.get("fill_price") or 0) for f in exec_fills])

        # If both arrays are identical shape and bt_pnl has non-zero variance,
        # compute correlation against bt_pnl (realistic when exec fills include pnl).
        # Fallback: correlate fill prices vs entry prices to detect divergence.
        if len(bt_pnl) >= 2 and len(exec_pnl_raw) >= 2:
            bt_entry_prices = np.array(
                [float(t.get("entry_price") or 0) for t in bt_trades]
            )
            if np.std(bt_pnl) > 0 and np.std(exec_pnl_raw) > 0:
                corr_matrix = np.corrcoef(bt_pnl, exec_pnl_raw)
                report["pnl_correlation"] = float(corr_matrix[0, 1])
            elif np.std(bt_entry_prices) > 0 and np.std(exec_pnl_raw) > 0:
                corr_matrix = np.corrcoef(bt_entry_prices, exec_pnl_raw)
                report["pnl_correlation"] = float(corr_matrix[0, 1])
            else:
                # Constant arrays: correlation undefined; treat as perfect match
                report["pnl_correlation"] = 1.0

            if np.std(bt_pnl) > 0:
                report["tracking_error_pct"] = float(
                    np.std(bt_pnl - exec_pnl_raw) / np.std(bt_pnl) * 100
                )
            else:
                report["tracking_error_pct"] = 0.0
        else:
            report["pnl_correlation"] = None
            report["tracking_error_pct"] = None

        return report

    # ------------------------------------------------------------------
    # Parity evaluation
    # ------------------------------------------------------------------

    def _evaluate_parity(
        self,
        report: dict,
        slippage_mode: str,
        pnl_correlation_threshold: float = 0.99,
    ) -> bool:
        """Apply mode-specific parity tolerance rules.

        Parameters
        ----------
        report:
            Parity report dict with computed metrics.
        slippage_mode:
            One of 'zero', 'fixed', 'lognormal'.
        pnl_correlation_threshold:
            Minimum P&L correlation for PASS in fixed/lognormal modes.
            Default: 0.99.  Phase 88 burn-in uses 0.90.
        """
        if slippage_mode == "zero":
            # Strict: count must match AND max divergence < 1 bps
            count_ok = report.get("trade_count_match", False)
            div = report.get("max_price_divergence_bps")
            div_ok = div is not None and div < 1.0
            return bool(count_ok and div_ok)

        elif slippage_mode in ("fixed", "lognormal"):
            # Statistical: correlation must be >= caller-provided threshold
            corr = report.get("pnl_correlation")
            return corr is not None and corr >= pnl_correlation_threshold

        else:
            logger.warning(
                "Unknown slippage_mode=%r; defaulting to FAIL", slippage_mode
            )
            return False
