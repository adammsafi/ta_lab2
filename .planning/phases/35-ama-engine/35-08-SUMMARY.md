---
phase: 35-ama-engine
plan: 08
subsystem: database
tags: [ama, orchestrator, daily-refresh, kama, dema, tema, hma, subprocess, pipeline]

# Dependency graph
requires:
  - phase: 35-04
    provides: BaseAMARefresher + refresh_cmc_ama_multi_tf.py (--ids, --tf, --all-tfs, --indicators)
  - phase: 35-05
    provides: AMAReturnsFeature + refresh_cmc_returns_ama.py
  - phase: 35-06
    provides: Calendar refreshers (refresh_cmc_ama_multi_tf_cal_from_bars.py + cal_anchor variant)
  - phase: 35-07
    provides: sync_cmc_ama_multi_tf_u.py + sync_cmc_returns_ama_multi_tf_u.py + refresh_returns_zscore --tables amas
provides:
  - run_all_ama_refreshes.py: all-in-one AMA orchestrator running 7-stage pipeline
  - run_daily_refresh.py --amas: standalone AMA stage in daily refresh
  - run_daily_refresh.py --all: now includes AMAs between EMAs and regimes
affects:
  - Phase 36+ (AMA data available for signal generators via cmc_ama_multi_tf_u)
  - Phase 37 (IC evaluation reads from cmc_returns_ama_multi_tf_u)
  - Ops (daily cron: --all flag now handles full 5-component pipeline)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "AMA orchestrator mirrors EMA orchestrator but uses -m module invocation instead of script path"
    - "PostStep dataclass separates value refreshers from downstream pipeline steps (returns, sync, z-scores)"
    - "Daily refresh: ids_for_amas = ids_for_emas if run_emas else parsed_ids — AMAs inherit fresh-bar IDs from EMA filtering"
    - "TIMEOUT_AMAS = 3600 constant follows same tier as TIMEOUT_EMAS"

key-files:
  created:
    - src/ta_lab2/scripts/amas/run_all_ama_refreshes.py
  modified:
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "Module invocation (-m) used for all AMA subprocesses instead of script file paths — AMA scripts are installed as package modules, consistent with how refresh_returns_zscore and stats runners are invoked"
  - "PostStep dataclass separates value refreshers (RefresherConfig) from post-processing steps — clearly communicates that returns/sync/z-scores only run after at least one value refresher succeeds"
  - "any_value_succeeded gate: post-steps run if at least one value refresher succeeds (not all) — prevents silent skip when one of 3 refreshers fails with --continue-on-error"
  - "ids_for_amas inherits ids_for_emas when run_emas is True — AMAs process same filtered set as EMAs, avoiding stale-bar IDs when running --all"
  - "--all-tfs always passed in run_daily_refresh.run_ama_refreshers() — daily refresh always processes all TFs for AMAs; no per-TF filtering at the orchestrator level"

patterns-established:
  - "7-stage AMA pipeline: multi_tf -> cal -> cal_anchor -> returns -> sync_values -> sync_returns -> zscores"
  - "Orchestrator dry-run shows all 7 stages including post-steps before any execution"

# Metrics
duration: 3min
completed: 2026-02-23
---

# Phase 35 Plan 08: AMA Orchestrator and Daily Refresh Integration Summary

**run_all_ama_refreshes.py orchestrates 7-stage AMA pipeline (3 value refreshers + returns + 2 syncs + z-scores); run_daily_refresh.py --all now includes AMAs between EMAs and regimes**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-23T22:29:08Z
- **Completed:** 2026-02-23T22:32:00Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- run_all_ama_refreshes.py: single command runs complete AMA pipeline in order: multi_tf values -> cal values -> cal_anchor values -> returns (all sources) -> sync values to _u -> sync returns to _u -> z-scores on returns tables
- run_daily_refresh.py: --amas flag for standalone AMA execution, --all now covers 5 components in correct dependency order (bars -> EMAs -> AMAs -> regimes -> stats)
- All CLI flags forwarded correctly: --ids, --tf, --all-tfs, --indicators, --num-processes, --full-rebuild, --continue-on-error, --verbose, --dry-run, --db-url

## Task Commits

Each task was committed atomically:

1. **Task 1: Create run_all_ama_refreshes.py orchestrator** - `cbc7e1dc` (feat)
2. **Task 2: Wire AMAs into run_daily_refresh.py** - `067c11c3` (feat)

**Plan metadata:** (created below as docs commit)

## Files Created/Modified

- `src/ta_lab2/scripts/amas/run_all_ama_refreshes.py` - AMA orchestrator: RefresherConfig + PostStep dataclasses, 3 value refreshers, 4 post-steps, any_value_succeeded gate, dry-run shows all 7 stages
- `src/ta_lab2/scripts/run_daily_refresh.py` - Updated: TIMEOUT_AMAS=3600, run_ama_refreshers() function, --amas CLI flag, --all updated description, AMA block inserted after EMAs before regimes

## Decisions Made

- Used `-m module` invocation for all AMA subprocesses (not script file paths). AMA scripts are installed as package modules — same pattern as `refresh_returns_zscore` and `run_all_stats_runners`. Consistent and avoids hardcoded path dependencies.
- `PostStep` dataclass separates value refreshers from downstream post-processing. Makes it clear that returns/sync/z-scores are downstream of values and only run if values produce data.
- `any_value_succeeded` gate for post-steps (not `all_succeeded`). With `--continue-on-error`, if 2 of 3 value refreshers succeed, post-steps still run on the produced data. This is the correct behavior for incremental recovery.
- `ids_for_amas = ids_for_emas if run_emas else parsed_ids` — when running `--all`, AMAs get the same filtered (fresh-bar) ID set as EMAs. When running `--amas` standalone, uses `parsed_ids` directly.
- `--all-tfs` always passed in `run_ama_refreshers()`. Daily refresh always processes all TFs for AMAs — no per-TF filtering needed at orchestrator level.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Windows CRLF line endings on run_all_ama_refreshes.py**

- **Found during:** Task 1 commit attempt
- **Issue:** Pre-commit mixed-line-ending hook failed — Windows writes CRLF, project uses LF
- **Fix:** Hook auto-fixed the file; re-staged and committed on second attempt
- **Files modified:** src/ta_lab2/scripts/amas/run_all_ama_refreshes.py
- **Verification:** Pre-commit passed on second commit attempt
- **Committed in:** cbc7e1dc (Task 1 commit, after re-stage)

**2. [Rule 1 - Bug] ruff-format reformatting on run_daily_refresh.py**

- **Found during:** Task 2 commit attempt
- **Issue:** Pre-commit ruff-format hook failed — long string literals and multiline expressions needed normalization
- **Fix:** Hook auto-fixed the file; re-staged and committed on second attempt
- **Files modified:** src/ta_lab2/scripts/run_daily_refresh.py
- **Verification:** Pre-commit passed on second commit attempt
- **Committed in:** 067c11c3 (Task 2 commit, after re-stage)

---

**Total deviations:** 2 auto-fixed (2 formatting/line-ending — same Windows CRLF + ruff pattern as prior AMA plans)
**Impact on plan:** No logic change. Formatting normalization only.

## Issues Encountered

None — both scripts followed established patterns exactly. AMA orchestrator mirrors EMA orchestrator structure with clear additions for post-steps. Daily refresh integration followed the exact run_ema_refreshers() pattern.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- AMA pipeline fully integrated: `python -m ta_lab2.scripts.run_daily_refresh --all` now refreshes bars, EMAs, AMAs (all 5 variants), returns, _u tables, and z-scores in one command
- AMA data available in `cmc_ama_multi_tf_u` for signal generators via LEFT JOINs (same pattern as `cmc_ema_multi_tf_u`)
- Phase 35 (AMA Engine) complete — all 8 plans executed
- Phase 36 signal generators can incorporate AMA indicators as signal sources
- Phase 37 IC evaluation can read AMA returns + z-scores from `cmc_returns_ama_multi_tf_u`

---
*Phase: 35-ama-engine*
*Completed: 2026-02-23*
