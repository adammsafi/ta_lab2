"""
Walk-forward bake-off orchestration engine.

Runs all signal strategies through purged K-fold CV and CPCV with the full
Kraken cost matrix (12 scenarios: 3 slippage x spot/perps), producing
out-of-sample metrics for composite scoring.

NOTE on expanding-window re-optimization:
    42-CONTEXT.md mentions "Run BOTH fixed-parameter and expanding-window
    re-optimization per fold." This module implements FIXED-PARAMETER evaluation
    only. Expanding-window re-optimization is DELIBERATELY DEFERRED to a
    follow-up plan. Rationale: Fixed-parameter walk-forward is the standard
    baseline and sufficient for V1 strategy selection.

Exports
-------
BakeoffConfig       - Configuration dataclass for a bake-off run
StrategyResult      - Per-strategy result (aggregated across folds)
BakeoffOrchestrator - Main orchestrator class with .run() entry point
cost_scenario_label - Convert CostModel to descriptive label string
build_t1_series     - Build label-end (t1) Series for CV splitters
load_strategy_data  - Load OHLCV + indicator data from DB for a given asset/TF
run_purged_kfold_backtest - Run one strategy through purged K-fold CV
run_cpcv_backtest   - Run one strategy through CPCV for PBO analysis
"""

from __future__ import annotations

import json
import logging
import math
import warnings
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.backtests.costs import CostModel
from ta_lab2.backtests.cv import CPCVSplitter, PurgedKFoldSplitter
from ta_lab2.backtests.psr import compute_dsr, compute_psr

try:
    import vectorbt as vbt
except ImportError:  # pragma: no cover
    vbt = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Kraken cost matrix: 6 spot + 6 perps = 12 scenarios
# Spot:  maker 0.16% (16 bps) x 3 slippage + taker 0.26% (26 bps) x 3 slippage
# Perps: same fees + funding 0.01%/8h = 0.03% per day (3 bps/day) x 6 fee/slip combos
# ---------------------------------------------------------------------------
_SLIPPAGE_LEVELS = [5.0, 10.0, 20.0]  # bps
_SPOT_MAKER_FEE_BPS = 16.0  # Kraken spot maker fee: 0.16% = 16 bps
_SPOT_TAKER_FEE_BPS = 26.0  # Kraken spot taker fee: 0.26% = 26 bps
_PERPS_MAKER_FEE_BPS = 2.0  # Kraken perps maker fee: 0.02% = 2 bps
_PERPS_TAKER_FEE_BPS = 5.0  # Kraken perps taker fee: 0.05% = 5 bps
_PERPS_FUNDING_BPS_DAY = 3.0  # 0.01%/8h * 3 = 0.03%/day = 3 bps/day

KRAKEN_COST_MATRIX: List[CostModel] = (
    [
        # Spot maker scenarios (3): maker 16 bps x slippage 5/10/20
        CostModel(fee_bps=_SPOT_MAKER_FEE_BPS, slippage_bps=slip, funding_bps_day=0.0)
        for slip in _SLIPPAGE_LEVELS
    ]
    + [
        # Spot taker scenarios (3): taker 26 bps x slippage 5/10/20
        CostModel(fee_bps=_SPOT_TAKER_FEE_BPS, slippage_bps=slip, funding_bps_day=0.0)
        for slip in _SLIPPAGE_LEVELS
    ]
    + [
        # Perps maker scenarios (3): maker 2 bps + funding x slippage 5/10/20
        CostModel(
            fee_bps=_PERPS_MAKER_FEE_BPS,
            slippage_bps=slip,
            funding_bps_day=_PERPS_FUNDING_BPS_DAY,
        )
        for slip in _SLIPPAGE_LEVELS
    ]
    + [
        # Perps taker scenarios (3): taker 5 bps + funding x slippage 5/10/20
        CostModel(
            fee_bps=_PERPS_TAKER_FEE_BPS,
            slippage_bps=slip,
            funding_bps_day=_PERPS_FUNDING_BPS_DAY,
        )
        for slip in _SLIPPAGE_LEVELS
    ]
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BakeoffConfig:
    """Configuration for a walk-forward bake-off run."""

    # CV settings
    n_folds: int = 10  # 10-fold purged K-fold (~330 bars/fold at 1D)
    embargo_bars: int = 20  # 1 month of daily bars
    cpcv_n_test_splits: int = 2  # C(10,2) = 45 combos for PBO

    # Run settings
    freq_per_year: int = 365  # daily crypto
    cost_matrix: List[CostModel] = field(default_factory=lambda: KRAKEN_COST_MATRIX)
    spot_only: bool = False  # if True, only run 6 spot scenarios

    # Data settings
    price_col: str = "close"
    min_bars: int = 300  # minimum bars required to run walk-forward

    # Deduplication
    overwrite: bool = False  # if False, skip already-computed rows

    def get_cost_matrix(self) -> List[CostModel]:
        if self.spot_only:
            return [c for c in self.cost_matrix if c.funding_bps_day == 0.0]
        return self.cost_matrix


@dataclass
class FoldMetric:
    """Metrics from a single fold."""

    fold_idx: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    sharpe: float
    total_return: float
    cagr: float
    max_drawdown: float
    trade_count: int
    oos_returns: List[float]  # per-bar OOS returns for PSR


@dataclass
class StrategyResult:
    """Aggregated result for one strategy x cost_scenario x cv_method."""

    strategy_name: str
    asset_id: int
    tf: str
    params: Dict[str, Any]
    cost_scenario: str
    cv_method: str  # "purged_kfold" or "cpcv"
    n_folds: int
    embargo_bars: int
    fold_metrics: List[FoldMetric]

    # Aggregated metrics
    sharpe_mean: float = 0.0
    sharpe_std: float = 0.0
    max_drawdown_mean: float = 0.0
    max_drawdown_worst: float = 0.0
    total_return_mean: float = 0.0
    cagr_mean: float = 0.0
    trade_count_total: int = 0
    turnover: float = 0.0
    psr: float = float("nan")
    dsr: float = float("nan")
    psr_n_obs: int = 0
    pbo_prob: float = float("nan")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def cost_scenario_label(cost: CostModel) -> str:
    """Convert a CostModel to a descriptive scenario label."""
    venue = "perps" if cost.funding_bps_day > 0 else "spot"
    return f"{venue}_fee{cost.fee_bps:.0f}_slip{cost.slippage_bps:.0f}"


def build_t1_series(price_index: pd.DatetimeIndex, holding_bars: int = 1) -> pd.Series:
    """
    Build label-end (t1) Series for CV splitters.

    For a holding period of `holding_bars`, each bar's label ends at
    price_index[i + holding_bars] (capped at the last bar).

    Parameters
    ----------
    price_index : pd.DatetimeIndex
        Sorted datetime index from the price DataFrame.
    holding_bars : int
        Number of bars in the holding period.

    Returns
    -------
    pd.Series
        Index = price_index (label-start), values = label-end timestamps.
    """
    idx = pd.DatetimeIndex(price_index)
    n = len(idx)
    # Shift forward by holding_bars, cap at last index
    ends = [idx[min(i + holding_bars, n - 1)] for i in range(n)]
    return pd.Series(ends, index=idx, name="t1")


def load_strategy_data(engine: Engine, asset_id: int, tf: str) -> pd.DataFrame:
    """
    Load OHLCV + indicator data from DB for a given asset and timeframe.

    Queries features for OHLCV and key indicators needed by all three
    signal generators (EMA, RSI, ATR columns). Also adds EMA columns from
    ema_multi_tf_u for periods needed by ema_trend strategy.

    Returns
    -------
    pd.DataFrame
        Indexed by ts (UTC-aware), columns include:
        open, high, low, close, volume, rsi_14, atr_14,
        ema_5 through ema_200 (computed locally from close if not in features),
        and any available vol/ta columns.
    """
    sql = text(
        """
        SELECT
            ts,
            open,
            high,
            low,
            close,
            volume,
            rsi_14,
            ta_is_outlier
        FROM public.features
        WHERE id = :asset_id
          AND tf = :tf
        ORDER BY ts
        """
    )

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params={"asset_id": asset_id, "tf": tf})

    if df.empty:
        logger.warning(f"No features data for asset_id={asset_id}, tf={tf}")
        return df

    # Timestamp handling - use utc=True to get tz-aware
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts").sort_index()

    # Add locally-computed indicators (fast, no extra DB round-trip)
    # RSI may already exist from features; compute ATR from OHLCV locally
    _add_local_indicators(df)

    logger.info(
        f"Loaded {len(df)} bars for asset_id={asset_id}, tf={tf}, "
        f"range={df.index[0].date()}..{df.index[-1].date()}"
    )
    return df


def _add_local_indicators(df: pd.DataFrame) -> None:
    """Add RSI, ATR, and EMA columns to df in-place (for signal generation)."""
    close = df["close"].astype(float)

    # ATR (Wilder) -- required by breakout_atr
    if "atr_14" not in df.columns and all(
        c in df.columns for c in ("high", "low", "close")
    ):
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        df["atr_14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    # RSI (Wilder) -- required by rsi_mean_revert; use from features if present
    if "rsi_14" not in df.columns:
        ret = close.diff()
        up = ret.clip(lower=0.0).ewm(alpha=1 / 14, adjust=False).mean()
        dn = (-ret.clip(upper=0.0)).ewm(alpha=1 / 14, adjust=False).mean()
        rs = up / dn.replace(0.0, np.nan)
        df["rsi_14"] = 100.0 - (100.0 / (1.0 + rs))

    # EMA columns for ema_trend strategy
    for span in [5, 10, 17, 21, 50, 77, 80, 100, 120, 150, 200]:
        col = f"ema_{span}"
        if col not in df.columns:
            df[col] = close.ewm(span=span, adjust=False).mean()


def _to_python(v: Any) -> Any:
    """Convert numpy scalars to native Python types for psycopg2 binding."""
    if v is None:
        return None
    if hasattr(v, "item"):  # numpy scalar
        return v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _run_single_fold(
    df: pd.DataFrame,
    train_idx: np.ndarray,
    test_idx: np.ndarray,
    signal_fn: Callable,
    params: Dict[str, Any],
    cost: CostModel,
    config: BakeoffConfig,
    fold_idx: int,
) -> Optional[FoldMetric]:
    """
    Execute one fold of walk-forward backtest.

    Parameters on train_idx are FIXED (no re-optimization within fold).
    Signal generation is run on FULL df (parameters are fixed), then
    restricted to test window for evaluation.
    """
    if vbt is None:
        raise ImportError("vectorbt is required; pip install vectorbt")

    if len(test_idx) < 10:
        logger.warning(f"Fold {fold_idx}: test set too small ({len(test_idx)} bars)")
        return None

    # Generate signals on full df (fixed params, no leakage in label generation)
    try:
        entries, exits, size = signal_fn(df, **params)
    except Exception as e:
        logger.warning(f"Fold {fold_idx}: signal_fn failed: {e}")
        return None

    # Restrict to test window for evaluation
    test_index = df.index[test_idx]
    test_start = test_index[0]
    test_end = test_index[-1]

    d_test = df.iloc[test_idx]
    e_in = entries.iloc[test_idx].astype(bool)
    e_out = exits.iloc[test_idx].astype(bool)

    if size is not None:
        sz = size.iloc[test_idx].astype(float)
    else:
        sz = None

    # Next-bar execution (shift signals by 1 bar)
    e_in = e_in.shift(1, fill_value=False).astype(np.bool_)
    e_out = e_out.shift(1, fill_value=False).astype(np.bool_)

    try:
        pf = vbt.Portfolio.from_signals(
            d_test[config.price_col],
            entries=e_in.to_numpy(),
            exits=e_out.to_numpy(),
            size=None if sz is None else sz.to_numpy(),
            **cost.to_vbt_kwargs(),
            init_cash=1_000.0,
            freq="D",
        )
    except Exception as e:
        logger.warning(f"Fold {fold_idx}: vectorbt failed: {e}")
        return None

    equity = pf.value()
    ret_series = pf.returns()
    oos_returns = ret_series.tolist()

    # Deduct perps funding costs post-hoc (CostModel.to_vbt_kwargs doesn't pass funding)
    if cost.funding_bps_day > 0:
        funding_daily = cost.funding_bps_day / 1e4
        # Simple approximation: deduct daily funding on all days with open position
        # (vectorbt returns are already after fee/slippage; deduct funding separately)
        position_open = e_in.cumsum() > e_out.cumsum()
        funding_adj = ret_series.copy()
        funding_adj[position_open] -= funding_daily
        oos_returns = funding_adj.tolist()

    n = len(test_idx)
    if n == 0 or equity.empty:
        return None

    total_return = (
        float(equity.iloc[-1] / equity.iloc[0] - 1.0) if len(equity) > 1 else 0.0
    )
    years = n / config.freq_per_year
    cagr = (
        (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
        if years > 0 and equity.iloc[0] > 0 and len(equity) > 1
        else 0.0
    )
    running_max = equity.cummax()
    dd = (equity / running_max) - 1.0
    max_drawdown = float(dd.min()) if not dd.empty else 0.0

    # Sharpe (annualized)
    ret_np = np.array(oos_returns, dtype=float)
    std = ret_np.std(ddof=0)
    sharpe = (
        float(np.sqrt(config.freq_per_year) * ret_np.mean() / std) if std > 0 else 0.0
    )

    trade_count = int(pf.trades.count())

    return FoldMetric(
        fold_idx=fold_idx,
        train_start=str(df.index[train_idx[0]].date()) if len(train_idx) > 0 else "",
        train_end=str(df.index[train_idx[-1]].date()) if len(train_idx) > 0 else "",
        test_start=str(test_start.date()),
        test_end=str(test_end.date()),
        sharpe=sharpe,
        total_return=total_return,
        cagr=cagr,
        max_drawdown=max_drawdown,
        trade_count=trade_count,
        oos_returns=oos_returns,
    )


def run_purged_kfold_backtest(
    df: pd.DataFrame,
    signal_fn: Callable,
    params: Dict[str, Any],
    t1_series: pd.Series,
    cost: CostModel,
    config: BakeoffConfig,
) -> Dict[str, Any]:
    """
    Run one strategy through purged K-fold CV.

    Parameters
    ----------
    df : pd.DataFrame
        Full dataset indexed by timestamp.
    signal_fn : Callable
        Signal adapter: (df, **params) -> (entries, exits, size).
    params : dict
        Fixed parameters passed to signal_fn.
    t1_series : pd.Series
        Label-end timestamps (from build_t1_series).
    cost : CostModel
        Cost scenario to apply.
    config : BakeoffConfig
        Run configuration.

    Returns
    -------
    dict with keys: fold_metrics, sharpe_mean, sharpe_std, max_drawdown_mean,
    max_drawdown_worst, total_return_mean, cagr_mean, trade_count_total,
    turnover, psr, psr_n_obs, all_oos_returns.
    """
    embargo_frac = config.embargo_bars / len(df) if len(df) > 0 else 0.01
    splitter = PurgedKFoldSplitter(
        n_splits=config.n_folds,
        t1_series=t1_series,
        embargo_frac=embargo_frac,
    )

    fold_metrics: List[FoldMetric] = []
    X_dummy = np.arange(len(df))

    for fold_idx, (train_idx, test_idx) in enumerate(splitter.split(X_dummy)):
        fm = _run_single_fold(
            df, train_idx, test_idx, signal_fn, params, cost, config, fold_idx
        )
        if fm is not None:
            fold_metrics.append(fm)

    return _aggregate_fold_metrics(fold_metrics, config.n_folds, config.embargo_bars)


def run_cpcv_backtest(
    df: pd.DataFrame,
    signal_fn: Callable,
    params: Dict[str, Any],
    t1_series: pd.Series,
    cost: CostModel,
    config: BakeoffConfig,
) -> Dict[str, Any]:
    """
    Run one strategy through CPCV (C(n_folds, 2) combinations) for PBO analysis.

    Parameters match run_purged_kfold_backtest. Returns same dict format
    plus pbo_prob (Probability of Backtest Overfitting estimate).
    """
    embargo_frac = config.embargo_bars / len(df) if len(df) > 0 else 0.01
    splitter = CPCVSplitter(
        n_splits=config.n_folds,
        n_test_splits=config.cpcv_n_test_splits,
        t1_series=t1_series,
        embargo_frac=embargo_frac,
    )

    fold_metrics: List[FoldMetric] = []
    X_dummy = np.arange(len(df))

    n_combos = splitter.get_n_splits()
    logger.debug(f"CPCV: running {n_combos} combinations")

    for fold_idx, (train_idx, test_idx) in enumerate(splitter.split(X_dummy)):
        fm = _run_single_fold(
            df, train_idx, test_idx, signal_fn, params, cost, config, fold_idx
        )
        if fm is not None:
            fold_metrics.append(fm)

    result = _aggregate_fold_metrics(fold_metrics, n_combos, config.embargo_bars)

    # PBO estimate: fraction of CPCV combinations where strategy underperforms
    # the median (simple approximation without full path-matrix construction)
    all_sharpes = [fm.sharpe for fm in fold_metrics]
    if len(all_sharpes) >= 2:
        median_sharpe = float(np.median(all_sharpes))
        n_below = sum(1 for s in all_sharpes if s < median_sharpe)
        result["pbo_prob"] = n_below / len(all_sharpes)
    else:
        result["pbo_prob"] = float("nan")

    return result


def _aggregate_fold_metrics(
    fold_metrics: List[FoldMetric], n_folds: int, embargo_bars: int
) -> Dict[str, Any]:
    """Aggregate per-fold metrics into summary statistics."""
    if not fold_metrics:
        return {
            "fold_metrics": [],
            "sharpe_mean": float("nan"),
            "sharpe_std": float("nan"),
            "max_drawdown_mean": float("nan"),
            "max_drawdown_worst": float("nan"),
            "total_return_mean": float("nan"),
            "cagr_mean": float("nan"),
            "trade_count_total": 0,
            "turnover": float("nan"),
            "psr": float("nan"),
            "psr_n_obs": 0,
            "all_oos_returns": [],
            "pbo_prob": float("nan"),
        }

    sharpes = [fm.sharpe for fm in fold_metrics]
    drawdowns = [fm.max_drawdown for fm in fold_metrics]
    total_returns = [fm.total_return for fm in fold_metrics]
    cagrs = [fm.cagr for fm in fold_metrics]
    trade_counts = [fm.trade_count for fm in fold_metrics]

    # Concatenate all OOS returns for PSR computation
    all_oos = []
    for fm in fold_metrics:
        all_oos.extend(fm.oos_returns)

    # Turnover: average trades per bar per fold
    turnover = (
        sum(trade_counts) / sum(len(fm.oos_returns) for fm in fold_metrics)
        if sum(len(fm.oos_returns) for fm in fold_metrics) > 0
        else 0.0
    )

    # PSR on concatenated OOS returns
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        psr_val = compute_psr(all_oos) if len(all_oos) >= 30 else float("nan")

    return {
        "fold_metrics": fold_metrics,
        "sharpe_mean": float(np.mean(sharpes)),
        "sharpe_std": float(np.std(sharpes, ddof=1)) if len(sharpes) > 1 else 0.0,
        "max_drawdown_mean": float(np.mean(drawdowns)),
        "max_drawdown_worst": float(np.min(drawdowns)),
        "total_return_mean": float(np.mean(total_returns)),
        "cagr_mean": float(np.mean(cagrs)),
        "trade_count_total": int(sum(trade_counts)),
        "turnover": float(turnover),
        "psr": float(psr_val)
        if not (isinstance(psr_val, float) and math.isnan(psr_val))
        else float("nan"),
        "psr_n_obs": len(all_oos),
        "all_oos_returns": all_oos,
        "pbo_prob": float("nan"),  # overridden for CPCV
    }


# ---------------------------------------------------------------------------
# BakeoffOrchestrator
# ---------------------------------------------------------------------------


class BakeoffOrchestrator:
    """
    Walk-forward bake-off orchestration engine.

    Runs each strategy through purged K-fold CV and CPCV with the full
    Kraken cost matrix, computing PSR/DSR and persisting results to
    strategy_bakeoff_results.

    Parameters
    ----------
    engine : Engine
        SQLAlchemy engine for DB reads and writes.
    config : BakeoffConfig
        Configuration controlling CV settings, cost matrix, etc.
    """

    def __init__(self, engine: Engine, config: Optional[BakeoffConfig] = None) -> None:
        self.engine = engine
        self.config = config or BakeoffConfig()

    def run(
        self,
        strategies: Dict[str, Tuple[Callable, List[Dict[str, Any]]]],
        asset_ids: Sequence[int],
        tf: str = "1D",
    ) -> List[StrategyResult]:
        """
        Run the full bake-off for all strategies x assets x cost scenarios.

        Parameters
        ----------
        strategies : dict
            {strategy_name: (signal_fn, [param_dict, ...])} mapping.
        asset_ids : sequence of int
            Asset IDs to evaluate (typically [1, 1027] for BTC/ETH).
        tf : str
            Timeframe (e.g. "1D").

        Returns
        -------
        List[StrategyResult]
            One result per (strategy x asset x params x cost_scenario x cv_method).
        """
        all_results: List[StrategyResult] = []

        for asset_id in asset_ids:
            logger.info(f"Loading data for asset_id={asset_id}, tf={tf}")
            df = load_strategy_data(self.engine, asset_id, tf)

            if df.empty or len(df) < self.config.min_bars:
                logger.warning(
                    f"Insufficient data for asset_id={asset_id}, tf={tf} "
                    f"({len(df)} bars < {self.config.min_bars} minimum). Skipping."
                )
                continue

            t1_series = build_t1_series(df.index, holding_bars=1)

            for strategy_name, (signal_fn, param_grid) in strategies.items():
                logger.info(
                    f"Strategy '{strategy_name}' on asset_id={asset_id}, tf={tf}: "
                    f"{len(param_grid)} param set(s) x {len(self.config.get_cost_matrix())} cost scenarios"
                )

                for params in param_grid:
                    for cost in self.config.get_cost_matrix():
                        scenario_label = cost_scenario_label(cost)

                        # Skip if already computed (unless overwrite=True)
                        if not self.config.overwrite:
                            if self._row_exists(
                                strategy_name,
                                asset_id,
                                tf,
                                params,
                                scenario_label,
                                "purged_kfold",
                            ):
                                logger.debug(
                                    f"  Skipping {strategy_name}/{scenario_label}/purged_kfold (exists)"
                                )
                                continue

                        # --- Purged K-fold ---
                        logger.info(
                            f"  purged_kfold: {strategy_name} / {scenario_label}"
                        )
                        try:
                            pkf_result = run_purged_kfold_backtest(
                                df, signal_fn, params, t1_series, cost, self.config
                            )
                        except Exception as e:
                            logger.error(
                                f"  purged_kfold failed for {strategy_name}/{scenario_label}: {e}"
                            )
                            continue

                        # Collect all Sharpe estimates across strategies for DSR
                        # (will be updated after all strategies run for a given asset/tf/cost)
                        pkf_result["dsr"] = float("nan")  # placeholder

                        pkf_sr = StrategyResult(
                            strategy_name=strategy_name,
                            asset_id=asset_id,
                            tf=tf,
                            params=params,
                            cost_scenario=scenario_label,
                            cv_method="purged_kfold",
                            n_folds=self.config.n_folds,
                            embargo_bars=self.config.embargo_bars,
                            fold_metrics=pkf_result["fold_metrics"],
                            sharpe_mean=pkf_result["sharpe_mean"],
                            sharpe_std=pkf_result["sharpe_std"],
                            max_drawdown_mean=pkf_result["max_drawdown_mean"],
                            max_drawdown_worst=pkf_result["max_drawdown_worst"],
                            total_return_mean=pkf_result["total_return_mean"],
                            cagr_mean=pkf_result["cagr_mean"],
                            trade_count_total=pkf_result["trade_count_total"],
                            turnover=pkf_result["turnover"],
                            psr=pkf_result["psr"],
                            dsr=pkf_result.get("dsr", float("nan")),
                            psr_n_obs=pkf_result["psr_n_obs"],
                            pbo_prob=pkf_result["pbo_prob"],
                        )

                        # --- CPCV ---
                        cpcv_exists = self._row_exists(
                            strategy_name, asset_id, tf, params, scenario_label, "cpcv"
                        )
                        if not self.config.overwrite and cpcv_exists:
                            logger.debug(
                                f"  Skipping {strategy_name}/{scenario_label}/cpcv (exists)"
                            )
                            cpcv_sr = None
                        else:
                            logger.info(f"  cpcv: {strategy_name} / {scenario_label}")
                            try:
                                cpcv_result = run_cpcv_backtest(
                                    df, signal_fn, params, t1_series, cost, self.config
                                )
                            except Exception as e:
                                logger.error(
                                    f"  cpcv failed for {strategy_name}/{scenario_label}: {e}"
                                )
                                cpcv_result = None

                            if cpcv_result is not None:
                                cpcv_result["dsr"] = float("nan")
                                cpcv_sr = StrategyResult(
                                    strategy_name=strategy_name,
                                    asset_id=asset_id,
                                    tf=tf,
                                    params=params,
                                    cost_scenario=scenario_label,
                                    cv_method="cpcv",
                                    n_folds=splitter_n_splits(self.config),
                                    embargo_bars=self.config.embargo_bars,
                                    fold_metrics=cpcv_result["fold_metrics"],
                                    sharpe_mean=cpcv_result["sharpe_mean"],
                                    sharpe_std=cpcv_result["sharpe_std"],
                                    max_drawdown_mean=cpcv_result["max_drawdown_mean"],
                                    max_drawdown_worst=cpcv_result[
                                        "max_drawdown_worst"
                                    ],
                                    total_return_mean=cpcv_result["total_return_mean"],
                                    cagr_mean=cpcv_result["cagr_mean"],
                                    trade_count_total=cpcv_result["trade_count_total"],
                                    turnover=cpcv_result["turnover"],
                                    psr=cpcv_result["psr"],
                                    dsr=cpcv_result.get("dsr", float("nan")),
                                    psr_n_obs=cpcv_result["psr_n_obs"],
                                    pbo_prob=cpcv_result.get("pbo_prob", float("nan")),
                                )
                            else:
                                cpcv_sr = None

                        all_results.append(pkf_sr)
                        if cpcv_sr is not None:
                            all_results.append(cpcv_sr)

        # --- Compute DSR across all strategies for the same asset/tf/cost combo ---
        _compute_and_attach_dsr(all_results)

        # --- Persist results ---
        for sr in all_results:
            try:
                self._persist_results(sr)
            except Exception as e:
                logger.error(
                    f"Failed to persist {sr.strategy_name}/{sr.cv_method}: {e}"
                )

        return all_results

    def _row_exists(
        self,
        strategy_name: str,
        asset_id: int,
        tf: str,
        params: Dict[str, Any],
        cost_scenario: str,
        cv_method: str,
    ) -> bool:
        """Check if a result row already exists in strategy_bakeoff_results."""
        params_json = json.dumps(params, sort_keys=True)
        sql = text(
            """
            SELECT 1 FROM public.strategy_bakeoff_results
            WHERE strategy_name = :strategy_name
              AND asset_id = :asset_id
              AND tf = :tf
              AND params_json = CAST(:params_json AS jsonb)
              AND cost_scenario = :cost_scenario
              AND cv_method = :cv_method
            LIMIT 1
            """
        )
        with self.engine.connect() as conn:
            result = conn.execute(
                sql,
                {
                    "strategy_name": strategy_name,
                    "asset_id": asset_id,
                    "tf": tf,
                    "params_json": params_json,
                    "cost_scenario": cost_scenario,
                    "cv_method": cv_method,
                },
            )
            return result.fetchone() is not None

    def _persist_results(self, sr: StrategyResult) -> None:
        """Persist a StrategyResult to strategy_bakeoff_results."""
        params_json = json.dumps(sr.params, sort_keys=True)

        # Build fold_metrics_json
        fold_metrics_list = [
            {
                "fold_idx": fm.fold_idx,
                "train_start": fm.train_start,
                "train_end": fm.train_end,
                "test_start": fm.test_start,
                "test_end": fm.test_end,
                "sharpe": _to_python(fm.sharpe),
                "total_return": _to_python(fm.total_return),
                "cagr": _to_python(fm.cagr),
                "max_drawdown": _to_python(fm.max_drawdown),
                "trade_count": fm.trade_count,
            }
            for fm in sr.fold_metrics
        ]
        fold_metrics_json = json.dumps(fold_metrics_list)

        sql = text(
            """
            INSERT INTO public.strategy_bakeoff_results (
                strategy_name, asset_id, tf, params_json, cost_scenario, cv_method,
                n_folds, embargo_bars,
                sharpe_mean, sharpe_std, max_drawdown_mean, max_drawdown_worst,
                total_return_mean, cagr_mean, trade_count_total, turnover,
                psr, dsr, psr_n_obs, pbo_prob, fold_metrics_json
            )
            VALUES (
                :strategy_name, :asset_id, :tf,
                CAST(:params_json AS jsonb), :cost_scenario, :cv_method,
                :n_folds, :embargo_bars,
                :sharpe_mean, :sharpe_std, :max_drawdown_mean, :max_drawdown_worst,
                :total_return_mean, :cagr_mean, :trade_count_total, :turnover,
                :psr, :dsr, :psr_n_obs, :pbo_prob,
                CAST(:fold_metrics_json AS jsonb)
            )
            ON CONFLICT (strategy_name, asset_id, tf, params_json, cost_scenario, cv_method)
            DO UPDATE SET
                n_folds = EXCLUDED.n_folds,
                embargo_bars = EXCLUDED.embargo_bars,
                sharpe_mean = EXCLUDED.sharpe_mean,
                sharpe_std = EXCLUDED.sharpe_std,
                max_drawdown_mean = EXCLUDED.max_drawdown_mean,
                max_drawdown_worst = EXCLUDED.max_drawdown_worst,
                total_return_mean = EXCLUDED.total_return_mean,
                cagr_mean = EXCLUDED.cagr_mean,
                trade_count_total = EXCLUDED.trade_count_total,
                turnover = EXCLUDED.turnover,
                psr = EXCLUDED.psr,
                dsr = EXCLUDED.dsr,
                psr_n_obs = EXCLUDED.psr_n_obs,
                pbo_prob = EXCLUDED.pbo_prob,
                fold_metrics_json = EXCLUDED.fold_metrics_json,
                computed_at = now()
            """
        )

        with self.engine.begin() as conn:
            conn.execute(
                sql,
                {
                    "strategy_name": sr.strategy_name,
                    "asset_id": sr.asset_id,
                    "tf": sr.tf,
                    "params_json": params_json,
                    "cost_scenario": sr.cost_scenario,
                    "cv_method": sr.cv_method,
                    "n_folds": sr.n_folds,
                    "embargo_bars": sr.embargo_bars,
                    "sharpe_mean": _to_python(sr.sharpe_mean),
                    "sharpe_std": _to_python(sr.sharpe_std),
                    "max_drawdown_mean": _to_python(sr.max_drawdown_mean),
                    "max_drawdown_worst": _to_python(sr.max_drawdown_worst),
                    "total_return_mean": _to_python(sr.total_return_mean),
                    "cagr_mean": _to_python(sr.cagr_mean),
                    "trade_count_total": _to_python(sr.trade_count_total),
                    "turnover": _to_python(sr.turnover),
                    "psr": _to_python(sr.psr),
                    "dsr": _to_python(sr.dsr),
                    "psr_n_obs": _to_python(sr.psr_n_obs),
                    "pbo_prob": _to_python(sr.pbo_prob),
                    "fold_metrics_json": fold_metrics_json,
                },
            )

        logger.info(
            f"Persisted: {sr.strategy_name}/{sr.cv_method}/{sr.cost_scenario} "
            f"asset_id={sr.asset_id} tf={sr.tf} "
            f"sharpe_mean={sr.sharpe_mean:.3f} psr={sr.psr:.3f}"
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def splitter_n_splits(config: BakeoffConfig) -> int:
    """Return the number of CPCV combinations: C(n_folds, n_test_splits)."""
    from math import comb

    return comb(config.n_folds, config.cpcv_n_test_splits)


def _compute_and_attach_dsr(all_results: List[StrategyResult]) -> None:
    """
    Compute DSR for each strategy using OOS returns from best strategy
    and all strategies' Sharpe estimates within the same (asset, tf, cost_scenario, cv_method).

    DSR requires:
      - best_trial_returns: OOS returns SERIES of the best-Sharpe strategy
      - sr_estimates: list of Sharpe floats from all strategies (for expected_max_sr)
    """
    # Group by (asset_id, tf, cost_scenario, cv_method)
    from collections import defaultdict

    groups: Dict[Tuple, List[StrategyResult]] = defaultdict(list)
    for sr in all_results:
        key = (sr.asset_id, sr.tf, sr.cost_scenario, sr.cv_method)
        groups[key].append(sr)

    # Frequency scaling: annualized Sharpe -> per-bar Sharpe
    # The PSR/DSR formula uses per-bar units (sr_hat = mean/std on per-bar returns).
    # Our sharpe_mean is annualized (multiplied by sqrt(365)).
    # De-annualize to match the per-bar Sharpe computed internally by compute_psr.
    _FREQ_PER_YEAR = 365
    _SR_SCALE = math.sqrt(_FREQ_PER_YEAR)

    # For each group, compute DSR
    for key, group in groups.items():
        if not group:
            continue

        # Collect all per-bar Sharpe estimates for the group
        # (de-annualize by dividing by sqrt(365))
        sr_estimates_perbar = [
            sr.sharpe_mean / _SR_SCALE
            for sr in group
            if not (isinstance(sr.sharpe_mean, float) and math.isnan(sr.sharpe_mean))
        ]

        if not sr_estimates_perbar:
            continue

        # Best strategy by sharpe_mean
        valid = [
            sr
            for sr in group
            if not (isinstance(sr.sharpe_mean, float) and math.isnan(sr.sharpe_mean))
        ]
        if not valid:
            continue

        # Attach DSR to each strategy using per-bar OOS returns + per-bar SR estimates
        # DSR: PSR(sr_star = E[max SR across all strategies in per-bar units])
        for sr in group:
            sr_oos = []
            for fm in sr.fold_metrics:
                sr_oos.extend(fm.oos_returns)

            if len(sr_oos) < 30:
                continue

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sr.dsr = compute_dsr(
                    best_trial_returns=sr_oos,
                    sr_estimates=sr_estimates_perbar,
                )
