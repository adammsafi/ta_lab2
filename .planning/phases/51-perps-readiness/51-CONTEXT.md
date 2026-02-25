# Phase 51: Perps Readiness - Context

**Gathered:** 2026-02-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the technical foundation for perpetual futures paper trading: funding rate ingestion from 6 venues, margin model (isolated + cross), liquidation buffer with alerts, backtester extension for funding payments and carry trade, and venue downtime playbook with hedge-on-alternate-venue procedure.

</domain>

<decisions>
## Implementation Decisions

### Funding Rate Data Scope
- **6 venues**: Hyperliquid, Binance, Bybit, dYdX, Aster, Lighter
- **Full available history** per venue (Binance has ~4-5 years for BTC/ETH; others vary)
- **Multi-granularity storage**: 8h (universal across all venues), 4h (where available), daily rollup
- **Standalone refresh script** (not wired into existing bar pipeline since source is exchange API, not CMC)
- BTC/ETH perps as primary pairs

### Margin and Liquidation Model
- **Both margin modes**: isolated and cross margin, configurable per strategy or globally
- **Leverage range**: 1-10x for paper V1
- **Venue-specific margin rates**: fetch actual initial and maintenance margin requirements per asset per venue (not simplified fixed rates)
- Liquidation alert at 1.5x maintenance margin, kill switch at 1.1x maintenance margin (per requirements)

### Backtester Funding Integration
- **Unified backtest** with `instrument='spot'|'perp'` flag controlling funding/margin behavior
- **Carry trade modeled as a strategy variant**: long spot + short perp to collect funding
- **Missing data fallback**: cross-venue average fill when a specific venue's funding rate is unavailable
- Funding payments modify backtest P&L (longs pay/receive, shorts receive/pay per settlement period)

### Venue Downtime Playbook
- **Downtime scope is comprehensive**: API failures, degraded performance (slow responses, stale orderbook), scheduled maintenance windows, regulatory halts, withdrawal suspensions, unusual spread widening
- **Open positions during downtime**: hedge on alternate venue to neutralize exposure
- Graduated health status: healthy > degraded > down

### Claude's Discretion
- Funding application timing in backtester (per-settlement vs daily aggregated vs both modes)
- RiskEngine integration approach for margin/liquidation gates (extend existing gates vs separate MarginMonitor)
- Playbook format (document only vs document + machine config YAML)
- Venue failover automation scope (manual procedure vs automated routing)
- Table schema design for funding rates (single table with tf column vs separate tables)
- Pipeline wiring decisions (standalone only vs also in daily refresh)

</decisions>

<specifics>
## Specific Ideas

- 6 specific venues chosen by user: Hyperliquid, Binance, Bybit, dYdX, Aster, Lighter -- these are the perps venues the user actively uses/monitors
- 4h funding rate granularity where available (some venues like Hyperliquid use 1h or 4h settlement periods, not just 8h)
- Carry trade as a strategy variant signals interest in basis/funding rate strategies beyond directional trading
- Hedge-on-alternate-venue for downtime handling implies multi-venue order routing capability is needed (at least for emergency hedging)

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope.

</deferred>

---

*Phase: 51-perps-readiness*
*Context gathered: 2026-02-25*
