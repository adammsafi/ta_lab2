# Phase 58: Portfolio Construction & Position Sizing - Context

**Gathered:** 2026-02-27
**Status:** Ready for planning
**Depends on:** Phase 56 (Factor Analytics), Phase 42 (Strategy Selection)

<domain>
## Phase Boundary

Graduate from per-asset backtesting to portfolio-level optimization. Integrate PyPortfolioOpt for multi-asset allocation, add intelligent position sizing from MLFinLab, and implement cross-asset strategies from Qlib. This is the bridge between individual signal quality (Phases 55-57) and portfolio-level performance.

**Source:** `.planning/research/quant_finance_ecosystem_review.md` — Tier 1 (PyPortfolioOpt), Tier 2 (bet sizing, Black-Litterman), Tier 3 (TopkDropout, stop laddering) from PyPortfolioOpt (5.5k stars), MLFinLab (4.6k stars), Qlib (37.8k stars), VectorBT PRO (6.7k stars).

</domain>

<decisions>
## Implementation Decisions

### Optimizer selection logic
- Always run all three optimizers (MV, CVaR, HRP) every period
- One is designated "active" for execution based on default regime mapping: bear → CVaR, stable → MV, uncertain/ill-conditioned → HRP
- Override available via config/CLI flag to force a specific optimizer
- **Claude's Discretion:** Whether HRP auto-fallback triggers on ill-conditioned covariance matrix vs warning-only
- Optimizer results persisted to DB table (e.g., `cmc_portfolio_allocations`) — full allocation history over time for all 3 optimizers

### Signal-to-allocation pipeline
- **Claude's Discretion:** How signal scores become expected return (mu) vectors — IC-weighted composite or probability-based
- **Claude's Discretion:** Whether all active signals or a curated subset feed into Black-Litterman views
- Market cap data already exists in `cmc_price_bars_multi_tf` (`market_cap` column) — no new data ingestion needed for BL priors
- Black-Litterman views support BOTH absolute views (directional signals like RSI → expected return for one asset) and relative views (cross-asset signals → "BTC outperforms ETH by X%")
- Sector constraints via `dim_listings` taxonomy for BL

### Sizing vs optimization layering
- **Two modes, both supported:**
  1. **Default (optimizer-first):** Optimizer produces raw weights → bet sizing scales based on signal confidence → risk controls cap final sizes
  2. **Alternative (sizing-as-constraints):** Bet sizing produces per-asset position bounds → optimizer respects as weight constraints
- Configurable via YAML; default is mode 1
- **Risk control integration — also two modes, both supported:**
  1. **Default (constraints-in-optimizer):** Phase 46 position caps fed into optimizer weight bounds — allocation feasible from the start
  2. **Alternative (post-optimization clipping):** Optimizer runs unconstrained, risk controls clip/reject over-limit positions
- Configurable; default is mode 1
- **Claude's Discretion:** Minimum order sizes — source from Phase 43 ExchangeConfig or separate portfolio config
- **Stop laddering:** Configurable at per-asset × per-strategy granularity (combined). Global defaults with per-asset and per-strategy overrides.

### Cash & yield management
- Cash is last resort — freed capital from low-confidence sizing redistributes first
- Groundwork laid for yield-bearing alternatives:
  - Crypto: stablecoin yield capture (e.g., USDC lending)
  - Brokerage: money market funds / structured products
- Not fully built out in this phase — interfaces and config for yield instruments, actual yield capture in future phase

### Leverage
- Optimizer can allocate above 100% gross exposure via margin/leverage
- **Funding-cost-aware:** Phase 51 perps funding rates incorporated into expected return/cost model during optimization
- **Belt and suspenders:** Optimizer has soft cap on leverage (configurable, default 2x), Phase 46 risk controls enforce hard cap
- **Claude's Discretion:** Default max exposure parameter value

### Rebalancing & turnover policy
- **Three rebalancing modes, all supported, configurable via YAML:**
  1. Time-based (default: daily, configurable to weekly/monthly)
  2. Signal-driven (rebalance on new signal arrival)
  3. Threshold-based (rebalance when actual vs target weights drift beyond X%)
  - Default: time-based daily with optional threshold overlay
- **TopkDropout defaults:** Claude's Discretion for K and dropout rate based on crypto universe size
- **Decomposed cost reporting:** Track and report gross return, turnover cost, and net return separately. Full cost transparency.
- **Turnover penalty in optimizer:** Available as configurable option (L1 regularization on weight changes), off by default. Post-hoc turnover tracking always on.

### Claude's Discretion
- HRP auto-fallback trigger logic (condition number threshold vs warning)
- Signal-to-mu mapping approach (IC-weighted vs probability)
- BL views: all signals vs curated subset
- Minimum order size sourcing (exchange config vs portfolio config)
- TopkDropout K and dropout rate defaults
- Max exposure default value

</decisions>

<specifics>
## Specific Ideas

- Cash should not sit idle — even "cash" positions should capture yield (stablecoin yield on crypto, money market on brokerage). Groundwork this phase, full implementation later.
- Leverage costs must be visible in the optimizer — funding rates from Phase 51 feed into expected return calculation so leveraged positions are priced correctly.
- "Belt and suspenders" for risk: optimizer soft caps + Phase 46 hard caps — defense in depth, not either/or.
- Both sizing modes (optimizer-first and sizing-as-constraints) AND both risk integration modes (constraints-in-optimizer and post-optimization clipping) must be switchable. Flexibility to compare approaches empirically.

</specifics>

<deferred>
## Deferred Ideas

- Full yield capture implementation (stablecoin lending protocols, money market fund integration) — future phase after groundwork
- Automated optimizer selection learning (which optimizer performs best in which regime over time) — future ML phase

</deferred>

---

*Phase: 58-portfolio-construction-sizing*
*Context gathered: 2026-02-27*
