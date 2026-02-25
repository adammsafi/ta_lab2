# Phase 55: Feature & Signal Evaluation - Context

**Gathered:** 2026-02-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Close the evaluation gap by running the existing v0.9.0 IC and experimentation infrastructure (Phases 37-38) on real data. Score all features and AMA variants, validate signal quality, populate dashboards with empirical results, and document feature lifecycle decisions. No new evaluation infrastructure is built — this phase runs what exists.

</domain>

<decisions>
## Implementation Decisions

### Feature coverage scope
- IC evaluation covers ALL assets in dim_assets (not just BTC/ETH)
- IC evaluation covers ALL 109 timeframes (not key TFs only)
- ExperimentRunner also runs all assets x all TFs (same scope as IC)
- Existing Phase 42 IC results in cmc_ic_results: PRESERVE and verify first — recompute a small sample to test methodology/parameter identity; if identical keep existing and extend; if different FLAG the discrepancy (do not silently replace)

### Adaptive vs static RSI A/B
- Claude investigates what "adaptive RSI" means in the codebase (may be AMA-smoothed RSI, may be existing variant)
- Comparison depth: full pipeline — IC scores + backtest Sharpe + walk-forward OOS with purged K-fold
- If adaptive wins: keep both variants available, default signal generator to the winner
- Win criteria: Claude's discretion based on the data (likely IC-IR AND walk-forward Sharpe must both be better)

### Evaluation output & documentation
- Findings report: BOTH Markdown report + Jupyter notebook — Markdown for summary/decisions, notebook for exploration/charts
- Feature lifecycle decisions: Claude's recommendation applied (likely auto-promote passing features, manual review for deprecation)
- Regime-conditional IC breakdown: YES, full breakdown for ALL features (not just top-N)
- CSV artifacts: YES, in reports/evaluation/ — IC rankings, experiment results, BH gate results, promotion decisions

### YAML registry expansion
- All ~112 canonical cmc_features columns added to features.yaml as experiment entries
- All 4 AMA types (KAMA, DEMA, TEMA, HMA) with key parameter sets — Claude designs sensible defaults
- EMA crossover features added (ema_cross_9_21, ema_cross_21_50, etc.) as inline expressions
- Parameter sweep ranges: Claude designs defaults based on domain knowledge

### Claude's Discretion
- Adaptive RSI win criteria thresholds
- Feature lifecycle policy (auto-promote vs manual-deprecate split)
- Parameter sweep ranges for all feature types
- AMA parameter set selection
- Which EMA crossover pairs to define
- Ordering/batching of the full evaluation run for practical compute time

</decisions>

<specifics>
## Specific Ideas

- Phase 42 IC sweep pattern (per-pair transaction isolation, table_exists pre-check) should be reused for the full evaluation
- Existing features.yaml has 5 experimental features — this expands to ~130+ including canonical features, AMA variants, and EMA crossovers
- Reports go in reports/evaluation/ (gitignored), matching Phase 42's reports/bakeoff/ pattern
- Methodology verification step before bulk run: recompute small Phase 42 sample, compare, flag if different

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 55-feature-signal-evaluation*
*Context gathered: 2026-02-25*
