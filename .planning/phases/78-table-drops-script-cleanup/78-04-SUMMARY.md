---
phase: 78-table-drops-script-cleanup
plan: "04"
subsystem: database
tags: [postgresql, price_bars, _u-tables, audit, gap-closure]

# Dependency graph
requires:
  - phase: 78-03
    provides: "30 siloed price_bars_multi_tf variants dropped; only _u table remains"
  - phase: 78-01
    provides: "alignment_source='multi_tf' pattern established for base table rows in _u"
provides:
  - "5 runtime files query price_bars_multi_tf_u with alignment_source='multi_tf'"
  - "run_all_audits.py cleaned of 14 deleted audit script references"
affects: [phase-79, executor, dashboard, drift, validation, exchange-feed]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "All _u table queries filter alignment_source='multi_tf' for base table data"
    - "ALL_AUDIT_SCRIPTS only references scripts verified to exist on disk"

key-files:
  created: []
  modified:
    - src/ta_lab2/executor/position_sizer.py
    - src/ta_lab2/dashboard/pages/10_macro.py
    - src/ta_lab2/drift/data_snapshot.py
    - src/ta_lab2/scripts/exchange/refresh_exchange_price_feed.py
    - src/ta_lab2/scripts/validation/run_preflight_check.py
    - src/ta_lab2/scripts/run_all_audits.py

key-decisions:
  - "alignment_source='multi_tf' (not 'default') is the correct filter for base table data in _u; consistent with 78-01 pattern"
  - "ALL_AUDIT_SCRIPTS trimmed from 17 entries to 3 (only scripts that exist on disk kept)"

patterns-established:
  - "Gap closure: after table drop, grep all runtime files for dropped table name and redirect to _u with alignment_source filter"

# Metrics
duration: 2min
completed: 2026-03-21
---

# Phase 78 Plan 04: Runtime Table Redirect & Audit List Cleanup Summary

**5 runtime files redirected from dropped price_bars_multi_tf to price_bars_multi_tf_u with alignment_source='multi_tf'; run_all_audits.py pruned from 17 entries to 3 valid scripts**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-21T14:35:34Z
- **Completed:** 2026-03-21T14:37:38Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- Restored 5 broken production runtime files that were querying the dropped `price_bars_multi_tf` table (executor, dashboard, drift, exchange feed, preflight check)
- Cleaned `run_all_audits.py` from 17 audit script entries to 3 valid ones -- removed 14 entries for scripts deleted in Phase 78-02
- All 6 files pass syntax check and zero unqualified `price_bars_multi_tf` references remain in source

## Task Commits

1. **Tasks 1+2: Redirect runtime files + clean audit list** - `2e7901b6` (fix)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/executor/position_sizer.py` - Fallback bar price query uses price_bars_multi_tf_u + alignment_source='multi_tf'; debug log source string updated
- `src/ta_lab2/dashboard/pages/10_macro.py` - BTC/ETH overlay chart query uses price_bars_multi_tf_u + alignment_source='multi_tf'
- `src/ta_lab2/drift/data_snapshot.py` - Staleness snapshot bar query uses price_bars_multi_tf_u + alignment_source='multi_tf'
- `src/ta_lab2/scripts/exchange/refresh_exchange_price_feed.py` - Bar close lookup uses price_bars_multi_tf_u + alignment_source='multi_tf'
- `src/ta_lab2/scripts/validation/run_preflight_check.py` - Check 9 staleness query uses price_bars_multi_tf_u + alignment_source='multi_tf'
- `src/ta_lab2/scripts/run_all_audits.py` - ALL_AUDIT_SCRIPTS trimmed from 17 to 3; removed bar/ema/returns-siloed audit entries for deleted scripts

## Decisions Made

- `alignment_source = 'multi_tf'` is the correct filter value for base-table rows in `price_bars_multi_tf_u`, consistent with the pattern established in Plan 78-01. Applied uniformly across all 5 file redirects.
- `ALL_AUDIT_SCRIPTS` trimmed to only the 3 scripts verified to exist: `returns/audit_returns_d1_integrity.py`, `returns/audit_returns_ema_multi_tf_integrity.py`, `returns/audit_returns_ema_multi_tf_u_integrity.py`. A comment explains why the 14 entries were removed.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - all grep matches for the dropped table name were source files (no tricky indirect references found). The `.pyc` cache files matched grep but those are stale bytecode, not source.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 6 files now query the correct `price_bars_multi_tf_u` table with proper `alignment_source` filter
- `run_all_audits.py` will no longer fail with "Script not found" errors for 14 missing scripts
- Ready for Phase 78-05 and 78-06 gap-closure plans

---
*Phase: 78-table-drops-script-cleanup*
*Completed: 2026-03-21*
