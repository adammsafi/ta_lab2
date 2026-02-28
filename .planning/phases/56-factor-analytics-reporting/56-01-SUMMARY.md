---
phase: 56-factor-analytics-reporting
plan: 01
subsystem: database
tags: [alembic, migration, postgresql, schema, ic-results, backtest, cmc-features, cross-sectional]

# Dependency graph
requires:
  - phase: 55-feature-signal-evaluation
    provides: cmc_ic_results table and evaluation framework this extends
  - phase: 51-perps-readiness
    provides: 30eac3660488 alembic head this migration chain starts from
provides:
  - rank_ic NUMERIC column on cmc_ic_results (backfilled from ic)
  - mae + mfe NUMERIC columns on cmc_backtest_trades
  - mc_sharpe_lo/hi/median + mc_n_samples on cmc_backtest_metrics
  - tearsheet_path TEXT on cmc_backtest_runs
  - 6 cross-sectional normalization columns on cmc_features (cs_zscore + cs_rank for ret_arith, rsi_14, vol_parkinson_20)
  - Reference DDL at sql/migration/add_factor_analytics_columns.sql
affects:
  - 56-02: quantstats tear sheet writer needs tearsheet_path column
  - 56-03: quintile sweep needs CS-norm columns on cmc_features
  - 56-04: MAE/MFE analyzer needs mae/mfe columns on cmc_backtest_trades
  - 56-05: Monte Carlo Sharpe needs mc_sharpe_* columns on cmc_backtest_metrics
  - 56-06: rank IC evaluator needs rank_ic column on cmc_ic_results

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Alembic migration chain with fixed revision IDs for predictable dependency ordering"
    - "All Phase 56 schema columns added as nullable (zero data loss risk)"
    - "COMMENT ON COLUMN for every new column (self-documenting schema)"
    - "Reference DDL file documents schema changes separate from Alembic (Alembic is authoritative)"

key-files:
  created:
    - alembic/versions/a1b2c3d4e5f6_add_rank_ic_to_ic_results.py
    - alembic/versions/b2c3d4e5f6a1_add_mae_mfe_to_trades.py
    - alembic/versions/c3d4e5f6a1b2_add_mc_ci_to_metrics.py
    - alembic/versions/d4e5f6a1b2c3_add_cs_norms_to_features.py
    - sql/migration/add_factor_analytics_columns.sql
  modified: []

key-decisions:
  - "Used fixed revision IDs (not auto-generated UUIDs) for readable migration chain in git history"
  - "rank_ic backfilled from ic on migration since existing Spearman IC values are rank-based"
  - "CS-norm columns use DOUBLE PRECISION (sa.Float) to match existing cmc_features float columns; MC and IC columns use NUMERIC for precision"
  - "14 columns total (plan said 13 - miscounted; all 14 specified columns were implemented)"

patterns-established:
  - "Phase 56 migration pattern: group all schema additions in Plan 01, data-writing in Plans 04-07"
  - "Comment-only downgrade reference in SQL DDL file prevents accidental execution while documenting rollback steps"

# Metrics
duration: 15min
completed: 2026-02-28
---

# Phase 56 Plan 01: Factor Analytics Schema Migrations Summary

**4 chained Alembic migrations adding 14 nullable columns across 5 tables: rank IC, MAE/MFE, Monte Carlo Sharpe CI, QuantStats tearsheet path, and 6 CS-normalization columns**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-02-28T06:25:13Z
- **Completed:** 2026-02-28T06:40:00Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- All 4 Alembic migrations applied cleanly: `alembic upgrade head` took chain from `30eac3660488` (perps_readiness) to `d4e5f6a1b2c3` (add_cs_norms_to_features)
- 14 nullable columns added across 5 tables with full COMMENT ON documentation in PostgreSQL
- Downgrade path verified: `alembic downgrade -1` cleanly removed CS-norm columns, re-upgrade restored them
- Reference DDL file created as documentation-only artifact (Alembic is authoritative)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create 4 Alembic migration files** - `28ae320d` (feat)
2. **Task 2: Create reference DDL for Phase 56 columns** - `491e36f4` (docs)

## Files Created/Modified

- `alembic/versions/a1b2c3d4e5f6_add_rank_ic_to_ic_results.py` - rank_ic on cmc_ic_results + backfill from ic
- `alembic/versions/b2c3d4e5f6a1_add_mae_mfe_to_trades.py` - mae + mfe on cmc_backtest_trades
- `alembic/versions/c3d4e5f6a1b2_add_mc_ci_to_metrics.py` - 4 MC Sharpe CI columns on cmc_backtest_metrics + tearsheet_path on cmc_backtest_runs
- `alembic/versions/d4e5f6a1b2c3_add_cs_norms_to_features.py` - 6 CS-norm DOUBLE PRECISION columns on cmc_features
- `sql/migration/add_factor_analytics_columns.sql` - Reference DDL with 14 ADD COLUMN + COMMENT ON + downgrade documentation

## Decisions Made

- **Fixed revision IDs:** Used readable IDs (a1b2c3d4e5f6, b2c3d4e5f6a1, etc.) instead of auto-generated UUIDs. Makes migration chain easy to follow in git log and alembic history.
- **rank_ic backfill:** Immediately backfilled rank_ic = ic for existing rows since existing Spearman IC values in the ic column are already rank-based. Future evaluators can overwrite independently.
- **CS-norm as DOUBLE PRECISION:** Matched existing cmc_features float column types (sa.Float = DOUBLE PRECISION). MC and IC result columns use NUMERIC for exact decimal precision.
- **14 columns, not 13:** Plan specification said "13" but listed 14 distinct columns (1+2+4+1+6=14). Implemented all 14 as specified — plan had a counting error in the summary text.

## Deviations from Plan

None - plan executed exactly as written. The "13 vs 14 column" discrepancy was a counting error in the plan text, not a scope change. All specified columns were implemented as listed.

## Issues Encountered

- **Pre-commit hook: mixed line endings** - Windows CRLF vs LF issue. Pre-commit auto-fixed on first commit attempt; re-staged and committed successfully on second attempt. Expected behavior on Windows per MEMORY.md.

## User Setup Required

None - no external service configuration required. Run `alembic upgrade head` to apply (already applied in this session).

## Next Phase Readiness

- All 14 Phase 56 columns exist in the database. Plans 02-07 can write data immediately.
- `tearsheet_path`: ready for Plan 02 (QuantStats reporter)
- `ret_arith_cs_zscore/rank`, `rsi_14_cs_zscore/rank`, `vol_parkinson_20_cs_zscore/rank`: ready for Plan 03 (quintile sweep)
- `mae`, `mfe`: ready for Plan 04 (MAE/MFE analyzer)
- `mc_sharpe_lo`, `mc_sharpe_hi`, `mc_sharpe_median`, `mc_n_samples`: ready for Plan 05 (Monte Carlo)
- `rank_ic`: ready for Plan 06 (rank IC evaluator)
- No blockers.

---
*Phase: 56-factor-analytics-reporting*
*Completed: 2026-02-28*
