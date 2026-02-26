"""V1 validation tooling -- gate assessment, daily logs, audit, reports."""

from ta_lab2.validation.gate_framework import (
    AuditSummary,
    GateResult,
    GateStatus,
    build_gate_scorecard,
    score_gate,
)

try:
    from ta_lab2.validation.audit_checker import AuditChecker, AuditFinding
except ImportError:
    pass

try:
    from ta_lab2.validation.daily_log import DailyValidationLog
except ImportError:
    pass

try:
    from ta_lab2.validation.report_builder import ValidationReportBuilder
except ImportError:
    pass

__all__ = [
    "GateStatus",
    "GateResult",
    "AuditSummary",
    "score_gate",
    "build_gate_scorecard",
    "AuditChecker",
    "AuditFinding",
    "DailyValidationLog",
    "ValidationReportBuilder",
]
