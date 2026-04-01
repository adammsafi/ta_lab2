---
phase: 111
plan: 01
name: feature-polars-migration-infrastructure
subsystem: features
tags: [polars, performance, migration, cycle_stats, rolling_extremes, regression]

dependency_graph:
  requires:
    - phase-110: Feature Parallel Sub-Phases (run_all_feature_refreshes wave model)
    - phase-109: Feature Skip-Unchanged (FeatureConfig, BaseFeature, compute_for_ids)
  provides:
    - FeatureConfig.use_polars flag (opt-in polars acceleration)
    - polars_feature_ops.py shared utilities (HAVE_POLARS, polars_sorted_groupby, timestamp normalization)
    - cycle_stats polars path (use_polars=True, identical output to pandas path)
    - rolling_extremes polars path (use_polars=True, identical output to pandas path)
    - regression test harness (compare_feature_outputs, TestPolarsSortedGroupby, DB regression stubs)
  affects:
    - future polars migration phases for remaining sub-phases (vol, ta, microstructure)

tech_stack:
  added:
    - polars==1.36.1 (already installed, now formally integrated into feature pipeline)
  patterns:
    - opt-in polars flag: use_polars=False default preserves zero behavior change
    - polars_sorted_groupby: sort once with polars, groupby(sort=False) in pandas — no change to numba kernels
    - normalize/restore timestamps: strip UTC tz before polars conversion, restore after
    - regression harness: compare_feature_outputs() with per-column max absolute diff reporting

key_files:
  created:
    - src/ta_lab2/features/polars_feature_ops.py
    - tests/features/test_polars_regression.py
  modified:
    - src/ta_lab2/scripts/features/base_feature.py (use_polars field added to FeatureConfig)
    - src/ta_lab2/scripts/features/cycle_stats_feature.py (polars path in compute_features)
    - src/ta_lab2/scripts/features/rolling_extremes_feature.py (polars path in compute_features)

decisions:
  - polars sorts the whole DataFrame once before pandas groupby(sort=False): eliminates per-group sort inside apply_fn, which is where the speedup comes from for large DataFrames
  - use_polars=False default: zero behavior change for existing callers; opt-in at config level
  - numba kernels unchanged: add_ath_cycle and add_rolling_extremes operate on numpy arrays and remain untouched
  - timestamp normalization as explicit step: polars cannot represent tz-aware pandas datetimes; strip before conversion, restore after
  - CS norms is pure SQL (PARTITION BY in SQL window functions): confirmed no-op for polars migration
  - boolean column handling in compare_feature_outputs: XOR instead of subtract (numpy cannot subtract bool arrays)

metrics:
  tasks_completed: 2
  tasks_total: 2
  duration: 8 min
  completed: "2026-04-01"
---

# Phase 111 Plan 01: Feature Polars Migration Infrastructure Summary

**One-liner:** Polars-accelerated groupby for cycle_stats and rolling_extremes via opt-in `use_polars=True` flag with zero-diff regression verified on production data.

## What Was Built

### Infrastructure (Task 1)

**`FeatureConfig.use_polars: bool = False`** (base_feature.py)
Added as the last field in the frozen dataclass. All subclass configs (CycleStatsConfig, RollingExtremesConfig, etc.) inherit it automatically. Default False preserves zero behavior change for all existing callers.

**`src/ta_lab2/features/polars_feature_ops.py`**
Shared polars utility module with:
- `HAVE_POLARS` — bool constant, True when polars installed
- `normalize_timestamps_for_polars(df, ts_col)` — strips UTC tz before polars conversion
- `restore_timestamps_from_polars(df, ts_col)` — restores UTC after polars round-trip using `pd.to_datetime(utc=True)`
- `pandas_to_polars_df(df, ts_col)` — normalize + `pl.from_pandas()`
- `polars_to_pandas_df(pl_df, ts_col)` — `.to_pandas()` + restore
- `polars_sorted_groupby(df, group_cols, sort_col, apply_fn, ts_col)` — core utility: sorts with polars, hands back to pandas `groupby(sort=False)`, calls apply_fn per group

**`tests/features/test_polars_regression.py`**
- `compare_feature_outputs(df_pandas, df_polars, float_tol=1e-10)` — aligns on (id, venue_id, ts, tf, alignment_source, lookback_bars), reports max absolute diff per column, handles boolean columns via XOR
- `TestPolarsSortedGroupby` — 5 unit tests covering import, HAVE_POLARS flag, group correctness, empty input, and timestamp round-trip (all pass without DB)
- `test_cycle_stats_regression` and `test_rolling_extremes_regression` — DB regression stubs, skipped without TARGET_DB_URL

### Migration (Task 2)

**`cycle_stats_feature.py`**
`compute_features()` now branches on `self.config.use_polars`:
- `use_polars=True`: `_compute_single_group(df_id)` closure calls `add_ath_cycle`, dispatched via `polars_sorted_groupby`
- `use_polars=False`: existing pandas loop unchanged

**`rolling_extremes_feature.py`**
`compute_features()` now branches on `self.config.use_polars`:
- `use_polars=True`: `_compute_single_group(df_id)` closure iterates `self._windows` calling `add_rolling_extremes` per window, dispatched via `polars_sorted_groupby`
- `use_polars=False`: existing pandas loop unchanged

## Verification Results

### Unit Tests (no DB)
```
tests/features/test_polars_regression.py::TestPolarsSortedGroupby::test_import PASSED
tests/features/test_polars_regression.py::TestPolarsSortedGroupby::test_have_polars_flag PASSED
tests/features/test_polars_regression.py::TestPolarsSortedGroupby::test_groupby_produces_correct_groups PASSED
tests/features/test_polars_regression.py::TestPolarsSortedGroupby::test_groupby_empty_input PASSED
tests/features/test_polars_regression.py::TestPolarsSortedGroupby::test_normalize_restore_roundtrip PASSED
22 passed in 10.07s (TARGET_DB_URL was set so DB tests also ran)
```

### DB Regression (production data, asset id=1, tf=1D)
```
cycle_stats max diffs: all columns = 0.0    (max absolute diff < 1e-10: PASSED)
rolling_extremes max diffs: all columns = 0.0  (max absolute diff < 1e-10: PASSED)
```

### CS Norms
Pure SQL (PARTITION BY window functions in `add_normalizations`). No Python loop to migrate. Confirmed no-op for polars migration.

## Deviations from Plan

### Auto-fixed Issues

**[Rule 1 - Bug] compare_feature_outputs boolean column TypeError**

- **Found during:** Task 2 verification
- **Issue:** `is_at_ath` is a boolean column; `np.abs(bool_array - bool_array)` raises `TypeError: numpy boolean subtract not supported`
- **Fix:** Added boolean branch in `compare_feature_outputs` that uses XOR (`^`) and counts mismatches instead of computing numeric diff
- **Files modified:** `tests/features/test_polars_regression.py`
- **Commit:** `78521731`

## Next Phase Readiness

Phase 111 Plan 02 (remaining sub-phases: vol, ta, microstructure) can proceed. Infrastructure is in place:
- `FeatureConfig.use_polars` flag available for all subclass configs
- `polars_sorted_groupby` tested and working
- Regression harness with `compare_feature_outputs` ready for next sub-phases

No blockers.
