---
phase: 60-ml-infrastructure-experimentation
plan: "02"
subsystem: database, ml
tags: [postgresql, sqlalchemy, uuid, jsonb, experiment-tracking, numpy, pandas]

# Dependency graph
requires:
  - phase: 60-01-ml-infrastructure-experimentation
    provides: ml package skeleton, expression engine, feature_importance.py

provides:
  - cmc_ml_experiments DDL (sql/ml/095_cmc_ml_experiments.sql) with UUID PK, JSONB params, TEXT[] feature_set, OOS metrics, feature importance JSONB columns, and GIN/B-tree indexes
  - ExperimentTracker class (src/ta_lab2/ml/experiment_tracker.py) with log_run(), get_run(), list_runs(), compare_runs(), ensure_table()
  - _to_python() numpy scalar normalisation helper
  - _compute_feature_set_hash() order-independent SHA-256 feature set hashing

affects:
  - 60-03-regime-router (logs runs via ExperimentTracker)
  - 60-04-feature-importance (logs MDA/SFI importances via ExperimentTracker)
  - 60-05-double-ensemble (logs DoubleEnsemble runs via ExperimentTracker)
  - 60-06-optuna-sweep (logs Optuna study summaries via ExperimentTracker)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ExperimentTracker: engine-injection pattern (no hardcoded credentials)"
    - "feature_set_hash: SHA-256 of sorted feature list for order-independent equality"
    - "_to_python() + hasattr(v, 'item') pattern for numpy scalar normalisation"
    - "SQL DDL opened with encoding='utf-8' (Windows CRLF-safe)"
    - "Timestamps read with pd.to_datetime(utc=True) to avoid tz-naive pitfall"
    - "JSONB columns cast explicitly via CAST(:param AS JSONB) in INSERT SQL"

key-files:
  created:
    - sql/ml/095_cmc_ml_experiments.sql
    - src/ta_lab2/ml/experiment_tracker.py
  modified: []

key-decisions:
  - "ExperimentTracker takes SQLAlchemy engine from caller — no DB config inside module"
  - "feature_set_hash uses SHA-256 of sorted, comma-joined feature names for order-independence"
  - "ensure_table() splits DDL on semicolons and executes each statement (handles multi-statement DDL with CREATE TABLE + CREATE INDEX + COMMENT)"
  - "asset_ids passed as PostgreSQL array literal string '{1,2}' to avoid psycopg2 list binding issues"
  - "All JSONB columns cast explicitly with CAST(:param AS JSONB) to avoid type inference errors"
  - "compare_runs() uses named parameters (eid_0, eid_1, ...) for the IN clause to avoid positional binding issues"

patterns-established:
  - "ML experiment logging pattern: tracker.log_run() -> UUID string experiment_id"
  - "Numpy-safe DB insert: wrap all numeric params with _to_python() before binding"
  - "JSONB serialisation: always use _to_jsonb() which recurses to normalise nested numpy"

# Metrics
duration: 5min
completed: "2026-02-28"
---

# Phase 60 Plan 02: ML Experiment Tracking Summary

**PostgreSQL-backed ExperimentTracker with SHA-256 feature-set hashing, JSONB serialisation, and numpy scalar normalisation for logging all Phase 60 ML runs**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-28T14:29:55Z
- **Completed:** 2026-02-28T14:35:02Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `cmc_ml_experiments` DDL with UUID PK, 30+ columns covering model params, feature set, CV config, OOS metrics (accuracy/sharpe/precision/recall/F1), MDA/SFI importances JSONB, Optuna study linkage, and regime routing support
- Created ExperimentTracker class with log_run(), get_run(), list_runs(), compare_runs(), ensure_table() — all other Phase 60 modules will use this as the central run registry
- Implemented _to_python() and _to_jsonb() helpers for safe numpy scalar handling before psycopg2 binding

## Task Commits

Each task was committed atomically:

1. **Task 1: Create cmc_ml_experiments DDL** - committed in `248a1538` (feat: part of 60-01 docs commit)
2. **Task 2: Create ExperimentTracker module** - committed in `248a1538` (feat: 60-01 docs commit)

**Note:** Both deliverables were committed by the prior plan 60-01 execution session in the docs/metadata commit (248a1538). The artifacts are in place and fully verified.

## Files Created/Modified

- `sql/ml/095_cmc_ml_experiments.sql` - DDL: CREATE TABLE cmc_ml_experiments with UUID PK, JSONB params, TEXT[] feature_set, OOS metric columns, GIN + B-tree indexes, column COMMENTs
- `src/ta_lab2/ml/experiment_tracker.py` - ExperimentTracker class: log_run(), get_run(), list_runs(), compare_runs(), ensure_table(), _to_python(), _to_jsonb(), _compute_feature_set_hash()

## Decisions Made

- Used engine-injection pattern for ExperimentTracker (no hardcoded DB config)
- feature_set_hash: SHA-256 of sorted feature names (order-independent, enables cache lookup by feature set)
- CAST(:param AS JSONB) in INSERT SQL prevents type inference failures when passing JSON strings
- asset_ids passed as PostgreSQL array literal string to sidestep psycopg2 list binding
- compare_runs() uses named parameter expansion (eid_0, eid_1, ...) for the IN clause

## Deviations from Plan

None - plan executed exactly as written. Both artifacts were already committed by the prior session's 60-01 execution; this execution verified the artifacts and produced the SUMMARY.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required. The ExperimentTracker requires a live PostgreSQL engine but uses `ensure_table()` to create the table on first use. Callers pass their own engine.

## Next Phase Readiness

- `ExperimentTracker` is ready for use by all subsequent Phase 60 plans (60-03 through 60-08)
- `ensure_table()` must be called once before first use — each ML script should call it at startup
- No blockers for 60-03 (regime router), 60-04 (feature importance CLI), 60-05 (DoubleEnsemble)

---
*Phase: 60-ml-infrastructure-experimentation*
*Completed: 2026-02-28*
