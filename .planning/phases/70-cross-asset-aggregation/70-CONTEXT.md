# Phase 70: Cross-Asset Aggregation - Context

**Gathered:** 2026-03-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Cross-asset signals -- BTC/ETH correlation, aggregate funding rates, and crypto-macro correlation regime -- provide market-wide context that complements per-asset regimes. Covers XAGG-01 through XAGG-04.

This phase computes and stores cross-asset features. It does NOT build the portfolio optimizer integration (Phase 58 already did that) or risk gates (Phase 71).

</domain>

<decisions>
## Implementation Decisions

### Funding rate aggregation
- All 6 venues included (Binance, Hyperliquid, Bybit, dYdX, Aevo, Aster)
- Store BOTH simple average (primary, always available) and volume-weighted average (secondary, when volume data exists)
- 30d z-score is the primary signal for regime/risk consumption; 90d z-score is secondary
- Missing venue data: exclude from average (NaN venues silently excluded, no forward-fill)

### Correlation anomaly detection
- Sign flip defined by magnitude threshold: correlation going from >0.3 to <-0.3 (or vice versa). Ignores near-zero noise.
- On sign flip: feed into macro regime as a dimension in cmc_macro_regimes AND send Telegram alert
- Macro variables for crypto-macro correlation: VIX + DXY + HY OAS + net liquidity (4 variables)
- Compute crypto-macro correlations for ALL tradeable assets with data, not just BTC

### Storage & table design
- Claude decides schema, with naming rule: `cmc_` prefix only for tables whose assets come from cmc_price_histories7. Tables mixing crypto with non-crypto (macro) data drop the prefix.
- Separate aggregate table for funding rate signal (not columns in cmc_funding_rates)
- Crypto-macro correlation regime label stored as new columns in cmc_macro_regimes (alongside monetary/liquidity/risk/carry)
- BTC/ETH 30d correlation stored in cross-asset table, NOT fred_macro_features (it's not FRED data)

### High-correlation flag behavior
- When >0.7 average pairwise correlation fires: reduce diversification benefit assumption in portfolio optimizer (increase correlation estimate in covariance matrix)
- Asset scope: ALL assets from both cmc_price_histories7 AND tvc_price_histories
- 0.7 threshold is YAML-configurable (consistent with macro regime threshold approach)
- High-correlation flag considers BOTH crypto-to-crypto AND crypto-to-macro correlations ("everything is correlated" = true macro-driven market)

### Claude's Discretion
- Exact schema design for cross-asset tables (within naming convention constraint)
- Rolling window sizes for correlation computation (60d specified for crypto-macro, others TBD)
- How to wire the diversification reduction into existing PortfolioOptimizer
- Refresh frequency and watermark strategy

</decisions>

<specifics>
## Specific Ideas

- The aggregate funding rate is a sentiment proxy -- when all venues agree on high positive funding, the market is overleveraged long
- Crypto-macro sign flip is a regime change detector -- historically these have preceded major moves
- The high-correlation flag is about systemic risk -- when everything moves together, portfolio diversification is illusory

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 70-cross-asset-aggregation*
*Context gathered: 2026-03-03*
