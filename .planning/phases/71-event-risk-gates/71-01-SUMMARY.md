---
phase: 71-event-risk-gates
plan: 01
subsystem: database
tags: [alembic, postgresql, risk, macro, event-gates, fomc, cpi, nfp]

# Dependency graph
requires:
  - phase: 70-cross-asset-aggregation
    provides: e1f2a3b4c5d6 alembic head (cross_asset_aggregation_tables)
  - phase: 46-risk-controls
    provides: cmc_risk_events table with CHECK constraints chk_risk_events_type / chk_risk_events_source
provides:
  - dim_macro_events table: macro event calendar (FOMC/CPI/NFP), unique on (event_type, event_ts)
  - dim_macro_gate_state table: live gate state for 8 gates, seeded with fomc/cpi/nfp/vix/carry/credit/freshness/composite
  - cmc_macro_stress_history table: composite stress score time series with stress_tier CHECK
  - dim_macro_gate_overrides table: per-gate operator overrides with expiry
  - cmc_risk_events CHECK extensions: +5 macro gate event types, +macro_gate source
  - seed_macro_events.py: CLI script to seed FOMC/CPI/NFP dates
affects:
  - 71-02 (macro gate logic reads dim_macro_events, dim_macro_gate_state)
  - 71-03 (observability/reporting reads cmc_macro_stress_history, dim_macro_gate_overrides)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Revision ID a2b3c4d5e6f7 used (f1a2b3c4d5e6 was taken by l4_executor_run_log)"
    - "gate_state CHECK constraint: ('normal','reduce','flatten') -- 3-tier gate severity"
    - "size_mult BETWEEN 0.0 AND 1.0 for linear position scaling"
    - "stress_tier CHECK: ('calm','elevated','stressed','crisis') -- 4-tier stress regime"
    - "dim_macro_gate_overrides uses gen_random_uuid() PK with partial index on active rows"
    - "Seed script defaults to --fomc-only when no mode flag specified"
    - "FOMC UTC conversion: EST months = 19:00 UTC, EDT months = 18:00 UTC (announcement at 2 PM ET)"

key-files:
  created:
    - alembic/versions/a2b3c4d5e6f7_event_risk_gates.py
    - src/ta_lab2/scripts/risk/seed_macro_events.py
  modified: []

key-decisions:
  - "Used revision ID a2b3c4d5e6f7 instead of f1a2b3c4d5e6 (plan default) because f1a2b3c4d5e6 was already taken by l4_executor_run_log migration"
  - "CHECK constraint history: included all 15 existing event types from 30eac3660488 (perps_readiness) as current head -- did NOT include drift types lost in a9ec3c00a54a rewrite"
  - "Seed script uses stdlib urllib.request (no requests dependency) for FRED API calls"
  - "Upsert uses ON CONFLICT DO NOTHING -- existing events are never overwritten"

patterns-established:
  - "Pattern: Alembic revision ID collision check -- always run `ls alembic/versions/ | grep` before using plan-specified ID"
  - "Pattern: CHECK constraint evolution -- always read the actual latest migration file, not guessing from memory"

# Metrics
duration: 12min
completed: 2026-03-03
---

# Phase 71 Plan 01: Event Risk Gates -- Database Foundation Summary

**4 macro gate tables (dim_macro_events, dim_macro_gate_state, cmc_macro_stress_history, dim_macro_gate_overrides) + extended cmc_risk_events CHECK constraints + FOMC/CPI/NFP seed script with FRED API auto-fetch**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-03T16:13:45Z
- **Completed:** 2026-03-03T16:25:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Alembic migration a2b3c4d5e6f7 creates 4 tables foundational to all Phase 71 gate logic
- dim_macro_gate_state seeded with 8 gates (fomc, cpi, nfp, vix, carry, credit, freshness, composite) at migration time
- cmc_risk_events now accepts 5 macro gate event types and macro_gate trigger source
- seed_macro_events.py covers all 16 FOMC meetings 2026-2027 with correct EST/EDT UTC times; FRED API fetch for CPI+NFP available behind --fetch-api flag

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration -- 4 tables + CHECK constraint extensions** - `5dad0185` (feat)
2. **Task 2: Event calendar seed script with FRED API auto-fetch** - `408d0e53` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified
- `alembic/versions/a2b3c4d5e6f7_event_risk_gates.py` - 4 new tables + cmc_risk_events CHECK extensions + 8-row gate seed
- `src/ta_lab2/scripts/risk/seed_macro_events.py` - FOMC/CPI/NFP seed CLI with dry-run and FRED API modes

## Decisions Made
- Revision ID collision: plan specified `f1a2b3c4d5e6` but that ID was taken by `f1a2b3c4d5e6_l4_executor_run_log.py`. Used `a2b3c4d5e6f7` instead.
- CHECK constraint state: traced the full migration chain to confirm current event_type list (15 types from 30eac3660488_perps_readiness). The drift event types added by ac4cf1223ec7 were lost when a9ec3c00a54a rewrote the constraint without them -- this is a pre-existing issue, not introduced here.
- FRED API implementation uses stdlib `urllib.request` to avoid adding a `requests` dependency.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Revision ID f1a2b3c4d5e6 already taken**
- **Found during:** Task 1 (pre-flight check)
- **Issue:** Plan specified `f1a2b3c4d5e6` but `ls alembic/versions/` showed `f1a2b3c4d5e6_l4_executor_run_log.py` already exists
- **Fix:** Used `a2b3c4d5e6f7` as the revision ID for this migration
- **Files modified:** alembic/versions/a2b3c4d5e6f7_event_risk_gates.py (used alternate ID)
- **Verification:** `alembic heads` shows `a2b3c4d5e6f7 (head)` -- single head, no branches
- **Committed in:** 5dad0185 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Zero scope impact -- only the revision ID string changed, all schema content as specified.

## Issues Encountered
None beyond the revision ID collision handled above.

## User Setup Required
None - no external service configuration required for migration. FRED API key (FRED_API_KEY) is only needed when running `seed_macro_events.py --fetch-api`.

## Next Phase Readiness
- All 4 tables from the must_haves exist in the migration
- dim_macro_gate_state seeded with all 8 required gate types
- CHECK constraints on cmc_risk_events include all 5 new macro gate event types
- seed_macro_events.py operational in --fomc-only --dry-run mode (verified)
- Plan 71-02 (macro gate logic) can now implement against dim_macro_events and dim_macro_gate_state
- Plan 71-03 (observability) can read cmc_macro_stress_history and dim_macro_gate_overrides

---
*Phase: 71-event-risk-gates*
*Completed: 2026-03-03*
