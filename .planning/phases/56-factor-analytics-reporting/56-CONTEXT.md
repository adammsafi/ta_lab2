# Phase 56: Factor Analytics & Reporting Upgrade - Context

**Gathered:** 2026-02-26
**Status:** Not started
**Depends on:** Phase 55 (Feature & Signal Evaluation)

<domain>
## Phase Boundary

Upgrade strategy and feature evaluation with industry-standard analytics from QuantStats, Qlib, and VectorBT PRO. This phase adds richer metrics, HTML tear sheets, cross-sectional normalization, and anti-overfitting tools. It builds on Phase 55's IC infrastructure and backtest tables.

**Source:** `.planning/research/quant_finance_ecosystem_review.md` — Tier 1 + Tier 2 items from QuantStats (6.8k stars), Qlib (37.8k stars), VectorBT PRO (6.7k stars).

</domain>

<scope>
## Scope

### QuantStats HTML Tear Sheets (from QuantStats)
- Integrate `qs.reports.html()` for every backtest run
- 60+ metrics + 18 charts + BTC benchmark comparison
- Missing metrics to add: omega_ratio, smart_sharpe, smart_sortino, probabilistic_sharpe_ratio, kelly_criterion, ulcer_index, ulcer_performance_index, skew, kurtosis, tail_ratio, recovery_factor, serenity_index, risk_of_ruin, consecutive_wins/losses, alpha/beta/correlation vs benchmark
- Bridge: vectorbt daily returns Series → `qs.stats.*` functions
- BTC benchmark from `cmc_price_bars_multi_tf WHERE tf='1D' AND id=<btc_id>`

### IC Decay Analysis (from Qlib)
- Extend existing IC computation to 2/5/10/20-bar forward return horizons
- Reveals predictive half-life per factor — informs correct holding period and TF alignment
- Add to `cmc_ic_results` table or new `cmc_ic_decay` table

### Rank IC & ICIR (from Qlib)
- **Rank IC**: Spearman rank correlation (more robust to outliers than Pearson IC)
- **ICIR**: IC / std(IC) — risk-adjusted IC, the single best factor quality metric
- Add both to `cmc_ic_results` alongside existing IC

### Quintile Group Returns (from Qlib)
- Rank all assets by factor score into 5 buckets at each timestamp
- Track cumulative return per bucket — gold standard monotonicity test
- Long-short spread (top vs bottom quintile) = direct alpha measurement
- Plotly visualization for any factor

### Cross-Sectional Normalization (from Qlib)
- **CSZScoreNorm**: `(value - AVG OVER (ts, tf)) / STDDEV OVER (ts, tf)` — normalize each asset vs all assets at same timestamp
- **CSRankNorm**: `PERCENT_RANK() OVER (PARTITION BY ts, tf ORDER BY value)` — rank-based
- Complementary to existing time-series z-scores (`_zscore_30/90/365`)
- Essential for multi-asset ranking and factor-neutral portfolio construction

### MAE/MFE Trade Metrics (from VectorBT PRO)
- **MAE**: Maximum Adverse Excursion — how far each trade went against you before closing
- **MFE**: Maximum Favorable Excursion — how far each trade went in your favor before closing
- Add `mae` and `mfe` columns to `cmc_backtest_trades`
- Reveals: stops too tight (MAE clusters near stop) or profits left on table (MFE >> actual exit)

### Monte Carlo Trade Resampling (from Jesse)
- Resample completed trades from `cmc_backtest_trades` N=1000 times with replacement
- Compute Sharpe/CAGR confidence intervals per backtest run
- Low-cost anti-overfitting check (~50 lines of Python)
- Report 95% CI alongside point estimates

</scope>

<requirements>
## Requirements

- ANALYTICS-01: QuantStats HTML tear sheets for every backtest run
- ANALYTICS-02: IC decay + Rank IC + ICIR in `cmc_ic_results`
- ANALYTICS-03: Quintile group returns with monotonicity charts
- ANALYTICS-04: Cross-sectional normalization (CSZScoreNorm, CSRankNorm)
- ANALYTICS-05: MAE/MFE per trade + Monte Carlo confidence intervals

</requirements>

<success_criteria>
## Success Criteria

1. Every backtest run produces an HTML tear sheet with 60+ metrics and benchmark comparison
2. IC results include Rank IC, ICIR, and IC decay at 5 horizons for all canonical features
3. Cross-sectional z-scores and ranks computed and persisted alongside existing time-series z-scores
4. MAE/MFE columns populated in `cmc_backtest_trades`; Monte Carlo CI reported per backtest run
5. Quintile return charts available for any factor — monotonicity visually confirmed or rejected

</success_criteria>
