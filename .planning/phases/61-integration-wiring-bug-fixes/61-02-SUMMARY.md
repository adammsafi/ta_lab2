---
phase: 61-integration-wiring-bug-fixes
plan: 02
subsystem: pipeline-orchestration
tags: [daily-refresh, feature-pipeline, drift-report, subprocess, orchestration, bug-fix]

# Dependency graph
requires:
  - phase: 47-drift-guard
    provides: drift_report.py and cmc_drift_metrics DDL with attr_* columns
  - phase: 55-feature-signal-evaluation
    provides: run_all_feature_refreshes script used as subprocess target
provides:
  - Feature refresh stage wired into daily refresh pipeline between regimes and signals
  - Fixed drift_report.py column names aligned to DDL (attr_unexplained not attr_unexplained_residual)
  - Fixed _load_te_threshold fallback to 0.015 matching drift_pause.py default
  - Removed dead drift_paused reference (column never existed in DDL)
affects: [daily-refresh-operators, drift-report-consumers, 61-03-onwards]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Feature refresh stage pattern: subprocess call with --all --tf 1D, reads TARGET_DB_URL from env (no --db-url passthrough)"
    - "Component gate pattern: if not result.success and not args.continue_on_error: return 1"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py
    - src/ta_lab2/drift/drift_report.py

key-decisions:
  - "Feature refresh subprocess does NOT receive --db-url (reads TARGET_DB_URL from env, unlike other stages)"
  - "TE threshold fallback is 0.015 (1.5%) matching drift_pause.py, not 0.05 (5%)"
  - "drift_paused removed entirely (dead code - column never in DDL, not conditional)"

patterns-established:
  - "New pipeline stages follow same ComponentResult pattern as run_signal_refreshes"
  - "TIMEOUT_ constants defined at module top for each stage"

# Metrics
duration: 20min
completed: 2026-02-28
---

# Phase 61 Plan 02: Integration Wiring Bug Fixes - Daily Pipeline + Drift Report Summary

**Feature refresh stage added to daily pipeline (bars->EMAs->AMAs->regimes->features->signals) and 4 DDL-mismatched column names fixed in drift_report.py**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-02-28T19:45:36Z
- **Completed:** 2026-02-28T20:05:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `TIMEOUT_FEATURES = 1800` and `run_feature_refresh_stage()` function to `run_daily_refresh.py` following the same ComponentResult pattern as existing stages
- Added `--features` and `--no-features` CLI arguments; wired into validation check and pipeline after regimes
- Fixed `attr_unexplained_residual` -> `attr_unexplained` in all 3 occurrences in `drift_report.py` (_ATTR_COLUMNS list, exclusion filter, waterfall residual check)
- Removed dead `drift_paused` block (3 lines) -- column never existed in `cmc_drift_metrics` DDL
- Fixed `_load_te_threshold` fallback from `0.05` to `0.015` in docstring, log message, and return value

## Task Commits

Each task was committed atomically:

1. **Task 1: Add feature refresh stage to run_daily_refresh.py** - `4a4e8628` (feat)
2. **Task 2: Fix drift_report.py column-name bugs and TE threshold** - `64f6ed8e` (fix)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/scripts/run_daily_refresh.py` - Added TIMEOUT_FEATURES, run_feature_refresh_stage(), --features/--no-features args, feature stage in pipeline between regimes and signals
- `src/ta_lab2/drift/drift_report.py` - Fixed attr_unexplained column names, removed drift_paused dead code, fixed TE threshold fallback to 0.015

## Decisions Made

- Feature refresh subprocess calls `run_all_feature_refreshes --all --tf 1D` without `--db-url` because the script reads `TARGET_DB_URL` from the environment directly (unlike bar/EMA/regime refreshers that accept `--db-url`). The `db_url` param is accepted in the function signature for interface consistency only.
- All `0.05` references in drift_report.py updated to `0.015` including docstring example values for consistency with drift_pause.py defaults.
- The `drift_paused` block was removed unconditionally (not conditionally guarded) because the column will never appear in `cmc_drift_metrics` DDL -- it is not a soft condition.

## Deviations from Plan

None - plan executed exactly as written. All 8 changes specified in Task 1 and 4 bug fixes in Task 2 were applied without additional work needed.

One minor extension: updated the illustrative docstring example in `_plot_tracking_error` from `0.05 for 5%` to `0.015 for 1.5%` and updated the inline comment in `generate_weekly_report` from `fall back to 0.05` to `fall back to 0.015`. These were clearly implied by Bug 3 fix (achieving 0 grep matches for `0.05`) but not explicitly listed in the action steps.

## Issues Encountered

The pre-commit hook reverted drift_report.py changes after a failed first commit attempt (the file was staged but the commit failed due to unstaged modifications to another file triggering the hook's stash/restore cycle). Re-applied all changes and committed successfully on second attempt by staging only the target file.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Daily refresh pipeline is now complete: bars -> EMAs -> AMAs -> desc_stats -> regimes -> features -> signals -> portfolio -> executor -> drift -> stats
- `--all` includes features by default; `--all --no-features` skips it
- drift_report.py renders without column-name errors and uses correct TE threshold
- Ready for Plan 03 (next bug-fix batch in Phase 61)

---
*Phase: 61-integration-wiring-bug-fixes*
*Completed: 2026-02-28*
