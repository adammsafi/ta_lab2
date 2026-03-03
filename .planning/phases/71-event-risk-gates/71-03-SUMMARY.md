---
phase: 71-event-risk-gates
plan: 03
subsystem: risk
tags: [macro, risk-gates, risk-engine, cli, gate-wiring, backward-compat]

# Dependency graph
requires:
  - phase: 71-01
    provides: dim_macro_gate_state, dim_macro_gate_overrides tables
  - phase: 71-02
    provides: MacroGateEvaluator (7 gates + composite), GateOverrideManager (CRUD + expiry)
  - phase: 46-risk-controls
    provides: RiskEngine base, cmc_risk_events, kill switch + circuit breaker + tail risk gates
provides:
  - Gate 1.7 macro gates wired into RiskEngine.check_order() after tail risk, before circuit breaker
  - MacroGateEvaluator injectable via RiskEngine(engine, macro_gate_evaluator=evaluator)
  - No-op behavior when macro_gate_evaluator=None (full backward compatibility)
  - evaluate_macro_gates.py CLI: full evaluate cycle or dry-run read of DB state
  - macro_gate_cli.py CLI: create/list/revert overrides + status subcommands
  - MacroGateEvaluator, MacroGateResult, GateOverrideManager exported from risk __init__.py
affects:
  - executor integration: inject MacroGateEvaluator at RiskEngine construction
  - 72-macro-observability: reads same dim_macro_gate_state for dashboards/reporting

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dependency injection for optional gates: Optional[MacroGateEvaluator] = None preserves backward compat"
    - "Fail-open macro gate: check_order_gates() exception returns ('normal', 1.0) -- never blocks on infra failure"
    - "Stacking multipliers: tail risk and macro gate both scale order_qty independently (worst-of stacking)"
    - "Gate ordering: 1->1.5->1.7->2->3->4->1.6->5 (macro gates after tail, before circuit breaker)"
    - "CLI exit code encodes state: 0=normal, 1=reduce, 2=flatten (scriptable for monitoring)"

# Key files
key-files:
  created:
    - src/ta_lab2/scripts/risk/evaluate_macro_gates.py
    - src/ta_lab2/scripts/risk/macro_gate_cli.py
  modified:
    - src/ta_lab2/risk/risk_engine.py
    - src/ta_lab2/risk/__init__.py

# Decisions
decisions:
  - decision: Fail-open on MacroGateEvaluator exception in check_order()
    rationale: Infrastructure failure (DB down) should not block all orders; fail hard only on explicit configuration errors
    alternatives: Fail-hard (block orders when gate errors) -- rejected as too disruptive
  - decision: Size multipliers stack independently (not worst-of)
    rationale: Tail risk halves qty, then macro gate scales the result; both apply independently for maximum protection
    alternatives: Take worst-of single multiplier -- rejected since plan spec says "both stack (tighten-only)"
  - decision: Gate 1.7 positioned after tail risk (1.5) and before circuit breaker (2)
    rationale: Macro gates are slower-moving regime signals that should not override kill switch/tail risk; circuit breaker is strategy-specific and logically follows
    alternatives: After circuit breaker -- rejected, macro gates should apply broadly

# Metrics
metrics:
  tasks_completed: 2
  tasks_total: 2
  duration: "5 minutes"
  completed: "2026-03-03"

---

# Phase 71 Plan 03: RiskEngine Wiring + CLI Summary

**One-liner:** Gate 1.7 macro gates wired into RiskEngine via optional MacroGateEvaluator injection; evaluate_macro_gates.py and macro_gate_cli.py CLIs created.

## What Was Built

### Gate 1.7 in RiskEngine (risk_engine.py)

`RiskEngine.__init__()` now accepts an optional `macro_gate_evaluator: Optional[MacroGateEvaluator] = None` parameter. When `None` (the default), Gate 1.7 is a complete no-op -- all existing behavior is preserved with zero performance overhead.

Gate 1.7 is inserted in `check_order()` immediately after Gate 1.5 (tail risk) and before Gate 2 (circuit breaker). The gate:

- Calls `_check_macro_gates()` which delegates to `MacroGateEvaluator.check_order_gates()`
- On `FLATTEN`: blocks the order with `macro_stress_gate_triggered` event logged to `cmc_risk_events`
- On `REDUCE` with buy order: scales `order_qty` by `macro_size_mult`
- On `NORMAL`: passes through with no change

Size multipliers from Gate 1.5 and Gate 1.7 stack: tail risk halves the quantity first, then macro gates scale the result. Both apply independently for maximum protection.

`_check_macro_gates()` is fail-open: if `check_order_gates()` raises an exception (e.g., DB down), it returns `('normal', 1.0)` and logs a warning. Infrastructure failures never block orders.

### risk/__init__.py exports

Added `MacroGateEvaluator`, `MacroGateResult`, and `GateOverrideManager` to both imports and `__all__`.

### evaluate_macro_gates.py

Runnable as `python -m ta_lab2.scripts.risk.evaluate_macro_gates`.

- Default mode: calls `MacroGateEvaluator.evaluate()` (triggers full gate evaluation + DB updates)
- `--dry-run`: reads current state from `dim_macro_gate_state` without triggering evaluate
- `--json`: outputs structured JSON with gates array + overall object
- Exit codes: `0=normal`, `1=reduce`, `2=flatten` (scriptable for monitoring/alerting)

### macro_gate_cli.py

Runnable as `python -m ta_lab2.scripts.risk.macro_gate_cli <subcommand>`.

Subcommands:
- `create --gate-id <gate> --type <type> --reason <text> --operator <name> [--expires-hours N]`
- `list [--gate-id <gate>] [--all]`
- `revert --override-id <uuid> --reason <text> --operator <name>`
- `status` -- reads `dim_macro_gate_state`, prints formatted table of all 8 gates

Follows the pattern of `kill_switch_cli.py` and `override_cli.py` (argparse subcommands, `resolve_db_url`, `NullPool`).

## Deviations from Plan

None -- plan executed exactly as written.

## Next Phase Readiness

Phase 72 (macro observability) can now:
- Read `dim_macro_gate_state` for dashboard displays (same table used by CLIs)
- Import `MacroGateEvaluator` from `ta_lab2.risk` for report generation

Executor integration: inject `MacroGateEvaluator` at construction:

```python
from ta_lab2.risk import RiskEngine, MacroGateEvaluator
evaluator = MacroGateEvaluator(engine)
risk = RiskEngine(engine, macro_gate_evaluator=evaluator)
```
