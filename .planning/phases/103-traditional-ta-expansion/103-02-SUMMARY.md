---
phase: 103-traditional-ta-expansion
plan: 02
subsystem: features
tags: [ta, indicators, alembic, dim_indicators, ta_feature, indicators_extended, postgres]

# Dependency graph
requires:
  - phase: 103-01
    provides: indicators_extended.py with 20 new indicator functions
provides:
  - Alembic migration v5w6x7y8z9a0 seeding 20 dim_indicators rows
  - 35 new DOUBLE PRECISION columns added to ta table via ALTER TABLE
  - TAFeature.compute_features() dispatches all 20 new indicator types
  - TAFeature.get_feature_columns() returns column names for all 20 new types
  - TAFeature.get_output_schema() includes all 35 new output columns
  - 20 private _compute_XXX() helper methods wiring indx.* calls with params
affects: [103-03, feature-pipeline, refresh-ta]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "dim_indicators ON CONFLICT (indicator_name) DO UPDATE for idempotent seeding"
    - "ALTER TABLE ... ADD COLUMN IF NOT EXISTS for additive schema migrations"
    - "TAFeature private _compute_XXX pattern for each indicator type"
    - "indicators_extended imported as indx at module level"

key-files:
  created:
    - alembic/versions/v5w6x7y8z9a0_phase103_extended_indicators.py
  modified:
    - src/ta_lab2/scripts/features/ta_feature.py

key-decisions:
  - "chaikin_osc output column fixed to 'chaikin_osc' (not chaikin_osc_3_10) to match schema DDL"
  - "coppock output column fixed to 'coppock' (not coppock_10) to match schema DDL"
  - "ichimoku get_feature_columns uses hardcoded column list (not f-strings) since output names are param-independent"
  - "Mass index column name uses mass_idx_{sum_period} to match the indicators_extended default out_col"

patterns-established:
  - "Extended indicator helpers follow same _compute_XXX(df, params) pattern as original 6"
  - "inplace=True used throughout for consistency with indicators.py helpers"
  - "output column names in schema match indicators_extended default out_col values exactly"

# Metrics
duration: 3min
completed: 2026-04-01
---

# Phase 103 Plan 02: Traditional TA Expansion - Registry Integration Summary

**Alembic migration seeds 20 extended indicators into dim_indicators and wires all 20 into TAFeature via 20 private _compute_XXX() helpers dispatched from compute_features()**

## Performance

- **Duration:** 3 min
- **Started:** 2026-04-01T21:36:36Z
- **Completed:** 2026-04-01T21:40:14Z
- **Tasks:** 2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments
- Alembic migration v5w6x7y8z9a0 seeds 20 new dim_indicators rows with correct indicator_type, params JSONB, and is_active=TRUE; ON CONFLICT (indicator_name) DO UPDATE for idempotency
- 35 new DOUBLE PRECISION columns added to public.ta via ADD COLUMN IF NOT EXISTS (ichimoku x5, keltner x4, aroon x3, elder_ray x2, force_index x2, vwap x2, trix x2, vortex x2, emv x2, kst x2, and single columns for willr, cci, cmf, chaikin_osc, hurst, vidya, frama, uo, mass_idx, coppock)
- TAFeature extended with 20 new elif branches in compute_features(), 20 private helper methods, 20 new elif blocks in get_feature_columns(), and 35 new schema entries in get_output_schema()

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration — seed dim_indicators + add features table columns** - `ec11e5bf` (feat)
2. **Task 2: Extend TAFeature dispatch, column list, and schema** - `e7718560` (feat)

## Files Created/Modified
- `alembic/versions/v5w6x7y8z9a0_phase103_extended_indicators.py` - Migration seeding 20 dim_indicators rows and adding 35 ta columns
- `src/ta_lab2/scripts/features/ta_feature.py` - Extended with indicators_extended import, 20 compute dispatchers, 20 helper methods, updated schema/column methods

## Decisions Made
- chaikin_osc output column fixed to `chaikin_osc` (not `chaikin_osc_3_10`) to match schema DDL and migration column name
- coppock output column fixed to `coppock` (not `coppock_10`) to match schema DDL and migration column name
- ichimoku `get_feature_columns` uses hardcoded string list (not f-strings with params) since all 5 output column names are fixed regardless of tenkan/kijun/senkou_b values
- mass_index column name uses `mass_idx_{sum_period}` matching the indicators_extended default `out_col` pattern

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None - ruff auto-formatted the migration file on first commit attempt; re-staged and committed cleanly.

## User Setup Required

None - no external service configuration required. Run `alembic upgrade head` to apply the migration.

## Next Phase Readiness
- dim_indicators now has 20 new rows ready for query by TAFeature.load_indicator_params()
- TAFeature.compute_features() will dispatch all 20 new types once migration is applied
- Phase 103 Plan 03 can proceed (refresh pipeline integration and end-to-end smoke test)

---
*Phase: 103-traditional-ta-expansion*
*Completed: 2026-04-01*
