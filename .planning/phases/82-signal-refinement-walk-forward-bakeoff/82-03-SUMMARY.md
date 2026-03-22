---
phase: 82-signal-refinement-walk-forward-bakeoff
plan: "03"
subsystem: backtests
tags: [ama, expression-engine, yaml, bakeoff, multi-exchange, hyperliquid, kraken, ic-ir, walk-forward]

# Dependency graph
requires:
  - phase: 82-01
    provides: "COST_MATRIX_REGISTRY, load_strategy_data_with_ama, parse_active_features, experiment_name column"
  - phase: 82-02
    provides: "ama_momentum_signal, ama_mean_reversion_signal, ama_regime_conditional_signal in registry"
provides:
  - "configs/experiments/signals_phase82.yaml: 6 YAML experiments covering all 3 archetypes"
  - "_make_expression_signal(): factory that wraps expression engine into bakeoff signal function"
  - "_load_experiments_yaml(): loads YAML experiments into strategies dict"
  - "--exchange flag: selects kraken/hyperliquid/all cost matrix at runtime"
  - "--experiments-yaml flag: loads expression engine experiments from YAML into bakeoff run"
  - "--experiment-name flag: lineage tag stored in strategy_bakeoff_results.experiment_name"
  - "AMA param grids in _BAKEOFF_PARAM_GRIDS for all 3 AMA strategies"
  - "BakeoffOrchestrator.run(ama_features, experiment_name): extended signature"
  - "load_universal_ic_weights(): normalize IC-IR from feature_selection.yaml"
  - "load_per_asset_ic_weights(): per-asset IC-IR weights from ic_results with universal fallback"
affects:
  - 82-04-composite-scoring
  - 82-05-walk-forward-engine
  - 82-06-reporting

# Tech tracking
tech-stack:
  added: [PyYAML (already in deps, now also used in run_bakeoff.py)]
  patterns:
    - "_make_expression_signal() factory: wraps evaluate_expression() into (entries, exits, None) signal tuple"
    - "_AMA_STRATEGY_NAMES frozenset: O(1) membership test for AMA-strategy detection"
    - "YAML experiment -> signal function: expression + holding_bars list -> param grid of {holding_bars: hb} dicts"
    - "load_per_asset_ic_weights(): pivot(asset_id x feature) + per-row normalization + universal fallback"

key-files:
  created:
    - configs/experiments/signals_phase82.yaml
  modified:
    - src/ta_lab2/scripts/backtests/run_bakeoff.py
    - src/ta_lab2/backtests/bakeoff_orchestrator.py

key-decisions:
  - "Expression signal param grid = [{holding_bars: hb} for hb in holding_bars_list]: holding period is the only free param per expression experiment"
  - "AMA loader auto-detection: any AMA strategy OR experiments-yaml triggers load_strategy_data_with_ama -- unified logic, no per-strategy branching in main()"
  - "exchange=all concatenates both matrices into one list: orchestrator runs all 18 scenarios in a single sweep (no separate runs per exchange)"
  - "load_per_asset_ic_weights() in orchestrator (not run_bakeoff.py): keeps weight loading close to execution, available to Plan 05 per_asset_weight_fn"
  - "load_strategy_data_with_ama not re-imported in run_bakeoff.py: CLI delegates data loading to orchestrator via ama_features parameter"

patterns-established:
  - "Pattern: YAML experiment file -> signal function factory pattern (_make_expression_signal)"
  - "Pattern: --exchange flag -> COST_MATRIX_REGISTRY lookup -> cost_matrix in BakeoffConfig"

# Metrics
duration: 6min
completed: 2026-03-22
---

# Phase 82 Plan 03: YAML Experiments and Bakeoff CLI Extension Summary

**6 YAML expression engine experiments defined across 3 archetypes; run_bakeoff.py extended with --exchange, --experiments-yaml, --experiment-name flags; BakeoffOrchestrator.run() gains ama_features and experiment_name parameters; per-asset IC-IR weight loaders added to orchestrator**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-03-22T20:00:28Z
- **Completed:** 2026-03-22T20:09:06Z
- **Tasks:** 2/2
- **Files created/modified:** 3 (1 created, 2 modified)

## Accomplishments

- Created `configs/experiments/signals_phase82.yaml` with 6 expression engine experiments spanning all 3 archetypes:
  - Momentum: `ama_momentum_weighted_top5` (IC-IR weighted top-5 AMA + EMA smoother), `ama_kama_crossover` (fast-minus-slow KAMA spread)
  - Mean-reversion: `ama_kama_reversion_zscore` (close vs KAMA / 20-bar Std), `ama_hma_reversion_zscore` (close-HMA spread / 30-bar Std)
  - Regime-conditional: `ama_trend_direction_conditional` (DEMA delta * sign(close vs 20-MA)), `ama_multi_agreement` (TEMA/DEMA/HMA consensus [-1, +1])
- All 6 expressions validated via `validate_expression(expr, None)` before commit
- Extended `run_bakeoff.py` with `--exchange` (kraken/hyperliquid/all), `--experiments-yaml`, `--experiment-name` flags
- Added `_make_expression_signal()` factory and `_load_experiments_yaml()` loader for expression engine integration
- Added AMA param grids to `_BAKEOFF_PARAM_GRIDS` (3 grids x 3 params each = 9 AMA param sets)
- Auto-detection of AMA loader need: any `ama_*` strategy OR `--experiments-yaml` triggers `load_strategy_data_with_ama()`
- Extended `BakeoffOrchestrator.run()` with `ama_features` and `experiment_name` parameters (additive, backward-compatible)
- Added `load_universal_ic_weights()` and `load_per_asset_ic_weights()` to orchestrator for Plan 05 walk-forward weight computation

## Task Commits

Each task was committed atomically:

1. **Task 1: YAML expression engine experiments** - `5a7a8df5` (feat)
2. **Task 2: Extend bakeoff CLI and orchestrator** - `f018cdf8` (feat)

## Files Created/Modified

- `configs/experiments/signals_phase82.yaml` - 6 YAML experiments with expression syntax, archetypes, holding_bars sweeps
- `src/ta_lab2/scripts/backtests/run_bakeoff.py` - --exchange/--experiments-yaml/--experiment-name flags, AMA param grids, _make_expression_signal(), _load_experiments_yaml(), AMA loader auto-detection
- `src/ta_lab2/backtests/bakeoff_orchestrator.py` - BakeoffOrchestrator.run() ama_features + experiment_name params, load_universal_ic_weights(), load_per_asset_ic_weights()

## Decisions Made

- **Expression signal param grid = `[{holding_bars: hb}]`**: The holding period is the only free parameter for expression experiments; the expression itself encodes the signal formula. This creates clean param grids that map naturally to t1_series construction.
- **AMA loader auto-detection in main()**: Any AMA strategy name OR `--experiments-yaml` triggers `load_strategy_data_with_ama()`. Unified detection avoids per-strategy branching and ensures expression experiments (which reference AMA cols) always get the full DataFrame.
- **`exchange=all` concatenates matrices into one list**: Orchestrator runs all 18 scenarios in a single sweep rather than two separate runs. Simpler code, natural with the existing cost_matrix iteration loop.
- **`load_per_asset_ic_weights()` placed in bakeoff_orchestrator.py**: Co-locates weight loading with execution logic; Plan 05 can import it directly from the orchestrator module for `per_asset_weight_fn` callback without modifying run_bakeoff.py.
- **`load_strategy_data_with_ama` not re-imported in run_bakeoff.py**: The CLI delegates data loading to the orchestrator via the `ama_features` parameter. Cleaner separation of concerns; run_bakeoff.py only manages CLI argument parsing and strategy building.

## Deviations from Plan

### Auto-added Functionality

**1. [Rule 2 - Missing Critical] `load_universal_ic_weights()` and `load_per_asset_ic_weights()`**

- **Found during:** Task 2 implementation
- **Issue:** The plan's must-have truth states "Per-asset IC-IR weights loadable from ic_results for walk-forward weight computation". These functions were not in Plans 01 or 02 and are needed by Plan 05.
- **Fix:** Added both functions to bakeoff_orchestrator.py. `load_universal_ic_weights()` reads feature_selection.yaml IC-IR values and normalizes to sum=1. `load_per_asset_ic_weights()` queries ic_results, pivots to wide (asset_id x feature) DataFrame, normalizes per row, falls back to universal weights for missing per-asset data.
- **Files modified:** src/ta_lab2/backtests/bakeoff_orchestrator.py
- **Committed in:** f018cdf8

**Total deviations:** 1 auto-added (1 missing critical functionality).

## Verification Results

All dry-run checks passed:

```
# AMA momentum shows 3 param combos x 12 Kraken scenarios x 2 CV = 72 runs
python -m ta_lab2.scripts.backtests.run_bakeoff --dry-run --assets 1 --tf 1D --strategies ama_momentum
# PASS: 72 result rows, AMA loader enabled

# Hyperliquid: 6 scenarios
python -m ta_lab2.scripts.backtests.run_bakeoff --dry-run --assets 1 --tf 1D --exchange hyperliquid
# PASS: 6 HL scenarios shown

# All exchanges: 18 scenarios (12 Kraken + 6 HL)
python -m ta_lab2.scripts.backtests.run_bakeoff --dry-run --assets 1 --tf 1D --exchange all
# PASS: 18 scenarios shown

# Expression experiments: 6 experiments loaded from YAML
python -m ta_lab2.scripts.backtests.run_bakeoff --dry-run --assets 1 --tf 1D \
    --experiments-yaml configs/experiments/signals_phase82.yaml
# PASS: 12 strategies total (6 registry + 6 expressions)

# Backward compatibility
python -m ta_lab2.scripts.backtests.run_bakeoff --dry-run --assets 1 --tf 1D
# PASS: 6 strategies, 12 Kraken scenarios, identical to pre-plan behavior
```

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 6 expression engine experiments are runnable end-to-end via `--experiments-yaml`
- `load_per_asset_ic_weights()` ready for Plan 05 walk-forward weight computation
- `BakeoffOrchestrator.run(ama_features, experiment_name)` ready for Plan 05's `per_asset_weight_fn` callback addition (additive, no conflict)
- `--experiment-name` allows per-run lineage tagging in `strategy_bakeoff_results`
- No blockers for Plans 04-06

---
*Phase: 82-signal-refinement-walk-forward-bakeoff*
*Completed: 2026-03-22*
