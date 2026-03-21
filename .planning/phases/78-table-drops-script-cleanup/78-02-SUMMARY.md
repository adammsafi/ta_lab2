---
phase: 78-table-drops-script-cleanup
plan: 02
subsystem: database
tags: [pipeline, cleanup, sync-scripts, audit-scripts, dead-code, refactor]

requires:
  - phase: 77-direct-to-u-remaining-families
    provides: "Builders write directly to _u tables; sync scripts confirmed no-ops"

provides:
  - "6 deprecated sync scripts deleted (git rm)"
  - "14 Category D audit scripts deleted (git rm)"
  - "_resync_u_tables() dangerous function fully removed from refresh_returns_zscore.py"
  - "All 4 orchestrator files cleaned of sync references"
  - "POST_STEPS in run_all_ama_refreshes.py reduced from 4 to 2 entries"

affects:
  - phase 78-03: table drops can proceed knowing no script will fail on missing tables
  - any operator using refresh_returns_zscore.py: --skip-resync arg removed

tech-stack:
  added: []
  patterns:
    - "Builders write directly to _u tables; no sync step needed anywhere in pipeline"
    - "Dead code removal via git rm (not just disabling) for clean git history"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/amas/run_all_ama_refreshes.py
    - src/ta_lab2/scripts/pipeline/run_go_forward_daily_refresh.py
    - src/ta_lab2/scripts/returns/refresh_returns_zscore.py
    - src/ta_lab2/scripts/setup/ensure_ema_unified_table.py

key-decisions:
  - "Removed --skip-resync CLI arg entirely (function gone, arg would be confusing)"
  - "ensure_ema_unified_table --sync-after replaced with informative no-op message (flag kept for backward compat)"
  - "rename_cmc_prefix.py and refresh_ama_multi_tf.py cosmetic references (string data / docstring) not removed -- they are not live code"

patterns-established:
  - "Pattern: When sync scripts are deleted, also remove all orchestrator PostStep/Step entries referencing them in the same pass"
  - "Pattern: _resync approach (TRUNCATE + sync) is deprecated; builders now own _u table writes directly"

duration: 3min
completed: 2026-03-21
---

# Phase 78 Plan 02: Script Cleanup Summary

**Deleted 20 deprecated scripts (6 sync + 14 audit) and excised the dangerous `_resync_u_tables()` TRUNCATE+sync function from `refresh_returns_zscore.py`, preventing accidental destruction of 400M+ _u table rows**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-21T03:55:15Z
- **Completed:** 2026-03-21T03:58:11Z
- **Tasks:** 2
- **Files modified:** 4 modified, 20 deleted

## Accomplishments

- 6 sync scripts deleted via `git rm`: confirmed Phase 77 no-ops that print deprecation warnings and exit 0
- 14 Category D audit scripts deleted via `git rm`: query siloed tables at runtime, will error after Phase 78-03 drops
- `_resync_u_tables()` function removed from `refresh_returns_zscore.py` -- this function TRUNCATED _u returns tables then called sync scripts; with builders now writing directly to _u, running it would have permanently destroyed all data
- 4 orchestrator files cleaned: `run_all_ama_refreshes.py`, `run_go_forward_daily_refresh.py`, `refresh_returns_zscore.py`, `ensure_ema_unified_table.py`
- All 4 files compile cleanly; `run_all_bar_builders.py` and `run_daily_refresh.py` confirmed clean

## Task Commits

Each task was committed atomically:

1. **Task 1: Delete 6 sync scripts and 14 Category D audit scripts** - `7fe863df` (chore)
2. **Task 2: Clean orchestrator references and remove _resync_u_tables()** - `3689bc57` (chore)

## Files Created/Modified

**Modified (4 orchestrators cleaned):**
- `src/ta_lab2/scripts/amas/run_all_ama_refreshes.py` - POST_STEPS reduced from 4 to 2 (removed sync_values, sync_returns entries)
- `src/ta_lab2/scripts/pipeline/run_go_forward_daily_refresh.py` - ema_u_sync Step removed; --bars-only help updated
- `src/ta_lab2/scripts/returns/refresh_returns_zscore.py` - _RESYNC_MODULES, _RESYNC_U_TABLES, _resync_u_tables(), --skip-resync arg all removed; subprocess import removed
- `src/ta_lab2/scripts/setup/ensure_ema_unified_table.py` - --sync-after block replaced with no-op message; subprocess import + TIMEOUT_SYNC removed

**Deleted (20 scripts):**

Sync scripts (6):
- `src/ta_lab2/scripts/bars/sync_price_bars_multi_tf_u.py`
- `src/ta_lab2/scripts/returns/sync_returns_bars_multi_tf_u.py`
- `src/ta_lab2/scripts/emas/sync_ema_multi_tf_u.py`
- `src/ta_lab2/scripts/returns/sync_returns_ema_multi_tf_u.py`
- `src/ta_lab2/scripts/amas/sync_ama_multi_tf_u.py`
- `src/ta_lab2/scripts/amas/sync_returns_ama_multi_tf_u.py`

Category D audit scripts (14):
- `src/ta_lab2/scripts/bars/audit_price_bars_tables.py`
- `src/ta_lab2/scripts/bars/audit_price_bars_integrity.py`
- `src/ta_lab2/scripts/bars/audit_price_bars_samples.py`
- `src/ta_lab2/scripts/emas/audit_ema_expected_coverage.py`
- `src/ta_lab2/scripts/emas/audit_ema_tables.py`
- `src/ta_lab2/scripts/emas/audit_ema_integrity.py`
- `src/ta_lab2/scripts/emas/audit_ema_samples.py`
- `src/ta_lab2/scripts/returns/audit_returns_bars_multi_tf_integrity.py`
- `src/ta_lab2/scripts/returns/audit_returns_bars_multi_tf_cal_us_integrity.py`
- `src/ta_lab2/scripts/returns/audit_returns_bars_multi_tf_cal_iso_integrity.py`
- `src/ta_lab2/scripts/returns/audit_returns_bars_multi_tf_cal_anchor_us_integrity.py`
- `src/ta_lab2/scripts/returns/audit_returns_bars_multi_tf_cal_anchor_iso_integrity.py`
- `src/ta_lab2/scripts/returns/audit_returns_ema_multi_tf_cal_integrity.py`
- `src/ta_lab2/scripts/returns/audit_returns_ema_multi_tf_cal_anchor_integrity.py`

## Decisions Made

- Removed `--skip-resync` CLI arg from `refresh_returns_zscore.py` entirely rather than keeping as no-op. The function is gone and keeping a meaningless flag would be confusing to operators.
- `ensure_ema_unified_table.py --sync-after` kept as a flag but now logs an informative message explaining sync scripts were removed in Phase 78; preserves backward compatibility for any scripts that pass `--sync-after`.
- Two cosmetic references to sync script names were left in place: a docstring comment in `refresh_ama_multi_tf.py` (line 14) and historical rename mappings in `rename_cmc_prefix.py` (string data in a dict). These are not live executable code and removing them would be unnecessary churn.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 78-03 (SQL DROP TABLE statements) can proceed: no Python script will reference the 30 siloed tables after this cleanup
- The dangerous `_resync_u_tables()` path is fully eliminated; operators running `refresh_returns_zscore.py` are safe
- All orchestrators (run_all_ama_refreshes, run_go_forward_daily_refresh) no longer try to call deleted sync scripts

---
*Phase: 78-table-drops-script-cleanup*
*Completed: 2026-03-21*
