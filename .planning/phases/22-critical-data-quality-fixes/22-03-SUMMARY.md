---
phase: 22-critical-data-quality-fixes
plan: 03
subsystem: database
tags: [postgresql, backfill-detection, state-management, incremental-refresh, data-integrity]

# Dependency graph
requires:
  - phase: 21-comprehensive-review
    provides: Gap analysis identifying GAP-C03 (missing backfill detection in 1D builder)
provides:
  - Backfill detection for 1D bar builder via daily_min_seen state tracking
  - Auto-migration ensuring all installations gain backfill detection capability
  - Full rebuild trigger when historical data backfilled before first processed date
  - Test suite verifying backfill detection logic and state cleanup behavior
affects:
  - 22-04-multi-tf-derivation (will rely on 1D backfill detection for derived bars)
  - 23-reliable-incremental-refresh (orchestration can assume backfill detection exists)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Auto-migration pattern: Schema changes applied transparently at runtime"
    - "Backfill detection via MIN timestamp comparison (already used by multi-TF builders)"
    - "Full rebuild on backfill: DELETE bars + state for affected ID only"

key-files:
  created:
    - sql/ddl/create_cmc_price_bars_1d_state.sql
  modified:
    - src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py
    - tests/test_bar_contract.py

key-decisions:
  - "Auto-migration at startup: Column added transparently without manual SQL execution"
  - "Conservative backfill initialization: Set daily_min_seen = last_src_ts for existing rows"
  - "String timestamp comparison: Database format returned directly, avoids TZ conversion issues"
  - "Default backfill rebuild enabled: --rebuild-if-backfill defaults to True for safety"

patterns-established:
  - "ensure_state_schema(): Runtime schema migration pattern for adding columns"
  - "check_for_backfill(): Query MIN(timestamp) and compare to state.daily_min_seen"
  - "handle_backfill(): DELETE bars and state for affected ID only, preserving other IDs"

# Metrics
duration: 45min
completed: 2026-02-05
---

# Phase 22 Plan 03: 1D Backfill Detection

**Added backfill detection to 1D bar builder with daily_min_seen state tracking, auto-migration, and full rebuild on historical data insertion**

## Performance

- **Duration:** 45 min
- **Started:** 2026-02-05 (estimated)
- **Completed:** 2026-02-05
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- 1D builder now detects when historical data is backfilled before first processed date
- Auto-migration adds daily_min_seen column to existing installations without manual intervention
- Full rebuild triggered automatically when backfill detected (bars and state deleted, full reprocessing)
- Test suite verifies detection logic, state cleanup, and no-backfill baseline behavior

## Task Commits

Each task was committed atomically:

1. **Task 1: Add daily_min_seen column to 1D state table** - `3027d97c` (feat)
   - DDL file documents schema with daily_min_seen column
   - Migration queries for adding column and backfilling existing rows
   - COMMENT documenting column purpose

2. **Task 2: Add backfill detection logic to 1D builder** - `af2d31e1` (feat)
   - ensure_state_schema() for auto-migration at startup
   - check_for_backfill() to compare source MIN(timestamp) vs state
   - handle_backfill() to delete bars and state for affected ID
   - State save updated to track daily_min_seen (earliest timestamp ever seen)
   - CLI arguments --rebuild-if-backfill / --no-rebuild-if-backfill (default True)
   - Processing loop integrates backfill check before each ID
   - Output reports backfill_rebuilds count

3. **Task 3: Test backfill detection** - `236e43ad` (test)
   - Added _exec() helper for DDL/DML statements (no result fetching)
   - test_check_for_backfill_detects_historical_data: Verifies backfill triggered when MIN < daily_min_seen
   - test_check_for_backfill_no_state: Verifies first run (no state) doesn't trigger backfill
   - test_handle_backfill_deletes_bars_and_state: Verifies cleanup for affected ID only
   - test_daily_min_seen_updated_after_processing: Verifies state tracking over multiple runs
   - All tests handle timezone issues by using database-returned formats directly

## Files Created/Modified
- `sql/ddl/create_cmc_price_bars_1d_state.sql` - DDL with daily_min_seen column, migration queries, documentation
- `src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py` - Backfill detection functions, auto-migration, CLI args, state tracking
- `tests/test_bar_contract.py` - Backfill detection test suite (4 tests) + _exec() helper

## Decisions Made

**Auto-migration at startup:**
- Rationale: Users don't need to run manual SQL migrations. ensure_state_schema() checks column existence and adds it if missing.
- Impact: Existing installations gain backfill detection transparently on next 1D builder run.

**Conservative backfill initialization (daily_min_seen = last_src_ts):**
- Rationale: Safest assumption for existing rows is that we haven't seen data earlier than what we've already processed.
- Impact: Won't trigger false backfill rebuilds on first run after migration.

**String timestamp comparison:**
- Rationale: Avoid timezone conversion issues. Compare timestamps as strings in format returned by PostgreSQL.
- Impact: Tests query database MIN(timestamp) to get actual format for comparison baseline.

**Default backfill rebuild enabled:**
- Rationale: Data integrity is paramount. Backfill detection should be enabled by default.
- Impact: Users must explicitly pass --no-rebuild-if-backfill to disable (rare case).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

**Timezone comparison in tests:**
- Issue: Initial tests used hardcoded timestamps ('2025-01-10T00:00:00Z'), but PostgreSQL returned timestamps in EST timezone ('2025-01-09 19:00:00-05:00'), causing string comparison failures.
- Resolution: Changed tests to query actual MIN(timestamp) from database and use that as baseline, avoiding hardcoded timezone formats.
- Impact: Tests now robust across different database timezone configurations.

**Linter formatting:**
- Issue: Ruff formatter required docstring after imports, not before.
- Resolution: Moved docstring below import statements to satisfy E402 check.
- Impact: No functional change, cleaner linting.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

**What's ready:**
- 1D builder has parity with multi-TF builders for backfill detection
- GAP-C03 Part 1 (simple fix) is complete
- Auto-migration ensures all installations are upgraded
- Test suite validates backfill detection logic

**Next steps:**
- GAP-C03 Part 2: Derive multi-TF bars from 1D bars (Plan 22-04)
- GAP-C01: Multi-TF reject tables (if not already completed)
- GAP-C02: EMA output validation (if not already completed)
- GAP-C04: Expand automated validation test suite

**Blockers/concerns:**
None - backfill detection working as designed.

---
*Phase: 22-critical-data-quality-fixes*
*Completed: 2026-02-05*
