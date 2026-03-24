---
phase: 88-integration-testing-go-live
plan: 01
subsystem: testing
tags: [smoke-test, parity-checker, integration, pipeline-validation, cli]

# Dependency graph
requires:
  - phase: 87-live-pipeline-alert-wiring
    provides: full v1.2.0 pipeline stages (bars, emas, features, garch, signals, stop_calibrations, portfolio, executor, drift)
provides:
  - scripts/integration/smoke_test.py: single-command pipeline health check CLI (26 checks, 9 stages + Step 0)
  - parity_checker.py: configurable pnl_correlation_threshold parameter
  - run_parity_check.py: --pnl-correlation-threshold CLI flag for Phase 88 burn-in
affects:
  - 88-02: burn-in protocol uses smoke_test + parity_check with 0.90 threshold
  - 88-03: runbook documents smoke_test usage and parity threshold flag

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Smoke test follows run_preflight_check.py namedtuple pattern: SmokeCheck(name, query, validator) + SmokeResult(name, status, detail)"
    - "NullPool engine + resolve_db_url() for all CLI scripts"
    - "ASCII-only output (no UTF-8 box-drawing chars) for Windows cp1252 safety"
    - "pnl_correlation_threshold stored in report dict and displayed in format_report"

key-files:
  created:
    - src/ta_lab2/scripts/integration/__init__.py
    - src/ta_lab2/scripts/integration/smoke_test.py
  modified:
    - src/ta_lab2/executor/parity_checker.py
    - src/ta_lab2/scripts/executor/run_parity_check.py

key-decisions:
  - "smoke_test IDs: BTC(1), ETH(52), USDT(825), XRP(5426) as default test assets; --ids flag for override"
  - "26 total checks: 4 Step0 + 4 bars + 3 emas + 3 features + 2 garch + 2 signals + 2 stop_calibrations + 2 portfolio + 2 executor + 2 drift"
  - "garch/stop_calibrations/portfolio: table-has-rows check not recency (burn-in may be Day 1)"
  - "executor/drift: accessibility-only checks (paper trading may have no fills yet)"
  - "pnl_correlation_threshold=0.99 preserved as default -- no behavior change when flag omitted"
  - "threshold added to report dict ('pnl_correlation_threshold' key) and displayed in format_report"

patterns-established:
  - "SmokeCheck namedtuple: (name, query, validator) -- same shape as PreflightCheck in run_preflight_check.py"
  - "SmokeResult namedtuple: (name, status, detail) -- same shape as _CheckResult in run_preflight_check.py"
  - "Validator helpers (_val_count_gte, _val_count_zero, _val_stale_check, _val_range, _val_accessible) are closures returning callables"

# Metrics
duration: 6min
completed: 2026-03-24
---

# Phase 88 Plan 01: Integration Smoke Test + Configurable Parity Threshold Summary

**26-check pipeline smoke test CLI covering all 9 v1.2.0 stages, plus configurable pnl_correlation_threshold (default 0.99, Phase 88 burn-in uses 0.90)**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-24T14:57:47Z
- **Completed:** 2026-03-24T15:03:48Z
- **Tasks:** 2
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- Created `scripts/integration/smoke_test.py` with 26 checks across 9 pipeline stages + Step 0 prerequisites
- Recency checks use `ts >= NOW() - 48h` (not just row existence) for bars, emas, features, signals
- Extended `ParityChecker.check()` with `pnl_correlation_threshold` parameter (default 0.99, no behavior change)
- Added `--pnl-correlation-threshold FLOAT` CLI flag to `run_parity_check.py` for Phase 88 burn-in soft gate

## Task Commits

1. **Task 1: Create end-to-end pipeline smoke test script** - `c0739d1c` (feat)
2. **Task 2: Extend parity checker with configurable correlation threshold** - `8c30595a` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `src/ta_lab2/scripts/integration/__init__.py` - Package init for integration scripts
- `src/ta_lab2/scripts/integration/smoke_test.py` - 26-check pipeline smoke test CLI; --db-url/--verbose/--ids flags; exit 0=all pass, 1=any fail
- `src/ta_lab2/executor/parity_checker.py` - Added `pnl_correlation_threshold` param to `check()` and `_evaluate_parity()`; threshold in report dict and format_report
- `src/ta_lab2/scripts/executor/run_parity_check.py` - Added `--pnl-correlation-threshold FLOAT` flag; passes to both bakeoff and single-signal paths

## Decisions Made
- smoke_test IDs: BTC(1), ETH(52), USDT(825), XRP(5426) as default test assets; --ids flag allows override at runtime
- 26 total checks: 4 Step0 + 4 bars + 3 emas + 3 features + 2 garch + 2 signals + 2 stop_calibrations + 2 portfolio + 2 executor + 2 drift
- garch/stop_calibrations/portfolio use table-has-rows (not recency) checks -- valid on burn-in Day 1 before all stages have run
- executor/drift use accessibility-only checks -- paper trading tables may have no rows yet
- pnl_correlation_threshold=0.99 preserved as default -- no behavior change when flag omitted
- threshold stored in report dict and displayed in format_report alongside P&L Correlation line

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- `python -m ta_lab2.scripts.integration.smoke_test` is ready for burn-in Day 1 health verification
- `--pnl-correlation-threshold 0.90` flag ready for Phase 88 soft parity gate
- Phase 88 Plan 02 (daily burn-in report) and Plan 03 (runbook updates) can proceed

---
*Phase: 88-integration-testing-go-live*
*Completed: 2026-03-24*
