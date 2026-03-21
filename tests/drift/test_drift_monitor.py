"""Unit tests for DriftMonitor -- mock DB and SignalBacktester, no live DB."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from ta_lab2.drift.drift_metrics import DriftMetrics
from ta_lab2.drift.drift_monitor import DriftMonitor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_engine():
    """Create a mock SQLAlchemy engine with context manager support."""
    engine = MagicMock()
    conn = MagicMock()
    engine.begin.return_value.__enter__ = MagicMock(return_value=conn)
    engine.begin.return_value.__exit__ = MagicMock(return_value=False)
    engine.connect.return_value.__enter__ = MagicMock(return_value=conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return engine, conn


def _make_sample_metrics(config_id=1, asset_id=100) -> DriftMetrics:
    return DriftMetrics(
        metric_date=date(2026, 2, 25),
        config_id=config_id,
        asset_id=asset_id,
        signal_type="ema_crossover",
        pit_replay_run_id="abc-123",
        cur_replay_run_id="abc-123",
        paper_trade_count=3,
        replay_trade_count=3,
        unmatched_paper=0,
        unmatched_replay=0,
        paper_cumulative_pnl=50.0,
        replay_pit_cumulative_pnl=48.0,
        replay_cur_cumulative_pnl=48.0,
        absolute_pnl_diff=2.0,
        data_revision_pnl_diff=0.0,
        tracking_error_5d=0.005,
        tracking_error_30d=None,
        paper_sharpe=0.8,
        replay_sharpe=0.75,
        sharpe_divergence=0.05,
        threshold_breach=False,
        drift_pct_of_threshold=33.3,
    )


def _make_sample_config(config_id=1) -> dict:
    return {
        "config_id": config_id,
        "signal_id": 10,
        "signal_type": "ema_crossover",
        "fee_bps": 5.0,
        "slippage_base_bps": 3.0,
        "slippage_mode": "lognormal",
        "asset_ids": [100, 200],
    }


# ---------------------------------------------------------------------------
# _load_active_executor_configs
# ---------------------------------------------------------------------------


def test_load_active_executor_configs_queries_db():
    """_load_active_executor_configs() queries dim_executor_config and includes fee_bps."""
    engine, conn = _make_mock_engine()

    # Return one config row
    config_row = MagicMock()
    config_row.__iter__ = MagicMock(
        return_value=iter([1, 10, "ema_crossover", 5.0, 3.0, "lognormal"])
    )
    config_row.__getitem__ = MagicMock(
        side_effect=lambda i: [1, 10, "ema_crossover", 5.0, 3.0, "lognormal"][i]
    )

    asset_row = MagicMock()
    asset_row.__getitem__ = MagicMock(side_effect=lambda i: [100][i])

    # First call: config query; second call: asset query
    conn.execute.return_value.fetchall.side_effect = [[config_row], [asset_row]]

    monitor = DriftMonitor(engine)
    configs = monitor._load_active_executor_configs()

    # Verify dim_executor_config was queried
    first_sql = str(conn.execute.call_args_list[0][0][0])
    assert "dim_executor_config" in first_sql
    assert "is_active" in first_sql
    assert "fee_bps" in first_sql

    # Verify result structure
    assert len(configs) == 1
    assert configs[0]["config_id"] == 1
    assert configs[0]["fee_bps"] == 5.0
    assert "asset_ids" in configs[0]


# ---------------------------------------------------------------------------
# _check_strategy_drift
# ---------------------------------------------------------------------------


def test_check_strategy_drift_calls_backtester():
    """_check_strategy_drift() instantiates SignalBacktester and calls run_backtest."""
    engine, conn = _make_mock_engine()

    # Mock paper fills as empty (no fills in test)
    conn.execute.return_value.fetchall.return_value = []

    monitor = DriftMonitor(engine)
    config = _make_sample_config()

    mock_trades_df = pd.DataFrame(
        {
            "exit_ts": [pd.Timestamp("2026-01-10")],
            "pnl_dollars": [50.0],
        }
    )
    mock_bt_result = MagicMock()
    mock_bt_result.run_id = "test-run-id"
    mock_bt_result.trades_df = mock_trades_df

    with patch(
        "ta_lab2.drift.drift_monitor._get_signal_backtester_class"
    ) as mock_get_cls:
        mock_cls = MagicMock()
        mock_get_cls.return_value = mock_cls
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_instance.run_backtest.return_value = mock_bt_result

        metrics = monitor._check_strategy_drift(
            config=config,
            asset_id=100,
            paper_start="2026-01-01",
            today="2026-01-31",
        )

    mock_instance.run_backtest.assert_called_once()
    call_kwargs = mock_instance.run_backtest.call_args[1]
    assert call_kwargs.get("signal_type") == "ema_crossover"
    assert call_kwargs.get("signal_id") == 10
    assert call_kwargs.get("asset_id") == 100

    assert isinstance(metrics, DriftMetrics)
    assert metrics.config_id == 1
    assert metrics.asset_id == 100


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


def test_run_writes_metrics_for_each_config():
    """run() should call _write_metrics for each (config, asset) pair."""
    engine, conn = _make_mock_engine()
    monitor = DriftMonitor(engine)

    config = _make_sample_config()  # has asset_ids=[100, 200]
    sample_metrics = _make_sample_metrics()

    monitor._load_active_executor_configs = MagicMock(return_value=[config])
    monitor._check_strategy_drift = MagicMock(return_value=sample_metrics)
    monitor._write_metrics = MagicMock()
    monitor._refresh_summary_view = MagicMock()

    with patch("ta_lab2.drift.drift_monitor.check_drift_threshold", return_value=False):
        with patch(
            "ta_lab2.drift.drift_monitor.check_drift_escalation", return_value=False
        ):
            results = monitor.run(paper_start_date="2026-01-01")

    # 2 assets in config -> 2 calls to _write_metrics
    assert monitor._write_metrics.call_count == 2
    assert len(results) == 2


def test_run_dry_run_skips_writes():
    """With dry_run=True, _write_metrics should NOT be called."""
    engine, conn = _make_mock_engine()
    monitor = DriftMonitor(engine)

    config = _make_sample_config()
    sample_metrics = _make_sample_metrics()

    monitor._load_active_executor_configs = MagicMock(return_value=[config])
    monitor._check_strategy_drift = MagicMock(return_value=sample_metrics)
    monitor._write_metrics = MagicMock()
    monitor._refresh_summary_view = MagicMock()

    with patch("ta_lab2.drift.drift_monitor.check_drift_threshold", return_value=False):
        results = monitor.run(paper_start_date="2026-01-01", dry_run=True)

    monitor._write_metrics.assert_not_called()
    monitor._refresh_summary_view.assert_not_called()
    assert len(results) == 2  # still returns results


def test_run_checks_threshold_and_triggers_pause():
    """run() calls check_drift_threshold for each processed (config, asset) pair."""
    engine, conn = _make_mock_engine()
    monitor = DriftMonitor(engine)

    config = _make_sample_config()
    sample_metrics = _make_sample_metrics()

    monitor._load_active_executor_configs = MagicMock(return_value=[config])
    monitor._check_strategy_drift = MagicMock(return_value=sample_metrics)
    monitor._write_metrics = MagicMock()
    monitor._refresh_summary_view = MagicMock()

    with patch(
        "ta_lab2.drift.drift_monitor.check_drift_threshold", return_value=True
    ) as mock_check:
        with patch(
            "ta_lab2.drift.drift_monitor.check_drift_escalation", return_value=False
        ):
            monitor.run(paper_start_date="2026-01-01")

    # Should have been called twice (once per asset in config)
    assert mock_check.call_count == 2


# ---------------------------------------------------------------------------
# _write_metrics
# ---------------------------------------------------------------------------


def test_write_metrics_upsert_sql():
    """_write_metrics() executes INSERT ... ON CONFLICT DO UPDATE SQL."""
    engine, conn = _make_mock_engine()
    monitor = DriftMonitor(engine)

    metrics = _make_sample_metrics()
    monitor._write_metrics(metrics)

    conn.execute.assert_called_once()
    sql_str = str(conn.execute.call_args[0][0])

    assert "INSERT INTO drift_metrics" in sql_str
    assert "ON CONFLICT" in sql_str
    assert "DO UPDATE" in sql_str


# ---------------------------------------------------------------------------
# _refresh_summary_view
# ---------------------------------------------------------------------------


def test_refresh_summary_view_empty_first():
    """When view has no rows, non-concurrent REFRESH should be used."""
    engine, conn = _make_mock_engine()
    monitor = DriftMonitor(engine)

    # Simulate empty view: COUNT returns 0
    conn.execute.return_value.scalar.return_value = 0

    monitor._refresh_summary_view()

    # Find the refresh call
    refresh_calls = [
        str(c[0][0]) for c in conn.execute.call_args_list if "REFRESH" in str(c[0][0])
    ]
    assert len(refresh_calls) >= 1
    # Non-concurrent refresh should NOT contain 'CONCURRENTLY'
    non_concurrent = [c for c in refresh_calls if "CONCURRENTLY" not in c]
    assert len(non_concurrent) >= 1


# ---------------------------------------------------------------------------
# _aggregate_daily_pnl
# ---------------------------------------------------------------------------


def test_aggregate_daily_pnl_no_fills():
    """Empty fills list -> array of zeros for the date range."""
    engine, _ = _make_mock_engine()
    monitor = DriftMonitor(engine)

    result = monitor._aggregate_daily_pnl(
        fills=[],
        start_date="2026-01-01",
        end_date="2026-01-05",
    )

    assert isinstance(result, np.ndarray)
    assert len(result) == 5
    assert np.all(result == 0.0)
