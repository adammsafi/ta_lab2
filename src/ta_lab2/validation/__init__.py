"""
V1 validation package.

Provides the gate framework (GateStatus/GateResult/score_gate/build_gate_scorecard)
used to score V1 success criteria during Phase 53 paper trading validation,
plus the daily log generator and audit gap detection engine.
"""

from ta_lab2.validation.audit_checker import AuditChecker, AuditFinding
from ta_lab2.validation.daily_log import DailyValidationLog
from ta_lab2.validation.gate_framework import (
    AuditSummary,
    GateResult,
    GateStatus,
    build_gate_scorecard,
    score_gate,
)

__all__ = [
    "GateStatus",
    "GateResult",
    "AuditSummary",
    "score_gate",
    "build_gate_scorecard",
    "DailyValidationLog",
    "AuditChecker",
    "AuditFinding",
]
