---
phase: 69-l4-resolver-integration
plan: 03
subsystem: executor
tags: [python, sqlalchemy, postgresql, paper-executor, macro-regime, l4, gross-cap, audit-logging]

# Dependency graph
requires:
  - phase: 69-02
    provides: "Alembic migration f1a2b3c4d5e6: l4_regime + l4_size_mult columns on cmc_executor_run_log; cmc_regimes populated with l4_label, gross_cap, size_mult by refresh pipeline"
  - phase: 69-01
    provides: "resolver.py L4 policy entries with gross_cap and size_mult fields"
  - phase: 45-paper-trade-executor
    provides: "PaperExecutor base class, _process_asset_signal, _write_run_log, RiskEngine integration"
provides:
  - "_load_regime_for_asset(): reads l0/l1/l2/l4_label, gross_cap, size_mult from cmc_regimes per asset; graceful fallback to gross_cap=1.0 on any failure"
  - "L4 gross_cap scaling on target_qty in _process_asset_signal() BEFORE RiskEngine gate"
  - "Full regime layers INFO log (l0, l1, l2, l4, size_mult, gross_cap, delta, side) per trade decision"
  - "_write_run_log() INSERT includes l4_regime and l4_size_mult for full audit trail"
  - "run() loads L4 once and stores as self._current_l4_label / _current_l4_size_mult"
affects:
  - "70-macro-risk-gates: risk gate logic can now read l4_regime from run log for post-hoc analysis"
  - "72-macro-observability: dashboard can query l4_regime/l4_size_mult from cmc_executor_run_log"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Load-once-on-self pattern: load global state (L4) once in run(), store as self attributes for per-call access"
    - "getattr fallback for self attributes: getattr(self, '_current_l4_label', None) keeps _write_run_log safe for early-exit paths"
    - "Graceful query degradation: try/except around all regime queries returns defaults, never raises"
    - "Apply gross_cap < 1.0 only: no-op when gross_cap >= 1.0 avoids unnecessary Decimal operations"

key-files:
  created: []
  modified:
    - "src/ta_lab2/executor/paper_executor.py"

key-decisions:
  - "gross_cap scaling applied BEFORE RiskEngine: RiskEngine sees already-scaled qty, preventing double-cap"
  - "Load L4 per-asset (not once globally) in _process_asset_signal: each asset may have different regime row; global L4 stored on self is only for run-log audit"
  - "asset_id=1 used for run-level L4 load in run(): L4 is a global macro regime, same for all assets; id=1 is representative"
  - "Separate INFO log after risk gate: emitted for every decision that passes risk check, giving clean trade-decision audit trail"
  - "getattr(self, '_current_l4_label', None) in _write_run_log: safe for stale-signal and failed early-exit paths that call _write_run_log before run() sets _current_l4_label"

patterns-established:
  - "Load-once-on-self: store run-level global context as self attributes in run(), read via getattr in helpers"
  - "Graceful regime fallback: all regime query failures silently return defaults; DEBUG log only, no WARNING spam"

# Metrics
duration: 2min
completed: 2026-03-03
---

# Phase 69 Plan 03: Executor L4 Awareness + Gross Cap + Audit Logging Summary

**PaperExecutor wired to read full regime context (L0-L4) from cmc_regimes, scale target_qty by L4 gross_cap before the RiskEngine gate, emit all-layer regime log per trade decision, and record l4_regime/l4_size_mult in cmc_executor_run_log**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-03T11:54:56Z
- **Completed:** 2026-03-03T11:57:05Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments
- Added `_load_regime_for_asset()`: queries `cmc_regimes` for `l0_label`, `l1_label`, `l2_label`, `l4_label`, `gross_cap`, `size_mult`; handles missing table, absent row, NULL columns -- all degrade to `gross_cap=1.0` without raising
- Inserted L4 gross_cap scaling block in `_process_asset_signal()` immediately after `target_qty` computation and before the current-position query (ensuring RiskEngine sees already-scaled quantity); scaling only activates when `gross_cap < 1.0`
- Added INFO log line after the risk gate emitting all four regime layers (l0, l1, l2, l4), size_mult, gross_cap, delta, and trade side for every trade decision that passes the risk check
- Extended `run()` to load L4 once before the strategy loop, storing result as `self._current_l4_label` / `self._current_l4_size_mult` for run-level audit access
- Extended `_write_run_log()` INSERT to include `l4_regime` and `l4_size_mult` columns via `getattr` fallback, completing the audit trail for Phase 69

## Task Commits

Each task was committed atomically:

1. **Task 1+2: L4 regime read, gross_cap scaling, regime logging, run log audit columns** - `c1369556` (feat)

**Plan metadata:** (committed after summary creation)

## Files Created/Modified
- `src/ta_lab2/executor/paper_executor.py` - Added `_load_regime_for_asset()` helper, L4 gross_cap scaling in `_process_asset_signal()`, full regime INFO log, run()-level L4 load, `_write_run_log()` l4_regime/l4_size_mult INSERT columns

## Decisions Made
- **gross_cap applied BEFORE RiskEngine**: The risk engine receives the already-scaled `target_qty`, so the gross_cap cap and the risk engine's own position limits compose correctly without double-counting.
- **Per-asset regime read in _process_asset_signal**: Each asset's latest regime row is read individually (despite L4 being global) because l0/l1/l2 vary per asset -- one query covers all layers.
- **Run-level L4 via asset_id=1**: The run log needs a single representative L4 label; since L4 is global, any asset works. Asset_id=1 is consistent with the refresh pipeline's representative row.
- **getattr fallback in _write_run_log**: Safe for the stale-signal and exception paths that call `_write_run_log` before `run()` initializes `_current_l4_label`.

## Deviations from Plan

None - plan executed exactly as written. All four changes (helper method, gross_cap scaling, regime log, run-level load + run log columns) implemented as specified.

## Issues Encountered

ruff-format auto-reformatted the file on the first commit attempt (pre-commit hook). File was re-staged and a new commit was created -- standard workflow.

## User Setup Required

None - no external service configuration required. The `alembic upgrade head` must be run to activate the `f1a2b3c4d5e6` migration (adding `l4_regime`/`l4_size_mult` columns) before executor run logging of L4 data takes effect. This was established in Plan 02.

## Next Phase Readiness

- Phase 69 is complete: L4 resolver (Plan 01) + regime refresh injection (Plan 02) + executor L4 awareness (Plan 03) are all in place
- L4 macro regime flows end-to-end: classifier -> refresh pipeline -> cmc_regimes -> executor -> cmc_executor_run_log
- Phase 70 (macro risk gates) can read `l4_regime` from `cmc_executor_run_log` and/or directly from `cmc_regimes` for real-time gate decisions
- Phase 72 (macro observability dashboard) can query `l4_regime`/`l4_size_mult` from the run log for historical visualisation

---
*Phase: 69-l4-resolver-integration*
*Completed: 2026-03-03*
