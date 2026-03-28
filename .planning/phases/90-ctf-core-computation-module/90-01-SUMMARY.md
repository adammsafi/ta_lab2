---
phase: 90-ctf-core-computation-module
plan: 01
subsystem: features
tags: [cross-timeframe, ctf, sqlalchemy, pandas, merge_asof, yaml, dim_ctf_indicators]

# Dependency graph
requires:
  - phase: 89-ctf-schema-dimension-table
    provides: dim_ctf_indicators (22 seeded indicators), ctf fact table, ctf_config.yaml
  - phase: 27-regimes
    provides: build_alignment_frame in regimes/comovement.py
provides:
  - CTFConfig frozen dataclass with alignment_source, venue_id, yaml_path fields
  - CTFFeature class with YAML config loading, dimension table loading, batch indicator loading, and timeframe alignment
  - _load_indicators_batch handles all 4 source tables with correct asymmetries (timestamp alias, roll filter, venue_id WHERE)
affects:
  - 90-02 (plan 02): composite computations (slope, divergence, agreement, crossover), orchestrator, write logic

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CTFConfig frozen dataclass: 3 fields (alignment_source, venue_id, yaml_path)"
    - "Source table asymmetry handling: returns_bars_multi_tf_u uses 'timestamp' alias + roll=FALSE filter"
    - "per-asset alignment loop: build_alignment_frame called once per unique asset_id in base_df"
    - "Cache pattern: _yaml_config, _dim_indicators, _table_columns cached after first load"

key-files:
  created:
    - src/ta_lab2/features/cross_timeframe.py
  modified: []

key-decisions:
  - "ta/vol/features all have venue_id in PK (not column-only as earlier research suggested) -- confirmed via information_schema query"
  - "Only features table gets AND venue_id = :venue_id in WHERE (ta/vol filtering by alignment_source is sufficient)"
  - "build_alignment_frame imported from regimes.comovement -- not reimplemented"
  - "numpy imported but unused in plan 01 (noqa: F401 comment) -- reserved for plan 02 composite computations"

patterns-established:
  - "CTFFeature follows same __init__ pattern as BaseFeature: optional config + optional engine"
  - "_load_indicators_batch constructs SQL dynamically based on source_table to handle asymmetries"
  - "_align_timeframes iterates per asset_id, skips assets with no ref data, pd.concat at end"

# Metrics
duration: 4min
completed: 2026-03-23
---

# Phase 90 Plan 01: CTF Core Computation Module Summary

**CTFConfig frozen dataclass + CTFFeature class with YAML config loading, dim_ctf_indicators querying, 4-source-table batch indicator loading with asymmetry handling, and build_alignment_frame-based timeframe alignment**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-23T19:58:57Z
- **Completed:** 2026-03-23T20:02:37Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- CTFConfig frozen dataclass with 3 fields (alignment_source='multi_tf', venue_id=1, yaml_path=None)
- CTFFeature class with 5 methods: _load_ctf_config, _load_dim_ctf_indicators, _load_indicators_batch, _align_timeframes, _get_table_columns
- _load_indicators_batch correctly handles all 4 source tables: `ta` (6781 rows/1D), `vol` (6781 rows/1D), `returns_bars_multi_tf_u` (6779 rows/1D with roll=FALSE + timestamp alias), `features` (5614 rows/1D with venue_id WHERE)
- _align_timeframes produces [id, ts, base_value, ref_value] output via build_alignment_frame per asset
- All 4 verification checks passed

## Task Commits

1. **Task 1: Create cross_timeframe.py with CTFConfig and data loading methods** - `dda75e6d` (feat)

## Files Created/Modified
- `src/ta_lab2/features/cross_timeframe.py` - CTFConfig dataclass and CTFFeature class with data loading and alignment methods

## Decisions Made
- ta/vol/features all have venue_id in PK (confirmed via information_schema; plan's "column-only" note was from earlier Phase 89 research predating the actual migration). Only `features` gets `AND venue_id = :venue_id` in WHERE since it helps narrow results; ta/vol filtering by alignment_source is sufficient.
- numpy imported with `# noqa: F401` comment: reserved for plan 02 composite computations (slope, divergence), avoids re-importing later
- `build_alignment_frame` imported directly from `ta_lab2.regimes.comovement` -- not reimplemented locally

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Plan 02 can import CTFConfig, CTFFeature directly
- _load_indicators_batch tested with all 4 source tables, returns correct schemas
- _align_timeframes produces [id, ts, base_value, ref_value] as expected by composite computation layer
- No blockers

---
*Phase: 90-ctf-core-computation-module*
*Completed: 2026-03-23*
