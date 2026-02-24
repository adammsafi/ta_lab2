---
phase: 38-feature-experimentation
plan: "01"
subsystem: database
tags: [alembic, postgres, migration, feature-registry, experiments, ic]

# Dependency graph
requires:
  - phase: 37-ic-evaluation
    provides: "Phase 37 Alembic head revision c3b718c2d088 (cmc_ic_results table)"
provides:
  - "dim_feature_registry table with lifecycle CHECK constraint (experimental/promoted/deprecated)"
  - "cmc_feature_experiments table with UUID PK and 9-col unique natural key"
  - "Alembic migration 6f82e9117c58 chained from c3b718c2d088"
affects:
  - 38-02
  - 38-03
  - 38-04
  - 38-05

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Alembic migration with schema=public on all DDL ops for Windows compat"
    - "UUID server_default=gen_random_uuid() for experiment PK"
    - "TEXT[] ARRAY columns for input_tables and input_columns in registry"

key-files:
  created:
    - alembic/versions/6f82e9117c58_feature_experiment_tables.py
  modified: []

key-decisions:
  - "Revision ID generated via uuid.uuid4().hex[:12] = 6f82e9117c58 (not alembic revision subprocess)"
  - "ic_p_value_bh added for Benjamini-Hochberg corrected p-values (plan spec)"
  - "Compute cost columns (wall_clock_seconds, peak_memory_mb, n_rows_computed) in cmc_feature_experiments"
  - "No UTF-8 box-drawing chars in comments to avoid Windows cp1252 UnicodeDecodeError"

patterns-established:
  - "Feature registry lifecycle: experimental -> promoted -> deprecated enforced by CHECK constraint"
  - "Experiment unique key: (feature_name, asset_id, tf, horizon, return_type, regime_col, regime_label, train_start, train_end)"

# Metrics
duration: 1min
completed: 2026-02-24
---

# Phase 38 Plan 01: Feature Experiment Tables Summary

**Alembic migration 6f82e9117c58 creates dim_feature_registry (lifecycle CHECK) and cmc_feature_experiments (UUID PK, 9-col unique key, BH p-value + compute cost columns), chained from Phase 37 head c3b718c2d088**

## Performance

- **Duration:** 1 min
- **Started:** 2026-02-24T12:18:06Z
- **Completed:** 2026-02-24T12:19:46Z
- **Tasks:** 1/1
- **Files modified:** 1

## Accomplishments

- Created `dim_feature_registry` with TEXT PK (feature_name), lifecycle CHECK IN ('experimental','promoted','deprecated'), compute spec fields, promotion metadata, and best-IC tracking
- Created `cmc_feature_experiments` with UUID PK (gen_random_uuid()), 9-column unique natural key, IC metrics including BH-corrected p-value, and compute cost columns (wall_clock_seconds, peak_memory_mb, n_rows_computed)
- Verified upgrade and downgrade against live PostgreSQL database: both clean

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Alembic migration for dim_feature_registry and cmc_feature_experiments** - `829560fb` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `alembic/versions/6f82e9117c58_feature_experiment_tables.py` - Alembic migration creating dim_feature_registry and cmc_feature_experiments with full DDL, constraints, and indexes

## Decisions Made

- Generated revision ID `6f82e9117c58` using `uuid.uuid4().hex[:12]` directly in Python (per plan spec, not via `alembic revision` subprocess)
- Added `ic_p_value_bh` column for Benjamini-Hochberg corrected p-values as specified in plan
- Used `schema="public"` on all `create_table`, `drop_table`, `create_index`, `drop_index` calls to maintain Windows compat
- No UTF-8 box-drawing characters used in comments (avoids cp1252 UnicodeDecodeError on Windows)
- Pre-commit hook fixed mixed CRLF/LF line endings on first commit attempt; re-staged and committed cleanly on second attempt

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-commit hook (mixed-line-ending) rejected first commit because the file had CRLF line endings from Windows. The hook auto-fixed the line endings but the file needed to be re-staged. Second `git add` + `git commit` succeeded cleanly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Both tables exist in the DB at head revision `6f82e9117c58`
- `dim_feature_registry` and `cmc_feature_experiments` are ready for ExperimentRunner (38-02) and FeaturePromoter (38-03) to write results
- No blockers for remaining Phase 38 plans

---
*Phase: 38-feature-experimentation*
*Completed: 2026-02-24*
