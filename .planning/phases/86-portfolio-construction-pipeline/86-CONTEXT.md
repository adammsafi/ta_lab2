# Phase 86: Portfolio Construction Pipeline - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary

End-to-end portfolio construction from IC scores through paper execution with GARCH-informed sizing. Takes bake-off winners (Phase 82), GARCH vol forecasts (Phase 81), and per-asset IC-IR scores (Phase 80) and produces a rebalanceable portfolio with calibrated stops and a verified dry run.

Depends on Phase 81 (GARCH vol), Phase 82 (bake-off winners). Live market data execution is Phase 87/88 scope.

</domain>

<decisions>
## Implementation Decisions

### Black-Litterman view construction
- Claude's discretion on: IC-IR to BL view translation, prior equilibrium returns, omega (confidence) calibration, and IC source selection
- Must use **per-asset IC-IR from ic_results** (not universal average from feature_selection.yaml) -- this is a hard requirement from Phase 80 learnings
- AMA-derived features dominate active tier (18/20) -- BL pipeline must load from BOTH features + ama_multi_tf tables

### Bet sizing & target volatility
- **Target vol stored in dim_executor_config** -- configurable without code changes
- High risk tolerance: annualized vol can exceed 100% for short-term positions
- **70% max single-position concentration** -- this is a high-conviction, concentrated portfolio
- Claude's discretion on: sizing method (target-vol scaling vs Kelly), rebalance frequency, GARCH vol integration approach

### Stop ladder calibration
- **Per-asset-strategy combination** granularity -- each (asset, strategy) pair gets its own stop levels from bake-off MAE/MFE data
- Claude's discretion on: derivation method (MAE percentile vs ATR-multiple), fixed vs trailing vs tiered stops, tightness calibration

### Dry run & parity testing
- **Parity defined as: same trade direction and timing** -- fill price is secondary (slippage expected to differ)
- **Historical replay for now** -- deterministic comparison against backtest results. Live market data deferred to Phase 87/88.
- Claude's discretion on: dry run duration, failure mode (halt vs log-and-continue), specific parity tolerance thresholds

</decisions>

<specifics>
## Specific Ideas

- Portfolio is high-conviction and concentrated (70% max position) -- not a diversified low-vol portfolio
- Target vol is configurable per executor config, not hardcoded -- allows different risk profiles for different strategy instances
- Phase 80 established that IC-IR varies significantly per asset -- the BL view must reflect this heterogeneity
- Existing modules: `portfolio/` (Black-Litterman, TopK, bet sizing, stop ladder), `executor/` (paper executor, fill simulator, parity checker)

</specifics>

<deferred>
## Deferred Ideas

- Live market data dry run -- Phase 87/88 when live pipeline is wired
- Real-time vol adjustment (intraday position scaling) -- future enhancement beyond daily pipeline

</deferred>

---

*Phase: 86-portfolio-construction-pipeline*
*Context gathered: 2026-03-24*
