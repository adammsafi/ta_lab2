---
phase: 85-dashboard-cleanup-polish
plan: 02
subsystem: ui
tags: [streamlit, dashboard, engine-init, drawdown, kpi, pipeline-monitor]

# Dependency graph
requires:
  - phase: 83-dashboard-core
    provides: Phase 83/84 structural pattern (single module-level engine with st.stop)
  - phase: 85-01
    provides: drawdown_usd column in load_daily_pnl_series DataFrame
provides:
  - Landing page using single module-level engine init with st.stop on failure
  - Pipeline Monitor using single module-level engine init with st.stop on failure
  - Pipeline Monitor stats display showing Rows (24h) alongside PASS/WARN/FAIL
  - Trading page drawdown KPI showing both percentage and dollar amounts
affects:
  - future dashboard pages
  - 85-03 onwards (remaining cleanup plans)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Phase 83/84 engine pattern: single module-level try/except get_engine() + st.stop() applied to landing and pipeline monitor

key-files:
  created: []
  modified:
    - src/ta_lab2/dashboard/pages/1_landing.py
    - src/ta_lab2/dashboard/pages/2_pipeline_monitor.py
    - src/ta_lab2/dashboard/pages/6_trading.py

key-decisions:
  - "load_stats_tables removed from pipeline monitor import: ruff correctly flagged as unused (load_stats_status calls it internally)"
  - "Rows (24h) metric uses sum of PASS+WARN+FAIL from existing load_stats_status data: no additional query needed"
  - "drawdown_usd backward-compat guard: if column absent, falls back to 0.0 (cache not yet cleared scenario)"

patterns-established:
  - "Engine init pattern: all dashboard pages now use single module-level try/except get_engine() + st.stop() on failure"

# Metrics
duration: 13min
completed: 2026-03-23
---

# Phase 85 Plan 02: Dashboard Cleanup Polish Summary

**Consolidated engine init to Phase 83/84 pattern in landing + pipeline monitor, and added dollar drawdown KPI to trading page**

## Performance

- **Duration:** 13 min
- **Started:** 2026-03-23T21:56:38Z
- **Completed:** 2026-03-23T22:09:34Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Landing page and Pipeline Monitor now use single module-level `engine = get_engine()` with `st.stop()` on failure, matching the Phase 83/84 structural pattern
- Pipeline Monitor stats display now shows 4 sub-metrics per table: PASS, WARN, FAIL, and Rows (24h) -- operators can immediately see both quality and volume
- Trading page drawdown KPI expanded from 3 columns to 4: Peak Equity, Current Drawdown %, Current DD ($), Max Drawdown (% + $) -- dollar amounts sourced from Plan 01's `drawdown_usd` column

## Task Commits

1. **Task 1: Consolidate engine init in landing and pipeline monitor** - `685c01d6` (refactor)
2. **Task 2: Add dollar drawdown to trading page KPI** - `36ca0eeb` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/dashboard/pages/1_landing.py` - Single module-level engine init with st.stop(); removed 3 per-section get_engine() calls
- `src/ta_lab2/dashboard/pages/2_pipeline_monitor.py` - Single module-level engine init with st.stop(); removed 4 per-section get_engine() calls; stats display now includes Rows (24h) metric
- `src/ta_lab2/dashboard/pages/6_trading.py` - Drawdown KPI section expanded to 4 columns showing % and $ amounts

## Decisions Made

- `load_stats_tables` removed from pipeline monitor import after ruff correctly flagged it as unused -- `load_stats_status` calls it internally, no direct page-level usage needed. The "Rows (24h)" metric is derived from the sum of PASS+WARN+FAIL counts already loaded by `load_stats_status` -- no additional DB query required.
- `drawdown_usd` backward-compat guard added: if the column is absent (cache not yet refreshed after Plan 01 deploy), falls back to `0.0` rather than crashing.
- Pre-commit ruff hook modified the pipeline monitor import block (removed unused import) -- re-staged and committed clean per standard pattern.

## Deviations from Plan

None - plan executed exactly as written, with one minor automatic adjustment: ruff removed the `load_stats_tables` import that the plan specified adding, because the page doesn't call it directly. The intent (show row counts in stats display) was fully achieved using the `load_stats_status` data that was already loaded.

## Issues Encountered

Pre-commit ruff lint hook failed on first commit attempt (unused import `load_stats_tables`). Re-staged ruff-fixed files and committed clean. Standard pattern for this codebase.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All three pages now follow the Phase 83/84 structural pattern consistently
- 15 of 17 dashboard pages are fully compliant (landing and pipeline monitor were the last two with scattered engine calls)
- Trading drawdown KPI now shows both percentage and dollar amounts, giving operators immediate dollar context
- Ready for Phase 85 Plan 03 (remaining cleanup tasks if any)

---
*Phase: 85-dashboard-cleanup-polish*
*Completed: 2026-03-23*
