---
phase: 58-portfolio-construction-sizing
plan: 03
subsystem: portfolio
tags: [portfolio, pypfopt, black-litterman, bet-sizing, ic-ir, signal-views, scipy, market-cap-prior]

# Dependency graph
requires:
  - phase: 58-01
    provides: configs/portfolio.yaml with black_litterman and bet_sizing sections
  - phase: 58-02
    provides: PortfolioOptimizer.run_all() producing S (Ledoit-Wolf covariance) and mu

provides:
  - src/ta_lab2/portfolio/black_litterman.py with BLAllocationBuilder class
  - src/ta_lab2/portfolio/bet_sizing.py with BetSizer class and probability_bet_size function
  - signals_to_mu: IC-IR weighted composite -> cross-sectional z-score -> vol-scaled returns
  - build_views: IC-IR threshold filter + confidence normalization to [0.2, 0.8]
  - BLAllocationBuilder.run: market_implied_prior + BlackLittermanModel (Idzorek) + EfficientFrontier
  - probability_bet_size: de Prado AFML Ch10 formula, prob=0.5->0, prob=0.8->~0.45
  - BetSizer.scale_weights: optimizer_first mode scales raw weights by bet size
  - BetSizer.compute_bounds: sizing_as_constraints mode returns (lower, upper) per asset

affects:
  - 58-04 (rebalancer and cost_tracker consume BLAllocationBuilder and BetSizer)
  - 58-05 (consolidates __init__.py exports: BLAllocationBuilder, BetSizer, probability_bet_size)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "BL asset alignment: common_assets = intersection of S.columns and market_caps.index"
    - "Dynamic weight bounds floor max(max_position_pct, 1/n_assets) carried from optimizer.py"
    - "IC-IR threshold filter (_MIN_IC_IR_FOR_VIEW=0.1) gates view inclusion"
    - "View confidence normalization: min-max IC-IR to [min_conf, max_conf] via conf_range scale"
    - "BetSizer min_confidence gate: assets with prob < 0.2 receive weight 0 (excluded)"
    - "_TF_DAYS_FALLBACK pattern duplicated from optimizer.py for offline operation"

key-files:
  created:
    - src/ta_lab2/portfolio/black_litterman.py
    - src/ta_lab2/portfolio/bet_sizing.py
  modified: []

key-decisions:
  - "BLAllocationBuilder produces a single scalar confidence per asset (weighted mean of per-signal IC-IR confidences) rather than one confidence per signal view -- BlackLittermanModel requires one confidence per view (per asset), not per signal type"
  - "view_confidences assigned as list ordered by absolute_views.keys() iteration order (Python 3.7+ dict ordering is insertion order)"
  - "BetSizer.scale_weights returns bounds dict when mode=sizing_as_constraints (same interface) rather than raising, to keep callers consistent"

patterns-established:
  - "IC-IR weight normalization: clip(lower=0) then / sum() to get signal importance weights"
  - "Cross-sectional z-score: (composite - mean) / std.clip(lower=1e-8)"
  - "Alpha scale: z * annualized_vol * 0.1 (10% of vol = max expected alpha)"
  - "No-views fallback: optimize prior returns directly on EfficientFrontier when all IC-IR < threshold"

# Metrics
duration: 3min
completed: 2026-02-28
tasks_completed: 2
tasks_total: 2
---

# Phase 58 Plan 03: BLAllocationBuilder and BetSizer Summary

**Black-Litterman allocation (market cap prior + IC-IR signal views -> posterior weights) and de Prado probability bet sizing (signal confidence -> position scale) implemented as standalone portfolio modules.**

## Performance

- **Duration:** ~3 minutes
- **Started:** 2026-02-28T08:00:06Z
- **Completed:** 2026-02-28T08:03:00Z
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments

- `BLAllocationBuilder` wraps PyPortfolioOpt's `BlackLittermanModel` with IC-IR weighted signal views from the project's existing IC evaluation pipeline
- `signals_to_mu()` converts signal score DataFrames to return-scale estimates using IC-IR weighted composite + cross-sectional z-scoring + vol scaling
- `probability_bet_size()` implements the de Prado AFML Chapter 10 formula correctly: prob=0.5 -> 0 (no edge), prob=0.8 -> ~0.45, prob=0.9 -> ~0.58
- `BetSizer` supports both `optimizer_first` (post-optimization scaling) and `sizing_as_constraints` (bound generation) modes with min_confidence gating

## Task Commits

Each task was committed atomically:

1. **Task 1: BLAllocationBuilder** - `b8d11abb` (feat)
2. **Task 2: BetSizer** - `629b16a9` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `src/ta_lab2/portfolio/black_litterman.py` - BLAllocationBuilder class: signals_to_mu, build_views, run methods + _resolve_tf_days fallback
- `src/ta_lab2/portfolio/bet_sizing.py` - probability_bet_size function + BetSizer class with scale_weights and compute_bounds methods

## Decisions Made

**D1: Per-asset confidence vs per-signal confidence**

`BlackLittermanModel(omega="idzorek", view_confidences=...)` requires one confidence scalar per view (i.e., per asset), not per signal type. The `build_views()` method computes a single weighted-mean confidence scalar from the per-signal IC-IR normalized values, then assigns it uniformly to all assets. This is mathematically coherent (one view per asset uses its composite IC-IR confidence).

**D2: Cross-sectional z-score in build_views uses z=0 center**

The build_views method uses the same cross-sectional z-score normalization as signals_to_mu, but without vol scaling (views are dimensionless signals, not return forecasts). This ensures views span positive and negative values symmetrically around zero.

**D3: BetSizer mode=sizing_as_constraints returns bounds dict from scale_weights**

Rather than raising a TypeError or requiring the caller to always call compute_bounds directly, scale_weights in sizing_as_constraints mode infers max_pos from the raw_weights and delegates to compute_bounds. This keeps the public interface uniform.

## Deviations from Plan

None - plan executed exactly as written. The numpy import was removed by ruff (unused) since all numpy operations are delegated to pandas internally.

## Issues Encountered

Ruff auto-fixed line endings (CRLF -> LF) and removed unused `numpy` import on first commit attempt. Required re-staging after hook correction. No logic changes.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `BLAllocationBuilder` and `BetSizer` are ready for 58-04 (rebalancer + cost tracker)
- 58-05 will consolidate `__init__.py` exports: `BLAllocationBuilder`, `BetSizer`, `probability_bet_size`
- Both modules load config from `portfolio.yaml` via `load_portfolio_config()` and work offline (no DB required)

---
*Phase: 58-portfolio-construction-sizing*
*Completed: 2026-02-28*
