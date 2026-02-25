"""Drift guard computation library -- DriftMetrics dataclass, rolling tracking error, and PIT data snapshots."""

from ta_lab2.drift.data_snapshot import collect_data_snapshot
from ta_lab2.drift.drift_metrics import (
    DriftMetrics,
    compute_drift_metrics,
    compute_rolling_tracking_error,
    compute_sharpe,
)
from ta_lab2.drift.drift_monitor import DriftMonitor
from ta_lab2.drift.drift_pause import (
    activate_drift_pause,
    check_drift_escalation,
    check_drift_threshold,
    disable_drift_pause,
)

__all__ = [
    "DriftMetrics",
    "compute_drift_metrics",
    "compute_rolling_tracking_error",
    "compute_sharpe",
    "collect_data_snapshot",
    "activate_drift_pause",
    "disable_drift_pause",
    "check_drift_threshold",
    "check_drift_escalation",
    "DriftMonitor",
]
