---
phase: 53-v1-validation
plan: 01
subsystem: validation
tags: [validation, gate-framework, preflight, dataclass, sqlalchemy, paper-trading]

# Dependency graph
requires:
  - phase: 42-strategy-selection
    provides: BT-01/BT-02 hardcoded gate values from BAKEOFF_SCORECARD.md
  - phase: 45-executor
    provides: cmc_executor_run_log, cmc_orders, cmc_fills tables queried by framework
  - phase: 46-risk-controls
    provides: dim_risk_state, dim_risk_limits, cmc_risk_events, dim_executor_config tables
  - phase: 47-drift-guard
    provides: cmc_drift_metrics table queried for VAL-02 tracking error gate
provides:
  - GateStatus enum (PASS/CONDITIONAL/FAIL) as scoring language for all Phase 53 scripts
  - GateResult dataclass with all gate assessment fields
  - score_gate() function for numeric threshold comparison
  - build_gate_scorecard() returning 7 GateResult objects (BT-01, BT-02, VAL-01 to VAL-05)
  - Query helpers for run days, tracking error, slippage bps, kill switch events
  - AuditSummary dataclass (placeholder for Plan 02)
  - run_preflight_check.py CLI with 15 go/no-go conditions
affects: [53-02, 53-03, 53-04, 54-v1-results-memo]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "3-tier gate assessment: PASS (threshold met), CONDITIONAL (failed but mitigation documented), FAIL (failed, no mitigation)"
    - "PreflightCheck namedtuple pattern: name + query + validator callable"
    - "NullPool engine creation helper (_get_engine) in all validation scripts"
    - "WARN not FAIL for informational checks that don't block the clock"
    - "V1 EXERCISE tagging: exercise kill switch events filtered from real incident counts"

key-files:
  created:
    - src/ta_lab2/validation/__init__.py
    - src/ta_lab2/validation/gate_framework.py
    - src/ta_lab2/scripts/validation/__init__.py
    - src/ta_lab2/scripts/validation/run_preflight_check.py
  modified: []

key-decisions:
  - "3-tier PASS/CONDITIONAL/FAIL framework: CONDITIONAL handles known-fail situations (MaxDD gate) where mitigation exists and was tested"
  - "BT-02 MaxDD gate hardcoded as CONDITIONAL: structural impossibility for long-only BTC; 10% sizing + circuit breaker is the documented mitigation"
  - "V1 EXERCISE event tagging: kill switch exercise events filtered via reason LIKE '%V1 EXERCISE%' to prevent double-counting real incidents in VAL-04"
  - "Check 15 slippage mode is WARN not FAIL: zero-mode is valid for parity but means VAL-03 cannot measure realistic slippage"
  - "AuditSummary is placeholder for Plan 01; full audit_checker.py implementation is in Plan 02"
  - "run_full_audit() in gate_framework.py returns all_signed_off=True placeholder; Plan 02 replaces with real audit"

patterns-established:
  - "Validation gate scorecard: build_gate_scorecard(engine, start_date, end_date) -> list[GateResult]"
  - "Pre-flight checklist: PreflightCheck namedtuple with validator callable returning (bool, detail_str)"
  - "Staleness check: pd.Timestamp with tz_localize/tz_convert to UTC for reliable comparison"

# Metrics
duration: 5min
completed: 2026-02-26
---

# Phase 53 Plan 01: Gate Framework and Pre-Flight Checklist Summary

**PASS/CONDITIONAL/FAIL gate framework (7 V1 gates) and 15-check pre-flight CLI as the scoring engine and go/no-go gate for Phase 53 paper trading validation**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-26T18:22:09Z
- **Completed:** 2026-02-26T18:26:27Z
- **Tasks:** 2
- **Files modified:** 4 created

## Accomplishments

- Created `src/ta_lab2/validation/` package with `GateStatus` enum, `GateResult` dataclass, `score_gate()`, `build_gate_scorecard()`, and all 5 query helpers
- `build_gate_scorecard()` returns 7 GateResult objects covering BT-01, BT-02, VAL-01 through VAL-05 using DB evidence
- Created `run_preflight_check.py` CLI with 15 go/no-go conditions, PASS/WARN/FAIL output, exit code 0/1

## Task Commits

Each task was committed atomically:

1. **Task 1: Gate framework library** - `e37a9635` (feat)
2. **Task 2: Pre-flight checklist CLI** - `ee5a907c` (feat)

**Plan metadata:** (to be committed after SUMMARY.md creation)

## Files Created/Modified

- `src/ta_lab2/validation/__init__.py` - Package exports: GateStatus, GateResult, AuditSummary, score_gate, build_gate_scorecard
- `src/ta_lab2/validation/gate_framework.py` - Core framework: enums, dataclasses, query helpers, scorecard builder (555 lines)
- `src/ta_lab2/scripts/validation/__init__.py` - Scripts package marker
- `src/ta_lab2/scripts/validation/run_preflight_check.py` - Pre-flight CLI (469 lines after reformatting)

## Decisions Made

**3-tier gate framework (PASS/CONDITIONAL/FAIL):** Chosen over binary PASS/FAIL because the MaxDD gate is structurally impossible to pass for long-only BTC strategies. CONDITIONAL handles "gate failed, mitigation documented and tested, proceeding with documented risk" -- how quant risk committees actually work. Reference: PRA SS5/18 on documenting and managing algorithmic trading risks.

**BT-02 MaxDD as CONDITIONAL:** Hardcoded with mitigation string: "Structural: long-only BTC strategies face 70-75% bear-market drawdowns. Mitigation: 10% position fraction + 15% portfolio circuit breaker." This is consistent with the Phase 42 bakeoff scorecard approach (same source data).

**V1 EXERCISE event tagging:** kill switch exercise events tagged via reason LIKE '%V1 EXERCISE%' and excluded from real incident counts. Using existing event_type='kill_switch_activated' with distinguishing reason string avoids the cmc_risk_events CHECK constraint (Pitfall 5 from research).

**Slippage mode as WARN not FAIL:** Zero-mode is a valid configuration for parity testing. Making it a FAIL would block pre-flight unnecessarily. The WARN informs the operator that VAL-03 slippage measurement requires non-zero mode.

**AuditSummary placeholder:** run_full_audit() returns a stub in Plan 01. Plan 02 implements audit_checker.py with full gap detection. The VAL-05 gate will update to use the real implementation.

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered

Pre-commit hooks (ruff + mixed line endings) required two re-stages on each commit. Standard Windows CRLF issue handled automatically by the hook. No manual fixes needed.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

- Gate framework is complete and importable: all downstream Phase 53 plans (02-04) can use `from ta_lab2.validation import GateStatus, GateResult, score_gate, build_gate_scorecard`
- Pre-flight CLI is ready: run `python -m ta_lab2.scripts.validation.run_preflight_check` before starting the 14-day clock
- Plan 02 should replace `run_full_audit()` stub with real `audit_checker.py` implementation (VAL-05 gate accuracy depends on it)
- Plan 03 (kill switch exercise) must tag events with 'V1 EXERCISE' in reason string per the filtering pattern established here

---
*Phase: 53-v1-validation*
*Completed: 2026-02-26*
