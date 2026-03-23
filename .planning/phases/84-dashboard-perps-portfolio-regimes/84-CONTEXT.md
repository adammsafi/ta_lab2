# Phase 84: Dashboard — Perps, Portfolio & Regimes - Context

**Gathered:** 2026-03-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Four new dashboard pages covering Hyperliquid perps data, portfolio allocation, cross-asset regime views, and AMA/EMA inspection. All pages follow the established query-layer pattern (queries/*.py + pages/*.py) from Phase 83 and use @st.fragment(run_every=900) for auto-refresh. Portfolio allocation page uses placeholder/mock data since the BL pipeline (Phase 86) doesn't exist yet.

</domain>

<decisions>
## Implementation Decisions

### Hyperliquid Perps Page
- **Landing view**: Top perps dashboard (cards/tiles for top 10-15 perps by volume showing funding, OI, price) as primary landing
- **Additional views**: Funding rate heatmap (assets x time, color-coded) AND sortable data table with funding/OI sparklines — all three views available, dashboard first
- **Funding rate charts**: Both single-asset line chart (dropdown selector) AND multi-asset overlay (up to 5 assets overlaid for comparison)
- **Candle charts**: User-selectable from all 190 perps via dropdown (not limited to top N)
- **Time range default**: 30 days for funding rate and OI data
- **Data source**: `hyperliquid` schema tables (hl_assets, hl_candles, hl_funding_rates, hl_open_interest, hl_oi_snapshots)

### Portfolio Allocation Page
- **Current state**: Placeholder page with mock structure — shows the full page layout with sample/mock data or empty states, ready to wire when Phase 86 delivers the BL pipeline
- **Exposure viz**: Both treemap AND stacked bar chart with a toggle button to switch between views
- **Weight history**: Both stacked area chart (visual) AND timestamped table (audit-style) for weight changes over time
- **Position sizing**: Both bet size per asset with rationale (what drove it: IC-IR, vol, risk limit) AND risk budget utilization (used vs available per asset) — unified view showing all sizing info
- **Mock data strategy**: Use representative sample data that demonstrates the page's intended behavior once real data flows from Phase 86

### Regime Heatmap Page
- **Asset organization**: All three modes available — cluster by regime similarity (using regime_comovement), alphabetical with sector tags, AND top 30 by default with expand-to-all option
- **Regime timeline**: Both compact strip chart (one narrow row per asset, color-coded) AND paginated view (15-20 assets per page with full regime bands) — user can toggle between dense/readable modes
- **Comovement visualization**: Tab between NxN correlation matrix heatmap AND network graph (nodes=assets, edges=high comovement)
- **Regime stats**: Overview cards at top (how many assets in each regime state, avg duration) with expandable per-asset detail table below (current regime, duration, historical flip count)

### AMA/EMA Inspector Page
- **Mode**: Both per-asset deep-dive (select one asset, see all curves) AND cross-asset comparison (select 2-5 assets side-by-side) with toggle between modes
- **AMA curves displayed**: Full suite — efficiency ratio, AMA value, d1, d2, d1_roll, d2_roll — all toggleable overlays
- **AMA vs EMA comparison**: Both overlay on same chart AND side-by-side charts — user can switch between views
- **Period selector**: Configurable with preset buttons (Short/Medium/Long) plus custom period input

### Claude's Discretion
- OI snapshot display format and positioning within HL page
- Regime color palette (consistent with existing Phase 83 REGIME_COLORS or new scheme)
- Network graph layout algorithm for comovement visualization
- Mock data generation approach for portfolio placeholder
- Exact preset period groupings for AMA/EMA inspector (Short/Medium/Long breakpoints)
- Page ordering within the Analysis sidebar group
- Loading states and error handling patterns

</decisions>

<specifics>
## Specific Ideas

- Hyperliquid page should be operational — focused on live perps monitoring, not historical research
- Portfolio page is explicitly a placeholder: full UI structure with mock data, designed to be trivially wired to real data when Phase 86 delivers
- Regime heatmap needs to handle 109 assets gracefully — multiple view modes serve different use cases (quick scan vs deep analysis)
- AMA/EMA Inspector is a diagnostic tool — shows HOW the adaptive moving average behaves, useful for tuning signal parameters

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 84-dashboard-perps-portfolio-regimes*
*Context gathered: 2026-03-23*
