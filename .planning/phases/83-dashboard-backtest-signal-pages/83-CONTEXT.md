# Phase 83: Dashboard — Backtest & Signal Pages - Context

**Gathered:** 2026-03-23
**Status:** Ready for planning

<domain>
## Phase Boundary

Dashboard surfaces backtest results and live signal state so the user can monitor strategy performance and signal activity without SQL. Includes:
- Backtest Results page with equity curves, PSR/DSR badges, Monte Carlo CI, trade table, cost breakdown
- Signal Browser page with active signals, history, filtering
- OHLCV candlestick charts replacing plain close lines across all price-data pages
- All new pages follow existing query-layer pattern (queries/*.py + pages/*.py)
- Charts have HTML download buttons

NOT in scope: Perps data, portfolio allocation, regime heatmap (Phase 84), cache TTL fixes and UI polish (Phase 85).

</domain>

<decisions>
## Implementation Decisions

### Backtest Results Layout
- **Three switchable views**: strategy-first, asset-first, and leaderboard. User can toggle between all three.
- **Primary visual**: Equity curve sparkline thumbnails for quick visual comparison
- **Supporting metrics**: Sharpe + DSR/PSR colored badges and composite scores easily accessible (adjacent columns or hover/click)
- **Cost scenario comparison**: Side-by-side table showing all 16 cost scenarios in columns, metrics in rows. Full degradation visibility.
- **Monte Carlo**: Summary card at top ("Sharpe 95% CI: [0.42, 0.89]") PLUS expandable interactive Plotly fan chart with 5th/25th/50th/75th/95th percentile bands

### Signal Browser
- **Three active signal views**: Dashboard cards (asset name, strategy, direction, entry time, PnL), live sortable table, AND heatmap grid (assets on Y, strategies on X, color = direction). User switches between all three.
- **Signal history**: Timeline chart for visual overview (horizontal bars showing signal on/off periods) + event log table below for chronological detail
- **Filtering**: Multi-filter sidebar with: strategy, asset, direction (long/short/flat), date range, signal strength, cost scenario
- **Confidence display**: Numeric signal strength score (0-100), derived from IC-IR weights / composite score / fold agreement

### Candlestick Charts
- **Scope**: Every page showing price data gets OHLCV candlesticks — Research Explorer, Backtest Results, Signal Browser, Asset Hub, any asset-level view
- **Overlays**: Full indicator suite with checkboxes to toggle each: EMA lines, AMA efficiency ratio, Bollinger Bands, RSI subplot, volume bars, regime band shading
- **Timeframe switching**: TF buttons directly on chart toolbar (1H / 4H / 1D / 1W) for quick switching without page reload
- **Chart technology**: Full Plotly interactive — zoom, pan, hover tooltips, crosshairs

### Cross-Page Navigation
- **Sidebar reorganization**: Rethink the full sidebar into logical groups (e.g., Data, Analysis, Trading, Operations). This may move existing page placements.
- **Deep linking**: Click-through navigation everywhere — click an asset in backtest results → signal browser for that asset → candlestick chart. Full cross-referencing between pages.
- **Asset hub page**: Unified asset detail view combining candlestick chart, active signals, backtest results, regime state — all in one place for the selected asset
- **State persistence**: URL query params for selected asset, strategy, TF. Sharable links, back button works.

### Claude's Discretion
- Exact sidebar group names and page ordering within groups
- Loading skeleton / spinner design
- Error state handling for missing data
- Chart color scheme (as long as it's consistent)
- Exact sparkline implementation for equity curve thumbnails
- How to compute the 0-100 signal strength score from available data
- Whether the asset hub is a separate page or a modal/drawer

</decisions>

<specifics>
## Specific Ideas

- Dashboard should feel like a complete trading terminal — all views interconnected, not isolated pages
- URL query params for state means someone can bookmark "BTC backtest results, Kraken cost matrix, strategy-first view" and return to it
- Full Plotly interactive charts are non-negotiable — this is the primary analysis tool, not a reporting dashboard
- Phase 82 produced 76,298 results across 109 assets, 12 strategies, 16 cost scenarios — the backtest page must handle this data volume without being overwhelming

</specifics>

<deferred>
## Deferred Ideas

- **Pipeline health monitor**: Status of daily refresh pipeline (last run times, success/fail, data freshness per table) — Phase 84 or new phase
- **IC/Feature quality view**: Feature selection results from Phase 80 (IC-IR scores, stationarity, active vs pruned) — Phase 84 or new phase
- **GARCH vol dashboard**: Phase 81 GARCH forecasts, model comparison, vol surfaces, blend weights — Phase 84 or new phase
- **Portfolio/exposure summary**: Current positions, exposure by asset, PnL attribution, risk gate status — Phase 84 (Portfolio Allocation view) or Phase 86

</deferred>

---

*Phase: 83-dashboard-backtest-signal-pages*
*Context gathered: 2026-03-23*
