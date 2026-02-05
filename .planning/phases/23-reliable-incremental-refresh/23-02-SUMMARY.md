---
phase: 23-reliable-incremental-refresh
plan: 02
subsystem: orchestration
tags: [daily-refresh, state-management, subprocess, bars, emas]

# Dependency graph
requires:
  - phase: 23-01
    provides: EMA orchestrator with subprocess isolation
provides:
  - Unified daily refresh script with bars + EMAs coordination
  - State-based bar freshness checking before EMA refresh
  - Shared refresh utilities (parse_ids, resolve_db_url, check_bar_freshness)
affects: [daily-operations, asset-onboarding, maintenance]

# Tech tracking
tech-stack:
  added: []
  patterns: [state-based-coordination, freshness-checking, unified-orchestration]

key-files:
  created:
    - src/ta_lab2/scripts/refresh_utils.py
    - src/ta_lab2/scripts/run_daily_refresh.py
  modified: []

key-decisions:
  - "Explicit target flags required (--bars, --emas, or --all) for clarity"
  - "Bar freshness check runs before EMAs unless --skip-stale-check"
  - "Stale IDs are logged and skipped for EMA refresh to prevent invalid computations"

patterns-established:
  - "State-based coordination: Check bar staleness before EMA refresh"
  - "Shared utilities: parse_ids, resolve_db_url, check_bar_freshness for DRY"
  - "Unified orchestration: Single entry point with component isolation via subprocess"

# Metrics
duration: 5min
completed: 2026-02-05
---

# Phase 23 Plan 02: Unified Daily Refresh Orchestration Summary

**Single command for daily refresh with state-based bar freshness checking and modular bars + EMAs coordination**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-05T20:40:52Z
- **Completed:** 2026-02-05T20:45:25Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `refresh_utils.py` with shared utilities for state checking and ID parsing
- Created `run_daily_refresh.py` as unified orchestration entry point
- Implemented state-based bar freshness checking before EMA refresh
- Stale IDs are automatically filtered out to prevent EMA computations on stale bars

## Task Commits

Each task was committed atomically:

1. **Task 1: Create refresh utilities module** - `a74539df` (feat)
2. **Task 2: Create unified daily refresh script** - `5543ddf5` (feat)

## Files Created/Modified

- `src/ta_lab2/scripts/refresh_utils.py` - Shared utilities for state checking, ID parsing, DB URL resolution
- `src/ta_lab2/scripts/run_daily_refresh.py` - Unified daily refresh orchestrator with bars + EMAs coordination

## Decisions Made

1. **Explicit target flags required**: Users must specify `--bars`, `--emas`, or `--all` for clarity and to prevent accidental runs
2. **Bar freshness check by default**: Before running EMAs, check `cmc_price_bars_1d_state.last_src_ts` and filter to fresh IDs only (configurable via `--staleness-hours`, default 48h)
3. **Skip stale IDs for EMAs**: IDs with stale bars are logged and skipped to prevent EMA computations on incomplete data
4. **Shared utilities module**: Extract common patterns (parse_ids, resolve_db_url) to avoid duplication across orchestrators

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Daily refresh orchestration complete with state-based coordination
- Users can run `run_daily_refresh.py --all --ids all` for complete daily refresh
- Bar freshness checking prevents EMA computations on stale data
- Ready for Pattern Consistency phase (Phase 24) to standardize patterns across all scripts

---
*Phase: 23-reliable-incremental-refresh*
*Completed: 2026-02-05*
