---
phase: 112-pipeline-architecture-separation
plan: 03
subsystem: infra
tags: [pipeline, orchestration, signals, execution, monitoring, polling-loop, dry-run]

# Dependency graph
requires:
  - phase: 112-01
    provides: pipeline_utils.py (ComponentResult, STAGE_ORDER, TIMEOUT_*, run log helpers, kill switch, dead-man switch, completion alert)
  - phase: 112-02
    provides: run_data_pipeline.py, run_features_pipeline.py (chain targets upstream)
provides:
  - run_signals_pipeline.py: standalone signals entry point with macro gates before signal generation
  - run_execution_pipeline.py: execution entry point with single-shot and polling loop modes
  - run_monitoring_pipeline.py: monitoring entry point (single-shot, external timer expected)
affects:
  - 112-04 (sync_signals_to_vm script is the chain target of run_signals_pipeline.py)
  - 112-05 (backward-compat wrapper for run_daily_refresh.py can call all 5 pipelines)
  - Phase 113 (VM deployment uses run_execution_pipeline --loop and run_monitoring_pipeline with systemd timer)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "signal_gate_blocked flag pattern: gate exit code 2 sets bool that controls chain sync, not pipeline failure"
    - "run_polling_loop() as importable function: polling logic separate from main() for testability"
    - "_get_last_signal_ts / _get_last_execution_ts: GREATEST(MAX(ts)) pattern across N signal tables for freshness check"
    - "Consecutive failure limit (3) in polling loop: self-healing guard against persistent executor failures"
    - "pipeline_run_id guard pattern: if pipeline_run_id: before every _complete_pipeline_run call (dry-run safety)"

key-files:
  created:
    - src/ta_lab2/scripts/pipelines/run_signals_pipeline.py
    - src/ta_lab2/scripts/pipelines/run_execution_pipeline.py
    - src/ta_lab2/scripts/pipelines/run_monitoring_pipeline.py
  modified: []

key-decisions:
  - "signal_gate_blocked = True when gate exits code 2: pipeline returns 0 (gate block is informational, not a failure); --chain sync is skipped"
  - "run_polling_loop is importable function not embedded in main(): enables unit testing without running infinite loop"
  - "_SIGNAL_TABLES list of 7 tables: _get_last_signal_ts() queries GREATEST(MAX(ts)) via UNION ALL for accurate freshness detection"
  - "Consecutive failure limit 3 in polling loop: prevents tight infinite retry loop on persistent DB/executor errors"
  - "drift_monitor silently skipped (not errored) when --paper-start absent: matching run_daily_refresh.py Phase 87 behavior"
  - "pipeline_alerts non-blocking: run_pipeline_completion_alert() already returns success=True on failure; no extra guard needed in monitoring pipeline"
  - "stats failure IS terminal in monitoring pipeline: data quality gate -- consistent with monolith behavior"
  - "run_signals_pipeline.py was bundled into Plan 02 commit aaebfb59 (both scripts untracked simultaneously; Plan 02 agent git-added all pipelines/)"

patterns-established:
  - "Signals pipeline: macro_gates -> macro_alerts -> signals -> signal_validation_gate -> ic_staleness_check"
  - "Execution pipeline: calibrate_stops -> portfolio -> executor (single-shot or polling)"
  - "Monitoring pipeline: drift_monitor -> pipeline_alerts -> stats (single-shot, external timer)"

# Metrics
duration: 12min
completed: 2026-04-02
---

# Phase 112 Plan 03: Signals + Execution + Monitoring Pipeline Scripts Summary

**Three VM-ready pipeline entry points: Signals pipeline with macro-gated signal chain, Execution pipeline with always-on polling loop, and Monitoring pipeline as single-shot timer target**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-04-02T03:13:08Z
- **Completed:** 2026-04-02T03:25:00Z
- **Tasks:** 2
- **Files created:** 3

## Accomplishments
- Created `run_signals_pipeline.py` with correct stage order (macro_gates FIRST before signal generation), signal_gate_blocked flag, and --chain support for sync_signals_to_vm
- Created `run_execution_pipeline.py` with both single-shot and polling loop modes; `run_polling_loop()` is an importable, testable function; `_get_last_signal_ts()` queries MAX(ts) across all 7 signal tables
- Created `run_monitoring_pipeline.py` with drift silently skipped when --paper-start absent, non-blocking pipeline_alerts, and terminal stats failure (data quality gate)
- All 3 pipelines verified with `--dry-run` (exit 0) and importable

## Task Commits

Each task was committed atomically:

1. **Task 1: Create run_signals_pipeline.py** - `aaebfb59` (feat, bundled with Plan 02 pipeline commit)
2. **Task 2: Create run_execution_pipeline.py and run_monitoring_pipeline.py** - `cc58afa5` (feat)

## Files Created/Modified
- `src/ta_lab2/scripts/pipelines/run_signals_pipeline.py` - Signals pipeline with PIPELINE_NAME='signals', 5 stages, signal_gate_blocked flag, --chain trigger
- `src/ta_lab2/scripts/pipelines/run_execution_pipeline.py` - Execution pipeline with PIPELINE_NAME='execution', single-shot + polling loop, _get_last_signal_ts / _get_last_execution_ts helpers
- `src/ta_lab2/scripts/pipelines/run_monitoring_pipeline.py` - Monitoring pipeline with PIPELINE_NAME='monitoring', drift skip, non-blocking alerts, terminal stats

## Decisions Made
- **signal_gate_blocked = True on exit code 2:** Pipeline still returns 0 (gate blocking is informational for the chain, not a pipeline failure). The --chain flag controls whether sync_signals_to_vm runs, gated by signal_gate_blocked.
- **run_polling_loop() as importable function:** Extracted from main() so it can be tested, imported, or called without spawning the infinite loop from __main__. Consistent with existing patterns in run_daily_refresh.py.
- **Consecutive failure limit 3 in polling loop:** Prevents tight retry loop on persistent DB/executor errors; sends Telegram alert per failure; exits code 1 on 3rd consecutive failure.
- **drift_monitor silently skipped when --paper-start absent:** Print informational message, continue to pipeline_alerts and stats. Matches Phase 87 behavior from run_daily_refresh.py lines 4619-4645.
- **run_pipeline_completion_alert imported from pipeline_utils:** Plan correctly identified that it was extracted to pipeline_utils in Plan 01, not in run_daily_refresh.py.
- **pipeline_run_id guards (if pipeline_run_id:) before _complete_pipeline_run:** Prevents UUID cast error on empty string when dry_run=True (run_id is None in dry-run, _complete_pipeline_run would try CAST('' AS UUID)).
- **run_signals_pipeline.py bundled in aaebfb59:** Both scripts were untracked simultaneously; Plan 02's pre-commit hook git-added all files in pipelines/. File content is correct (written during Plan 03 execution).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] UUID cast error in dry-run mode**
- **Found during:** Task 1 (run_signals_pipeline.py verification)
- **Issue:** `_complete_pipeline_run(db_url, pipeline_run_id or "", ...)` passed empty string when pipeline_run_id=None (dry-run), causing `CAST('' AS UUID)` PostgreSQL error
- **Fix:** Wrapped all `_complete_pipeline_run` calls with `if pipeline_run_id:` guard; applied same pattern to Tasks 2 pipelines preemptively
- **Files modified:** run_signals_pipeline.py, run_execution_pipeline.py, run_monitoring_pipeline.py
- **Verification:** `--dry-run` exits cleanly with no UUID error
- **Committed in:** aaebfb59 and cc58afa5

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Necessary for dry-run correctness. No scope creep.

## Issues Encountered
- Pre-commit hook auto-formatted files twice (ruff lint fixed unused import, ruff format reformatted); re-staged on second commit attempt (standard project pattern)
- run_signals_pipeline.py was swept into Plan 02's commit (aaebfb59) because both were untracked simultaneously; the file content is the Plan 03 implementation

## User Setup Required
None - no external service configuration required. Pipelines are ready to run with --dry-run; full execution requires DB connection and configured services.

## Next Phase Readiness
- All 5 pipeline scripts exist (Data + Features from Plan 02, Signals + Execution + Monitoring from Plan 03)
- Plan 04 (sync_signals_to_vm) is the next dependency: run_signals_pipeline.py --chain calls it
- Plan 05 (backward-compat wrapper for run_daily_refresh.py) can now import all 5 pipelines
- Phase 113 (VM deployment) can use: `run_execution_pipeline --loop` and `run_monitoring_pipeline` with systemd timer
- No blockers

---
*Phase: 112-pipeline-architecture-separation*
*Completed: 2026-04-02*
