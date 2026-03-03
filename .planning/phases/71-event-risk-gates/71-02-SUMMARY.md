---
phase: 71-event-risk-gates
plan: 02
subsystem: risk
tags: [macro, risk-gates, fred, vix, carry, credit, freshness, composite-score, telegram, cooldown]

# Dependency graph
requires:
  - phase: 71-01
    provides: dim_macro_events, dim_macro_gate_state, cmc_macro_stress_history, dim_macro_gate_overrides tables
  - phase: 66-fred-derived-features
    provides: fred.fred_macro_features with vixcls, hy_oas_30d_zscore, dexjpus_daily_zscore, nfci_level
  - phase: 46-risk-controls
    provides: cmc_risk_events with macro_gate source and event types
provides:
  - MacroGateEvaluator: 7-gate macro evaluator reading fred.fred_macro_features + dim_macro_events
  - GateOverrideManager: per-gate override CRUD with expiry and audit logging
  - Composite stress score (0-100) persisted to cmc_macro_stress_history on each evaluate()
  - Gate state managed with 4h cooldown in dim_macro_gate_state
  - Telegram alerts on all gate state transitions
affects:
  - 71-03 (observability/reporting reads MacroGateEvaluator.evaluate() and GateOverrideManager)
  - executor integration (check_order_gates() for hot-path per-order size scaling)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Worst-of gate stacking: multiple active gates use worst-of state + tightest size_mult among equal states"
    - "Cooldown prevents de-escalation oscillation: escalation is immediate, de-escalation requires 4h cooldown"
    - "carry_signal = -dexjpus_zscore: DEXJPUS=JPY/USD, strengthening JPY = negative zscore = positive carry_signal"
    - "Configurable FLATTEN thresholds via None sentinel (default disabled) -- VIX and carry FLATTEN DB-configurable"
    - "Composite score weights: VIX=0.40, HY=0.25, carry=0.20, NFCI=0.15; re-weighted when components are None"
    - "Freshness uses USFederalHolidayCalendar from pandas.tseries.holiday; graceful fallback to calendar days"
    - "Telegram alerts use plain string severity ('info', 'warning', 'critical') not AlertSeverity enum"

key-files:
  created:
    - src/ta_lab2/risk/macro_gate_evaluator.py
    - src/ta_lab2/risk/macro_gate_overrides.py
  modified: []

key-decisions:
  - "Worst-of stacking: used worst-of (not multiplicative) to match existing L4 tighten-only semantics"
  - "Composite gate activates only at stressed/crisis tier (50+); calm/elevated return normal to avoid false positives"
  - "Freshness gate uses fred.series_values MAX(date) per series_id -- no new table needed"
  - "GateOverrideManager.revert_override() logs event_type='macro_gate_override_expired' (reuse existing type) to keep event log consistent with auto-expiry"
  - "check_order_gates() is intentionally lightweight (single DB read, no writes) for per-order hot path"

patterns-established:
  - "Pattern: Gate override check before applying gate result (override wins, not skipped)"
  - "Pattern: _load_latest_features() returns Optional[float] for all columns, never raises -- gates handle None safely"
  - "Pattern: All gate methods return tuple[str, float] -- ('state', size_mult)"

# Metrics
duration: 6min
completed: 2026-03-03
---

# Phase 71 Plan 02: Event Risk Gates -- MacroGateEvaluator + GateOverrideManager Summary

**MacroGateEvaluator with 7 gates (FOMC/CPI/NFP event windows, VIX, carry, credit, freshness) + composite score, 4h cooldown state management, Telegram alerts, and GateOverrideManager CRUD**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-03T16:20:54Z
- **Completed:** 2026-03-03T16:26:38Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- MacroGateEvaluator.evaluate() reads fred.fred_macro_features and dim_macro_events, evaluates all 7 gates, updates dim_macro_gate_state with cooldown-aware state transitions, and returns worst-of MacroGateResult
- Composite stress score (VIX 40%, HY OAS 25%, carry 20%, NFCI 15%) normalized to 0-100 scale, mapped to calm/elevated/stressed/crisis tiers, and persisted to cmc_macro_stress_history on every evaluate() call
- GateOverrideManager provides full CRUD on dim_macro_gate_overrides: create, get, revert, check, and batch expire -- all with cmc_risk_events dual audit trail
- Gate state cooldown (4h) prevents oscillation: escalation is immediate, de-escalation requires cooldown expiry
- Telegram alerts sent on all gate state transitions via lazy import (graceful degradation if not configured)

## Task Commits

Each task was committed atomically:

1. **Task 1: MacroGateEvaluator -- all gates + composite score + state management** - `c1f1c262` (feat)
2. **Task 2: GateOverrideManager -- per-gate override CRUD with expiry** - `939e8610` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `src/ta_lab2/risk/macro_gate_evaluator.py` - MacroGateEvaluator with 7 gates, composite score, cooldown state management, Telegram alerts, and override integration
- `src/ta_lab2/risk/macro_gate_overrides.py` - GateOverrideManager: create/get/revert/check/expire with dual audit trail

## Decisions Made
- Worst-of stacking chosen over multiplicative (matches L4 tighten-only semantics -- most restrictive gate wins)
- Composite gate activates only at stressed/crisis tier (score >= 50); calm/elevated return normal to avoid constant false positives from background macro noise
- Freshness gate queries `fred.series_values MAX(date)` per series_id directly -- no separate staleness table needed
- GateOverrideManager.revert_override() logs `macro_gate_override_expired` event type (same as auto-expiry) for consistent audit trail
- check_order_gates() is read-only (single DB query, no computation) to keep hot-path overhead minimal
- VIX and carry FLATTEN thresholds default to None (disabled) per plan requirements -- DB-configurable when needed

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered
None beyond ruff format auto-fixing line length in both files (two pre-commit hook cycles resolved cleanly).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- MacroGateEvaluator.evaluate() is callable with any SQLAlchemy engine pointing to the DB with the Phase 71-01 schema
- GateOverrideManager is ready for CLI integration (Phase 71-03 observability)
- check_order_gates() is ready for executor hot-path wiring
- Plan 71-03 (observability/reporting) can read cmc_macro_stress_history and query active gate state

---
*Phase: 71-event-risk-gates*
*Completed: 2026-03-03*
