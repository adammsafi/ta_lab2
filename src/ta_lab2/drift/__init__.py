"""Drift guard package (Phase 47).

Provides continuous drift monitoring between paper executor and backtest replay:
- DriftMonitor: daily drift comparison orchestrator
- DriftMetrics: drift measurement dataclass and computation
- DriftAttributor: 6-source sequential OAT attribution decomposition
- ReportGenerator: Markdown + Plotly weekly drift reports
- Drift pause: tiered graduated response (WARNING/PAUSE/ESCALATE)
"""

from ta_lab2.drift.attribution import AttributionResult, DriftAttributor
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
from ta_lab2.drift.drift_report import ReportGenerator

__all__ = [
    "AttributionResult",
    "DriftAttributor",
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
    "ReportGenerator",
]
