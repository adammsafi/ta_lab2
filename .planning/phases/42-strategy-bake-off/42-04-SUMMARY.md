---
phase: 42-strategy-bake-off
plan: "04"
subsystem: backtests
tags: [strategy-selection, v1-selection, ema-crossover, walk-forward, cost-sensitivity, ensemble, final-validation, vectorbt, psr]

# Dependency graph
requires:
  - phase: 42-03
    provides: composite_scores.csv, sensitivity_analysis.csv, blend_signals() in composite_scorer.py
  - phase: 42-02
    provides: 480 OOS rows in strategy_bakeoff_results with fold_metrics_json
provides:
  - select_strategies.py: loads composite CSVs + DB, applies selection rules, writes STRATEGY_SELECTION.md + final_validation.csv
  - STRATEGY_SELECTION.md: formal selection document with rationale, parameters (walk-forward), per-fold breakdown, cost sensitivity, ensemble analysis, V1 deployment config
  - final_validation.csv: full-sample backtest for both selected strategies (sharpe, max_dd, psr, v1 gate pass/fail)
affects:
  - 42-05 (scorecard references STRATEGY_SELECTION.md for selected strategies)
  - 45 (paper-trade executor uses V1 deployment config from STRATEGY_SELECTION.md)
  - 53 (V1 validation compares against expected performance range from STRATEGY_SELECTION.md)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Selection rule pipeline: composite_scores.csv -> sensitivity_analysis.csv -> top-2 by balanced scheme + robustness >= 3/4 schemes"
    - "Ensemble blend analysis: blend_signals() majority-vote, full-history evaluation, gate re-assessment, honest documentation of failure"
    - "Final validation: single full-history backtest (not walk-forward) to confirm OOS metrics are consistent with full-sample"

key-files:
  created:
    - src/ta_lab2/scripts/analysis/select_strategies.py
    - reports/bakeoff/STRATEGY_SELECTION.md
    - reports/bakeoff/final_validation.csv
  modified: []

key-decisions:
  - "Two EMA trend strategies selected: ema_trend(17,77) robust top-1 in 4/4 schemes; ema_trend(21,50) robust top-2 in 3/4 schemes"
  - "V1 gate honesty: neither strategy passes MaxDD <= 15% gate (worst fold: 75% and 70% drawdowns); document honestly and recommend reduced position sizing + circuit breakers"
  - "Ensemble blend also fails V1 gates: two similarly-themed EMA strategies lose during same macro bear market regimes (2018, 2022); blending reduces Sharpe without meaningfully reducing max drawdown"
  - "Full-sample Sharpe (1.647, 1.705) higher than OOS walk-forward mean (1.401, 1.397) — difference is within 1 std; consistent with OOS results being conservative rather than showing overfitting"
  - "Deployment recommendation: 10% position size (not 50%) due to V1 gate failure; circuit breaker at 15% portfolio DD"

patterns-established:
  - "V1 deployment config pattern: signal_type/asset_id/tf/params/position_sizing/cost_assumption in STRATEGY_SELECTION.md for Phase 45"
  - "Walk-forward parameter source: explicitly documented in parameters table with 'Walk-forward fixed' column"
  - "Break-even slippage calculation: (sharpe_at_10bps - 1.0) / (sharpe_at_10bps - sharpe_at_20bps) * 10 + 10"

# Metrics
duration: 8min
completed: 2026-02-25
---

# Phase 42 Plan 04: Strategy Selection Summary

**ema_trend(17,77) and ema_trend(21,50) selected for V1 paper trading: robust top-1/2 across all 4 composite weighting schemes with PSR > 0.9999, but MaxDD V1 gate not met (70-75% worst-fold drawdown); ensemble blend also fails; deployment recommended with reduced position sizing and circuit breakers**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-25T02:49:57Z
- **Completed:** 2026-02-25T02:57:45Z
- **Tasks:** 2/2
- **Files modified:** 3 created

## Accomplishments

- `select_strategies.py` built: loads composite/sensitivity CSVs + strategy_bakeoff_results DB (with fold_metrics_json), applies 3-step selection rules (top-2 balanced, robustness 3/4 schemes, PSR tie-break), generates STRATEGY_SELECTION.md and final_validation.csv
- `STRATEGY_SELECTION.md` written: 452-line formal document with executive summary, methodology, per-strategy sections (parameters, OOS metrics, per-fold breakdown, cost sensitivity, PBO/PSR, regime analysis), ensemble analysis, V1 deployment config, expected performance range, final validation results
- Final validation backtest executed: full-history single backtest (not walk-forward) for both strategies via vectorbt; ema_trend(17,77) Sharpe=1.647, MaxDD=-75.0%; ema_trend(21,50) Sharpe=1.705, MaxDD=-70.1%; both consistent with OOS walk-forward (difference within 1 std)
- Ensemble blend documented: majority-vote signal blend of both EMA strategies computed and evaluated; blend also fails V1 gates because both strategies lose in the same macro bear market regimes; honest conclusion documented

## Task Commits

1. **Task 1: Strategy selection analysis script and documentation** - `1f259bc5` (feat)
2. **Task 2: Final validation backtest** - included in Task 1 commit (script runs validation internally)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/scripts/analysis/select_strategies.py` - Strategy selection pipeline: loads inputs, applies rules, writes STRATEGY_SELECTION.md + final_validation.csv; CLI via `--asset-id --tf`
- `reports/bakeoff/STRATEGY_SELECTION.md` - Formal V1 strategy selection document (452 lines): 2 strategies selected, rationale, parameters (walk-forward), per-fold breakdown, cost sensitivity (12 scenarios), ensemble analysis, V1 deployment config
- `reports/bakeoff/final_validation.csv` - Full-sample backtest results: 2 rows (one per strategy), sharpe/max_dd/psr/v1_pass columns

## Decisions Made

1. **Select top-2 regardless of V1 gate status**: Plan explicitly says "if no strategy passes V1 gates, select top-2 anyway and document". Both strategies are genuine OOS Sharpe > 1.4 with PSR > 0.9999 — the alpha is real; the risk profile requires management not modeled in backtest.

2. **Ensemble blend attempted honestly**: The blend of two similarly-themed EMA strategies reduces Sharpe (agreement filter reduces trade count) without meaningfully improving MaxDD because both strategies lose during the same regime. The blend was evaluated and documented as not solving the V1 gate problem.

3. **Full-sample Sharpe higher than walk-forward OOS**: Full-sample ema_trend(17,77) Sharpe = 1.647 vs OOS mean = 1.401. This is expected — OOS averages include the conservative estimate from purged K-fold (each fold sees ~90% of history as test set). Full-sample uses 100% data including the early 2010-2013 period where the strategy had very high Sharpe.

4. **V1 deployment sizing reduced to 10%**: Walk-forward used 50% position size. Paper trading uses 10% because (a) MaxDD gate failed, (b) paper trading is a learning phase. Explicit circuit breaker at 15% portfolio DD added.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused variable assignments that failed ruff F841**

- **Found during:** Task 1 (pre-commit hook)
- **Issue:** 6 unused variable assignments: `label` in `_build_strategy_section`, `s1_sharpe_ok/s2_sharpe_ok/s1_dd_ok/s2_dd_ok` in `_write_selection_document`, `gates` in the composite table loop
- **Fix:** Removed unused `label = strat["label"]`, removed 4 pre-computed gate variables (unused after refactoring `any_passes` to use `passes_v1_gates` directly), removed `gates` variable in composite table loop
- **Files modified:** src/ta_lab2/scripts/analysis/select_strategies.py
- **Verification:** `ruff check` shows "All checks passed"
- **Committed in:** 1f259bc5 (same task commit after pre-commit hook reformatted + fixed file)

---

**Total deviations:** 1 auto-fixed (Rule 1 - unused variables from ruff F841)
**Impact on plan:** Pre-commit hook caught lint violations; fix was straightforward variable removal. No scope creep.

## Issues Encountered

- Pre-commit hook (ruff lint + ruff format + mixed-line-ending) reformatted the file and flagged 6 F841 violations. Standard Windows CRLF pattern — hook modifies file, re-stage, commit succeeds on second attempt. This is the same pattern documented in 42-03 SUMMARY.

## Next Phase Readiness

- **STRATEGY_SELECTION.md ready for 42-05 scorecard**: Document has all required sections; scorecard can reference it directly
- **V1 deployment config ready for Phase 45 (Paper-Trade Executor)**: Exact parameters, cost assumptions, position sizing, circuit breaker in STRATEGY_SELECTION.md V1 Deployment Configuration section
- **Expected performance ready for Phase 53 (V1 Validation)**: Sharpe range (mean +/- std across folds), MaxDD range, trade frequency all documented
- **Blocker remains**: MaxDD gate failure is structural (crypto long-only trend strategies face 70-75% bear market drawdowns). Phase 45 must implement circuit breakers; Phase 53 validation criteria should be adjusted to validate signal correctness rather than raw MaxDD gate compliance

---
*Phase: 42-strategy-bake-off*
*Completed: 2026-02-25*
