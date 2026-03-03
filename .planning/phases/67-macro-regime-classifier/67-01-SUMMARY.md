---
phase: 67-macro-regime-classifier
plan: 01
subsystem: database
tags: [alembic, postgresql, macro-regime, hysteresis, migration]

# Dependency graph
requires:
  - phase: 66-fred-derived-features
    provides: "Alembic head c4d5e6f7a8b9 (fred_phase66_derived_columns)"
provides:
  - "cmc_macro_regimes table (PK: date, profile) for daily macro regime labels"
  - "cmc_macro_hysteresis_state table (PK: profile, dimension) for hysteresis persistence"
  - "Alembic head d5e6f7a8b9c0"
affects:
  - 67-macro-regime-classifier (plans 02-03 need these tables)
  - 68-l4-integration (macro_state column for policy lookups)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Macro regime tables in public schema (not fred) since they are trading-system tables"
    - "Hysteresis state table for incremental classifier resume with pending_count confirmation"

key-files:
  created:
    - "alembic/versions/d5e6f7a8b9c0_macro_regime_tables.py"
  modified: []

key-decisions:
  - "Tables in public schema (not fred) -- macro regimes are trading-system artifacts, not raw FRED data"
  - "server_default='default' on profile column -- supports multi-profile without requiring explicit value"
  - "pending_count server_default=0 -- ensures clean hysteresis state initialization"

patterns-established:
  - "Macro regime dimension labels: monetary_policy, liquidity, risk_appetite, carry"
  - "Bucketed macro_state values: favorable/constructive/neutral/cautious/adverse"
  - "Composite regime_key format: 'Cutting-Expanding-RiskOn-Stable' (dash-separated dimension labels)"

# Metrics
duration: 2min
completed: 2026-03-03
---

# Phase 67 Plan 01: Macro Regime Tables Summary

**Alembic migration creating cmc_macro_regimes (daily macro regime labels with 4 dimensions + bucketed state) and cmc_macro_hysteresis_state (persistent hysteresis tracker for incremental classifier resume)**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-03T10:15:07Z
- **Completed:** 2026-03-03T10:16:46Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Created Alembic migration d5e6f7a8b9c0 chaining from Phase 66 head c4d5e6f7a8b9
- cmc_macro_regimes table with PK (date, profile), 4 dimension label columns, composite regime_key, bucketed macro_state, and regime_version_hash for provenance
- cmc_macro_hysteresis_state table with PK (profile, dimension) for persisting pending label transitions and confirmation counts
- Two indexes: idx_cmc_macro_regimes_date (date DESC) and idx_cmc_macro_regimes_state (macro_state) for downstream policy lookups

## Task Commits

Each task was committed atomically:

1. **Task 1: Discover Alembic head and create migration** - `fa07e682` (feat)

**Plan metadata:** (pending below)

## Files Created/Modified
- `alembic/versions/d5e6f7a8b9c0_macro_regime_tables.py` - Alembic migration creating both Phase 67 foundation tables with PKs, indexes, and server defaults

## Decisions Made
- **Public schema (not fred):** Macro regime labels are trading-system artifacts consumed by the risk engine and executor, not raw FRED data. Placing them in public schema follows the pattern of all other `cmc_*` tables.
- **Profile column with server_default='default':** Enables multi-profile classifier runs (e.g., different threshold configs) without breaking single-profile usage. The PK (date, profile) allows one row per profile per day.
- **Hysteresis state as separate table:** Separating tracker state from regime output allows the classifier to resume incrementally without reprocessing, and keeps the regime table clean for downstream queries.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- `alembic upgrade head --sql` fails on a pre-existing bug in `adf582a23467_psr_column_rename.py` where `_column_exists()` returns None in offline/SQL-generation mode. This is unrelated to the new migration and has been present since Phase 36. Verified the new migration's correctness via Python AST parsing, module import validation, and `alembic heads`/`alembic branches` checks instead.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Both tables ready for Plan 02 (classifier module implementation)
- Alembic chain clean with single head d5e6f7a8b9c0
- No blockers

---
*Phase: 67-macro-regime-classifier*
*Completed: 2026-03-03*
