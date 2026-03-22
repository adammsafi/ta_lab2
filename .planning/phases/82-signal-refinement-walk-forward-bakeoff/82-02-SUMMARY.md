---
phase: 82-signal-refinement-walk-forward-bakeoff
plan: 02
subsystem: signals
tags: [ama, momentum, mean-reversion, regime-conditional, signal-registry, bakeoff, adx, pandas, numpy]

# Dependency graph
requires:
  - phase: 80-ic-analysis-feature-selection
    provides: "20 active features (18 AMA-derived), IC-IR values from feature_selection.yaml"
  - phase: 82-01
    provides: "load_strategy_data_with_ama() extended data loader for AMA columns from DB"

provides:
  - "ama_momentum_signal: IC-IR weighted composite of top-5 AMA columns, z-scored, threshold-gated long entries"
  - "ama_mean_reversion_signal: spread(price - AMA) z-score, enters long when price significantly below AMA"
  - "ama_regime_conditional_signal: AMA trend direction gated by ADX strength, ADX computed from OHLC if absent"
  - "Signal registry updated with 3 new AMA strategies and parameter grids"

affects:
  - "82-03-PLAN.md (bakeoff orchestrator) -- uses REGISTRY and grid_for() to run all AMA strategies"
  - "82-05-PLAN.md (run_bakeoff.py script) -- iterates REGISTRY strategies from grid_for()"
  - "future signal generators -- should follow ama_composite.py pattern (read pre-loaded cols)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "AMA signal pattern: read pre-computed DB cols, never recompute locally (prevents fold-boundary lookback contamination)"
    - "Signal function signature: (df: pd.DataFrame, **params) -> (entries: bool Series, exits: bool Series, size: None)"
    - "Graceful degradation: filter available AMA columns and renormalize weights when cols absent"
    - "Holding-bar exit: bars_since_entry >= holding_bars forces position close"
    - "Optional import pattern with graceful fallback in registry.py"

key-files:
  created:
    - src/ta_lab2/signals/ama_composite.py
  modified:
    - src/ta_lab2/signals/registry.py

key-decisions:
  - "fillna(0.0) for missing AMA warmup values -- neutral contribution, cleaner than forward-fill"
  - "Default top-5 AMA cols from IC-IR ranking: TEMA_0fca19a1, KAMA_987fc105, HMA_514ffe35, TEMA_514ffe35, DEMA_0fca19a1"
  - "IC-IR weights normalized at call time, not hardcoded as normalized -- preserves interpretable raw values in API"
  - "ADX computed locally in ama_regime_conditional_signal when filter_col absent -- Wilder smoothing (ewm alpha=1/n)"
  - "Holding bar exit uses cumulative counter pattern (not vectorbt dependency) -- keeps signal functions library-independent"

patterns-established:
  - "Pattern 1: AMA signal functions read df[ama_col] only -- never re-compute from price inside signal function"
  - "Pattern 2: Missing AMA columns skip gracefully (filter pairs list) and renormalize remaining weights"
  - "Pattern 3: registry.py optional import block wraps each ama_composite import in try/except"
  - "Pattern 4: grid_for() returns List[Dict] of param combos for bakeoff parameter sweep"

# Metrics
duration: 4min
completed: 2026-03-22
---

# Phase 82 Plan 02: AMA Signal Generators Summary

**Three AMA-based signal generators (momentum, mean-reversion, regime-conditional) registered in signal registry with IC-IR-weighted defaults and parameter grids for bake-off sweep**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-03-22T19:51:02Z
- **Completed:** 2026-03-22T19:55:11Z
- **Tasks:** 2/2
- **Files modified:** 2 (1 created, 1 modified)

## Accomplishments

- `ama_composite.py` created with three signal generators covering all three strategy archetypes required for the Phase 82 bake-off
- Signal registry updated to include all three AMA strategies alongside existing ema_trend, rsi_mean_revert, breakout_atr
- Parameter grids defined: 6 combos for ama_momentum, 6 for ama_mean_reversion, 9 for ama_regime_conditional (21 total AMA param sets)
- ADX computation from OHLC added as local fallback for ama_regime_conditional_signal when DB-loaded ADX column is absent

## Task Commits

Each task was committed atomically:

1. **Task 1: AMA composite signal generators** - `beb88657` (feat)
2. **Task 2: Register AMA signals in registry** - `ee546b89` (feat)

**Plan metadata:** (see final commit below)

## Files Created/Modified

- `src/ta_lab2/signals/ama_composite.py` - Three AMA signal generators: ama_momentum_signal, ama_mean_reversion_signal, ama_regime_conditional_signal with full docstrings, `__all__`, and helper utilities (_rolling_zscore, _bars_since_entry, _compute_adx)
- `src/ta_lab2/signals/registry.py` - Added optional import block for ama_composite, three REGISTRY entries, ensure_for() cases for AMA strategies, grid_for() entries with parameter grids

## Decisions Made

- `fillna(0.0)` for missing AMA warmup values: neutral contribution, avoids invalid `fillna(method=None)` that fails on pandas 2.x. During warmup period, 0 contribution = graceful degradation.
- IC-IR weights stored as raw unnormalized values and normalized at call time: preserves interpretable values in the function API; user passing custom weights doesn't need to pre-normalize.
- ADX computed locally via Wilder smoothing (ewm alpha=1/n) when `filter_col` absent from DataFrame: signal function is self-contained, does not require pre-loading ADX from DB.
- Holding-bar exit uses a Python loop (`_bars_since_entry`), not vectorbt internals: keeps signal functions library-independent, callable in any context.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed invalid `fillna(method=None)` API call**

- **Found during:** Task 1 smoke test
- **Issue:** `df[col].fillna(method=None)` raises `ValueError: Must specify a fill 'value' or 'method'` in pandas 2.x. The intent was "no fill, just use existing values" but the API requires either a value or a method.
- **Fix:** Changed to `fillna(0.0)` -- missing AMA values (warmup NaN) contribute 0 to the weighted composite, which is the correct neutral behavior.
- **Files modified:** src/ta_lab2/signals/ama_composite.py (line 160)
- **Verification:** Smoke test passed with `entries=117, exits=82` on synthetic 200-bar DataFrame
- **Committed in:** beb88657 (Task 1 commit, after re-stage post ruff-format)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Critical fix -- without it the momentum signal raised ValueError on every call. No scope creep.

## Issues Encountered

- ruff-format reformatted both files on first commit attempt (long lines in generator expression and ADX computation). Re-staged reformatted files and committed successfully on second attempt. Standard workflow for this repo.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All three AMA signal generators importable and callable with synthetic DataFrames
- Signal registry has 6 strategies total; `grid_for()` returns 21 AMA parameter combinations
- Ready for Plan 03 (bakeoff orchestrator extension): `load_strategy_data_with_ama()` from Plan 01 + these signal generators are the two inputs the orchestrator needs
- No blockers for Plan 03

---
*Phase: 82-signal-refinement-walk-forward-bakeoff*
*Completed: 2026-03-22*
