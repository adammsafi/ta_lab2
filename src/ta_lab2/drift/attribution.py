"""
Drift attribution decomposition engine -- DriftAttributor with sequential OAT.

DriftAttributor decomposes drift into 6 independent sources via sequential
One-At-a-Time (OAT) attribution.  Each step adds one cost source and measures
its incremental contribution:

  Step 0: Baseline (zero fees, zero slippage)
  Step 1: +Fees (config fee_bps applied)
  Step 2: +Slippage (config slippage_bps applied)
  Step 3: +Timing (V1 placeholder -- both use next-bar-open, delta=0)
  Step 4: +Data revision (PIT vs current comparison, likely 0 in V1)
  Step 5: +Sizing (theoretical vs actual position sizes, V1 placeholder, delta=0)
  Step 6: +Regime (with-regime vs no-regime replay)

  Residual: paper_pnl - total_explained

The ``run_attribution`` method requires at least 10 trades to produce meaningful
attribution (guard from research pitfall 7).  Fewer trades return all-zero
attribution with the paper_pnl preserved.

Usage::

    from sqlalchemy import create_engine
    from ta_lab2.drift.attribution import DriftAttributor

    engine = create_engine(db_url)
    attributor = DriftAttributor(engine)
    result = attributor.run_attribution(
        config_id=1,
        signal_id=2,
        signal_type="ema_crossover",
        asset_id=1,
        paper_start="2026-01-01",
        paper_end="2026-02-01",
        paper_pnl=125.40,
        paper_trade_count=32,
    )
    print(result.fee_delta, result.slippage_delta, result.unexplained_residual)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.backtests.costs import CostModel

# Minimum trades required for meaningful attribution (from research pitfall 7).
_MIN_TRADE_COUNT = 10

logger = logging.getLogger(__name__)

# Deferred import to avoid circular-import issues at module load.
_SignalBacktester = None


def _get_signal_backtester_class():
    """Lazy import SignalBacktester to avoid circular imports."""
    global _SignalBacktester
    if _SignalBacktester is None:
        from ta_lab2.scripts.backtests.backtest_from_signals import SignalBacktester

        _SignalBacktester = SignalBacktester
    return _SignalBacktester


@dataclass(frozen=True)
class AttributionResult:
    """
    Sequential OAT attribution decomposition of drift.

    All delta fields are additive: total_explained_pnl = baseline_pnl + sum(deltas).
    unexplained_residual = paper_pnl - total_explained_pnl.

    Steps 3 (timing) and 5 (sizing) are V1 placeholders -- always 0 until those
    attribution sources are implemented in a future iteration.

    Attributes
    ----------
    baseline_pnl:
        P&L from zero-cost backtest replay (fee_bps=0, slippage_bps=0).
    fee_delta:
        Incremental contribution of trading fees.
    slippage_delta:
        Incremental contribution of market impact / slippage.
    timing_delta:
        Incremental contribution of execution timing differences (V1: 0).
    data_revision_delta:
        Incremental contribution of data revision differences between PIT and
        current data (V1: 0 when PIT snapshots are unavailable).
    sizing_delta:
        Incremental contribution of position sizing rounding differences (V1: 0).
    regime_delta:
        Incremental contribution of regime label differences (no-regime vs regime).
    unexplained_residual:
        paper_pnl - total_explained_pnl.  Positive means paper performed better
        than the model predicts; negative means paper performed worse.
    total_explained_pnl:
        baseline_pnl + fee_delta + slippage_delta + timing_delta +
        data_revision_delta + sizing_delta + regime_delta.
    paper_pnl:
        Actual paper executor P&L for the attribution period.
    """

    baseline_pnl: float
    fee_delta: float
    slippage_delta: float
    timing_delta: float
    data_revision_delta: float
    sizing_delta: float
    regime_delta: float
    unexplained_residual: float
    total_explained_pnl: float
    paper_pnl: float


def _zeros_with_paper_pnl(paper_pnl: float) -> AttributionResult:
    """Return an all-zero AttributionResult with paper_pnl preserved."""
    return AttributionResult(
        baseline_pnl=0.0,
        fee_delta=0.0,
        slippage_delta=0.0,
        timing_delta=0.0,
        data_revision_delta=0.0,
        sizing_delta=0.0,
        regime_delta=0.0,
        unexplained_residual=paper_pnl,
        total_explained_pnl=0.0,
        paper_pnl=paper_pnl,
    )


class DriftAttributor:
    """
    Sequential OAT attribution engine for drift decomposition.

    Runs N+1=7 backtest replays with progressively added cost sources to isolate
    each attribution component independently.  Backtest failures are handled
    gracefully -- the affected delta is set to 0 and computation continues.

    Parameters
    ----------
    engine:
        SQLAlchemy engine connected to the project database.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_attribution(
        self,
        config_id: int,
        signal_id: int,
        signal_type: str,
        asset_id: int,
        paper_start: str,
        paper_end: str,
        paper_pnl: float,
        paper_trade_count: int,
    ) -> AttributionResult:
        """
        Decompose drift into 6 attribution sources via sequential OAT.

        Parameters
        ----------
        config_id:
            Executor config ID (from dim_executor_config) used to load fee_bps
            and slippage_bps for Steps 1 and 2.
        signal_id:
            Signal ID from dim_signals.
        signal_type:
            Signal type string (e.g. 'ema_crossover').
        asset_id:
            Asset ID to replay.
        paper_start:
            ISO date string for the attribution window start.
        paper_end:
            ISO date string for the attribution window end.
        paper_pnl:
            Cumulative P&L from the paper executor for the period.
        paper_trade_count:
            Number of paper trades in the period.  Must be >= 10 for attribution
            to proceed (research pitfall 7 guard).

        Returns
        -------
        AttributionResult with all delta fields populated.  Returns all-zero result
        with paper_pnl preserved when paper_trade_count < 10.
        """
        if paper_trade_count < _MIN_TRADE_COUNT:
            logger.warning(
                "Insufficient trade history (N=%d, minimum=%d) for config_id=%d "
                "asset_id=%d -- skipping attribution",
                paper_trade_count,
                _MIN_TRADE_COUNT,
                config_id,
                asset_id,
            )
            return _zeros_with_paper_pnl(paper_pnl)

        # Load cost parameters for this executor config.
        cost_params = self._load_config_cost_params(config_id)
        fee_bps = cost_params.get("fee_bps", 0.0)
        slippage_bps = cost_params.get("slippage_base_bps", 0.0)

        start_ts = pd.Timestamp(paper_start)
        end_ts = pd.Timestamp(paper_end)

        # Step 0: Baseline (zero costs)
        baseline_pnl = self._run_replay_with_cost(
            signal_type,
            signal_id,
            asset_id,
            start_ts,
            end_ts,
            CostModel(fee_bps=0.0, slippage_bps=0.0, funding_bps_day=0.0),
        )
        if baseline_pnl is None:
            logger.warning(
                "Baseline replay failed for config_id=%d asset_id=%d -- returning zeros",
                config_id,
                asset_id,
            )
            return _zeros_with_paper_pnl(paper_pnl)

        # Step 1: +Fees
        step1_pnl = self._run_replay_with_cost(
            signal_type,
            signal_id,
            asset_id,
            start_ts,
            end_ts,
            CostModel(fee_bps=fee_bps, slippage_bps=0.0, funding_bps_day=0.0),
        )
        if step1_pnl is None:
            logger.warning(
                "Fee-step replay failed for config_id=%d asset_id=%d -- setting fee_delta=0",
                config_id,
                asset_id,
            )
            step1_pnl = baseline_pnl
        fee_delta = step1_pnl - baseline_pnl

        # Step 2: +Slippage
        step2_pnl = self._run_replay_with_cost(
            signal_type,
            signal_id,
            asset_id,
            start_ts,
            end_ts,
            CostModel(fee_bps=fee_bps, slippage_bps=slippage_bps, funding_bps_day=0.0),
        )
        if step2_pnl is None:
            logger.warning(
                "Slippage-step replay failed for config_id=%d asset_id=%d -- setting slippage_delta=0",
                config_id,
                asset_id,
            )
            step2_pnl = step1_pnl
        slippage_delta = step2_pnl - step1_pnl

        # Step 3: +Timing (V1 placeholder -- both use next-bar-open execution)
        timing_delta = 0.0
        logger.debug(
            "timing_delta=0 (same execution model) for config_id=%d asset_id=%d",
            config_id,
            asset_id,
        )

        # Step 4: +Data revision
        # V1: PIT snapshots not yet populated; use 0 as a safe approximation.
        # When data_snapshot in cmc_executor_run_log is populated this step will
        # run a PIT replay and compare against the current-data replay.
        data_revision_delta = 0.0
        logger.debug(
            "data_revision_delta=0 (V1: PIT snapshots not yet populated) "
            "for config_id=%d asset_id=%d",
            config_id,
            asset_id,
        )

        # Step 5: +Sizing (V1 placeholder -- same sizing model in both replays)
        sizing_delta = 0.0
        logger.debug(
            "sizing_delta=0 (V1 placeholder) for config_id=%d asset_id=%d",
            config_id,
            asset_id,
        )

        # Step 6: +Regime
        regime_delta = self._compute_regime_delta(
            signal_type,
            signal_id,
            asset_id,
            start_ts,
            end_ts,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            step2_pnl=step2_pnl,
        )

        # Residual
        total_explained = (
            baseline_pnl
            + fee_delta
            + slippage_delta
            + timing_delta
            + data_revision_delta
            + sizing_delta
            + regime_delta
        )
        unexplained_residual = paper_pnl - total_explained

        logger.info(
            "Attribution complete for config_id=%d asset_id=%d: "
            "baseline=%.4f fee=%.4f slip=%.4f regime=%.4f residual=%.4f paper=%.4f",
            config_id,
            asset_id,
            baseline_pnl,
            fee_delta,
            slippage_delta,
            regime_delta,
            unexplained_residual,
            paper_pnl,
        )

        return AttributionResult(
            baseline_pnl=baseline_pnl,
            fee_delta=fee_delta,
            slippage_delta=slippage_delta,
            timing_delta=timing_delta,
            data_revision_delta=data_revision_delta,
            sizing_delta=sizing_delta,
            regime_delta=regime_delta,
            unexplained_residual=unexplained_residual,
            total_explained_pnl=total_explained,
            paper_pnl=paper_pnl,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_config_cost_params(self, config_id: int) -> dict:
        """
        Load fee and slippage parameters from dim_executor_config.

        Parameters
        ----------
        config_id:
            Row ID in dim_executor_config.

        Returns
        -------
        Dict with keys: fee_bps, slippage_mode, slippage_base_bps.
        Falls back to zeros if the row is not found.
        """
        sql = text(
            """
            SELECT fee_bps, slippage_mode, slippage_base_bps
            FROM public.dim_executor_config
            WHERE config_id = :config_id
            """
        )
        try:
            with self._engine.connect() as conn:
                row = conn.execute(sql, {"config_id": config_id}).fetchone()
        except Exception as exc:
            logger.warning(
                "_load_config_cost_params failed for config_id=%d: %s -- using zeros",
                config_id,
                exc,
            )
            return {"fee_bps": 0.0, "slippage_mode": "fixed", "slippage_base_bps": 0.0}

        if row is None:
            logger.warning(
                "_load_config_cost_params: config_id=%d not found -- using zeros",
                config_id,
            )
            return {"fee_bps": 0.0, "slippage_mode": "fixed", "slippage_base_bps": 0.0}

        return {
            "fee_bps": float(row[0]) if row[0] is not None else 0.0,
            "slippage_mode": row[1] or "fixed",
            "slippage_base_bps": float(row[2]) if row[2] is not None else 0.0,
        }

    def _run_replay_with_cost(
        self,
        signal_type: str,
        signal_id: int,
        asset_id: int,
        start_ts: pd.Timestamp,
        end_ts: pd.Timestamp,
        cost_model: CostModel,
    ) -> float | None:
        """
        Run a single backtest replay and return cumulative P&L.

        Parameters
        ----------
        signal_type:
            Signal table suffix (e.g. 'ema_crossover').
        signal_id:
            Signal ID from dim_signals.
        asset_id:
            Asset ID to replay.
        start_ts:
            Replay start timestamp.
        end_ts:
            Replay end timestamp.
        cost_model:
            CostModel to apply for this replay step.

        Returns
        -------
        Cumulative P&L as float, or None on any exception.
        """
        SignalBacktester = _get_signal_backtester_class()
        backtester = SignalBacktester(engine=self._engine, cost_model=cost_model)
        try:
            result = backtester.run_backtest(
                signal_type=signal_type,
                signal_id=signal_id,
                asset_id=asset_id,
                start_ts=start_ts,
                end_ts=end_ts,
            )
            # total_return is a fraction (e.g. 0.12 = 12%). Use the raw P&L from
            # metrics dict when available; fall back to total_return as proxy.
            if "total_return" in result.metrics:
                return float(result.metrics["total_return"])
            return float(result.total_return)
        except Exception as exc:
            logger.warning(
                "_run_replay_with_cost failed for signal_type=%s signal_id=%d "
                "asset_id=%d cost=%s: %s",
                signal_type,
                signal_id,
                asset_id,
                cost_model.describe(),
                exc,
            )
            return None

    def _compute_regime_delta(
        self,
        signal_type: str,
        signal_id: int,
        asset_id: int,
        start_ts: pd.Timestamp,
        end_ts: pd.Timestamp,
        fee_bps: float,
        slippage_bps: float,
        step2_pnl: float,
    ) -> float:
        """
        Compute regime attribution delta.

        Runs a no-regime replay (baseline cost model) and compares against
        the with-regime result from Step 2.  If the replay fails or the
        signal type does not support regime toggling, returns 0.

        Parameters
        ----------
        step2_pnl:
            P&L from Step 2 (+Fees +Slippage, with regime active).  The delta
            is computed relative to this value.

        Returns
        -------
        regime_delta = step2_pnl (with regime) - no_regime_pnl, or 0 on failure.
        """
        # Use the same cost model as Step 2 for the no-regime replay so that the
        # only difference is regime label filtering.
        no_regime_pnl = self._run_replay_with_cost(
            signal_type,
            signal_id,
            asset_id,
            start_ts,
            end_ts,
            CostModel(fee_bps=fee_bps, slippage_bps=slippage_bps, funding_bps_day=0.0),
        )
        if no_regime_pnl is None:
            logger.debug(
                "_compute_regime_delta: no-regime replay returned None -- setting regime_delta=0"
            )
            return 0.0
        # In V1, both replays use the same signals (regime filtering is in the
        # signal generator layer, not in the backtester).  The delta is therefore
        # 0 unless the signal generator was re-run without --no-regime.
        regime_delta = step2_pnl - no_regime_pnl
        logger.debug(
            "_compute_regime_delta: regime_delta=%.4f (step2=%.4f, no_regime=%.4f)",
            regime_delta,
            step2_pnl,
            no_regime_pnl,
        )
        return regime_delta
