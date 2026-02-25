---
phase: 42-strategy-bake-off
plan: "03"
subsystem: backtests
tags: [composite-scoring, sensitivity-analysis, v1-gates, min-max-normalization, weighting-schemes, ranking-robustness, strategy-selection, bakeoff]

# Dependency graph
requires:
  - phase: 42-02
    provides: 480 OOS rows in strategy_bakeoff_results (BTC/ETH 1D x 3 strategies x 12 cost scenarios x 2 CV methods)
  - phase: 38
    provides: PSR/DSR library for PSR column used in scoring
provides:
  - composite_scorer.py: compute_composite_score, rank_strategies, sensitivity_analysis, blend_signals, load_bakeoff_metrics, WEIGHT_SCHEMES, V1_GATES
  - run_bakeoff_scoring.py: CLI to run composite scoring pipeline with formatted console output
  - reports/bakeoff/composite_scores.csv: ranked strategies under all 4 weighting schemes
  - reports/bakeoff/sensitivity_analysis.csv: robustness rankings with n_times_top2 and robust flag
affects:
  - 42-04 (strategy selection uses these rankings and gate flags)
  - 42-05 (scorecard uses composite scores and sensitivity analysis)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Min-max normalization with inversion for 'lower=better' metrics (max_drawdown, turnover)"
    - "Neutral 0.5 normalization for single-strategy edge case (all norms identical)"
    - "Sensitivity analysis: rank under N schemes, count top-K appearances for robustness"

key-files:
  created:
    - src/ta_lab2/backtests/composite_scorer.py
    - src/ta_lab2/scripts/analysis/run_bakeoff_scoring.py
  modified: []

key-decisions:
  - "Min-max normalization over z-score: interpretable [0,1] range, no distributional assumption; handles small N (3-10 strategies)"
  - "max_drawdown_worst (most extreme fold) over max_drawdown_mean: single worst fold is what kills live accounts"
  - "NaN psr -> 0.0: strategies with insufficient OOS data get worst-case PSR, conservative"
  - "Robust threshold: >= 3 of 4 weighting schemes to be top-2; ensures robustness is not sensitivity to a single scheme"
  - "V1 gates flag but do not eliminate: composite score ranks all strategies; gate failures documented but ranking proceeds"
  - "reports/ is gitignored (generated output); CLI is committed, CSVs are ephemeral artifacts"

patterns-established:
  - "Composite scorer pattern: normalize -> weight -> rank -> sensitivity with 4-scheme robustness check"
  - "_FALLBACK_COST_SCENARIOS: auto-resolve baseline if preferred scenario not in DB"
  - "parents[4] for project root from src/ta_lab2/scripts/analysis/ depth"

# Metrics
duration: 5min
completed: 2026-02-25
---

# Phase 42 Plan 03: Composite Scoring Summary

**Min-max composite scorer with 4-scheme sensitivity analysis: ema_trend(17,77) and ema_trend(21,50) are robust top-2 under 4/4 and 3/4 weighting schemes; no strategies pass both V1 gates (Sharpe>=1.0 AND MaxDD<=15%)**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-25T02:39:44Z
- **Completed:** 2026-02-25T02:45:00Z
- **Tasks:** 2/2
- **Files modified:** 2 created

## Accomplishments

- `composite_scorer.py` built with all required exports: `compute_composite_score` (min-max norm + weighted blend), `apply_v1_gates` (Sharpe >= 1.0, MaxDD <= 15%), `rank_strategies`, `sensitivity_analysis` (4 schemes, n_times_top2, robust flag), `blend_signals` (majority-vote ensemble), `load_bakeoff_metrics` (DB query with fallback scenario resolution)
- 4 weighting schemes: balanced (30/30/25/15), risk_focus (20/45/25/10), quality_focus (35/20/35/10), low_cost (30/25/20/25) for sharpe/drawdown/psr/turnover
- `run_bakeoff_scoring.py` CLI executed on BTC 1D purged_kfold: formatted V1 gate summary, per-scheme ranked tables, sensitivity table, robust top-2 summary
- Key finding confirmed: ema_trend(17,77) ranks #1 in all 4 schemes (robust), ema_trend(21,50) ranks top-2 in 3/4 schemes (robust). No strategy passes both V1 gates. Ensemble/blending path needed per 42-CONTEXT.md.

## Task Commits

1. **Task 1: Build composite_scorer.py** - `d1950ad2` (feat)
2. **Task 2: Build run_bakeoff_scoring CLI and execute scoring** - `96a52824` (feat)

## Files Created/Modified

- `src/ta_lab2/backtests/composite_scorer.py` - Composite scoring module: WEIGHT_SCHEMES, V1_GATES, compute_composite_score, apply_v1_gates, rank_strategies, sensitivity_analysis, blend_signals, load_bakeoff_metrics
- `src/ta_lab2/scripts/analysis/run_bakeoff_scoring.py` - CLI: argparse, DB loading, formatted tables, saves composite_scores.csv + sensitivity_analysis.csv

## Decisions Made

1. **Min-max normalization over z-score**: Produces interpretable [0,1] scores, makes no distributional assumption, handles small N (3-10 strategies per query). Z-score would compress all strategies to similar range when N is small.

2. **max_drawdown_worst as the drawdown metric**: Uses the single most extreme fold drawdown rather than the mean. Rationale: a single catastrophic fold is what destroys live accounts; mean drawdown understates tail risk.

3. **NaN PSR -> 0.0**: Strategies with insufficient OOS data (<30 bars) get PSR=0.0 for scoring. Conservative treatment; doesn't reward absence of data.

4. **Robust = top-2 in >= 3 of 4 schemes**: Threshold set at 3/4 to mean "mostly consistent ranking" while allowing one outlier scheme. 4/4 would be too strict; 2/4 would be too loose.

5. **V1 gates flag but don't eliminate**: All strategies receive composite scores regardless of gate failures. Gate failures are documented in the output. This allows selecting "best available" even when no strategy meets both gates, as documented in 42-CONTEXT.md.

6. **reports/ gitignored**: The `reports/bakeoff/` directory is gitignored (generated output). The CLI is committed; CSVs are ephemeral artifacts regenerated on each run.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed _PROJECT_ROOT path calculation (parents index)**

- **Found during:** Task 2 (first CLI execution)
- **Issue:** `Path(__file__).resolve().parents[5]` computed project root as `C:\Users\asafi\Downloads` instead of `C:\Users\asafi\Downloads\ta_lab2`. The file is 5 directories deep from the project root (ta_lab2/src/ta_lab2/scripts/analysis/), not 6.
- **Fix:** Changed `parents[5]` to `parents[4]`
- **Files modified:** src/ta_lab2/scripts/analysis/run_bakeoff_scoring.py
- **Verification:** Output path showed `C:\Users\asafi\Downloads\ta_lab2\reports\bakeoff\composite_scores.csv`
- **Committed in:** 96a52824

---

**Total deviations:** 1 auto-fixed (Rule 3 - Blocking)
**Impact on plan:** Without fix, CSVs saved to wrong directory. No scope creep.

## Issues Encountered

- ruff-format + mixed-line-ending hooks reformatted both new files (Windows CRLF vs LF). Standard pattern: hook modifies file, re-stage, commit succeeds second time.

## Next Phase Readiness

- **Composite scores ready for 42-04 strategy selection**: composite_scores.csv and sensitivity_analysis.csv generated; DB not written (in-memory only, per plan)
- **Key selection finding**: ema_trend with (17,77) params is robustly top-1 in all 4 schemes. ema_trend(21,50) is robust top-2 in 3/4. Both fail the MaxDD gate (70-75% drawdown).
- **V1 gate outcome**: No strategy passes both gates; this confirms the ensemble/blending path documented in 42-CONTEXT.md is the correct next step.
- **blend_signals() ready**: Majority-vote ensemble function implemented for Plan 42-04 if ensemble path is pursued.
- **No blockers for 42-04**: Strategy selection can proceed from these scores; scorecard needs the sensitivity CSV which is now generated.

---
*Phase: 42-strategy-bake-off*
*Completed: 2026-02-25*
