---
phase: 55-feature-signal-evaluation
plan: "04"
subsystem: evaluation
tags: [rsi, adaptive-rsi, ic-analysis, walk-forward, a-b-comparison, spearman-ic, bakeoff]

# Dependency graph
requires:
  - phase: 55-01
    provides: cmc_ic_results with rsi_14 IC baseline for BTC/ETH 1D
provides:
  - Adaptive vs static RSI A/B comparison with IC and walk-forward Sharpe
  - reports/evaluation/adaptive_rsi_ic_comparison.csv (28 rows, 7 horizons x 2 assets x 2 return types)
  - reports/evaluation/adaptive_rsi_bakeoff.csv (5-fold expanding walk-forward BTC 1D)
  - reports/evaluation/adaptive_rsi_ab_comparison.md (formal report with decision)
  - generate_signals_rsi.py documented with A/B decision comment
affects:
  - Phase 55 plans 05+: signal evaluation for other signal types (EMA crossover, ATR breakout)
  - Future adaptive signal development: normalization approach has signal quality cost

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "IC comparison: use full-history window (largest n_obs) from cmc_ic_results as representative IC"
    - "Walk-forward bakeoff: expanding IS window, fixed OOS folds, IS-calibrated thresholds for adaptive variant"
    - "A/B winner policy: BOTH IC-IR majority AND walk-forward Sharpe required for adaptive to win"

key-files:
  created:
    - reports/evaluation/adaptive_rsi_ic_comparison.csv
    - reports/evaluation/adaptive_rsi_bakeoff.csv
    - reports/evaluation/adaptive_rsi_ab_comparison.md
  modified:
    - src/ta_lab2/scripts/signals/generate_signals_rsi.py

key-decisions:
  - "Static RSI retained as default: adaptive normalization compresses IC signal quality (0/14 IC-IR wins), failing dual-criterion policy"
  - "Walk-forward Sharpe advantage for adaptive (4/5 folds) driven by threshold shift 30/70 -> 44/66, not signal quality improvement"
  - "Both code paths preserved per policy; use_adaptive=False default unchanged with decision comment"
  - "A/B comparison uses full-history IC (single-window) vs per-fold-calibrated adaptive thresholds for fair comparison"

patterns-established:
  - "Dual-criterion evaluation: IC-IR + Sharpe both required; split decision defaults to status quo"
  - "Adaptive threshold shift effect: moving from extremes (30/70) to distribution-calibrated (44/66) dramatically increases trade frequency"

# Metrics
duration: 45min
completed: 2026-02-26
---

# Phase 55 Plan 04: Adaptive vs Static RSI A/B Comparison Summary

**Static RSI wins IC dimension (0/14 adaptive wins, mean |IC-IR| 0.51 vs 0.29); adaptive wins walk-forward Sharpe (4/5 folds); inconclusive by dual-criterion policy; static default retained in generate_signals_rsi.py**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-02-26T00:00:00Z
- **Completed:** 2026-02-26T00:45:00Z
- **Tasks:** 3/3
- **Files modified:** 1 (generate_signals_rsi.py) + 3 created (reports/evaluation/)

## Accomplishments

- Retrieved static RSI IC from cmc_ic_results (full-history rows, 5,612 obs BTC / 3,761 ETH) and computed adaptive RSI IC fresh for 7 horizons x 2 assets x 2 return types (28 comparisons)
- Run 5-fold expanding walk-forward bakeoff on BTC 1D with IS-calibrated adaptive thresholds vs fixed 30/70 static thresholds
- Determined winner (inconclusive/static) per dual-criterion policy and documented in code comment and formal report

## Task Commits

Each task was committed atomically:

1. **Task 1: IC comparison — static vs adaptive RSI** - artifacts in reports/evaluation/ (gitignored)
2. **Task 2: Walk-forward backtest Sharpe comparison + A/B report** - artifacts in reports/evaluation/ (gitignored)
3. **Task 3: Update generate_signals_rsi.py default based on winner** - `3e2a8cb6` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `reports/evaluation/adaptive_rsi_ic_comparison.csv` - 28 rows (7 horizons x 2 assets x 2 return types), static vs adaptive IC and IC-IR with winner column
- `reports/evaluation/adaptive_rsi_bakeoff.csv` - 5-fold OOS walk-forward results: static -0.649 vs adaptive -0.076 mean Sharpe; static -12.7% vs adaptive -18.5% mean MaxDD
- `reports/evaluation/adaptive_rsi_ab_comparison.md` - Formal A/B report with IC tables, backtest tables, decision section, and appendix
- `src/ta_lab2/scripts/signals/generate_signals_rsi.py` - Added 5-line decision comment block above `use_adaptive: bool = False` parameter

## Decisions Made

1. **IC comparison method:** Used largest-n_obs row from cmc_ic_results per (asset, horizon, return_type) as the representative static IC value (full-history window, same as 55-01 baseline sweep). This is the most statistically robust estimate.

2. **Adaptive RSI feature definition:** `(rsi_14 - rolling_P20) / (rolling_P80 - rolling_P20 + 1e-10)` with lookback=100. This normalizes RSI into a [0,1] range relative to its rolling distribution. Different from the raw RSI used in static comparison.

3. **Adaptive threshold approach for bakeoff:** IS-period mean of rolling lower/upper thresholds, applied as fixed thresholds to OOS period. This is the current implementation in generate_signals_rsi.py (global average mode). Per-bar dynamic thresholds would require make_signals enhancement.

4. **Winner determination: INCONCLUSIVE (static retained).** Per CONTEXT.md dual criterion:
   - IC-IR: static wins 14/14 comparisons (BTC and ETH, 7 horizons each). Mean |IC-IR|: 0.51 (static) vs 0.29 (adaptive). Condition: adaptive must win majority. NOT MET.
   - Walk-forward Sharpe: adaptive wins 4/5 OOS folds. Mean: -0.076 (adaptive) vs -0.650 (static). Condition: adaptive must have higher mean Sharpe. MET.
   - Policy: both conditions required. Result: inconclusive -> status quo (static) retained.

5. **Root cause of adaptive Sharpe advantage:** Not improved signal quality. The adaptive threshold shift from 30/70 to ~44/66 (BTC RSI rarely reaches 30) dramatically increases trade frequency (7.8 vs 28.8 trades/fold). More trades = more chances to capture BTC's directional moves. But the increased frequency also increases MaxDD (-18.5% vs -12.7%) and the IC evidence suggests the normalized feature is a weaker predictor.

## Deviations from Plan

None - plan executed as written. The bakeoff used expanding-window (not purged K-fold) as the plan explicitly allowed this fallback. t1_series construction for RSI signals requires a holding period definition that was not available without additional complexity, so the simpler expanding-window approach was used. Results are valid for the comparison purpose.

## Issues Encountered

- Pre-existing test failures (test_returns_feature.py, test_wireup_signals_backtests.py) unrelated to this plan - deprecated returns_feature.py module per MEMORY.md.
- Reports directory is gitignored. Evaluation artifacts (CSVs, markdown) exist on disk but are not committed. This is expected per project configuration. The code change in generate_signals_rsi.py (which references the reports) is committed.

## Next Phase Readiness

- EVAL-03 complete: adaptive vs static RSI A/B comparison documented with full evidence
- generate_signals_rsi.py updated with decision comment for future reference
- Pattern established for A/B comparison: IC dual-criterion evaluation method documented
- Plan 55-05 (or subsequent) can apply same evaluation pattern to EMA crossover and ATR breakout signals
- If adaptive RSI is reconsidered: fix the normalization to preserve IC signal quality (don't divide by range), or evaluate per-bar dynamic thresholds via make_signals enhancement

---
*Phase: 55-feature-signal-evaluation*
*Completed: 2026-02-26*
