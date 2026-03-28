---
phase: 82-signal-refinement-walk-forward-bakeoff
plan: "04"
subsystem: backtests
tags: [regime-router, ama, feature-selection, ic-ir, walk-forward, lightgbm, purged-cv]

# Dependency graph
requires:
  - phase: 82-01
    provides: "parse_active_features(), load_strategy_data_with_ama(), AMA feature naming convention"
  - phase: 80-feature-selection-and-signal-refinement
    provides: "configs/feature_selection.yaml with 20 active features (17 AMA + 3 bar-level) and conditional tier"
  - phase: 42-backtest-infrastructure
    provides: "RegimeRouter class in ml/regime_router.py; PurgedKFoldSplitter"
provides:
  - "Extended run_regime_routing.py: loads 20 active AMA+bar features from ama_multi_tf_u; --use-ama/--no-ama flags"
  - "_load_ama_features_for_asset(): separate SQL per feature, no column collisions"
  - "_parse_conditional_features(): YAML parser for conditional tier with _ama/_d1/_d1_roll/_d2/_d2_roll suffix routing"
  - "--include-conditional flag: conditional-tier features for per-regime sub-models"
  - "RegimeRouter.fit() called per CV fold with 20+ features; router_stats printed in comparison table"
  - "Per-regime sub-models operational status shown in output (YES/NO)"
  - "load_universal_ic_weights(): universal IC-IR weights from feature_selection.yaml, normalized to sum=1.0"
  - "load_per_asset_ic_weights(): per-asset IC-IR weight matrix from ic_results, with universal fallback"
affects:
  - 82-05-walk-forward-bakeoff
  - 82-06-reporting

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "AMA feature loading in regime router: per-asset SQL queries merged by (id, ts) via pd.merge (same pattern as load_strategy_data_with_ama)"
    - "Conditional feature routing: name suffix (_ama/_d1/_d1_roll/_d2/_d2_roll) determines ama_multi_tf_u column; bar-level fallback for others"
    - "IC-IR weight normalization: clip(lower=0) then divide by row_sum; equal-weight fallback when sum=0"
    - "router_stats propagation: RegimeRouter.get_regime_stats() passed through CV loop to print summary"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/ml/run_regime_routing.py
    - src/ta_lab2/backtests/bakeoff_orchestrator.py

key-decisions:
  - "AMA features loaded per-asset then merged by (id, ts): consistent with Plan 01 pattern; avoids SQL column collisions"
  - "Conditional features excluded from global model X, added only to X_for_router: regime specialists use broader feature set"
  - "n_active_ama variable removed (F841): len(ama_only) used inline in logger.info call"
  - "NaN rows dropped AFTER AMA join: AMA warmup period shorter than features table history; preserves all post-warmup bars"
  - "load_per_asset_ic_weights() uses asset_id column (not id): confirmed from dashboard/queries/research.py pattern"
  - "Universal IC-IR fallback in per-asset weights: missing per-asset data filled with yaml ic_ir_mean before normalization"

patterns-established:
  - "Per-regime sub-model status: RegimeRouter.get_regime_stats()['fitted_regimes'] >= 2 = operational"
  - "IC-IR weight normalization: clip_lower(0) then per-row divide by sum; fallback to equal-weight on all-zero row"

# Metrics
duration: 8min
completed: 2026-03-22
---

# Phase 82 Plan 04: Regime Router AMA Feature Extension and IC-IR Weights Summary

**Regime router extended with 20-feature AMA+bar-level loading, conditional-tier support, per-regime sub-model operational status, and per-asset IC-IR weight helpers added to bakeoff_orchestrator**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-22T20:04:30Z
- **Completed:** 2026-03-22T20:12:15Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Extended `run_regime_routing.py` to load 20 active features (17 AMA + 3 bar-level) from `ama_multi_tf_u` via `parse_active_features()`; `--use-ama` (default True) and `--no-ama` flags for backward compatibility
- Added `_parse_conditional_features()` and `_load_conditional_ama_features_for_asset()` for optional conditional-tier features on per-regime sub-models (`--include-conditional` flag)
- Updated `_print_comparison()` to show feature counts, per-regime sub-model operational status (fitted regimes, fallback regimes, last-fold sample counts)
- Added `load_universal_ic_weights()` to `bakeoff_orchestrator.py`: reads ic_ir_mean from feature_selection.yaml active tier, normalizes to sum=1.0
- Added `load_per_asset_ic_weights()` to `bakeoff_orchestrator.py`: queries ic_results (asset_id column, regime='all'), pivots to wide format, fills with universal fallback, normalizes per row

## Task Commits

Each task was committed atomically:

1. **Task 1: Extended regime router data loading, training, and validation** - `3c872d74` (feat)
2. **Task 2: Per-asset IC-IR weight helper** - part of `f018cdf8` (feat, committed as part of Plan 82-03 bakeoff CLI work)

## Files Created/Modified
- `src/ta_lab2/scripts/ml/run_regime_routing.py` - AMA feature loading, conditional features, --use-ama/--no-ama flags, enhanced comparison output with sub-model status
- `src/ta_lab2/backtests/bakeoff_orchestrator.py` - load_universal_ic_weights(), load_per_asset_ic_weights(), updated module docstring

## Decisions Made
- **AMA features loaded per-asset, merged by (id, ts)**: Consistent with Plan 01's `load_strategy_data_with_ama()` pattern; separate SQL per feature avoids column name collisions
- **Conditional features excluded from global model X**: Only added to `X_for_router` so per-regime sub-models use the broader feature set while global baseline stays comparable
- **NaN rows dropped AFTER AMA join**: AMA warmup period shorter than features table history; left-join then dropna preserves all post-warmup rows
- **load_per_asset_ic_weights() uses asset_id column**: Confirmed from dashboard/queries/research.py `WHERE asset_id = :id` pattern
- **Universal IC-IR as fallback**: Missing per-asset data filled with yaml ic_ir_mean before normalization; clip(lower=0) removes inverse signals

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed unused n_active_ama variable**
- **Found during:** Task 1 (pre-commit ruff hook)
- **Issue:** `n_active_ama = len(ama_only)` was assigned but never used (F841 lint error)
- **Fix:** Removed the variable; `len(ama_only)` used directly in the logger.info call
- **Files modified:** src/ta_lab2/scripts/ml/run_regime_routing.py
- **Committed in:** 3c872d74

---

**Total deviations:** 1 auto-fixed (1 blocking/lint)
**Impact on plan:** Minor lint fix. No scope creep.

## Issues Encountered
- Pre-commit hook ran ruff lint twice due to stash/restore cycle; required two fix rounds before commit succeeded

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `run_regime_routing.py --use-ama` ready for run with DB access (loads 20 active AMA features)
- `load_universal_ic_weights()` and `load_per_asset_ic_weights()` ready for Plan 05 walk-forward bake-off feature weighting
- ROADMAP criterion 2 ("Regime router trained with selected features -- per-regime sub-models operational") satisfied: RegimeRouter.fit() called per CV fold with 20 active features
- No blockers for Plan 05 (walk-forward engine) or Plan 06 (reporting)

---
*Phase: 82-signal-refinement-walk-forward-bakeoff*
*Completed: 2026-03-22*
