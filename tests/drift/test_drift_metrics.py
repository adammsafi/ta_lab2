"""Unit tests for drift metrics computation -- pure functions, no DB required."""

from __future__ import annotations

import math
from datetime import date

import numpy as np
import pytest

from ta_lab2.drift import (
    compute_drift_metrics,
    compute_rolling_tracking_error,
    compute_sharpe,
)


# ---------------------------------------------------------------------------
# compute_rolling_tracking_error
# ---------------------------------------------------------------------------


def test_compute_rolling_tracking_error_basic() -> None:
    """Rolling std of (paper - replay) diffs with window=3.

    paper=[1,2,3,4,5], replay=[1,1,1,1,1] => diff=[0,1,2,3,4]
    window=3: first two values are NaN; remaining values are std of [0,1,2], [1,2,3], [2,3,4]
    All equal 1.0 (ddof=1).
    """
    paper = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    replay = np.array([1.0, 1.0, 1.0, 1.0, 1.0])
    result = compute_rolling_tracking_error(paper, replay, window=3)

    assert len(result) == 5
    assert np.isnan(result[0])
    assert np.isnan(result[1])
    assert result[2] == pytest.approx(1.0)
    assert result[3] == pytest.approx(1.0)
    assert result[4] == pytest.approx(1.0)


def test_compute_rolling_tracking_error_insufficient_data() -> None:
    """Arrays shorter than window produce an all-NaN result."""
    paper = np.array([1.0, 2.0])
    replay = np.array([0.5, 0.5])
    result = compute_rolling_tracking_error(paper, replay, window=5)

    assert len(result) == 2
    assert all(np.isnan(v) for v in result)


def test_compute_rolling_tracking_error_identical() -> None:
    """paper == replay => diff is all zeros => rolling std is 0.0 (no variation)."""
    paper = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    replay = paper.copy()
    result = compute_rolling_tracking_error(paper, replay, window=3)

    assert len(result) == 5
    assert np.isnan(result[0])
    assert np.isnan(result[1])
    # std of three zeros is 0.0
    assert result[2] == pytest.approx(0.0)
    assert result[3] == pytest.approx(0.0)
    assert result[4] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# compute_sharpe
# ---------------------------------------------------------------------------


def test_compute_sharpe_normal() -> None:
    """Known P&L array: Sharpe = mean/std * sqrt(365)."""
    arr = np.array([0.01, 0.02, 0.03, 0.01, 0.02])
    mean = float(np.mean(arr))
    std = float(np.std(arr, ddof=1))
    expected = mean / std * math.sqrt(365)

    result = compute_sharpe(arr)

    assert result is not None
    assert result == pytest.approx(expected, rel=1e-6)


def test_compute_sharpe_zero_std() -> None:
    """All identical values => std == 0 => returns None."""
    arr = np.array([0.05, 0.05, 0.05, 0.05])
    assert compute_sharpe(arr) is None


def test_compute_sharpe_single_value() -> None:
    """Single-element array => len < 2 => returns None."""
    arr = np.array([0.05])
    assert compute_sharpe(arr) is None


# ---------------------------------------------------------------------------
# compute_drift_metrics -- helper
# ---------------------------------------------------------------------------


def _make_metrics(**overrides):
    """Build a DriftMetrics via compute_drift_metrics with sensible defaults."""
    defaults = dict(
        config_id=1,
        asset_id=100,
        signal_type="ema_crossover",
        metric_date=date(2026, 2, 25),
        paper_daily_pnl=np.array([0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01]),
        replay_pit_daily_pnl=np.array([0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01]),
        replay_cur_daily_pnl=np.array([0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01]),
        paper_trade_count=7,
        replay_trade_count=7,
        unmatched_paper=0,
        unmatched_replay=0,
        pit_replay_run_id="aaaaaaaa-0000-0000-0000-000000000001",
        cur_replay_run_id="aaaaaaaa-0000-0000-0000-000000000002",
        threshold=0.015,
        window=5,
    )
    defaults.update(overrides)
    return compute_drift_metrics(**defaults)


# ---------------------------------------------------------------------------
# compute_drift_metrics -- tests
# ---------------------------------------------------------------------------


def test_compute_drift_metrics_no_breach() -> None:
    """Arrays that are nearly identical -> tracking error well below threshold -> no breach."""
    paper = np.array([0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01])
    replay = np.array([0.0099, 0.0099, 0.0099, 0.0099, 0.0099, 0.0099, 0.0099])
    metrics = _make_metrics(
        paper_daily_pnl=paper,
        replay_pit_daily_pnl=replay,
        replay_cur_daily_pnl=replay,
        threshold=0.015,
    )

    assert metrics.threshold_breach is False
    assert metrics.tracking_error_5d is not None
    assert metrics.tracking_error_5d < 0.015


def test_compute_drift_metrics_with_breach() -> None:
    """Large divergence between paper and replay -> tracking error exceeds threshold -> breach."""
    paper = np.array([0.05, 0.10, 0.05, 0.10, 0.05, 0.10, 0.05])
    replay = np.array([-0.05, -0.10, -0.05, -0.10, -0.05, -0.10, -0.05])
    metrics = _make_metrics(
        paper_daily_pnl=paper,
        replay_pit_daily_pnl=replay,
        replay_cur_daily_pnl=replay,
        threshold=0.015,
    )

    assert metrics.threshold_breach is True
    assert metrics.drift_pct_of_threshold is not None
    assert metrics.drift_pct_of_threshold > 100.0


def test_compute_drift_metrics_insufficient_window() -> None:
    """Fewer than 5 days of data -> tracking_error_5d is None -> no breach."""
    paper = np.array([0.01, 0.02, 0.03])
    replay = np.array([0.01, 0.01, 0.01])
    metrics = _make_metrics(
        paper_daily_pnl=paper,
        replay_pit_daily_pnl=replay,
        replay_cur_daily_pnl=replay,
        paper_trade_count=3,
        replay_trade_count=3,
        threshold=0.015,
        window=5,
    )

    assert metrics.tracking_error_5d is None
    assert metrics.threshold_breach is False


def test_compute_drift_metrics_cumulative_pnl() -> None:
    """paper_cumulative_pnl == sum(paper_daily_pnl) and absolute_pnl_diff is correct."""
    paper = np.array([0.01, 0.02, 0.03, 0.04, 0.05, 0.01, 0.02])
    replay_pit = np.array([0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01])
    metrics = _make_metrics(
        paper_daily_pnl=paper,
        replay_pit_daily_pnl=replay_pit,
        replay_cur_daily_pnl=replay_pit,
    )

    expected_paper_cum = float(np.sum(paper))
    expected_replay_pit_cum = float(np.sum(replay_pit))
    expected_abs_diff = abs(expected_paper_cum - expected_replay_pit_cum)

    assert metrics.paper_cumulative_pnl == pytest.approx(expected_paper_cum)
    assert metrics.replay_pit_cumulative_pnl == pytest.approx(expected_replay_pit_cum)
    assert metrics.absolute_pnl_diff == pytest.approx(expected_abs_diff)


def test_data_revision_pnl_diff() -> None:
    """data_revision_pnl_diff == abs(replay_pit_cum - replay_cur_cum) when arrays differ."""
    replay_pit = np.array([0.01, 0.02, 0.03, 0.04, 0.05, 0.01, 0.02])
    replay_cur = np.array([0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02])
    metrics = _make_metrics(
        replay_pit_daily_pnl=replay_pit,
        replay_cur_daily_pnl=replay_cur,
    )

    pit_cum = float(np.sum(replay_pit))
    cur_cum = float(np.sum(replay_cur))
    expected = abs(pit_cum - cur_cum)

    assert metrics.data_revision_pnl_diff == pytest.approx(expected)
    assert metrics.replay_pit_cumulative_pnl == pytest.approx(pit_cum)
    assert metrics.replay_cur_cumulative_pnl == pytest.approx(cur_cum)
