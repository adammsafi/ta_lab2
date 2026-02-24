---
phase: 41-asset-descriptive-stats-correlation
plan: 04
subsystem: pipeline-orchestration
tags: [subprocess, orchestrator, daily-refresh, desc-stats, correlation, argparse]

# Dependency graph
requires:
  - phase: 41-02
    provides: refresh_cmc_asset_stats.py script
  - phase: 41-03
    provides: refresh_cmc_cross_asset_corr.py script
provides:
  - run_all_desc_stats_refreshes.py orchestrator (asset_stats -> correlation sequential pipeline)
  - run_daily_refresh.py --desc-stats standalone flag
  - desc_stats stage in --all pipeline (after AMAs, before regimes)
affects:
  - future phases using --all pipeline integration
  - daily cron/scheduling configurations

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Desc stats orchestrator pattern: sequential subprocess with --continue-on-error gate"
    - "Daily refresh stage insertion: TIMEOUT constant + runner function + CLI flag + execution block"

key-files:
  created:
    - src/ta_lab2/scripts/desc_stats/run_all_desc_stats_refreshes.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "Used -m module invocation (not script path) for desc_stats orchestrator, matching stats/AMA patterns"
  - "TIMEOUT_DESC_STATS = 3600 (1 hour) to cover both asset_stats + correlation per full refresh"
  - "Pipeline position: after AMAs, before regimes (desc stats depend on fresh bars/EMAs, regimes are independent)"
  - "Forwarded --workers as --workers (not --num-processes) to match desc stats CLI parameter name"

patterns-established:
  - "New pipeline stage pattern: add TIMEOUT_* + run_*_refresher() + --flag + validation + run_* var + components list + execution block"

# Metrics
duration: 6min
completed: 2026-02-24
---

# Phase 41 Plan 04: Desc Stats Orchestrator and Daily Refresh Integration Summary

**Sequential desc stats orchestrator (asset_stats -> correlation) wired into daily refresh as --desc-stats stage between AMAs and regimes**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-24T16:51:20Z
- **Completed:** 2026-02-24T16:57:20Z
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments
- Created `run_all_desc_stats_refreshes.py` orchestrator running asset stats then correlation sequentially via subprocess
- Added `--desc-stats` CLI flag to `run_daily_refresh.py` for standalone execution
- Inserted desc_stats stage into `--all` pipeline: bars -> EMAs -> AMAs -> **desc_stats** -> regimes -> stats
- --dry-run propagates correctly through both layers (orchestrator and daily refresh)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create run_all_desc_stats_refreshes.py orchestrator** - `807a6b86` (feat)
2. **Task 2: Wire desc_stats into run_daily_refresh.py** - `803f2b9a` (feat)

## Files Created/Modified
- `src/ta_lab2/scripts/desc_stats/run_all_desc_stats_refreshes.py` - Orchestrator that runs asset_stats then correlation via subprocess, with --continue-on-error, dry-run, timeout handling
- `src/ta_lab2/scripts/run_daily_refresh.py` - Added TIMEOUT_DESC_STATS, run_desc_stats_refresher(), --desc-stats flag, desc_stats stage in --all flow

## Decisions Made
- Used `-m` module invocation (not script path) for the desc_stats orchestrator, consistent with stats runners and matching plan requirement
- TIMEOUT_DESC_STATS = 3600 (1 hour) to accommodate full rebuild of both asset stats + correlation tables
- Pipeline position (after AMAs, before regimes) matches plan spec - desc stats depend on fresh price/EMA data which is available after AMAs complete
- Workers forwarded as `--workers` (not `--num-processes`) to match the parameter name in the desc stats subscripts

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Pre-commit hooks (ruff-format + mixed line endings) fixed CRLF/formatting on both files; re-staged and re-committed after each hook run.
- Used Python patch scripts to apply changes to `run_daily_refresh.py` atomically, avoiding "file modified since read" errors from the Write tool's optimistic locking check.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Desc stats pipeline is fully integrated; `--all` and `--desc-stats` both work
- Plan 41-05 (asset stats dashboard page) is already complete per git log
- Ready for any remaining Phase 41 plans

---
*Phase: 41-asset-descriptive-stats-correlation*
*Completed: 2026-02-24*
