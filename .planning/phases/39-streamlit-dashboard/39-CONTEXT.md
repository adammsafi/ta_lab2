# Phase 39: Streamlit Dashboard - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

A single Streamlit app with two modes — Pipeline Monitor (run status, data freshness, stats PASS/FAIL) and Research Explorer (IC scores, regime timelines) — plus a summary landing page. All DB queries cached with NullPool. Windows-compatible. Read-only (no write-path from the UI).

Requirements: DASH-01, DASH-02, DASH-03, DASH-04

Does NOT include triggering IC evaluations or experiments from the UI, equity curve visualization, or feature comparison views.

</domain>

<decisions>
## Implementation Decisions

### Page Structure & Navigation
- **Multipage app**: Separate .py files in `pages/` directory. Streamlit multipage app with sidebar auto-navigation. Most scalable for adding future pages.
- **Landing page**: Dashboard overview (summary) showing key stats from both modes — pipeline health summary + top IC scores — with links to drill into Pipeline Monitor or Research Explorer.
- **Global filters**: Claude's discretion — pick the pattern that works best with Streamlit's multipage session state.
- **Dark theme**: Dark background default. Common for trading/finance dashboards. Configure via `.streamlit/config.toml`.

### Pipeline Monitor Content
- **Table detail**: Expandable rows — summary row per table family (Bars, EMAs, AMAs, Returns, Vol, TA, Regimes, Features), click to expand for per-table breakdown (multi_tf, cal_us, etc.).
- **Data freshness**: Traffic light badges (green < 1 day, yellow 1-3 days, red > 3 days) PLUS hover/tooltip with exact refresh timestamp. Visual scan + precision on demand.
- **Asset coverage grid**: Yes — matrix of assets x table families showing coverage status. Uses `asset_data_coverage` table data. Helps identify which assets need attention.
- **Alert history**: Claude's discretion — include if readily available from existing stats runner tables.

### Research Explorer Content
- **Research views**: IC score table for selected asset/TF, IC decay chart (Plotly), and regime timeline overlay. Core research views from Phase 37. No equity curves or feature comparison in v0.9.0.
- **Selection UX**: Text search with autocomplete for feature names, plus dropdown selectboxes for asset and TF.
- **Regime display**: Both — price chart with colored regime background bands (Up=green, Down=red, Sideways=gray) on Research Explorer, AND standalone regime timeline bar chart.
- **Read-only**: Dashboard only displays existing results from `cmc_ic_results` and `cmc_regimes`. No IC evaluation runs triggered from the UI.

### Auto-refresh & Interactivity
- **Refresh model**: Manual refresh button only. No auto-polling. Simpler, less DB load. User clicks 'Refresh' to reload.
- **Charts**: Interactive Plotly — hover tooltips, zoom, pan, export. Consistent with Phase 37 IC decay plot helpers (`plot_ic_decay`, etc.).
- **Export**: CSV download for tables + PNG/SVG for charts. Useful for sharing results outside the dashboard.
- **Cache TTL**: Configurable via sidebar slider/input (default 300s). Power users can tune freshness vs performance.

### Claude's Discretion
- Global sidebar filters vs per-page filters (session state approach)
- Alert history panel inclusion and design
- Exact multipage app file structure (pages/ naming convention)
- Landing page layout and metric card design
- How feature search autocomplete is populated
- Color palette for regime bands (exact hex values)
- Cache TTL slider range and step size
- Export button placement and format options

</decisions>

<specifics>
## Specific Ideas

- Reuse Phase 37 Plotly helpers (`plot_ic_decay`, `plot_rolling_ic`) directly in the Research Explorer — no duplicate chart code
- Dark theme aligns with Plotly's dark templates (`plotly_dark`) for consistent chart appearance
- `asset_data_coverage` table already exists and tracks per-asset per-table row counts and date ranges — direct feed for the coverage grid
- NullPool is already the project standard for one-shot DB connections; dashboard queries should follow the same pattern
- `fileWatcherType = "poll"` in `.streamlit/config.toml` is required for Windows compatibility (documented in DASH-04)

</specifics>

<deferred>
## Deferred Ideas

- Equity curve visualization — would need to read from cmc_backtest_runs; add when backtest pipeline is more mature
- Feature comparison side-by-side view — useful but not core for v0.9.0 research explorer
- Triggering IC evaluations from the dashboard — adds write-path complexity; CLI is the right invocation path
- Live auto-refresh / WebSocket push — v0.9.0 is batch/research, not real-time

</deferred>

---

*Phase: 39-streamlit-dashboard*
*Context gathered: 2026-02-24*
