"""
Drift attribution decomposition engine -- DriftAttributor with sequential OAT.

DriftAttributor decomposes drift into 7 independent sources via sequential
One-At-a-Time (OAT) attribution.  Each step adds one cost source and measures
its incremental contribution:

  Step 0: Baseline (zero fees, zero slippage)
  Step 1: +Fees (config fee_bps applied)
  Step 2: +Slippage (config slippage_bps applied)
  Step 3: +Timing (V1 placeholder -- both use next-bar-open, delta=0)
  Step 4: +Data revision (PIT vs current comparison, likely 0 in V1)
  Step 5: +Sizing (theoretical vs actual position sizes, V1 placeholder, delta=0)
  Step 6: +Regime (with-regime vs no-regime replay)
  Step 7: +Macro Regime (dominant macro_state paper period vs backtest training period)

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


# State ordering for macro regime distance calculation.
# Lower score = more favorable conditions.
_MACRO_STATE_SCORE: dict[str, int] = {
    "favorable": 0,
    "constructive": 1,
    "neutral": 2,
    "cautious": 3,
    "adverse": 4,
}


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
    macro_regime_delta:
        Drift contribution from differing macro regime conditions between the paper
        trading period and backtest training period. Computed by comparing the
        dominant macro_state in each period. Zero when macro data is unavailable
        or the dominant state is unchanged.
    unexplained_residual:
        paper_pnl - total_explained_pnl.  Positive means paper performed better
        than the model predicts; negative means paper performed worse.
    total_explained_pnl:
        baseline_pnl + fee_delta + slippage_delta + timing_delta +
        data_revision_delta + sizing_delta + regime_delta + macro_regime_delta.
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
    macro_regime_delta: float
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
        macro_regime_delta=0.0,
        unexplained_residual=paper_pnl,
        total_explained_pnl=0.0,
        paper_pnl=paper_pnl,
    )


class DriftAttributor:
    """
    Sequential OAT attribution engine for drift decomposition.

    Runs N+1=8 backtest replays with progressively added cost sources to isolate
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
        Decompose drift into 7 attribution sources via sequential OAT.

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

        # Step 7: +Macro Regime (OBSV-04)
        macro_regime_delta, macro_details = self._compute_macro_regime_delta(
            paper_start=paper_start,
            paper_end=paper_end,
            step2_pnl=step2_pnl,
        )
        logger.debug(
            "macro_regime_delta=%.4f details=%s for config_id=%d asset_id=%d",
            macro_regime_delta,
            macro_details,
            config_id,
            asset_id,
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
            + macro_regime_delta
        )
        unexplained_residual = paper_pnl - total_explained

        logger.info(
            "Attribution complete for config_id=%d asset_id=%d: "
            "baseline=%.4f fee=%.4f slip=%.4f regime=%.4f macro=%.4f residual=%.4f paper=%.4f",
            config_id,
            asset_id,
            baseline_pnl,
            fee_delta,
            slippage_delta,
            regime_delta,
            macro_regime_delta,
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
            macro_regime_delta=macro_regime_delta,
            unexplained_residual=unexplained_residual,
            total_explained_pnl=total_explained,
            paper_pnl=paper_pnl,
        )

    def persist_attribution(
        self,
        config_id: int,
        asset_id: int,
        metric_date: str,
        result: AttributionResult,
    ) -> None:
        """
        Write attribution results to the attr_* columns of cmc_drift_metrics.

        Uses UPDATE (not INSERT) because the DriftMetrics row must already exist
        from the daily DriftMonitor run. This is called from
        run_drift_report.py --with-attribution AFTER run_attribution().

        Parameters
        ----------
        config_id:
            Executor config ID matching the cmc_drift_metrics row.
        asset_id:
            Asset ID matching the cmc_drift_metrics row.
        metric_date:
            ISO date string (YYYY-MM-DD) for the row to update.
        result:
            AttributionResult from run_attribution() containing all delta fields.
        """
        sql = text("""
            UPDATE cmc_drift_metrics
            SET attr_baseline_pnl = :baseline_pnl,
                attr_fee_delta = :fee_delta,
                attr_slippage_delta = :slippage_delta,
                attr_timing_delta = :timing_delta,
                attr_data_revision_delta = :data_revision_delta,
                attr_sizing_delta = :sizing_delta,
                attr_regime_delta = :regime_delta,
                attr_macro_regime_delta = :macro_regime_delta,
                attr_unexplained = :unexplained_residual
            WHERE config_id = :config_id
              AND asset_id = :asset_id
              AND metric_date = :metric_date
        """)
        params = {
            "config_id": config_id,
            "asset_id": asset_id,
            "metric_date": metric_date,
            "baseline_pnl": result.baseline_pnl,
            "fee_delta": result.fee_delta,
            "slippage_delta": result.slippage_delta,
            "timing_delta": result.timing_delta,
            "data_revision_delta": result.data_revision_delta,
            "sizing_delta": result.sizing_delta,
            "regime_delta": result.regime_delta,
            "macro_regime_delta": result.macro_regime_delta,
            "unexplained_residual": result.unexplained_residual,
        }
        with self._engine.begin() as conn:
            row_count = conn.execute(sql, params).rowcount
        if row_count == 0:
            logger.warning(
                "persist_attribution: no matching row for config_id=%d asset_id=%d "
                "metric_date=%s -- run DriftMonitor first to create the base row",
                config_id,
                asset_id,
                metric_date,
            )
        else:
            logger.debug(
                "persist_attribution: updated %d row(s) for config_id=%d asset_id=%d date=%s",
                row_count,
                config_id,
                asset_id,
                metric_date,
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

    def _compute_macro_regime_delta(
        self,
        paper_start: str,
        paper_end: str,
        step2_pnl: float,
    ) -> tuple[float, dict]:
        """
        Compute macro regime attribution delta (Step 7).

        Compares the dominant macro_state during the paper period vs the
        full backtest training period (defined as 1 year before paper_start).
        If they differ, the delta represents the estimated drift contribution
        from macro environment changes.

        Parameters
        ----------
        paper_start:
            ISO date string for the paper trading period start.
        paper_end:
            ISO date string for the paper trading period end.
        step2_pnl:
            P&L from Step 2 (+Fees +Slippage). Used as basis for heuristic scaling.

        Returns
        -------
        Tuple of (delta, details_dict) where details_dict contains:
          paper_dominant_state, backtest_dominant_state, state_distance.
        Returns (0.0, {}) when macro data is unavailable.
        """
        paper_start_dt = pd.Timestamp(paper_start).date()
        paper_end_dt = pd.Timestamp(paper_end).date()
        bt_end_dt = paper_start_dt - pd.Timedelta(days=1)
        bt_start_dt = paper_start_dt - pd.Timedelta(days=365)

        sql_dominant = text("""
            SELECT macro_state, COUNT(*) AS n
            FROM cmc_macro_regimes
            WHERE date BETWEEN :start AND :end
              AND profile = 'default'
            GROUP BY macro_state
            ORDER BY n DESC
            LIMIT 1
        """)

        try:
            with self._engine.connect() as conn:
                paper_row = conn.execute(
                    sql_dominant,
                    {
                        "start": paper_start_dt.isoformat(),
                        "end": paper_end_dt.isoformat(),
                    },
                ).fetchone()
                bt_row = conn.execute(
                    sql_dominant,
                    {"start": bt_start_dt.isoformat(), "end": bt_end_dt.isoformat()},
                ).fetchone()
        except Exception as exc:
            logger.debug(
                "_compute_macro_regime_delta: DB query failed (%s) -- returning 0",
                exc,
            )
            return 0.0, {}

        if paper_row is None or bt_row is None:
            logger.debug(
                "_compute_macro_regime_delta: insufficient macro data "
                "(paper_row=%s bt_row=%s) -- returning 0",
                paper_row,
                bt_row,
            )
            return 0.0, {}

        paper_state = str(paper_row[0])
        bt_state = str(bt_row[0])

        if paper_state == bt_state:
            return 0.0, {
                "paper_dominant_state": paper_state,
                "backtest_dominant_state": bt_state,
                "state_distance": 0,
            }

        paper_score = _MACRO_STATE_SCORE.get(paper_state, 2)  # default: neutral
        bt_score = _MACRO_STATE_SCORE.get(bt_state, 2)
        state_distance = abs(paper_score - bt_score)

        # Heuristic: each state step = ~0.5% of explained PnL (step2_pnl basis).
        # Negative because more adverse conditions reduce expected performance.
        macro_regime_delta = -state_distance * 0.005 * abs(step2_pnl)

        details = {
            "paper_dominant_state": paper_state,
            "backtest_dominant_state": bt_state,
            "state_distance": state_distance,
        }
        return macro_regime_delta, details
