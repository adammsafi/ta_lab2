# Phase 42: Strategy Bake-Off - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Use v0.9.0 research tooling (IC evaluation, PSR, purged K-fold, CPCV, feature experimentation) to evaluate all existing signals and experimental features, select the 2 best strategies for V1 paper trading, and document the rationale with a formal scorecard. Exchange integration, order management, and live execution belong in later phases.

</domain>

<decisions>
## Implementation Decisions

### Evaluation scope
- Evaluate both the 3 existing signal generators (EMA crossover, RSI mean-reversion, ATR breakout) AND the 7 experimental features from features.yaml as standalone signal strategy candidates
- Run IC evaluation on ALL 112 cmc_features columns -- comprehensive sweep, let the data reveal surprises
- Evaluate across ALL assets in DB (not just BTC/ETH) and ALL available timeframes (not just 1D) -- broad discovery phase
- Include regime-conditional analysis: IC-by-regime and backtest-by-regime alongside full-sample evaluation

### Selection criteria
- Composite score ranking: weighted blend of Sharpe, Max DD, PSR, and turnover -- no single metric dominates
- Turnover matters meaningfully (between "a lot" and "secondary") -- prefer lower turnover but don't eliminate high-turnover strategies that pass other gates
- V1 hard gates: Sharpe >= 1.0, Max DD <= 15% with realistic fees/slippage
- If no strategy hits Sharpe >= 1.0: try ensemble/blending of top signals before lowering criteria
- Top 2 by composite score regardless of style similarity -- pure meritocracy, not forced diversification
- Sensitivity analysis: run ranking under 3-4 different weighting schemes to test robustness of selection
- Produce BOTH structured data (DB tables) AND a formal scorecard document (markdown report with charts)

### Walk-forward design
- 10-fold purged K-fold CV (~330 bars per fold, ~0.9 years each)
- 20-bar embargo period between train and test folds (1 month)
- Run BOTH PurgedKFold and CPCV (combinatorial purged CV) for PBO overfitting analysis
- Run BOTH fixed-parameter and expanding-window re-optimization per fold, compare results
- IC evaluation horizons: Claude's discretion based on signal holding periods
- Minimum training window: Claude's discretion based on feature warmup requirements

### Fee & slippage model
- Target venue: Kraken (informing fee assumptions)
- Base fees: Kraken current tier -- maker 0.16%, taker 0.26% (spot)
- Slippage: test at 5, 10, and 20 bps to assess sensitivity
- Full cost matrix: all combinations of (3 slippage levels x spot/perps x base fee tier)
- Perps comparison: run backtest with funding costs alongside spot to inform Phase 51 readiness
- Funding rate: use historical average BTC/ETH funding rates (pull actual data if available, fixed 0.01%/8h otherwise)

### Claude's Discretion
- IC evaluation horizon set (likely [1, 2, 3, 5, 10, 20, 60] based on existing tooling)
- Minimum expanding-window training size (likely 252-504 bars based on feature warmup)
- Composite score default weights (will show sensitivity across 3-4 weighting schemes)
- How to structure the ensemble/blending attempt if no single strategy hits Sharpe >= 1.0
- Scorecard document format and chart selection

</decisions>

<specifics>
## Specific Ideas

- The existing CostModel dataclass (fee_bps, slippage_bps, funding_bps_day) already supports the cost matrix -- extend it rather than replace
- The 7 experimental features need to be evaluated via ExperimentRunner first, then the best promoted features become signal candidates
- CPCV analysis gives PBO estimate -- important for the V1 Results Memo (Phase 54) as evidence of robustness
- Historical funding rate data may need to be ingested as a pre-step if not already in DB

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 42-strategy-bake-off*
*Context gathered: 2026-02-24*
