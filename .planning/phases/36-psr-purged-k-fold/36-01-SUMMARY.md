---
phase: 36-psr-purged-k-fold
plan: 01
subsystem: database
tags: [alembic, postgresql, migration, psr, backtest-metrics, schema]

# Dependency graph
requires:
  - phase: 35-ama-engine
    provides: baseline Alembic revision 25f2b3c90f65 (empty no-op, snapshot of live schema)
provides:
  - Two Alembic revisions chained from 25f2b3c90f65 for PSR schema changes
  - psr_legacy and psr nullable NUMERIC columns on cmc_backtest_metrics
  - psr_results table with 14 columns, FK to cmc_backtest_runs, unique constraint on (run_id, formula_version)
  - Reference DDL sql/backtests/073_psr_results.sql for documentation
affects:
  - 36-02 and subsequent PSR plans (formula code reads/writes psr column and psr_results table)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Conditional migration: information_schema.columns check avoids errors on both fresh-install and rename paths"
    - "Unconditional downgrade with DROP IF EXISTS: safe regardless of which upgrade branch ran"
    - "Alembic revision chaining: each revision sets down_revision to predecessor hash"

key-files:
  created:
    - alembic/versions/adf582a23467_psr_column_rename.py
    - alembic/versions/5f8223cfbf06_psr_results_table.py
    - sql/backtests/073_psr_results.sql
  modified: []

key-decisions:
  - "Downgrade unconditionally drops psr and psr_legacy with DROP IF EXISTS rather than renaming back -- pre-migration state had no psr column so rename-back would create a phantom column"
  - "Two separate revisions rather than one: column rename and new table are independent concerns, easier to bisect"
  - "psr_results unique constraint on (run_id, formula_version) allows multiple formula variants per run for A/B comparison"
  - "return_source TEXT column distinguishes portfolio-level vs trade-reconstruction returns affecting distributional moment estimates"

patterns-established:
  - "PSR schema pattern: psr_legacy preserves historical approx values; new psr column holds formula-computed values"
  - "Reference DDL convention: 073_psr_results.sql matches 070/071/072 pattern, NOT executed by Alembic"

# Metrics
duration: 4min
completed: 2026-02-23
---

# Phase 36 Plan 01: PSR Column Rename + psr_results Table Migrations Summary

**Two Alembic revisions chained from baseline: conditional psr->psr_legacy rename on cmc_backtest_metrics plus new psr_results table (14 cols, FK, unique constraint) for full PSR/DSR/MinTRL audit trail**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-02-24T00:02:09Z
- **Completed:** 2026-02-24T00:05:39Z
- **Tasks:** 2
- **Files created:** 3

## Accomplishments

- Alembic revision `adf582a23467` conditionally renames existing `psr` to `psr_legacy` on `cmc_backtest_metrics` and adds new nullable `psr` column; downgrade unconditionally drops both via `DROP COLUMN IF EXISTS`
- Alembic revision `5f8223cfbf06` creates `psr_results` table with 14 columns (PSR, DSR, MinTRL, distributional moments, FK to `cmc_backtest_runs`, unique constraint, index)
- Full round-trip verified: `alembic downgrade base && alembic upgrade head` cleans up and restores cleanly; existing row count (1) unchanged
- Reference DDL `sql/backtests/073_psr_results.sql` with comprehensive `COMMENT ON TABLE/COLUMN` documentation

## Task Commits

Each task was committed atomically:

1. **Task 1: psr_column_rename Alembic migration** - `e9c9ebb0` (feat)
2. **Task 2: psr_results_table revision and reference DDL** - `bacd1131` (feat)

## Files Created/Modified

- `alembic/versions/adf582a23467_psr_column_rename.py` - Revision: conditional psr->psr_legacy rename + new psr column; safe downgrade via DROP IF EXISTS
- `alembic/versions/5f8223cfbf06_psr_results_table.py` - Revision: create psr_results table with FK, unique constraint, index
- `sql/backtests/073_psr_results.sql` - Reference DDL documentation (NOT executed by Alembic)

## Decisions Made

- **Unconditional downgrade with DROP IF EXISTS** (not rename-back): The pre-migration database had no `psr` column (it was removed from the live schema at some point). Renaming `psr_legacy` back to `psr` in downgrade would create a phantom column that never existed before the migration. Using `DROP COLUMN IF EXISTS` on both columns cleanly restores the exact pre-migration state.
- **Two separate revisions**: Column rename (`adf582a23467`) and table creation (`5f8223cfbf06`) are independent concerns. Keeping them separate makes bisecting failures easier and allows rolling back only the table creation without touching the column rename.
- **Unique constraint on (run_id, formula_version)**: Prevents duplicate PSR computations per run and enables multiple formula variants to coexist (A/B comparison between formula implementations).
- **`return_source` TEXT column**: Distinguishes whether returns came from portfolio-level aggregation vs trade-reconstruction -- this affects skewness/kurtosis estimates, which feed directly into the PSR formula.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hook (ruff format) reformatted the long `sa.UniqueConstraint(...)` line in `5f8223cfbf06` from single-line to multi-line style. Re-staged and committed cleanly on second attempt.
- SQL file had mixed line endings (CRLF from Windows write tool) -- pre-commit `mixed-line-ending` hook normalized to LF. Re-staged and committed cleanly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Both Alembic revisions are applied (`alembic current` shows `5f8223cfbf06 (head)`)
- `cmc_backtest_metrics` has `psr` and `psr_legacy` nullable NUMERIC columns
- `psr_results` table exists with correct schema, FK, unique constraint, and index
- Plan 36-02 (PSR formula implementation) can immediately write to both `psr` column and `psr_results` table
- No blockers

---
*Phase: 36-psr-purged-k-fold*
*Completed: 2026-02-23*
