---
phase: 73-macro-gate-alert-wiring
plan: 01
status: complete
wave: 1
commits:
  - hash: b14528fe
    message: "fix(73): inject MacroGateEvaluator into PaperExecutor + wire gates/alerts into daily pipeline"
files_modified:
  - src/ta_lab2/executor/paper_executor.py
  - src/ta_lab2/scripts/run_daily_refresh.py
  - .planning/REQUIREMENTS.md
---

# 73-01 Summary: Macro Gate & Alert Wiring

## What Was Done

### Task 1: Inject MacroGateEvaluator into PaperExecutor
- Added `from ta_lab2.risk.macro_gate_evaluator import MacroGateEvaluator` import
- Created `self._macro_gate_evaluator = MacroGateEvaluator(engine)` in `__init__`
- Passed to `RiskEngine(engine, macro_gate_evaluator=self._macro_gate_evaluator)`
- **Impact:** Gate 1.7 (FOMC/CPI/NFP event gates, VIX spike gate, carry unwind gate, credit stress gate, composite stress score) now actually reduces position sizing during live paper trading

### Task 2: Wire Gate Evaluation and Macro Alerts into Daily Pipeline
- Added `TIMEOUT_MACRO_GATES = 120` and `TIMEOUT_MACRO_ALERTS = 60` constants
- Created `run_evaluate_macro_gates()` function — subprocess call to `ta_lab2.scripts.risk.evaluate_macro_gates`
- Created `run_macro_alerts()` function — subprocess call to `ta_lab2.scripts.macro.run_macro_alerts`
- Wired both into pipeline after `cross_asset_agg`, before per-asset regimes, as non-blocking steps
- **Impact:** `dim_macro_gate_state` table auto-refreshes daily; Telegram macro regime transition alerts fire automatically

### Task 3: Fix Requirements Checkboxes
- Changed FRED-01 through FRED-07 from `[ ]` to `[x]` in requirements section
- Changed MREG-01 through MREG-09 from `[ ]` to `[x]` in requirements section
- Traceability table already showed Complete; checkboxes now match

## Gaps Closed

| Gap | Severity | Status |
|-----|----------|--------|
| MacroGateEvaluator not injected into PaperExecutor | CRITICAL | CLOSED |
| evaluate_macro_gates not in run_daily_refresh.py | MODERATE | CLOSED |
| run_macro_alerts not in run_daily_refresh.py | MODERATE | CLOSED |

## E2E Flows Fixed

| Flow | Before | After |
|------|--------|-------|
| Flow 2: Macro event → gate → order reduction | BROKEN | COMPLETE |
| Flow 3: Macro regime change → Telegram alert | PARTIAL | COMPLETE |
