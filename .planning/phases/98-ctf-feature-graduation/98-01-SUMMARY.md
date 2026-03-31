---
phase: 98-ctf-feature-graduation
plan: "01"
subsystem: features
tags: [ctf, cross-timeframe, alembic, feature-promotion, ic-results, features-table, yaml]

# Dependency graph
requires:
  - phase: 92-ctf-ic-analysis-feature-selection
    provides: ic_results table with CTF feature IC scores, dim_ctf_feature_selection, public.ctf fact table
  - phase: 89-ctf-infrastructure
    provides: load_ctf_features() function, CTF fact table schema, dim_ctf_indicators
provides:
  - Alembic migration r2s3t4u5v6w7 adding 401 CTF columns to features table
  - dim_feature_selection_asset table for per-asset CTF tier assignments
  - ctf_composites table for cross-asset composite signals (Plans 98-03, 98-04)
  - lead_lag_ic table for all-vs-all lead-lag IC matrix (Plan 98-04)
  - refresh_ctf_promoted.py ETL script materializing CTF features into features table
  - ctf_promoted section in feature_selection.yaml with 401 promoted features + IC metadata
  - 22,322 features rows updated with non-null CTF values (1D base_tf, 7 assets)
affects:
  - phase-99-backtest-expansion (features table now has CTF columns for strategy signals)
  - phase-100-ml-expansion (ML-01/02/03 require CTF features in features table)
  - phase-98-02 (asset-specific CTF selection reads dim_feature_selection_asset)
  - phase-98-03 (cross-asset composites writes to ctf_composites table)
  - phase-98-04 (lead-lag IC writes to lead_lag_ic table)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Data-dependent Alembic migration (queries ic_results at migration time to determine columns)
    - CTF feature promotion via UPDATE not DELETE+INSERT (supplemental column pattern)
    - Pre-flight column check with RuntimeError before any writes
    - PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) as cross-asset median IC aggregation

key-files:
  created:
    - alembic/versions/r2s3t4u5v6w7_phase98_ctf_graduation_schema.py
    - src/ta_lab2/scripts/features/refresh_ctf_promoted.py
  modified:
    - configs/feature_selection.yaml

key-decisions:
  - "401 CTF features promoted (IC > 0.02 cross-asset median) -- all passing features, no artificial cap"
  - "UPDATE pattern (not DELETE+INSERT) preserves other features columns -- microstructure_feature.py precedent"
  - "Dynamic IC query in Alembic migration: columns discovered at runtime from ic_results"
  - "Idempotency guard in migration: skip columns already in features (information_schema check)"
  - "dim_feature_selection_asset separate from dim_feature_selection to avoid TRUNCATE hazard"
  - "base_tf note in YAML is placeholder '1D' -- all base_tfs produce same promoted column set"

patterns-established:
  - "Supplemental UPDATE pattern: load_ctf_features() -> filter to promoted cols -> UPDATE features rows"
  - "Pre-flight check: compare information_schema.columns against expected set before any writes"
  - "Data-dependent migration: query live table in upgrade() to determine DDL scope"

# Metrics
duration: 30min
completed: 2026-03-31
---

# Phase 98 Plan 01: CTF Feature Graduation Schema + ETL Bridge Summary

**401 CTF features promoted from ctf fact table into production features table via Alembic migration + UPDATE ETL, with IC metadata registered in feature_selection.yaml ctf_promoted section**

## Performance

- **Duration:** ~30 min
- **Started:** 2026-03-31T13:40:00Z
- **Completed:** 2026-03-31T14:10:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Alembic migration r2s3t4u5v6w7 applies cleanly: adds 401 CTF promoted columns to features, creates dim_feature_selection_asset, ctf_composites, lead_lag_ic tables
- refresh_ctf_promoted.py materializes CTF values into features via UPDATE (supplemental column pattern, preserves all other feature columns)
- feature_selection.yaml updated with ctf_promoted section listing all 401 features with median_abs_ic and n_assets metadata
- Executed 1D base_tf refresh: 7 assets x up to 389 columns x ~3,000-5,600 rows = 22,322 total rows updated
- Dry-run mode functional, pre-flight check verified, all CLI flags working

## Task Commits

1. **Task 1: Alembic migration for all Phase 98 schema changes** - `c3dda87d` (feat)
2. **Task 2: refresh_ctf_promoted.py ETL + feature_selection.yaml update** - `89cb7a37` (feat)

**Plan metadata:** (pending docs commit)

## Files Created/Modified

- `alembic/versions/r2s3t4u5v6w7_phase98_ctf_graduation_schema.py` - Data-dependent migration: discovers CTF features from ic_results via PERCENTILE_CONT query, adds 401 columns to features table, creates 3 new tables
- `src/ta_lab2/scripts/features/refresh_ctf_promoted.py` - ETL bridge from ctf fact table to features table; pre-flight check, IC discovery, load_ctf_features() loop, batched UPDATE, YAML append
- `configs/feature_selection.yaml` - Added ctf_promoted top-level section with 401 features, median_abs_ic, n_assets, IC metadata

## Decisions Made

- **401 features promoted, no artificial cap:** All CTF features passing PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ABS(ic)) > 0.02 are promoted. Context decision was "All passing features -- no artificial cap."
- **UPDATE pattern inherited from microstructure_feature.py:** CTF columns are supplemental to base features rows. DELETE+INSERT would destroy other columns. UPDATE sets only CTF columns, NULL for NaN values.
- **Dynamic IC query in Alembic migration:** Columns are discovered at migration runtime from ic_results rather than hardcoded. Idempotency guard (information_schema check) skips columns already present.
- **dim_feature_selection_asset separate table:** Named distinctly from dim_feature_selection to avoid TRUNCATE hazard per Phase 92 lessons.
- **base_tf in YAML is '1D' placeholder:** The promoted feature set is the same for all base_tfs (IC was computed cross-asset). Actual per-base_tf coverage is at the scope level, not feature name level.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed deprecated pd.api.types.is_datetime64tz_dtype call**
- **Found during:** Task 2 (first execution of refresh_ctf_promoted.py)
- **Issue:** `pd.api.types.is_datetime64tz_dtype` is deprecated in newer Pandas with DeprecationWarning
- **Fix:** Replaced with `isinstance(dtype, pd.DatetimeTZDtype)` (modern Pandas API)
- **Files modified:** src/ta_lab2/scripts/features/refresh_ctf_promoted.py
- **Verification:** No DeprecationWarning on re-run
- **Committed in:** 89cb7a37 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Minor. Deprecated API replaced with correct modern alternative. No functional change.

## Issues Encountered

- Alembic migration applies only once (data-dependent migrations are one-way for the column discovery). The downgrade() uses a dynamic query of information_schema to find CTF columns by pattern, which is safe.
- refresh_ctf_promoted.py 1D refresh runs ~13 minutes (row-by-row UPDATE with 401 columns per row). Performance acceptable for periodic refresh. Full run with all base_tfs would take ~4-5x longer.

## User Setup Required

None - no external service configuration required. Run `python -m alembic upgrade head` if not already applied, then `python -m ta_lab2.scripts.features.refresh_ctf_promoted` to populate.

## Next Phase Readiness

- Phase 98-02 (asset-specific CTF selection): dim_feature_selection_asset table exists and ready
- Phase 98-03 (cross-asset composites): ctf_composites table exists and ready
- Phase 98-04 (lead-lag IC matrix): lead_lag_ic table exists and ready
- Phase 99 (backtest expansion): CTF features now in features table for 1D (run --base-tf 7D etc. for other tfs)
- Phase 100 (ML): CTF features available in features table for ML-01/02/03

---
*Phase: 98-ctf-feature-graduation*
*Completed: 2026-03-31*
