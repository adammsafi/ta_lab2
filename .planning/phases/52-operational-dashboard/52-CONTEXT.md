# Phase 52: Operational Dashboard - Context

**Gathered:** 2026-02-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Live operational views for paper trading: PnL, exposure, drawdown, drift status, risk controls status. Extends the existing Phase 39 Streamlit dashboard with new operational pages. Does NOT include live exchange WebSocket feeds, automated trading actions from the dashboard, or alerting (Phase 29 Telegram handles that).

</domain>

<decisions>
## Implementation Decisions

### App structure
- Extend the existing Phase 39 Streamlit app (app.py) -- one app, one place to look
- Add 3-4 new operational pages to the sidebar alongside existing Pipeline Monitor and Research Explorer
- Update the existing unified landing page to include an operational health summary section (traffic-light indicators for executor, risk, drift, data freshness)

### Page organization
- Separate pages for each concern (not a single dense page)
- Claude decides the exact page count (3 or 4) and sidebar grouping/headers based on content density
- Drift gets its own page/section separate from general risk -- drift has charts (equity overlay, TE series) that need space

### Navigation and visual flow
- Sidebar grouping: Claude decides whether to group under "Operations" / "Research" headers or keep flat
- Current state as default view with expandable 7-day history toggle per section

### Refresh behavior
- Auto-refresh every 15 minutes (configurable constant -- make it easy to change)
- Build the architecture to support future intraday data, but for now the dashboard only shows post-pipeline daily data
- Cache TTL: Claude decides per page (positions/risk shorter, historical stats longer)

### Staleness display
- Claude decides granularity (per-section timestamps vs global)

### Audience and usage mode
- Dual-mode: quick daily check most days, active monitoring during volatile periods or after changes
- Design should support both: fast scan at a glance, with drill-down for deeper analysis

### Claude's Discretion
- Exact page count (3 vs 4 operational pages)
- Sidebar grouping strategy (headers vs flat)
- Per-page cache TTL values
- Staleness indicator granularity
- Whether landing page traffic-light summary is a separate section or integrated into existing pipeline monitor
- Loading skeleton / spinner design
- Color palette for operational vs research sections

</decisions>

<decisions>
## Risk & Drift Display

### Kill switch / drift pause status
- Both: prominent red/yellow banner at top of ops pages when kill switch or drift pause is ACTIVE (can't miss it), plus status cards for normal-state details
- Binary indicators: kill switch on/off, drift paused on/off, circuit breaker tripped on/off

### Proximity to limits
- Traffic lights for current state + proximity gauges (progress bars) for key thresholds: daily loss as % of cap, tracking error as % of pause threshold
- Both current state and proximity visible at a glance

### Risk event history
- Filterable table of cmc_risk_events with type/timestamp/reason filters
- Full audit trail visible in the dashboard

### Drift monitor section
- Separate from general risk -- drift has its own charts and metrics
- Show tracking error time series, equity overlay (paper vs replay), drift pause status
- Consumes v_drift_summary and cmc_drift_metrics from Phase 47

</decisions>

<decisions>
## PnL & Position Views

### PnL scope
- Default to portfolio aggregate with toggle/expander to see per-strategy breakdown
- Both views available without page navigation

### Equity curve
- Stacked two-panel layout: top chart = cumulative PnL over time, bottom chart = drawdown
- Both panels always visible (not tabbed)

### Position table
- Detailed columns: Asset | Side | Qty | Avg Cost | Current Price | Unrealized PnL | % of Portfolio | Strategy | Entry Date | Realized PnL | Signal Type | Regime Label
- All columns visible by default

### Trade log
- Last 20 fills as scrollable table with timestamp, asset, qty, price, slippage
- Complements position table for recent activity visibility

</decisions>

<specifics>
## Specific Ideas

- 15-minute auto-refresh is the starting point, but make the constant easy to find and change (module-level or config)
- Build for future intraday price data even though current data is daily -- e.g., unrealized PnL column should work with any price source, not hardcoded to daily bars
- The dashboard should feel operational: when something is wrong (kill switch, drift pause, circuit breaker), it should be impossible to miss

</specifics>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 52-operational-dashboard*
*Context gathered: 2026-02-25*
