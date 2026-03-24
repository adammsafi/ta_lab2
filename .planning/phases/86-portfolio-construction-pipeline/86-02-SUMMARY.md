---
phase: 86-portfolio-construction-pipeline
plan: 02
subsystem: portfolio
tags: [black-litterman, ic-ir, position-sizing, garch, target-vol, paper-executor]

# Dependency graph
requires:
  - phase: 80-feature-selection
    provides: "ic_results table with per-asset IC-IR data; load_per_asset_ic_weights() function"
  - phase: 81-garch-vol-forecasting
    provides: "garch_blend.get_blended_vol() for GARCH conditional vol lookup"
  - phase: 82-bakeoff-orchestration
    provides: "bakeoff_orchestrator.load_per_asset_ic_weights, parse_active_features"
  - phase: 86-01
    provides: "dim_executor_config.target_annual_vol column (migration), stop calibration"
provides:
  - "BLAllocationBuilder with per-asset IC-IR dispatch via pd.DataFrame ic_ir parameter"
  - "PositionSizer target_vol sizing mode with GARCH vol annualization via sqrt(252)"
  - "refresh_portfolio_allocations.py loading real IC-IR from ic_results (no zero stub)"
  - "paper_executor.py wired to call get_blended_vol() and pass garch_vol to PositionSizer"
affects:
  - "86-03: portfolio integration tests should cover DataFrame ic_ir path and target_vol mode"
  - "87: signal_scores real values deferred (TODO in refresh script)"
  - "paper_executor: live target_vol sizing active once target_annual_vol set in DB"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ic_ir Union[Series, DataFrame] dispatch: private _per_asset_composite helper + isinstance check in each public method"
    - "GARCH vol kwarg pattern: paper_executor fetches vol, passes as kwarg, PositionSizer receives via **kwargs -- no import of garch_blend in position_sizer"
    - "Cross-sectional z-score applied once across all assets (not per-asset) to avoid degenerate composites"
    - "Uniform signal_scores=1.0 as default when real feature values unavailable (deferred to Phase 87)"

key-files:
  created: []
  modified:
    - "src/ta_lab2/portfolio/black_litterman.py"
    - "src/ta_lab2/executor/position_sizer.py"
    - "src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py"
    - "src/ta_lab2/executor/paper_executor.py"

key-decisions:
  - "Per-asset IC-IR path: _per_asset_composite() reindexes ic_ir_matrix to signal_scores shape; missing assets get column-mean fallback; IC-IR clipped to >=0"
  - "Single cross-sectional z-score for DataFrame path (not per-asset): avoids degenerate scores when a single asset's composite is constant"
  - "garch_vol NOT imported in position_sizer.py: passed as **kwargs by paper_executor, no circular dependency"
  - "GARCH daily vol annualized via sqrt(252) in target_vol branch: forgetting annualization causes ~15x oversizing (research pitfall 2)"
  - "Uniform signal_scores=1.0 for Phase 86: IC-IR differences alone drive view heterogeneity; TODO(Phase 87) for real feature-based scores"
  - "BL fallback to prior-only: when ic_results is empty for given TF, ic_ir=Series({'rsi': 0.0}) triggers empty views -> prior-only EfficientFrontier"
  - "ruff-format reformatted black_litterman.py on first commit (long-arg function calls): re-staged and committed clean (standard pattern)"

patterns-established:
  - "Union type dispatch in BL: isinstance(ic_ir, pd.DataFrame) check in run(), signals_to_mu(), build_views()"
  - "Graceful GARCH fallback: target_vol with no garch_vol logs info and uses fixed_fraction; near-zero vol logs warning and uses fixed_fraction"

# Metrics
duration: 8min
completed: 2026-03-24
---

# Phase 86 Plan 02: IC-IR + GARCH Target-Vol Sizing Summary

**Per-asset IC-IR from ic_results wired into Black-Litterman views via DataFrame dispatch; target_vol sizing mode using annualized GARCH vol added to PositionSizer and paper_executor**

## Performance

- **Duration:** 8 min
- **Started:** 2026-03-24T07:26:26Z
- **Completed:** 2026-03-24T07:34:18Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- BLAllocationBuilder now accepts ic_ir as pd.DataFrame (per-asset IC-IR matrix): `_per_asset_composite()` helper computes weighted composites, single cross-sectional z-score across all assets, per-asset mean IC-IR used as view confidence
- refresh_portfolio_allocations.py replaces zero-stub (`ic_ir = pd.Series({'rsi': 0.0})`) with real `load_per_asset_ic_weights()` call; uniform signal_scores=1.0 as default with Phase 87 TODO for real feature values; graceful fallback to prior-only when ic_results is empty
- PositionSizer adds `target_vol` as 4th sizing mode: daily GARCH vol annualized via `sqrt(252)`, vol_scalar = target_annual_vol / current_annual_vol, hard cap applied; graceful fallback to fixed_fraction when GARCH unavailable or near-zero vol
- paper_executor._process_asset_signal() calls `get_blended_vol()` when `target_annual_vol` is configured and passes result as `garch_vol` kwarg to `compute_target_position()` -- target_vol mode fully live, not dead code

## Task Commits

Each task was committed atomically:

1. **Task 1: Per-asset IC-IR in BLAllocationBuilder + refresh script (uniform signal_scores)** - `49b1c9d9` (feat)
2. **Task 2: GARCH target-vol sizing mode in PositionSizer + paper_executor wiring** - `ec0df580` (feat)

**Plan metadata:** `[see docs commit below]` (docs: complete plan)

## Files Created/Modified
- `src/ta_lab2/portfolio/black_litterman.py` - Added `_per_asset_composite()` helper; updated `signals_to_mu()`, `build_views()`, `run()` to accept `Union[pd.Series, pd.DataFrame]` for ic_ir; updated module + class docstrings
- `src/ta_lab2/executor/position_sizer.py` - Added `target_annual_vol: float | None = None` to ExecutorConfig; added `target_vol` branch in `compute_target_position()`; added `**kwargs` to module wrapper and static method
- `src/ta_lab2/scripts/portfolio/refresh_portfolio_allocations.py` - Replaced zero-stub BL section with `load_per_asset_ic_weights()` + `parse_active_features()` + uniform signal_scores + graceful fallback
- `src/ta_lab2/executor/paper_executor.py` - Added `get_blended_vol` import; added GARCH vol fetching in `_process_asset_signal()`; passes `garch_vol` kwarg to `compute_target_position()`

## Decisions Made
- `_per_asset_composite()`: reindexes ic_ir_matrix to signal_scores shape (missing columns -> 0, missing assets -> column-mean fallback). IC-IR clipped to >=0 before weighting.
- Cross-sectional z-score applied once across all assets in per-asset path: per-asset z-score would be degenerate (single value = 0). Single call is correct.
- `garch_vol` NOT imported inside `position_sizer.py`: passed as **kwargs from paper_executor. No circular dependency, follows project pattern of no DB construction in static methods.
- GARCH daily vol annualized via `sqrt(252)` in target_vol branch: research explicitly flagged ~15x oversizing as Pitfall 2 if annualization is forgotten.
- Uniform `signal_scores=1.0`: IC-IR row differences alone drive view heterogeneity for Phase 86. Real feature values deferred to Phase 87 via TODO comment.
- BL fallback: when ic_results empty for TF, stub Series path triggers empty views -> prior-only EfficientFrontier optimization (existing code path, unchanged).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- ruff-format reformatted `black_litterman.py` on first commit (multi-arg function calls). Re-staged and committed clean (standard pattern per STATE.md decisions).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- BL pipeline is now driven by real per-asset IC-IR from ic_results (Phase 80 roadmap criterion 1 satisfied)
- target_vol mode is fully live once `target_annual_vol` is set in `dim_executor_config` (Phase 86 plan 01 migration)
- Phase 86 plan 03 (integration tests) can test both the DataFrame ic_ir path and target_vol sizing mode
- Phase 87 can wire real signal_scores (feature + AMA values) to complete the BL signal pipeline -- TODO comment placed in refresh_portfolio_allocations.py

---
*Phase: 86-portfolio-construction-pipeline*
*Completed: 2026-03-24*
