"""Drift metrics dataclass and computation functions for paper trading vs backtest replay comparison."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DriftMetrics:
    """
    Represents a full day of drift measurements comparing paper trading to backtest replay.

    Fields align with cmc_drift_metrics table columns.
    """

    metric_date: date
    config_id: int
    asset_id: int
    signal_type: str
    pit_replay_run_id: Optional[str]  # UUID as string
    cur_replay_run_id: Optional[str]
    paper_trade_count: int
    replay_trade_count: int
    unmatched_paper: int
    unmatched_replay: int
    paper_cumulative_pnl: Optional[float]
    replay_pit_cumulative_pnl: Optional[float]
    replay_cur_cumulative_pnl: Optional[float]
    absolute_pnl_diff: Optional[float]
    data_revision_pnl_diff: Optional[float]
    tracking_error_5d: Optional[float]
    tracking_error_30d: Optional[float]
    paper_sharpe: Optional[float]
    replay_sharpe: Optional[float]
    sharpe_divergence: Optional[float]
    threshold_breach: bool = False
    drift_pct_of_threshold: Optional[float] = None


def compute_rolling_tracking_error(
    paper_daily_pnl: np.ndarray,
    replay_daily_pnl: np.ndarray,
    window: int = 5,
) -> np.ndarray:
    """
    Compute rolling standard deviation of (paper - replay) daily P&L differences.

    Uses pd.Series.rolling(window=window, min_periods=window).std() so the first
    (window - 1) entries are NaN. When input arrays have fewer elements than `window`,
    all entries are NaN.

    Parameters
    ----------
    paper_daily_pnl:
        Daily P&L array for paper trading.
    replay_daily_pnl:
        Daily P&L array for backtest replay.
    window:
        Rolling window size (number of trading days).

    Returns
    -------
    np.ndarray
        Rolling tracking error array of the same length as inputs.
    """
    paper = np.asarray(paper_daily_pnl, dtype=float)
    replay = np.asarray(replay_daily_pnl, dtype=float)
    diff = paper - replay
    result = pd.Series(diff).rolling(window=window, min_periods=window).std().values
    return result


def compute_sharpe(daily_pnl: np.ndarray) -> Optional[float]:
    """
    Compute annualized Sharpe ratio: mean(daily_pnl) / std(daily_pnl) * sqrt(365).

    Returns None when:
    - fewer than 2 data points are available, or
    - the standard deviation is zero (no variation in returns).

    Parameters
    ----------
    daily_pnl:
        Array of daily P&L values.

    Returns
    -------
    float | None
    """
    arr = np.asarray(daily_pnl, dtype=float)
    if len(arr) < 2:
        return None
    std = float(np.std(arr, ddof=1))
    if std == 0.0:
        return None
    mean = float(np.mean(arr))
    return mean / std * math.sqrt(365)


def compute_drift_metrics(
    config_id: int,
    asset_id: int,
    signal_type: str,
    metric_date: date,
    paper_daily_pnl: np.ndarray,
    replay_pit_daily_pnl: np.ndarray,
    replay_cur_daily_pnl: np.ndarray,
    paper_trade_count: int,
    replay_trade_count: int,
    unmatched_paper: int,
    unmatched_replay: int,
    pit_replay_run_id: Optional[str],
    cur_replay_run_id: Optional[str],
    threshold: float = 0.015,
    window: int = 5,
) -> DriftMetrics:
    """
    Aggregate paper fills vs replay results into a DriftMetrics object.

    Computes cumulative P&L, P&L differences, rolling tracking errors, Sharpe ratios,
    Sharpe divergence, threshold breach flag, and drift percentage of threshold.

    Parameters
    ----------
    config_id:
        Executor configuration identifier.
    asset_id:
        Asset CMC identifier.
    signal_type:
        Signal type string (e.g. 'ema_crossover').
    metric_date:
        Date for which these metrics apply.
    paper_daily_pnl:
        Daily P&L array from paper trading.
    replay_pit_daily_pnl:
        Daily P&L array from point-in-time backtest replay.
    replay_cur_daily_pnl:
        Daily P&L array from current-data backtest replay.
    paper_trade_count:
        Total trades in paper execution.
    replay_trade_count:
        Total trades in replay execution.
    unmatched_paper:
        Number of paper trades without a replay match.
    unmatched_replay:
        Number of replay trades without a paper match.
    pit_replay_run_id:
        UUID (as string) of the PIT replay backtest run, or None.
    cur_replay_run_id:
        UUID (as string) of the current-data replay backtest run, or None.
    threshold:
        Tracking error threshold for breach detection (default 1.5%).
    window:
        Rolling window for tracking error (default 5 trading days).

    Returns
    -------
    DriftMetrics
    """
    paper = np.asarray(paper_daily_pnl, dtype=float)
    replay_pit = np.asarray(replay_pit_daily_pnl, dtype=float)
    replay_cur = np.asarray(replay_cur_daily_pnl, dtype=float)

    # Cumulative P&L
    paper_cum: Optional[float] = float(np.sum(paper)) if len(paper) > 0 else None
    replay_pit_cum: Optional[float] = (
        float(np.sum(replay_pit)) if len(replay_pit) > 0 else None
    )
    replay_cur_cum: Optional[float] = (
        float(np.sum(replay_cur)) if len(replay_cur) > 0 else None
    )

    # P&L differences
    absolute_pnl_diff: Optional[float] = (
        abs(paper_cum - replay_pit_cum)
        if paper_cum is not None and replay_pit_cum is not None
        else None
    )
    data_revision_pnl_diff: Optional[float] = (
        abs(replay_pit_cum - replay_cur_cum)
        if replay_pit_cum is not None and replay_cur_cum is not None
        else None
    )

    # Tracking errors -- take last non-NaN value from rolling arrays
    def _last_non_nan(arr: np.ndarray) -> Optional[float]:
        non_nan = arr[~np.isnan(arr)]
        return float(non_nan[-1]) if len(non_nan) > 0 else None

    te_5d_arr = compute_rolling_tracking_error(paper, replay_pit, window=5)
    te_30d_arr = compute_rolling_tracking_error(paper, replay_pit, window=30)
    tracking_error_5d = _last_non_nan(te_5d_arr)
    tracking_error_30d = _last_non_nan(te_30d_arr)

    # Sharpe ratios
    paper_sharpe = compute_sharpe(paper)
    replay_sharpe = compute_sharpe(replay_pit)
    sharpe_divergence: Optional[float] = (
        abs(paper_sharpe - replay_sharpe)
        if paper_sharpe is not None and replay_sharpe is not None
        else None
    )

    # Threshold breach
    threshold_breach = tracking_error_5d is not None and tracking_error_5d > threshold
    drift_pct_of_threshold: Optional[float] = (
        (tracking_error_5d / threshold * 100) if tracking_error_5d is not None else None
    )

    return DriftMetrics(
        metric_date=metric_date,
        config_id=config_id,
        asset_id=asset_id,
        signal_type=signal_type,
        pit_replay_run_id=pit_replay_run_id,
        cur_replay_run_id=cur_replay_run_id,
        paper_trade_count=paper_trade_count,
        replay_trade_count=replay_trade_count,
        unmatched_paper=unmatched_paper,
        unmatched_replay=unmatched_replay,
        paper_cumulative_pnl=paper_cum,
        replay_pit_cumulative_pnl=replay_pit_cum,
        replay_cur_cumulative_pnl=replay_cur_cum,
        absolute_pnl_diff=absolute_pnl_diff,
        data_revision_pnl_diff=data_revision_pnl_diff,
        tracking_error_5d=tracking_error_5d,
        tracking_error_30d=tracking_error_30d,
        paper_sharpe=paper_sharpe,
        replay_sharpe=replay_sharpe,
        sharpe_divergence=sharpe_divergence,
        threshold_breach=threshold_breach,
        drift_pct_of_threshold=drift_pct_of_threshold,
    )
