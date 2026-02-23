---
phase: 35-ama-engine
plan: 03
subsystem: database
tags: [ama, kama, dema, tema, hma, sqlalchemy, pandas, incremental-refresh, template-method]

# Dependency graph
requires:
  - phase: 35-02
    provides: AMAParamSet, compute_params_hash, ALL_AMA_PARAMS, compute_ama() dispatcher
provides:
  - BaseAMAFeature abstract class with template method pattern for AMA computation
  - AMAStateManager class for incremental refresh watermarks per (id, tf, indicator, params_hash)
  - scripts/amas/ package init
affects:
  - 35-04 (AMA multi_tf refresher uses BaseAMAFeature and AMAStateManager)
  - Future calendar-aligned AMA refreshers (cal_us, cal_iso, etc.)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Template Method: BaseAMAFeature defines compute_for_asset_tf/add_derivatives/write_to_db; subclasses provide _load_bars/_get_timeframes/_get_source_table_info"
    - "Scoped DELETE + INSERT: write_to_db deletes (ids, tf) slice then inserts — matches MEMORY.md Feature write pattern"
    - "ON CONFLICT DO UPDATE: _pg_upsert provides safety net for concurrent writes"
    - "Column filtering: _get_table_columns() queries information_schema so df columns match actual DB columns"
    - "Derivative groups: add_derivatives() groups by (id, tf, indicator, params_hash, roll) for d1/d2/d1_roll/d2_roll"

key-files:
  created:
    - src/ta_lab2/features/ama/base_ama_feature.py
    - src/ta_lab2/scripts/amas/__init__.py
    - src/ta_lab2/scripts/amas/ama_state_manager.py
  modified: []

key-decisions:
  - "BaseAMAFeature is a sibling of BaseEMAFeature, NOT a subclass — different PK (indicator+params_hash vs period) requires independent _get_pk_columns() and _pg_upsert() implementations"
  - "AMAStateManager has (id, tf, indicator, params_hash) PK in DDL — standalone class, does not reuse EMAStateManager"
  - "er column set to NaN for non-KAMA indicators inline in compute_for_asset_tf — no NULL handling needed downstream"
  - "d1_roll == d1 and d2_roll == d2 for non-calendar AMA tables — roll column always False for multi_tf, columns kept for schema compatibility with EMA table family"
  - "AMAFeatureConfig uses list[AMAParamSet] not list[int] periods — AMA has multi-dimensional param space (indicator x params)"

patterns-established:
  - "TFSpec dataclass reused in AMA module — same (tf, tf_days) fields as EMA TFSpec"
  - "Windows tz pitfall: bars['ts'].tolist() used to preserve tz-awareness when building ts_list for DataFrame construction"
  - "save_state uses NOW() in SQL not Python datetime — avoids clock skew between Python process and DB server"

# Metrics
duration: 3min
completed: 2026-02-23
---

# Phase 35 Plan 03: AMA Infrastructure Layer Summary

**BaseAMAFeature abstract template class and AMAStateManager with (id, tf, indicator, params_hash) PK enabling incremental refresh for all AMA table variants**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-23T22:06:28Z
- **Completed:** 2026-02-23T22:09:37Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- BaseAMAFeature: abstract base class with 3 abstract methods (_load_bars, _get_timeframes, _get_source_table_info) and 6 concrete methods (compute_for_asset_tf, add_derivatives, write_to_db, _pg_upsert, _get_pk_columns, _get_table_columns)
- AMAStateManager: standalone state manager with (id, tf, indicator, params_hash) PK; 5 public methods for DDL, load, save, bulk-load, and clear
- scripts/amas/ package created as the home for all AMA refresh scripts

## Task Commits

Each task was committed atomically:

1. **Task 1+2: BaseAMAFeature + AMAStateManager + package init** - `89d23b72` (feat)

**Plan metadata:** (created below as docs commit)

## Files Created/Modified

- `src/ta_lab2/features/ama/base_ama_feature.py` - Abstract template for AMA computation (PK: id, ts, tf, indicator, params_hash); compute_for_asset_tf dispatches to compute_ama(), add_derivatives computes d1/d2/d1_roll/d2_roll, write_to_db uses scoped DELETE+INSERT
- `src/ta_lab2/scripts/amas/__init__.py` - Package init for AMA refresh scripts
- `src/ta_lab2/scripts/amas/ama_state_manager.py` - Incremental state tracking with (id, tf, indicator, params_hash) PK; DDL, load, save, load_all, clear

## Decisions Made

- BaseAMAFeature is a sibling of BaseEMAFeature (not subclass) because the PK is fundamentally different — `indicator + params_hash` replaces `period`. Sharing code would require awkward overrides of every DB method.
- AMAStateManager is standalone (does not wrap or extend EMAStateManager). EMAStateManager's DDL hardcodes `period INTEGER` in the PK which is incorrect for AMA state.
- `d1_roll = d1` and `d2_roll = d2` for multi_tf AMAs. Since all multi_tf rows have roll=FALSE, there is no intra-period roll variant. The `_roll` columns are populated identically to maintain schema compatibility with the EMA table family.
- `er` column explicitly set to `np.nan` (not NULL) for DEMA/TEMA/HMA within compute_for_asset_tf — avoids conditional NULL handling in write_to_db and downstream queries.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused `close` variable that failed ruff F841 lint**

- **Found during:** Pre-commit hook on first commit attempt
- **Issue:** `close = bars["ts"].copy()` was an artifact from draft code that was never used; pre-commit ruff flagged F841
- **Fix:** Removed the unused assignment
- **Files modified:** src/ta_lab2/features/ama/base_ama_feature.py
- **Verification:** Pre-commit ruff lint passed on second commit
- **Committed in:** 89d23b72

---

**Total deviations:** 1 auto-fixed (1 lint/bug)
**Impact on plan:** Minor cleanup, no logic change.

## Issues Encountered

None — both tasks implemented cleanly on first pass.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- BaseAMAFeature and AMAStateManager are ready for use by Plan 35-04 (multi_tf refresher)
- Subclass pattern: implement _load_bars() + _get_timeframes() + _get_source_table_info() to get a fully functional AMA refresher
- Calendar-aligned variants (cal_us, cal_iso, etc.) follow the same subclass pattern

---
*Phase: 35-ama-engine*
*Completed: 2026-02-23*
