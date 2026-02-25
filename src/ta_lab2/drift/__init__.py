"""Drift guard computation library -- DriftMetrics dataclass, rolling tracking error, and PIT data snapshots."""

from ta_lab2.drift.data_snapshot import collect_data_snapshot
from ta_lab2.drift.drift_metrics import (
    DriftMetrics,
    compute_drift_metrics,
    compute_rolling_tracking_error,
    compute_sharpe,
)

__all__ = [
    "DriftMetrics",
    "compute_drift_metrics",
    "compute_rolling_tracking_error",
    "compute_sharpe",
    "collect_data_snapshot",
]
