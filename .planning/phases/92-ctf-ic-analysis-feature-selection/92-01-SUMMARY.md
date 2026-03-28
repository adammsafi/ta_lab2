---
phase: 92-ctf-ic-analysis-feature-selection
plan: "01"
subsystem: database
tags: [ctf, ic-analysis, feature-selection, alembic, pandas, sqlalchemy]

# Dependency graph
requires:
  - phase: 91-ctf-cli-pipeline-integration
    provides: public.ctf fact table + dim_ctf_indicators populated by CTF engine
  - phase: 90-ctf-engine
    provides: CTFFeature engine writing slope/divergence/agreement/crossover composites
  - phase: 89-ctf-schema
    provides: public.ctf, dim_ctf_indicators, ctf_state Alembic migrations

provides:
  - load_ctf_features() pivot loader in cross_timeframe.py (long->wide reshape for IC analysis)
  - dim_ctf_feature_selection PostgreSQL table for storing CTF tier classifications

affects:
  - 92-02 (batch IC analysis uses load_ctf_features as input)
  - 92-03 (feature selection YAML generation reads dim_ctf_feature_selection)
  - Any future CTF dashboard pages

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Vectorized long->wide pivot via melt+pivot_table (no iterrows)"
    - "Column naming convention: {indicator_name}_{ref_tf_lower}_{composite}"
    - "Alembic migration: op.get_bind() + conn.execute(text(SQL)) raw SQL pattern"

key-files:
  created:
    - alembic/versions/l6m7n8o9p0q1_dim_ctf_feature_selection.py
  modified:
    - src/ta_lab2/features/cross_timeframe.py

key-decisions:
  - "load_ctf_features uses vectorized pivot (melt+pivot_table), not row-by-row iterrows -- matches batch_compute_ic input expectations"
  - "dim_ctf_feature_selection is separate from dim_feature_selection (Phase 80) -- avoids interference with existing feature selection pipeline"
  - "ref_tf_lower via str.lower() in Python (not SQL LOWER()) -- consistent with column naming done in Python layer"
  - "dropna(axis=1, how='all') drops crossover columns for non-directional indicators -- these are all-NaN by design in _compute_crossover"
  - "pd.to_datetime(utc=True) applied after pd.read_sql -- Windows tz-naive fix consistent with existing CTF patterns"

patterns-established:
  - "load_ctf_features(): conn parameter (not engine) -- caller controls connection lifecycle for batched queries"
  - "ANY(:param) list binding for ref_tfs/indicator_names -- consistent with _load_indicators_batch pattern"
  - "Empty DataFrame returned early if no rows -- prevents downstream NaN pivot errors"

# Metrics
duration: 3min
completed: 2026-03-24
---

# Phase 92 Plan 01: CTF Pivot Loader and Feature Selection Table Summary

**load_ctf_features() vectorized pivot (long->wide, {indicator}_{tf_lower}_{composite} columns) + dim_ctf_feature_selection PostgreSQL table (PK: feature_name/base_tf, tier/stationarity CHECK constraints)**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-24T02:21:41Z
- **Completed:** 2026-03-24T02:24:15Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `load_ctf_features()` to `cross_timeframe.py`: reads from `public.ctf JOIN dim_ctf_indicators`, pivots to wide DataFrame with `{indicator_name}_{ref_tf_lower}_{composite}` columns, drops all-NaN crossover columns for non-directional indicators, returns UTC-indexed DatetimeIndex
- Created Alembic migration `l6m7n8o9p0q1` for `dim_ctf_feature_selection`: PK `(feature_name, base_tf)`, tier CHECK (active/conditional/watch/archive), stationarity CHECK (STATIONARY/NON_STATIONARY/AMBIGUOUS/INSUFFICIENT_DATA), ic_ir_mean/pass_rate/ljung_box_flag/selected_at/yaml_version/rationale columns
- Applied migration to PostgreSQL: `alembic upgrade head` completed, head confirmed at `l6m7n8o9p0q1`

## Task Commits

Each task was committed atomically:

1. **Task 1: Add load_ctf_features() pivot loader to cross_timeframe.py** - `aca76809` (feat)
2. **Task 2: Create Alembic migration for dim_ctf_feature_selection** - `b4b5dd2e` (feat)

**Plan metadata:** (pending docs commit)

## Files Created/Modified

- `src/ta_lab2/features/cross_timeframe.py` - Added `load_ctf_features()` function (171 lines inserted) after module-level computation helpers, before CTFConfig dataclass
- `alembic/versions/l6m7n8o9p0q1_dim_ctf_feature_selection.py` - New Alembic migration, down_revision=k5l6m7n8o9p0

## Decisions Made

- **Vectorized pivot approach**: Used `melt + pivot_table` rather than row-by-row iterrows. Matches the performance requirements for IC analysis which processes hundreds of thousands of rows.
- **dim_ctf_feature_selection separate from dim_feature_selection**: Phase 80 created `dim_feature_selection` for standard features. CTF features have different composites (slope/divergence/agreement/crossover) and different tier classifications, so a separate table avoids schema interference.
- **ref_tf_lower in Python layer**: `df["ref_tf"].str.lower()` done in Python pivot step (not SQL `LOWER(ref_tf)`) -- consistent with the rest of the vectorized transformation chain.
- **dropna(axis=1, how="all")**: `_compute_crossover` returns all-NaN series for non-directional indicators by design. Dropping these columns before returning keeps the output clean for IC computation.
- **conn parameter (not engine)**: Caller controls connection lifecycle -- enables batching across multiple `load_ctf_features()` calls without creating/destroying engine connections per call.

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None -- no external service configuration required.

## Next Phase Readiness

- `load_ctf_features()` is ready as input to `batch_compute_ic()` in Plan 92-02
- `dim_ctf_feature_selection` table is deployed and ready for IC result writes in Plan 92-03
- Alembic chain unbroken: head = `l6m7n8o9p0q1`, down_revision chain: `l6m7n8o9p0q1 -> k5l6m7n8o9p0 -> j4k5l6m7n8o9`
- No blockers for Plan 92-02

---
*Phase: 92-ctf-ic-analysis-feature-selection*
*Completed: 2026-03-24*
