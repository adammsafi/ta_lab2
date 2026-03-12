"""
DriftMonitor -- daily drift comparison between paper executor and backtest replay.

Orchestrates the full drift guard pipeline (DRIFT-01/02/03):
  1. Load all active executor configs from dim_executor_config
  2. For each (config, asset): run PIT and current-data backtest replays
  3. Load paper fills from fills / orders
  4. Aggregate daily P&L arrays and compute DriftMetrics via drift_metrics.py
  5. Write metrics to drift_metrics (upsert)
  6. Check drift thresholds -- activate drift pause if breached
  7. Refresh v_drift_summary materialized view
  8. Check drift escalation -- escalate to kill switch if expired

Design invariants:
  - Each (config, asset) pair is processed independently; failure of one does not abort others.
  - dry_run=True skips all writes and view refreshes (safe for testing/diagnosis).
  - PIT replay and current-data replay produce identical results in V1 (crypto data revisions
    are rare). Both replays use current data; data_revision_pnl_diff is set to 0 when
    PIT snapshots are not populated. A WARNING is logged in that case.
  - _refresh_summary_view() uses REFRESH MATERIALIZED VIEW CONCURRENTLY when the view
    has existing rows; falls back to non-concurrent refresh for an empty view.

Usage:
    from sqlalchemy import create_engine
    from ta_lab2.drift.drift_monitor import DriftMonitor

    engine = create_engine(db_url)
    monitor = DriftMonitor(engine)
    results = monitor.run(paper_start_date="2026-01-01")
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.backtests.costs import CostModel
from ta_lab2.drift.drift_metrics import DriftMetrics, compute_drift_metrics
from ta_lab2.drift.drift_pause import check_drift_escalation, check_drift_threshold
from ta_lab2.executor.signal_reader import SIGNAL_TABLE_MAP

logger = logging.getLogger(__name__)

# Deferred import of SignalBacktester to avoid circular-import issues at module load.
# The backtests module imports from scripts which may indirectly touch drift.
_SignalBacktester = None


def _get_signal_backtester_class():
    """Lazy import SignalBacktester to avoid circular imports."""
    global _SignalBacktester
    if _SignalBacktester is None:
        from ta_lab2.scripts.backtests.backtest_from_signals import SignalBacktester

        _SignalBacktester = SignalBacktester
    return _SignalBacktester


class DriftMonitor:
    """Daily drift comparison between paper executor and backtest replay.

    Runs once per day (typically triggered by run_daily_refresh.py) to compare
    paper-trading P&L against backtest replays for each active executor configuration.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        paper_start_date: str,
        dry_run: bool = False,
    ) -> list[DriftMetrics]:
        """
        Run full drift comparison for all active executor configurations.

        Parameters
        ----------
        paper_start_date:
            Start date for paper trading history (ISO format: 'YYYY-MM-DD').
            Used as the start boundary for replay backtests and paper fill queries.
        dry_run:
            If True, skip all DB writes and view refreshes. Useful for diagnosis
            and testing without side effects.

        Returns
        -------
        List of DriftMetrics (one per (config, asset) pair that was processed).
        """
        today = datetime.now(timezone.utc).date().isoformat()
        logger.info(
            "DriftMonitor.run(): paper_start=%s today=%s dry_run=%s",
            paper_start_date,
            today,
            dry_run,
        )

        configs = self._load_active_executor_configs()
        if not configs:
            logger.warning("DriftMonitor.run(): no active executor configs found")
            return []

        results: list[DriftMetrics] = []

        for config in configs:
            config_id = config["config_id"]
            asset_ids = config.get("asset_ids", [])
            if not asset_ids:
                logger.warning(
                    "DriftMonitor: config_id=%d has no asset_ids -- skipping",
                    config_id,
                )
                continue

            for asset_id in asset_ids:
                try:
                    metrics = self._check_strategy_drift(
                        config=config,
                        asset_id=asset_id,
                        paper_start=paper_start_date,
                        today=today,
                    )
                except Exception as exc:
                    logger.error(
                        "DriftMonitor: config_id=%d asset_id=%d FAILED: %s",
                        config_id,
                        asset_id,
                        exc,
                        exc_info=True,
                    )
                    continue

                if not dry_run:
                    self._write_metrics(metrics)
                    check_drift_threshold(self._engine, metrics)

                results.append(metrics)
                logger.info(
                    "DriftMonitor: config_id=%d asset_id=%d TE_5d=%s breach=%s",
                    config_id,
                    asset_id,
                    metrics.tracking_error_5d,
                    metrics.threshold_breach,
                )

        if not dry_run:
            self._refresh_summary_view()
            check_drift_escalation(self._engine)

        logger.info(
            "DriftMonitor.run() complete: processed %d (config, asset) pairs",
            len(results),
        )
        return results

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    def _load_active_executor_configs(self) -> list[dict[str, Any]]:
        """
        Load all active executor configurations including their asset ID lists.

        Queries dim_executor_config WHERE is_active=TRUE, then for each config
        determines the set of asset IDs by querying the corresponding signal table.
        The signal table name is validated against SIGNAL_TABLE_MAP to prevent injection.

        Returns
        -------
        List of dicts: [{config_id, signal_id, signal_type, fee_bps, slippage_base_bps,
                          slippage_mode, asset_ids: [int]}]
        """
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    """
                    SELECT config_id, signal_id, signal_type, fee_bps,
                           slippage_base_bps, slippage_mode
                    FROM dim_executor_config
                    WHERE is_active = TRUE
                    ORDER BY config_id
                    """
                )
            ).fetchall()

        configs: list[dict[str, Any]] = []
        for row in rows:
            config_id = row[0]
            signal_id = row[1]
            signal_type = row[2]
            fee_bps = float(row[3]) if row[3] is not None else 0.0
            slippage_base_bps = float(row[4]) if row[4] is not None else 3.0
            slippage_mode = row[5] or "lognormal"

            # Validate signal_type against SIGNAL_TABLE_MAP (injection prevention)
            if signal_type not in SIGNAL_TABLE_MAP:
                logger.warning(
                    "_load_active_executor_configs: unknown signal_type=%r "
                    "for config_id=%d -- skipping",
                    signal_type,
                    config_id,
                )
                continue

            table_name = SIGNAL_TABLE_MAP[signal_type]

            # Load distinct asset IDs from the signal table for this config
            with self._engine.connect() as conn:
                asset_rows = conn.execute(
                    text(
                        f"SELECT DISTINCT id FROM {table_name} WHERE signal_id = :signal_id"  # noqa: S608
                    ),
                    {"signal_id": signal_id},
                ).fetchall()

            asset_ids = [r[0] for r in asset_rows]

            configs.append(
                {
                    "config_id": config_id,
                    "signal_id": signal_id,
                    "signal_type": signal_type,
                    "fee_bps": fee_bps,
                    "slippage_base_bps": slippage_base_bps,
                    "slippage_mode": slippage_mode,
                    "asset_ids": asset_ids,
                }
            )
            logger.debug(
                "_load_active_executor_configs: config_id=%d signal_type=%s "
                "asset_count=%d fee_bps=%.1f",
                config_id,
                signal_type,
                len(asset_ids),
                fee_bps,
            )

        return configs

    # ------------------------------------------------------------------
    # Strategy drift check
    # ------------------------------------------------------------------

    def _check_strategy_drift(
        self,
        config: dict[str, Any],
        asset_id: int,
        paper_start: str,
        today: str,
    ) -> DriftMetrics:
        """
        Run PIT and current-data backtest replays, load paper fills, compute metrics.

        For V1, both PIT and current-data replays use current data (crypto data
        revisions are rare). A WARNING is logged to note that PIT snapshots are
        not yet populated by the executor. data_revision_pnl_diff is set to 0.

        Parameters
        ----------
        config:
            Dict from _load_active_executor_configs().
        asset_id:
            The specific asset to check.
        paper_start:
            Start date for the comparison window (ISO format).
        today:
            End date for the comparison window (ISO format).

        Returns
        -------
        DriftMetrics with computed drift measures.
        """
        config_id = config["config_id"]
        signal_id = config["signal_id"]
        signal_type = config["signal_type"]

        # Build CostModel matching executor config
        cost_model = CostModel(
            fee_bps=config["fee_bps"],
            slippage_bps=config["slippage_base_bps"],
        )

        SignalBacktester = _get_signal_backtester_class()
        backtester = SignalBacktester(engine=self._engine, cost_model=cost_model)

        start_ts = pd.Timestamp(paper_start)
        end_ts = pd.Timestamp(today)

        # PIT replay -- V1: runs with current data (PIT snapshots not yet populated)
        logger.warning(
            "_check_strategy_drift: PIT snapshots not yet available for "
            "config_id=%d asset_id=%d -- using current data for both replays. "
            "data_revision_pnl_diff will be 0.",
            config_id,
            asset_id,
        )

        try:
            pit_result = backtester.run_backtest(
                signal_type=signal_type,
                signal_id=signal_id,
                asset_id=asset_id,
                start_ts=start_ts,
                end_ts=end_ts,
            )
        except (ValueError, RuntimeError) as exc:
            logger.warning(
                "_check_strategy_drift: PIT replay failed for "
                "config_id=%d asset_id=%d: %s",
                config_id,
                asset_id,
                exc,
            )
            pit_result = None

        # Current-data replay (same call -- identical to PIT in V1)
        cur_result = pit_result  # V1: both replays use current data

        pit_run_id = pit_result.run_id if pit_result is not None else None
        cur_run_id = cur_result.run_id if cur_result is not None else None

        # Load paper fills for this (signal_id, asset_id) over the date range
        paper_fills = self._load_paper_fills(
            signal_id=signal_id,
            asset_id=asset_id,
            start_date=paper_start,
            end_date=today,
        )

        # Aggregate daily P&L arrays
        paper_pnl = self._aggregate_daily_pnl(
            fills=paper_fills,
            start_date=paper_start,
            end_date=today,
        )

        if pit_result is not None and not pit_result.trades_df.empty:
            replay_pit_pnl = self._aggregate_trades_daily_pnl(
                trades_df=pit_result.trades_df,
                start_date=paper_start,
                end_date=today,
            )
        else:
            n_days = (pd.Timestamp(today) - pd.Timestamp(paper_start)).days + 1
            replay_pit_pnl = np.zeros(max(n_days, 0))

        replay_cur_pnl = replay_pit_pnl  # V1: identical

        # Trade counts
        paper_trade_count = len(paper_fills)
        replay_trade_count = len(pit_result.trades_df) if pit_result is not None else 0
        unmatched_paper = max(0, paper_trade_count - replay_trade_count)
        unmatched_replay = max(0, replay_trade_count - paper_trade_count)

        metrics = compute_drift_metrics(
            config_id=config_id,
            asset_id=asset_id,
            signal_type=signal_type,
            metric_date=date.fromisoformat(today),
            paper_daily_pnl=paper_pnl,
            replay_pit_daily_pnl=replay_pit_pnl,
            replay_cur_daily_pnl=replay_cur_pnl,
            paper_trade_count=paper_trade_count,
            replay_trade_count=replay_trade_count,
            unmatched_paper=unmatched_paper,
            unmatched_replay=unmatched_replay,
            pit_replay_run_id=pit_run_id,
            cur_replay_run_id=cur_run_id,
        )

        return metrics

    # ------------------------------------------------------------------
    # Paper fills loading
    # ------------------------------------------------------------------

    def _load_paper_fills(
        self,
        signal_id: int,
        asset_id: int,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Load paper executor fills for a given (signal_id, asset_id) date range."""
        sql = text(
            """
            SELECT f.filled_at, f.fill_price, f.fill_qty, f.side, o.asset_id, o.signal_id
            FROM fills f
            JOIN orders o ON f.order_id = o.order_id
            WHERE o.signal_id = :signal_id
              AND o.asset_id  = :asset_id
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
                    "asset_id": asset_id,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            ).fetchall()

        return [dict(r._mapping) for r in rows]

    # ------------------------------------------------------------------
    # Daily P&L aggregation
    # ------------------------------------------------------------------

    def _aggregate_daily_pnl(
        self,
        fills: list[dict[str, Any]],
        start_date: str,
        end_date: str,
    ) -> np.ndarray:
        """
        Convert paper fills to daily P&L array.

        For each calendar day in [start_date, end_date], sums the implied P&L
        for fills that occurred on that day (or 0 if no fills).

        NOTE: Paper fills from fills do not carry explicit P&L. A buy fill
        followed by a sell fill implies P&L via (exit_price - entry_price) * qty.
        For the V1 implementation, this uses fill_price * qty * side_multiplier
        as a signed cash flow proxy, so the P&L array represents net cash flows.

        Returns
        -------
        np.ndarray
            Array of daily P&L values (length = number of days in range).
        """
        date_range = pd.date_range(start=start_date, end=end_date, freq="D")
        n_days = len(date_range)

        if n_days == 0 or not fills:
            return np.zeros(max(n_days, 0))

        pnl_by_date: dict[date, float] = {d.date(): 0.0 for d in date_range}

        for fill in fills:
            filled_at = fill.get("filled_at")
            if filled_at is None:
                continue
            fill_ts = pd.Timestamp(filled_at)
            fill_date = fill_ts.date()
            if fill_date not in pnl_by_date:
                continue

            fill_price = float(fill.get("fill_price") or 0.0)
            fill_qty = float(fill.get("fill_qty") or 0.0)
            side = str(fill.get("side") or "buy").lower()

            # Cash flow: buy = negative (cash out), sell = positive (cash in)
            side_multiplier = -1.0 if side == "buy" else 1.0
            pnl_by_date[fill_date] += side_multiplier * fill_price * fill_qty

        return np.array([pnl_by_date[d.date()] for d in date_range], dtype=float)

    def _aggregate_trades_daily_pnl(
        self,
        trades_df: pd.DataFrame,
        start_date: str,
        end_date: str,
    ) -> np.ndarray:
        """
        Convert backtest trades DataFrame to daily P&L array.

        Uses trade-level pnl_dollars bucketed by exit_ts date.

        Returns
        -------
        np.ndarray of daily P&L values.
        """
        date_range = pd.date_range(start=start_date, end=end_date, freq="D")
        n_days = len(date_range)

        if n_days == 0 or trades_df.empty:
            return np.zeros(max(n_days, 0))

        pnl_by_date: dict[date, float] = {d.date(): 0.0 for d in date_range}

        for _, trade in trades_df.iterrows():
            exit_ts = trade.get("exit_ts")
            pnl_dollars = float(trade.get("pnl_dollars") or 0.0)
            if exit_ts is None:
                continue
            trade_date = pd.Timestamp(exit_ts).date()
            if trade_date in pnl_by_date:
                pnl_by_date[trade_date] += pnl_dollars

        return np.array([pnl_by_date[d.date()] for d in date_range], dtype=float)

    # ------------------------------------------------------------------
    # DB write
    # ------------------------------------------------------------------

    def _write_metrics(self, metrics: DriftMetrics) -> None:
        """
        Upsert a DriftMetrics record to drift_metrics.

        Uses ON CONFLICT (metric_date, config_id, asset_id) DO UPDATE SET
        to safely handle reruns on the same date.
        """
        sql = text(
            """
            INSERT INTO drift_metrics (
                metric_date, config_id, asset_id, signal_type,
                pit_replay_run_id, cur_replay_run_id,
                paper_trade_count, replay_trade_count,
                unmatched_paper, unmatched_replay,
                paper_cumulative_pnl, replay_pit_cumulative_pnl, replay_cur_cumulative_pnl,
                absolute_pnl_diff, data_revision_pnl_diff,
                tracking_error_5d, tracking_error_30d,
                paper_sharpe, replay_sharpe, sharpe_divergence,
                threshold_breach, drift_pct_of_threshold
            ) VALUES (
                :metric_date, :config_id, :asset_id, :signal_type,
                :pit_replay_run_id, :cur_replay_run_id,
                :paper_trade_count, :replay_trade_count,
                :unmatched_paper, :unmatched_replay,
                :paper_cumulative_pnl, :replay_pit_cumulative_pnl, :replay_cur_cumulative_pnl,
                :absolute_pnl_diff, :data_revision_pnl_diff,
                :tracking_error_5d, :tracking_error_30d,
                :paper_sharpe, :replay_sharpe, :sharpe_divergence,
                :threshold_breach, :drift_pct_of_threshold
            )
            ON CONFLICT (metric_date, config_id, asset_id) DO UPDATE SET
                signal_type             = EXCLUDED.signal_type,
                pit_replay_run_id       = EXCLUDED.pit_replay_run_id,
                cur_replay_run_id       = EXCLUDED.cur_replay_run_id,
                paper_trade_count       = EXCLUDED.paper_trade_count,
                replay_trade_count      = EXCLUDED.replay_trade_count,
                unmatched_paper         = EXCLUDED.unmatched_paper,
                unmatched_replay        = EXCLUDED.unmatched_replay,
                paper_cumulative_pnl    = EXCLUDED.paper_cumulative_pnl,
                replay_pit_cumulative_pnl = EXCLUDED.replay_pit_cumulative_pnl,
                replay_cur_cumulative_pnl = EXCLUDED.replay_cur_cumulative_pnl,
                absolute_pnl_diff       = EXCLUDED.absolute_pnl_diff,
                data_revision_pnl_diff  = EXCLUDED.data_revision_pnl_diff,
                tracking_error_5d       = EXCLUDED.tracking_error_5d,
                tracking_error_30d      = EXCLUDED.tracking_error_30d,
                paper_sharpe            = EXCLUDED.paper_sharpe,
                replay_sharpe           = EXCLUDED.replay_sharpe,
                sharpe_divergence       = EXCLUDED.sharpe_divergence,
                threshold_breach        = EXCLUDED.threshold_breach,
                drift_pct_of_threshold  = EXCLUDED.drift_pct_of_threshold
            """
        )

        params = {
            "metric_date": metrics.metric_date,
            "config_id": metrics.config_id,
            "asset_id": metrics.asset_id,
            "signal_type": metrics.signal_type,
            "pit_replay_run_id": metrics.pit_replay_run_id,
            "cur_replay_run_id": metrics.cur_replay_run_id,
            "paper_trade_count": metrics.paper_trade_count,
            "replay_trade_count": metrics.replay_trade_count,
            "unmatched_paper": metrics.unmatched_paper,
            "unmatched_replay": metrics.unmatched_replay,
            "paper_cumulative_pnl": metrics.paper_cumulative_pnl,
            "replay_pit_cumulative_pnl": metrics.replay_pit_cumulative_pnl,
            "replay_cur_cumulative_pnl": metrics.replay_cur_cumulative_pnl,
            "absolute_pnl_diff": metrics.absolute_pnl_diff,
            "data_revision_pnl_diff": metrics.data_revision_pnl_diff,
            "tracking_error_5d": metrics.tracking_error_5d,
            "tracking_error_30d": metrics.tracking_error_30d,
            "paper_sharpe": metrics.paper_sharpe,
            "replay_sharpe": metrics.replay_sharpe,
            "sharpe_divergence": metrics.sharpe_divergence,
            "threshold_breach": metrics.threshold_breach,
            "drift_pct_of_threshold": metrics.drift_pct_of_threshold,
        }

        with self._engine.begin() as conn:
            conn.execute(sql, params)

        logger.debug(
            "_write_metrics: upserted config_id=%d asset_id=%d date=%s breach=%s",
            metrics.config_id,
            metrics.asset_id,
            metrics.metric_date,
            metrics.threshold_breach,
        )

    # ------------------------------------------------------------------
    # View refresh
    # ------------------------------------------------------------------

    def _refresh_summary_view(self) -> None:
        """
        Refresh v_drift_summary materialized view.

        Uses REFRESH MATERIALIZED VIEW CONCURRENTLY when the view has existing
        rows (requires the unique index added in Plan 47-01 migration). Falls back
        to non-concurrent refresh when the view is empty to avoid the 'not yet
        populated' error from CONCURRENTLY on an empty view.

        Failure is logged as a WARNING but does not crash the monitor.
        """
        try:
            with self._engine.connect() as conn:
                row_count = conn.execute(
                    text("SELECT COUNT(*) FROM public.v_drift_summary")
                ).scalar()

            if row_count and row_count > 0:
                sql = "REFRESH MATERIALIZED VIEW CONCURRENTLY public.v_drift_summary"
                logger.debug(
                    "_refresh_summary_view: using CONCURRENTLY (%d rows)", row_count
                )
            else:
                sql = "REFRESH MATERIALIZED VIEW public.v_drift_summary"
                logger.debug("_refresh_summary_view: using non-concurrent (empty view)")

            with self._engine.begin() as conn:
                conn.execute(text(sql))

            logger.info("_refresh_summary_view: v_drift_summary refreshed successfully")

        except Exception as exc:
            logger.warning(
                "_refresh_summary_view: view refresh failed (non-fatal): %s", exc
            )
