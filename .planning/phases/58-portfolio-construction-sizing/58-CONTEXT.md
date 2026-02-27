# Phase 58: Portfolio Construction & Position Sizing - Context

**Gathered:** 2026-02-26
**Status:** Not started
**Depends on:** Phase 56 (Factor Analytics), Phase 42 (Strategy Selection)

<domain>
## Phase Boundary

Graduate from per-asset backtesting to portfolio-level optimization. Integrate PyPortfolioOpt for multi-asset allocation, add intelligent position sizing from MLFinLab, and implement cross-asset strategies from Qlib. This is the bridge between individual signal quality (Phases 55-57) and portfolio-level performance.

**Source:** `.planning/research/quant_finance_ecosystem_review.md` — Tier 1 (PyPortfolioOpt), Tier 2 (bet sizing, Black-Litterman), Tier 3 (TopkDropout, stop laddering) from PyPortfolioOpt (5.5k stars), MLFinLab (4.6k stars), Qlib (37.8k stars), VectorBT PRO (6.7k stars).

</domain>

<scope>
## Scope

### PyPortfolioOpt Integration (from PyPortfolioOpt)
Three optimizer families wired to ta_lab2 data:

**EfficientFrontier (mean-variance)**:
- `min_volatility()`, `max_sharpe()`, `efficient_risk(target_vol)`, `efficient_return(target_ret)`
- Custom mu vector from `cmc_features` signal scores
- Weight bounds, sector constraints, L2 regularization, transaction cost penalty

**EfficientCVaR (tail-risk)**:
- Minimizes average loss in worst alpha% of days
- Especially relevant for crypto given heavy left tails
- Regime-conditional: use in bear regimes (from `cmc_regimes`)

**HRPOpt (Hierarchical Risk Parity)**:
- Cluster-based, no matrix inversion required
- More robust out-of-sample than mean-variance
- Fallback when covariance matrix is ill-conditioned (small altcoin universes)

### Risk Models (from PyPortfolioOpt)
- `exp_cov(span)`: regime-sensitive span (30-90 in high vol, 180 in stable)
- `semicovariance`: downside-only risk
- `CovarianceShrinkage.ledoit_wolf()`: reduces estimation error
- All computed from `cmc_returns_bars_multi_tf_u`

### Black-Litterman Allocation (from PyPortfolioOpt)
- Prior: `market_implied_prior_returns(market_caps, risk_aversion, cov_matrix)` using CMC market cap data
- Views: signal outputs (EMA/RSI) as absolute or relative views via P and Q matrices
- Posterior: `bl.bl_returns()` → `EfficientFrontier(posterior_mu, posterior_cov)`
- Sector constraints via `dim_listings` taxonomy (chain/sector grouping)

### Probability-Based Bet Sizing (from MLFinLab)
- `bet_size_probability(events, prob, num_classes)` — maps classifier confidence to fractional position size
- Sigmoid or step function mapping
- `average_active=True` weights by concurrent positions
- Plugs into existing signal generators' output

### TopkDropout Portfolio Strategy (from Qlib)
- Hold top K assets by signal score
- Each period: sell bottom-ranked, buy top-ranked
- Controlled turnover rate: `2 * dropout_rate / K`
- Natural multi-asset upgrade to per-asset backtesting
- Backtest with turnover tracking; compare to equal-weight and per-asset baselines

### Stop Laddering (from VectorBT PRO)
- Array of incremental exit stops to scale out of positions:
  ```
  sl_stop = [0.02, 0.03, 0.05]  # Scale out at 2%, 3%, 5% adverse
  tp_stop = [0.03, 0.05, 0.10]  # Scale out at 3%, 5%, 10% favorable
  ```
- Extends ATR breakout and other signal generators
- Reduces single-exit cliff risk

### Discrete Allocation (from PyPortfolioOpt)
- `DiscreteAllocation(weights, prices, total_portfolio_value)` converts fractional weights to actionable quantities
- `greedy_portfolio()` (fast) or `lp_portfolio()` (exact)
- Post-process for exchange lot-size compliance (minimum order sizes)

</scope>

<requirements>
## Requirements

- PORT-01: PyPortfolioOpt integration (EfficientFrontier, EfficientCVaR, HRPOpt) with risk model options
- PORT-02: Black-Litterman allocation with CMC market caps as prior and signal views
- PORT-03: TopkDropout portfolio strategy backtested with turnover tracking
- PORT-04: Probability-based bet sizing mapping signal confidence to position size
- PORT-05: Stop laddering for scaled exits integrated into signal generators

</requirements>

<success_criteria>
## Success Criteria

1. Portfolio optimizer produces allocation weights for the crypto universe given signal scores and covariance matrix
2. CVaR and HRP optimizers available as regime-conditional alternatives (bear → CVaR, stable → mean-variance)
3. Black-Litterman integration: CMC market caps → prior, signals → views → posterior → weights
4. TopkDropout backtested across universe with turnover tracking; compared to equal-weight and per-asset baselines
5. Bet sizing function maps signal probability to position size; demonstrated improvement in Sharpe vs fixed sizing

</success_criteria>
