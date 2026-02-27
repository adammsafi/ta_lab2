# Phase 57: Advanced Labeling & Cross-Validation - Context

**Gathered:** 2026-02-26
**Status:** Not started
**Depends on:** Phase 55 (Feature & Signal Evaluation), Phase 56 (Factor Analytics)

<domain>
## Phase Boundary

Replace fixed-horizon return labels with adaptive triple barrier labeling, add meta-labeling for false positive reduction, and implement purged cross-validation to prevent data leakage in backtests. Based on "Advances in Financial Machine Learning" (Lopez de Prado) techniques implemented in MLFinLab and VectorBT PRO.

**Source:** `.planning/research/quant_finance_ecosystem_review.md` — Tier 1 (triple barrier, purged CV) + Tier 2 (CUSUM) + Tier 3 (trend scanning) from MLFinLab (4.6k stars).

</domain>

<scope>
## Scope

### Triple Barrier Labeling (from MLFinLab — AFML Chapter 3)
- Three barriers per event:
  1. **Profit-taking**: close when return exceeds `pt * daily_vol`
  2. **Stop-loss**: close when return drops below `-sl * daily_vol`
  3. **Vertical**: close after N bars (max holding period)
- Label = which barrier hit first: {+1 profit, -1 stop, 0 timeout}
- Vol-scaled thresholds adapt to market conditions
- Replaces fixed-horizon returns in `cmc_returns_*` for ML training labels

### Meta-Labeling (from MLFinLab — AFML Chapter 3)
- Two-model approach:
  1. Primary model: picks direction (long/short) — existing EMA crossover, RSI, breakout signals
  2. Secondary model (typically Random Forest): predicts whether to trade {0, 1}
  3. Size by confidence: `position_size = predicted_probability`
- Dramatically reduces false positives while maintaining recall
- `side_prediction` parameter in `get_events()` enables meta-labeling mode

### Purged K-Fold / CPCV (from MLFinLab + VectorBT PRO)
- **PurgedKFold**: Standard K-Fold with purging (removes training samples whose labels span test period) and embargo (time buffer after each test fold)
- **CombinatorialPurgedKFold (CPCV)**: C(N,k) splits generating multiple OOS backtest paths
  - CPCV(N=6, k=2) → 15 splits → ~6.67 backtest paths
  - Produces distribution of OOS Sharpe (not single point estimate)
  - Enables statistical tests on strategy performance
- Critical because: signal generators use multi-bar features; without purging, train/test contamination inflates metrics

### CUSUM Event Filter (from MLFinLab)
- Event-driven sampling: only generate signals when cumulative deviation crosses threshold
- `cusum_filter(close_series, threshold=daily_vol * 2)` → event timestamps
- Reduces noise trades in RSI/EMA/breakout signals
- Integrated as optional pre-filter for all 3 signal generators

### Trend Scanning Labels (from MLFinLab)
- OLS regression on expanding windows; t-value at max |t-stat| defines label
- `trend_scanning_labels(price_series, observation_window=20)`
- Sign(t-value) for {-1, 1} classification
- Raw t-value doubles as sample weight (high confidence = high weight)
- Alternative to triple barrier for trend-following strategies

</scope>

<requirements>
## Requirements

- LABEL-01: Triple barrier labeler with configurable pt/sl/vertical barriers
- LABEL-02: Meta-labeling pipeline (existing signals → direction, RF → trade/no-trade)
- LABEL-03: Purged K-Fold / CPCV producing OOS Sharpe distributions
- LABEL-04: CUSUM event filter + trend scanning labels as optional pre-filters

</requirements>

<success_criteria>
## Success Criteria

1. Triple barrier labeler produces {+1, -1, 0} labels for any (asset, tf) pair with configurable pt/sl multipliers and vertical barrier
2. Meta-labeling pipeline: existing signals → direction, RF classifier → trade/no-trade with probability-based sizing
3. CPCV produces distribution of OOS Sharpe ratios (not single point estimate) for each signal strategy
4. CUSUM filter integrated as optional pre-filter for all 3 signal generators; reduces trade count by 20-40% while maintaining or improving Sharpe

</success_criteria>
