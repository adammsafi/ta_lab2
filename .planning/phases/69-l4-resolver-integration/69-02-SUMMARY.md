---
phase: 69-l4-resolver-integration
plan: 02
subsystem: regimes
tags: [python, alembic, postgresql, regime-refresh, macro-regime, l4, telegram, sqlalchemy]

# Dependency graph
requires:
  - phase: 69-01
    provides: "resolver.py fnmatch glob matching, 8 L4 macro policy entries, regime_policies.yaml L4 overlay"
  - phase: 67-macro-regime-classifier
    provides: "cmc_macro_regimes table with regime_key and date columns"
  - phase: 45-paper-trade-executor
    provides: "cmc_executor_run_log original schema (225bf8646f03)"
provides:
  - "_load_macro_regime_with_staleness_check() helper: queries cmc_macro_regimes, validates staleness, sends Telegram alert on failure"
  - "compute_regimes_for_id() l4_label parameter: passes macro regime to resolve_policy_from_table(L4=l4_label)"
  - "main() loads L4 once before per-asset loop and passes to each compute_regimes_for_id() call"
  - "Alembic migration f1a2b3c4d5e6: l4_regime TEXT NULL + l4_size_mult NUMERIC NULL on cmc_executor_run_log"
  - "Updated chk_exec_run_status CHECK to include 'no_signals'"
affects:
  - "69-03: Plan 03 executor logging changes depend on l4_regime/l4_size_mult columns"
  - "refresh_cmc_regimes.py callers who call compute_regimes_for_id() directly"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_try_telegram_alert pattern: wrap send_critical_alert in try/except so alerting never crashes pipeline"
    - "Load-once-before-loop: macro regime is global, loaded once in main() not inside per-asset loop"
    - "Graceful L4 fallback: missing table, empty data, staleness all return None and send Telegram alert"

key-files:
  created:
    - "alembic/versions/f1a2b3c4d5e6_l4_executor_run_log.py"
  modified:
    - "src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py"
    - "sql/executor/089_cmc_executor_run_log.sql"

key-decisions:
  - "L4 staleness threshold set to 7 days (_L4_STALENESS_DAYS = 7)"
  - "Load macro regime ONCE before per-asset loop (not per-asset) since L4 is global"
  - "UndefinedTable and all exceptions caught together -- both mean L4 is unavailable"
  - "Telegram alert sent for all L4 disable conditions: missing table, empty, stale"
  - "chk_exec_run_status CHECK constraint updated to include 'no_signals' in same migration"
  - "Alembic revision ID f1a2b3c4d5e6 chains to e0d8f7aec87a (Phase 68 HMM tables)"

patterns-established:
  - "_try_telegram_alert: always wrap send_critical_alert in try/except to suppress alert failures in pipelines"
  - "Graceful fallback with logging: log warning + send alert + return None on all L4 disable conditions"

# Metrics
duration: 3min
completed: 2026-03-03
---

# Phase 69 Plan 02: L4 Macro Regime Injection into Refresh Pipeline Summary

**L4 macro regime wired into refresh_cmc_regimes.py with staleness gating (7d), Telegram alerts on fallback, and Alembic migration adding l4_regime/l4_size_mult to cmc_executor_run_log**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-03T11:49:07Z
- **Completed:** 2026-03-03T11:52:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added `_load_macro_regime_with_staleness_check()`: queries `cmc_macro_regimes`, handles missing table (UndefinedTable), empty result, and staleness >7 days -- each case disables L4 with a Telegram alert
- Extended `compute_regimes_for_id()` with `l4_label: Optional[str] = None` parameter; passes `L4=l4_label` to `resolve_policy_from_table` and stores it in the row builder replacing the previous hardcoded `None`
- Updated `main()` to load macro regime once before the per-asset loop and pass `l4_label` to each `compute_regimes_for_id()` call
- Created Alembic migration `f1a2b3c4d5e6` adding `l4_regime TEXT NULL` and `l4_size_mult NUMERIC NULL` to `cmc_executor_run_log`, updating `chk_exec_run_status` to include `'no_signals'`

## Task Commits

Each task was committed atomically:

1. **Task 1: Load macro regime in refresh_cmc_regimes.py and inject as L4** - `11fe4413` (feat)
2. **Task 2: Alembic migration for l4_regime and l4_size_mult on cmc_executor_run_log** - `4cf93230` (feat)

**Plan metadata:** (committed after summary creation)

## Files Created/Modified
- `src/ta_lab2/scripts/regimes/refresh_cmc_regimes.py` - Added import for send_critical_alert, _L4_STALENESS_DAYS/profile constants, _try_telegram_alert helper, _load_macro_regime_with_staleness_check(), l4_label param on compute_regimes_for_id(), L4 injection in resolve call + row builder, L4 loading in main()
- `alembic/versions/f1a2b3c4d5e6_l4_executor_run_log.py` - New migration: l4_regime, l4_size_mult columns + updated status CHECK constraint
- `sql/executor/089_cmc_executor_run_log.sql` - Reference DDL updated with new columns, updated CHECK, COMMENT statements

## Decisions Made
- **Staleness threshold 7 days**: Macro regime is updated weekly; >7 days means at least one full cycle missed.
- **Load once before loop**: Macro regime is global (same for all assets), so loading it N times per run would be redundant and add latency.
- **Catch all exceptions together**: Both `UndefinedTable` (Phase 67 not applied) and other errors indicate L4 is unavailable -- same treatment.
- **`_try_telegram_alert` helper**: Wraps `send_critical_alert` so network/config failures in alerting cannot crash the refresh pipeline.
- **`no_signals` added to CHECK in same migration**: Plan 03 needs this status value; cleaner to add it here alongside the l4 columns.

## Deviations from Plan

None - plan executed exactly as written. The three changes to `refresh_cmc_regimes.py` and the Alembic migration were implemented as specified.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required. The Alembic migration must be applied to the database before executor run logging of L4 data begins, but this is handled by the normal alembic upgrade flow.

## Next Phase Readiness
- Plan 03 (executor L4 logging) can now read `l4_regime` and `l4_size_mult` columns from `cmc_executor_run_log` after `alembic upgrade head` is run
- `compute_regimes_for_id()` now accepts `l4_label` -- callers that bypass `main()` can supply L4 directly
- Graceful fallback is fully in place: Phase 67 data absence (or staleness) will not break any existing pipeline run

---
*Phase: 69-l4-resolver-integration*
*Completed: 2026-03-03*
