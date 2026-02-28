---
phase: 60-ml-infrastructure-experimentation
plan: "08"
subsystem: database, ml
tags: [alembic, postgresql, migration, cmc_ml_experiments, optuna, lightgbm, expression-engine, verification]

# Dependency graph
requires:
  - phase: 60-01
    provides: expression_engine.py with evaluate_expression/validate_expression; 5 expression-mode factors in features.yaml
  - phase: 60-02
    provides: sql/ml/095_cmc_ml_experiments.sql DDL and ExperimentTracker module
  - phase: 60-03
    provides: FeatureRegistry and ExperimentRunner wired for expression mode end-to-end
provides:
  - Alembic migration 3caddeff4691_ml_experiments_table.py: revises f6a7b8c9d0e1, creates cmc_ml_experiments with 4 indexes and column comments
  - Confirmed optuna 4.7.0 and lightgbm 4.6.0 installed
  - End-to-end expression engine validation: 8 expression features (5 base + 3 param-sweep) all pass against synthetic OHLCV DataFrame
affects:
  - All Phase 60 ML modules that log to cmc_ml_experiments via ExperimentTracker
  - Future alembic migrations (down_revision = 3caddeff4691)

# Tech tracking
tech-stack:
  added:
    - optuna 4.7.0 (pre-installed by Wave 2 agents)
    - lightgbm 4.6.0 (pre-installed by Wave 2 agents)
  patterns:
    - "Alembic migration for complex tables: use op.create_table() + op.create_index() + op.execute(COMMENT) instead of reading raw SQL file"
    - "GIN index via op.create_index() with postgresql_using='gin' kwarg"
    - "Column-level PostgreSQL COMMENTs via op.execute() string literals after table creation"
    - "downgrade() drops indexes in reverse creation order before drop_table()"

key-files:
  created:
    - alembic/versions/3caddeff4691_ml_experiments_table.py
  modified: []

key-decisions:
  - "Used op.create_table() + op.execute() pattern rather than reading SQL file: consistent with all other migrations in codebase, avoids file-path dependency in migration"
  - "down_revision = f6a7b8c9d0e1 (portfolio_tables): actual head confirmed via 'alembic heads', not the plan's suggested 30eac3660488"
  - "optuna and lightgbm were already installed by prior Wave 2 agents - no install step needed"
  - "8 expression features validated (5 base + 3 param-sweep from vol_ratio_expr fast/slow combinations)"

patterns-established:
  - "Verify alembic head at runtime before writing down_revision (plan's suggested head may be stale)"

# Metrics
duration: 3min
completed: 2026-02-28
---

# Phase 60 Plan 08: Infrastructure Setup and Expression Engine Verification Summary

**Alembic migration 3caddeff4691 creates cmc_ml_experiments (UUID PK, JSONB params, GIN array indexes); 8 expression-mode factors validated end-to-end through FeatureRegistry + evaluate_expression()**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-28T14:51:05Z
- **Completed:** 2026-02-28T14:53:30Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Created Alembic migration `3caddeff4691_ml_experiments_table.py` that correctly chains from head `f6a7b8c9d0e1` (portfolio_tables); `alembic upgrade head` ran successfully
- Confirmed optuna 4.7.0 and lightgbm 4.6.0 are installed (pre-installed by prior Wave 2 agents)
- Verified all 8 expression-mode features in `configs/experiments/features.yaml` evaluate correctly end-to-end through `FeatureRegistry.load()` + `evaluate_expression()` against a synthetic 100-row OHLCV DataFrame

## Task Commits

Each task was committed atomically:

1. **Task 1: Install dependencies and create Alembic migration** - `fc0209c8` (feat)
2. **Task 2: End-to-end expression engine verification** - no commit (verification only, no files modified)

## Files Created/Modified

- `alembic/versions/3caddeff4691_ml_experiments_table.py` - Alembic migration: CREATE TABLE cmc_ml_experiments with UUID PK, JSONB model_params/label_params/mda_importances/sfi_importances/optuna_best_params/regime_performance, TEXT[] feature_set, INTEGER[] asset_ids, 4 indexes (btree x3 + GIN), column-level COMMENTs

## Decisions Made

- **op.create_table() over SQL file read**: All existing migrations in this codebase use `op.create_table()` + `op.execute()` rather than reading raw SQL files. The migration was written to match this established pattern for consistency and to avoid file-path dependencies at migration runtime.
- **Corrected down_revision**: Plan suggested `30eac3660488` (perps_readiness) but the actual alembic head was `f6a7b8c9d0e1` (portfolio_tables). Confirmed with `alembic heads` before writing the migration.
- **No install step needed**: Both optuna 4.7.0 and lightgbm 4.6.0 were already installed by prior Wave 2 agents (60-04 through 60-07). Verified with import checks before skipping pip install.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected down_revision from plan's suggested value to actual head**

- **Found during:** Task 1 (Alembic migration creation)
- **Issue:** Plan specified `down_revision = "30eac3660488"` (perps_readiness) but `alembic heads` returned `f6a7b8c9d0e1` (portfolio_tables). Using the wrong down_revision would break the migration chain.
- **Fix:** Ran `alembic heads` first, used the confirmed head `f6a7b8c9d0e1` as down_revision
- **Files modified:** `alembic/versions/3caddeff4691_ml_experiments_table.py`
- **Verification:** `alembic heads` after creating migration shows `3caddeff4691 (head)` and `alembic upgrade head` ran successfully
- **Committed in:** `fc0209c8` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 Bug - stale head revision in plan)
**Impact on plan:** Necessary for migration chain correctness. No scope creep.

## Issues Encountered

Pre-commit hooks (ruff-format, mixed-line-ending) reformatted the migration file on first commit attempt. Re-staged and committed successfully on second attempt with no logic changes.

## User Setup Required

None - `alembic upgrade head` was run successfully against the live database. No manual steps required.

## Next Phase Readiness

- `cmc_ml_experiments` table is now in the database (created via successful alembic upgrade)
- All expression-mode YAML factors are validated end-to-end
- Phase 60 Wave 3 infrastructure is complete: optuna + lightgbm installed, DB schema migrated, expression engine verified
- ExperimentTracker.ensure_table() will now find an existing table (no-op) rather than creating it

---
*Phase: 60-ml-infrastructure-experimentation*
*Completed: 2026-02-28*
