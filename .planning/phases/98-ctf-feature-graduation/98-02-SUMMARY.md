---
phase: 98-ctf-feature-graduation
plan: "02"
subsystem: features
tags: [ctf, cross-timeframe, feature-selection, asset-specific, ic-results, dim_feature_selection_asset]

# Dependency graph
requires:
  - phase: 98-ctf-feature-graduation
    plan: "01"
    provides: dim_feature_selection_asset table (created in Alembic migration r2s3t4u5v6w7), 401 globally promoted CTF features
provides:
  - run_ctf_asset_selection.py: per-asset CTF feature selection CLI script
  - 10,716 rows in dim_feature_selection_asset with tier='asset_specific' for 98 assets
affects:
  - phase-99-backtest-expansion (per-asset CTF feature sets available for strategy diversification)
  - phase-100-ml-expansion (ML per-asset feature selection can use dim_feature_selection_asset)
  - phase-98-03 (cross-asset composites may reference asset-specific winners)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Per-asset IC direct threshold (ABS(ic) > threshold, single-asset, not cross-asset median)
    - Asset-specific superset: effective features = global (dim_feature_selection) UNION asset-specific (dim_feature_selection_asset)
    - ON CONFLICT (feature_name, asset_id) DO UPDATE upsert into separate table (no TRUNCATE hazard)

key-files:
  created:
    - src/ta_lab2/scripts/analysis/run_ctf_asset_selection.py
  modified: []

key-decisions:
  - "Per-asset IC uses ABS(ic) > threshold (single asset value, not PERCENTILE_CONT) -- correct for per-asset evaluation"
  - "Asset-specific additions = per_asset_passing - global_features; only write additions not already in global tier"
  - "Write only asset-specific rows to dim_feature_selection_asset (not global rows); superset is a logical construct at query time"
  - "98 assets have CTF IC data; all 98 have asset-specific additions (53-164 per asset)"
  - "dim_feature_selection (global) verified unchanged at 205 rows before and after run"

# Metrics
duration: 11min
completed: 2026-03-31
---

# Phase 98 Plan 02: Per-Asset CTF Feature Selection Summary

**Per-asset CTF feature selection populates dim_feature_selection_asset with 10,716 rows for 98 assets; global dim_feature_selection unchanged at 205 rows; superset relationship verified**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-03-31T14:15:22Z
- **Completed:** 2026-03-31T14:26:30Z
- **Tasks:** 1
- **Files created:** 1

## Accomplishments

- run_ctf_asset_selection.py script created: queries ic_results per asset for CTF features where ABS(ic) > 0.02 threshold; subtracts global promoted set; writes only asset-specific additions with tier='asset_specific'
- 98 assets processed; all 98 have at least some asset-specific additions (range: 53-164 per asset)
- 10,716 rows written to dim_feature_selection_asset
- dim_feature_selection (global, 205 rows) verified unchanged before and after run -- no TRUNCATE damage
- Dry-run mode functional: shows per-asset counts and top features without DB writes
- --asset-id flag for single-asset processing
- Pre-flight check verifies dim_feature_selection_asset table exists (raises RuntimeError if not)
- Superset relationship verified: for any asset, querying dim_feature_selection_asset gives different count than global

## Task Commits

1. **Task 1: Build run_ctf_asset_selection.py** - `858d66c4` (feat)

## Files Created/Modified

- `src/ta_lab2/scripts/analysis/run_ctf_asset_selection.py` - Per-asset CTF feature selection CLI; pre-flight check, global feature loading, per-asset IC queries, asset-specific set subtraction, upsert to dim_feature_selection_asset, verification, dry-run support

## Decisions Made

- **Per-asset IC uses direct ABS(ic) > threshold:** Single-asset evaluation uses the single IC value for that asset (not PERCENTILE_CONT which is for cross-asset median aggregation). This is correct -- PERCENTILE_CONT would require multiple asset rows for a single feature, defeating the purpose.

- **Write only asset-specific additions (not global features):** The superset relationship is a logical query-time construct: `effective features = global (from dim_feature_selection) UNION asset-specific (from dim_feature_selection_asset)`. Writing duplicate rows for global features would waste space and create sync complexity.

- **ON CONFLICT upsert pattern:** INSERT ... ON CONFLICT (feature_name, asset_id) DO UPDATE. This is idempotent -- re-running the script with updated IC data will refresh the rows cleanly.

- **All 98 assets have asset-specific additions:** Every asset in ic_results has at least 53 CTF features that pass per-asset IC > 0.02 but were not in the global promoted set. This confirms the per-asset evaluation adds meaningful information beyond global promotion.

- **dim_feature_selection untouched:** Verified unchanged at 205 rows before and after run. This is the critical TRUNCATE hazard protection -- dim_feature_selection uses a TRUNCATE+INSERT pattern in save_to_db() which would wipe Phase 80 entries. By writing only to dim_feature_selection_asset, the global tier is safe.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Pre-commit ruff format reformatted file after initial commit attempt**

- **Found during:** Task 1 commit
- **Issue:** ruff-format pre-commit hook reformatted run_ctf_asset_selection.py (trailing whitespace, line length)
- **Fix:** Re-staged reformatted file and committed again
- **Files modified:** src/ta_lab2/scripts/analysis/run_ctf_asset_selection.py
- **Committed in:** 858d66c4 (Task 1 commit, second attempt)

---

**Total deviations:** 1 auto-fixed (formatting)
**Impact on plan:** None. Standard pre-commit reformatting.

## Verification Results

All 4 verification criteria passed:

1. `SELECT COUNT(*) FROM dim_feature_selection_asset` = **10,716** (> 0)
2. `SELECT DISTINCT tier FROM dim_feature_selection_asset` = **['asset_specific']**
3. `SELECT COUNT(*) FROM dim_feature_selection` = **205** (same as before run -- no TRUNCATE damage)
4. Asset 1 has 144 asset-specific rows; asset 2 has 105 rows -- each asset's per-asset count differs from 401 (global) confirming different feature sets

## Next Phase Readiness

- Phase 98-03 (cross-asset CTF composites): ctf_composites table exists (created in 98-01 migration), ready
- Phase 98-04 (lead-lag IC matrix): lead_lag_ic table exists, ready
- Phase 99 (backtest expansion): CTF features in features table for 1D; per-asset selection for downstream consumers
- Phase 100 (ML): dim_feature_selection_asset available for per-asset feature routing in ML models

---
*Phase: 98-ctf-feature-graduation*
*Completed: 2026-03-31*
