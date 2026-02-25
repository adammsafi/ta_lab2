---
phase: 46-risk-controls
plan: 01
subsystem: database
tags: [postgres, alembic, risk-controls, kill-switch, circuit-breaker, position-caps]

# Dependency graph
requires:
  - phase: 45-paper-trade-executor
    provides: paper_trade_executor migration (225bf8646f03) as down_revision chain anchor
  - phase: 44-order-fill-store
    provides: cmc_orders table that kill switch will cancel orders against
provides:
  - dim_risk_limits table with portfolio-wide defaults seeded
  - dim_risk_state table with state_id=1 and trading_state='active' seeded
  - cmc_risk_events immutable audit log table
  - cmc_risk_overrides discretionary override store table
  - sql/risk/ DDL reference directory with 4 files
affects:
  - 46-02 and later plans: Python risk engine classes depend on these tables
  - kill switch integration: dim_risk_state.trading_state gates all order submission
  - circuit breaker: dim_risk_state.cb_* columns and dim_risk_limits.cb_* thresholds

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single-row state table enforced via CHECK(state_id=1) constraint"
    - "Immutable audit log pattern: no DELETE, event_type constrained via CHECK"
    - "Scoped config pattern: NULL asset_id/strategy_id = portfolio-wide defaults"
    - "JSON-in-TEXT for per-key circuit breaker counters (cb_consecutive_losses, cb_breaker_tripped_at)"

key-files:
  created:
    - alembic/versions/b5178d671e38_risk_controls.py
    - sql/risk/090_dim_risk_limits.sql
    - sql/risk/091_dim_risk_state.sql
    - sql/risk/092_cmc_risk_events.sql
    - sql/risk/093_cmc_risk_overrides.sql
  modified: []

key-decisions:
  - "JSON stored as TEXT for per-asset circuit breaker counters (cb_consecutive_losses, cb_breaker_tripped_at) — avoids jsonb dependency, Python dicts serialize directly"
  - "CHECK(state_id=1) on dim_risk_state enforces single-row invariant at DB level — no application code needed to prevent duplicates"
  - "cmc_risk_overrides has no CHECK on system_signal/override_action — values are free-text to allow future signal types without migration"
  - "dim_risk_limits uses NULL asset_id/strategy_id for portfolio-wide defaults — scoped rows can override for specific assets/strategies"

patterns-established:
  - "Single-row table pattern: CHECK(state_id=1) + seed row in upgrade()"
  - "Immutable audit log pattern: UUID PK, no FK to mutable tables, CHECK on event_type enum"

# Metrics
duration: 10min
completed: 2026-02-25
---

# Phase 46 Plan 01: Risk Controls DB Schema Summary

**4-table risk schema via Alembic migration b5178d671e38: kill switch state, position cap config, immutable audit log, and discretionary override store -- all seeded and verified with round-trip upgrade/downgrade.**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-02-25T14:22:00Z
- **Completed:** 2026-02-25T14:32:30Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Created Alembic migration b5178d671e38 with all 4 risk tables, CHECK constraints, indexes, and seed data
- dim_risk_state seeded with state_id=1 and trading_state='active'; single-row enforced via CHECK(state_id=1)
- dim_risk_limits seeded with portfolio-wide defaults (15% per-asset cap, 80% portfolio cap, 3% daily loss, N=3 circuit breaker)
- Verified upgrade/downgrade round-trip: all 4 tables drop cleanly on downgrade -1
- Created 4 reference DDL files in sql/risk/ matching migration exactly

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Alembic migration for 4 risk tables** - `b4e49429` (feat)
2. **Task 2: Create reference DDL files** - `8b6bf43a` (docs)

**Plan metadata:** (included in docs commit above)

## Files Created/Modified
- `alembic/versions/b5178d671e38_risk_controls.py` - Full migration: 4 tables, CHECK constraints, seed data, upgrade/downgrade
- `sql/risk/090_dim_risk_limits.sql` - Reference DDL for runtime-editable risk limit config
- `sql/risk/091_dim_risk_state.sql` - Reference DDL for single-row kill switch and circuit breaker state
- `sql/risk/092_cmc_risk_events.sql` - Reference DDL for immutable risk audit log with 3 indexes
- `sql/risk/093_cmc_risk_overrides.sql` - Reference DDL for discretionary override store

## Decisions Made
- **JSON-as-TEXT for CB counters:** cb_consecutive_losses and cb_breaker_tripped_at store per-key JSON as TEXT columns. Avoids jsonb operator dependencies; Python dicts serialize directly via json.dumps(). Acceptable for low-frequency state updates.
- **CHECK(state_id=1) for single-row invariant:** DB-level enforcement means application code cannot accidentally insert a second row. Simple and reliable.
- **Free-text system_signal/override_action on cmc_risk_overrides:** No CHECK constraint so future signal types do not require a migration to add to the allowed set.
- **NULL-scope for dim_risk_limits defaults:** NULL asset_id + NULL strategy_id = portfolio-wide row. Non-NULL rows override for specific asset/strategy pairs. Same pattern used in dim_executor_config.

## Deviations from Plan

None - plan executed exactly as written. The pre-commit hook flagged mixed line endings in the SQL files (CRLF introduced by Write tool on Windows); re-staged and committed cleanly on second attempt. This is a routine Windows tooling artifact, not a code deviation.

## Issues Encountered
- Pre-commit `mixed-line-ending` hook failed on first commit attempt for SQL files. Fixed by re-staging the auto-corrected files before the second commit.

## User Setup Required
None - no external service configuration required. Migration runs against the configured PostgreSQL instance via existing db_config.env or TARGET_DB_URL.

## Next Phase Readiness
- All 4 risk tables exist in the database at alembic head b5178d671e38
- dim_risk_state row (state_id=1, trading_state='active') is ready for kill switch reads/writes
- dim_risk_limits row with portfolio-wide defaults is ready for position cap lookups
- cmc_risk_events and cmc_risk_overrides are empty and ready for application writes
- Phase 46 plans 02+ can proceed: Python risk engine, kill switch, position cap, circuit breaker, and override classes all depend on these tables

---
*Phase: 46-risk-controls*
*Completed: 2026-02-25*
