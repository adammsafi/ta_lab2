"""Risk controls for paper trading -- kill switch, position caps, daily loss, circuit breaker, tail risk, macro gates, margin monitoring."""

from ta_lab2.risk.flatten_trigger import (
    EscalationState,
    FlattenTriggerResult,
    check_flatten_trigger,
)
from ta_lab2.risk.kill_switch import (
    KillSwitchStatus,
    activate_kill_switch,
    get_kill_switch_status,
    print_kill_switch_status,
    re_enable_trading,
)
from ta_lab2.risk.macro_gate_evaluator import MacroGateEvaluator, MacroGateResult
from ta_lab2.risk.macro_gate_overrides import GateOverrideManager
from ta_lab2.risk.margin_monitor import (
    MarginState,
    MarginTier,
    compute_cross_margin_utilization,
    compute_margin_utilization,
    load_margin_tiers,
)
from ta_lab2.risk.override_manager import OverrideInfo, OverrideManager
from ta_lab2.risk.risk_engine import RiskCheckResult, RiskEngine, RiskLimits

__all__ = [
    "RiskEngine",
    "RiskCheckResult",
    "RiskLimits",
    "activate_kill_switch",
    "re_enable_trading",
    "get_kill_switch_status",
    "KillSwitchStatus",
    "print_kill_switch_status",
    "OverrideManager",
    "OverrideInfo",
    "MacroGateEvaluator",
    "MacroGateResult",
    "GateOverrideManager",
    "EscalationState",
    "FlattenTriggerResult",
    "check_flatten_trigger",
    "MarginTier",
    "MarginState",
    "compute_margin_utilization",
    "load_margin_tiers",
    "compute_cross_margin_utilization",
]
