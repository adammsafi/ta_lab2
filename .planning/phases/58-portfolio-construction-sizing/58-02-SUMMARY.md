---
phase: 58-portfolio-construction-sizing
plan: 02
subsystem: portfolio
tags: [portfolio, pypfopt, mean-variance, cvar, hrp, regime-routing, ledoit-wolf, optimization]

# Dependency graph
requires:
  - phase: 58-01
    provides: configs/portfolio.yaml + load_portfolio_config() + PyPortfolioOpt installed

provides:
  - src/ta_lab2/portfolio/optimizer.py with PortfolioOptimizer class (MV, CVaR, HRP)
  - Regime routing: bear->CVaR, stable->MV, uncertain->HRP (configurable via portfolio.yaml)
  - HRP auto-fallback when covariance condition number > 1000
  - max_sharpe failure gracefully falls back to min_volatility on fresh EfficientFrontier
  - Adaptive lookback: lookback_calendar_days / tf_days_nominal, floored at min_lookback_bars
  - _TF_DAYS_FALLBACK hardcoded map for offline/test operation without DB

affects:
  - 58-03 (bet_sizing, topk_selector consume PortfolioOptimizer.run_all() output)
  - 58-04 (rebalancer orchestrates PortfolioOptimizer calls)
  - 58-05 (stop_ladder works downstream of final portfolio weights)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fresh EfficientFrontier instance per optimizer call to prevent state contamination"
    - "Dynamic weight bounds: max(max_position_pct, 1/n_assets) to guarantee EF feasibility"
    - "Ledoit-Wolf shrinkage covariance via risk_models.CovarianceShrinkage"
    - "HRP common-assets filter: intersection of returns_df.columns and S.columns"
    - "_TF_DAYS_FALLBACK fallback map for DimTimeframe when DB is unavailable"

# File tracking
key-files:
  created:
    - src/ta_lab2/portfolio/optimizer.py
  modified:
    - src/ta_lab2/portfolio/__init__.py

# Decisions
decisions:
  - id: D1
    choice: "Dynamic weight bounds floor max(max_position_pct, 1/n_assets)"
    rationale: "EfficientFrontier requires sum(weights)=1.0 but n_assets*max_position_pct can be < 1.0 (e.g. 5 assets x 0.15 = 0.75). Dynamic floor prevents infeasibility without violating the intent of the constraint."
    alternatives: "Raise ValueError on infeasible config; let caller adjust max_position_pct."
  - id: D2
    choice: "_TF_DAYS_FALLBACK hardcoded map with DB-first, fallback-second resolution"
    rationale: "PortfolioOptimizer must work in unit tests and offline analysis without a live DB. DB lookup attempted first to stay authoritative; fallback map covers all common TF strings."
    alternatives: "Require DB connection always; pass tf_days as explicit parameter."

# Metrics
metrics:
  duration: "~4 minutes"
  completed: "2026-02-28"
  tasks_completed: 1
  tasks_total: 1
---

# Phase 58 Plan 02: PortfolioOptimizer Class Summary

**One-liner:** MV/CVaR/HRP optimizer with regime routing, Ledoit-Wolf shrinkage, and HRP ill-conditioning auto-fallback.

## What Was Built

`PortfolioOptimizer` in `src/ta_lab2/portfolio/optimizer.py` wraps PyPortfolioOpt's three
optimizers behind a unified `run_all(prices, regime_label, tf)` API.

### Core behavior

- **Adaptive lookback:** `lookback_bars = round(lookback_calendar_days / tf_days_nominal)`.
  For `1D` -> 180 bars, `4H` -> 1080 bars. Raises `ValueError` when result is below
  `min_lookback_bars` (e.g. `7D` yields 26 bars, below the 60-bar floor).
- **Covariance:** Ledoit-Wolf shrinkage via `CovarianceShrinkage(prices_window).ledoit_wolf()`.
- **MV optimizer:** `max_sharpe()` first; if `OptimizationError`, fresh instance runs
  `min_volatility()`; if both fail, returns `None`.
- **CVaR optimizer:** `min_cvar()` on `EfficientCVaR`; returns `None` on failure.
- **HRP optimizer:** `HRPOpt(returns, cov_matrix).optimize(linkage_method='ward')`; filters
  to common asset columns to avoid shape mismatches.
- **Regime routing:** `stable->mv`, `bear->cvar`, `uncertain->hrp`, `default->hrp` (from YAML).
  If ill-conditioned (cond > 1000), forces `hrp` with a warning.
- **Fallback:** If regime-selected optimizer returns `None`, falls back to `hrp`.

### Key design decision: dynamic weight bounds

`weight_bounds=(0, max(max_position_pct, 1/n_assets))` ensures the EF feasibility constraint
`sum(w)=1.0` can always be satisfied.  Without this floor, a 5-asset portfolio with
`max_position_pct=0.15` (max sum = 0.75) is infeasible.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Dynamic weight bounds floor**

- **Found during:** Task 1 smoke test debugging
- **Issue:** Plan specified `weight_bounds=(0, max_position_pct)` directly. With 5 assets and
  `max_position_pct=0.15`, `5 x 0.15 = 0.75 < 1.0` (required sum), making EF infeasible and
  causing `OptimizationError` for both `max_sharpe` and `min_volatility`.
- **Fix:** Applied `effective_max = max(self.max_position_pct, 1.0 / n_assets)` before
  creating any `EfficientFrontier` or `EfficientCVaR` instance.
- **Files modified:** `src/ta_lab2/portfolio/optimizer.py`
- **Impact:** Smoke test assertion `result['mv'] is not None` now passes correctly.

**2. [Rule 2 - Missing Critical] _TF_DAYS_FALLBACK offline map**

- **Found during:** Task 1 architecture review
- **Issue:** Plan said `DimTimeframe().tf_days(tf)` but `DimTimeframe()` requires a `meta`
  dict from DB; no-arg constructor doesn't exist. Smoke test runs without DB.
- **Fix:** Added `_resolve_tf_days(tf)` that tries DB first (via `TARGET_DB_URL` env var),
  falls back to hardcoded `_TF_DAYS_FALLBACK` dict covering all common TF strings.
- **Files modified:** `src/ta_lab2/portfolio/optimizer.py`

## Verification Results

All success criteria verified:

1. `run_all(prices, regime_label)` returns weights for all 3 optimizers -- PASS
2. Active optimizer selected by regime routing with HRP fallback for ill-conditioned -- PASS
3. `max_sharpe` failure gracefully falls back to `min_volatility` -- PASS (both branches tested)
4. Ledoit-Wolf shrinkage used for covariance -- PASS
5. Clean weights sum to ~1.0 for each optimizer (MV=1.0, CVaR=1.0, HRP=1.0) -- PASS
6. Adaptive lookback: 1D->180 bars, 4H->1080 bars, 7D->ValueError (26<60) -- PASS

## Commits

- `d051ca49` feat(58-02): PortfolioOptimizer with MV, CVaR, HRP and regime routing
