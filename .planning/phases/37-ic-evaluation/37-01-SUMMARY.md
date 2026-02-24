---
phase: 37-ic-evaluation
plan: "01"
subsystem: database
tags: [alembic, postgresql, pandas, feature-eval, ic-evaluation]

# Dependency graph
requires:
  - phase: 36-psr-purged-k-fold
    provides: Alembic chain head (5f8223cfbf06 psr_results_table) to chain from
provides:
  - fillna deprecation fixed in feature_eval.py (prior decision satisfied)
  - cmc_ic_results table in DB (UUID PK, 9-col natural key, 2 indexes)
  - Alembic migration c3b718c2d088 chained from 5f8223cfbf06
  - Reference DDL at sql/features/080_cmc_ic_results.sql
affects:
  - 37-ic-evaluation (Plans 02+): IC compute functions write to cmc_ic_results
  - 38-feature-experimentation: ExperimentRunner reads cmc_ic_results for BH correction

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Alembic hand-written migration with UUID PK + 9-col natural key UniqueConstraint pattern"
    - "Reference DDL file (sql/features/080_*.sql) for human documentation, separate from Alembic"

key-files:
  created:
    - alembic/versions/c3b718c2d088_ic_results_table.py
    - sql/features/080_cmc_ic_results.sql
  modified:
    - src/ta_lab2/analysis/feature_eval.py

key-decisions:
  - "cmc_ic_results natural key: 9 columns (asset_id, tf, feature, horizon, return_type, regime_col, regime_label, train_start, train_end) enforced via UniqueConstraint uq_ic_results_key"
  - "horizon_days nullable: derived from horizon * tf_days_nominal, may not always be populated at insert time"
  - "regime_col='all' + regime_label='all' sentinel for full-population IC (no regime filter)"

patterns-established:
  - "IC result upsert key: natural 9-column key allows ON CONFLICT DO UPDATE for re-computation"

# Metrics
duration: 5min
completed: 2026-02-24
---

# Phase 37 Plan 01: IC Evaluation Prerequisites Summary

**fillna deprecation fixed in feature_eval.py; cmc_ic_results table created via Alembic migration c3b718c2d088 with UUID PK, 9-column natural key, and two indexes**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-02-24T02:00:25Z
- **Completed:** 2026-02-24T02:05:30Z
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments

- Fixed pandas FutureWarning: replaced `fillna(method='ffill')` with `.ffill()` on line 78 of feature_eval.py (prior decision: "v0.9.0 fix fillna deprecation before IC")
- Created cmc_ic_results Alembic migration (c3b718c2d088) chained from 5f8223cfbf06 (psr_results_table), with 19 columns, UUID PK, 9-column unique constraint, and 2 indexes
- Created reference DDL sql/features/080_cmc_ic_results.sql documenting the schema for human readers
- Upgrade + downgrade + re-upgrade round-trip verified clean

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix fillna deprecation in feature_eval.py** - `97fe7e38` (fix)
2. **Task 2: Create Alembic migration for cmc_ic_results table + reference DDL** - `a3af7d0e` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/analysis/feature_eval.py` - Line 78: `fillna(method="ffill")` replaced with `.ffill()`
- `alembic/versions/c3b718c2d088_ic_results_table.py` - Alembic migration creating cmc_ic_results table
- `sql/features/080_cmc_ic_results.sql` - Reference DDL for cmc_ic_results (documentation only, not executed)

## Decisions Made

- **cmc_ic_results 9-column natural key:** (asset_id, tf, feature, horizon, return_type, regime_col, regime_label, train_start, train_end) -- enables upsert semantics; a re-run with identical inputs hits the unique constraint and can ON CONFLICT DO UPDATE
- **horizon_days nullable:** derived from horizon * tf_days_nominal; populated by IC compute code, not the migration itself
- **regime sentinel:** regime_col='all' + regime_label='all' for full-population IC slice (no regime filter) -- keeps IC compute code uniform (always has a regime_col/regime_label)

## Deviations from Plan

None - plan executed exactly as written. Pre-commit hook auto-fixed mixed line endings in the SQL file (not a code deviation, routine Windows behavior).

## Issues Encountered

- Pre-commit hook failed on first commit attempt for Task 2: `mixed-line-ending` check on `sql/features/080_cmc_ic_results.sql` (CRLF vs LF). Hook auto-corrected; re-staged and committed cleanly on second attempt.

## User Setup Required

None - no external service configuration required. The cmc_ic_results table was created in the database via `alembic upgrade head` during task execution.

## Next Phase Readiness

- cmc_ic_results table exists and is ready for IC compute functions (Plans 37-02+)
- feature_eval.py imports cleanly with no deprecation warnings
- Alembic chain intact: baseline -> psr_column_rename -> psr_results_table -> ic_results_table (4 revisions, linear)
- No blockers for IC evaluation implementation

---
*Phase: 37-ic-evaluation*
*Completed: 2026-02-24*
