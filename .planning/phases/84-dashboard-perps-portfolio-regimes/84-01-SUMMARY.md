---
phase: 84-dashboard-perps-portfolio-regimes
plan: 01
subsystem: ui
tags: [streamlit, plotly, hyperliquid, perps, funding-rates, ohlcv, dashboard]

# Dependency graph
requires:
  - phase: 83-dashboard-backtest-signal-pages
    provides: Dashboard page pattern (@st.fragment, sidebar-outside-fragment, query-layer)
  - phase: 74-foundation-shared-infrastructure
    provides: hyperliquid schema tables (hl_assets, hl_candles, hl_funding_rates, hl_open_interest)
provides:
  - queries/perps.py with 6 cached HL query functions
  - pages/14_perps.py with 4-section Hyperliquid Perps dashboard page
affects:
  - 84-02 (portfolio placeholder page - follows same page pattern)
  - 84-03 (ama.py queries - follows same query layer pattern)
  - 84-04 (regime heatmap - follows same page pattern)
  - 84-05 (app.py sidebar - needs pages 14-17 registered)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "cross-schema SQL: hyperliquid.hl_* prefix for all HL queries"
    - "@st.fragment(run_every=900) wraps content; sidebar controls passed as args"
    - "plotly_dark template + go.Candlestick with rangeslider_visible=False"
    - "make_subplots(shared_xaxes=True) for candle+OI stacked chart"
    - "pivot_table for heatmap: rows=symbol, columns=date, values=avg_funding_rate"

key-files:
  created:
    - src/ta_lab2/dashboard/queries/perps.py
    - src/ta_lab2/dashboard/pages/14_perps.py
  modified: []

key-decisions:
  - "hl_open_interest (82K rows Coinalyze) for OI timeseries, NOT hl_oi_snapshots (only 3 timestamps)"
  - "interval='1d' only for candles -- hourly covers only 3 days for most assets"
  - "load_hl_perp_list ttl=3600 (dimension data); all other functions ttl=900"
  - "make_subplots for candle+OI: conditional has_oi check to show single or stacked layout"
  - "pivot.values.tolist() on numeric heatmap DataFrame (not datetime) -- no tz-aware pitfall"
  - "perp_options dict passed into fragment as argument (not re-loaded inside fragment)"

patterns-established:
  - "cross-schema query pattern: hyperliquid.hl_* with schema prefix in all SQL"
  - "HL asset_id namespace is independent of public.dim_assets.id -- never cross-join"
  - "OI source selection: hl_open_interest for time series, hl_assets.open_interest for current"

# Metrics
duration: 4min
completed: 2026-03-23
---

# Phase 84 Plan 01: Hyperliquid Perps Dashboard Summary

**Streamlit Perps page with 6 cross-schema HL query functions, funding heatmap, candlestick+OI chart, and 15-minute auto-refresh**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-23T16:33:15Z
- **Completed:** 2026-03-23T16:37:11Z
- **Tasks:** 2
- **Files created:** 2

## Accomplishments

- Built `queries/perps.py` with 6 `@st.cache_data` functions covering perp list, top perps, funding history, funding heatmap, daily candles, and Coinalyze OI time series
- Built `pages/14_perps.py` with 4 sections: top perps table + metric cards, funding rate analysis (single + multi-asset tabs), funding heatmap (assets x days), and candlestick + OI chart
- All SQL uses `hyperliquid.*` schema prefix; OI correctly routes to `hl_open_interest` (82K rows) not `hl_oi_snapshots` (3 timestamps)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create queries/perps.py** - `8c74b43c` (feat)
2. **Task 2: Create pages/14_perps.py** - `481b858b` (feat, included with ama.py in same commit due to pre-commit hook behavior)

## Files Created

- `src/ta_lab2/dashboard/queries/perps.py` - 6 cached HL query functions (load_hl_perp_list, load_hl_top_perps, load_hl_funding_history, load_hl_funding_heatmap, load_hl_candles, load_hl_oi_timeseries)
- `src/ta_lab2/dashboard/pages/14_perps.py` - Full Hyperliquid Perps page (542 lines)

## Decisions Made

- `hl_open_interest` (82K rows, Coinalyze daily OI) for OI time series; `hl_oi_snapshots` has only 3 point-in-time timestamps from 2026-03-11 and is not a time series
- `interval='1d'` only for candles -- `interval='1h'` covers only 3 days for most assets and would show empty charts
- `load_hl_perp_list` uses ttl=3600 (dimension data); all data query functions use ttl=900
- `make_subplots(rows=2, shared_xaxes=True)` for candle+OI stacked layout; conditional `has_oi` check decides whether to use 1-row or 2-row layout
- `pivot.values.tolist()` on the heatmap DataFrame is safe -- it's a numeric pivot table, not a tz-aware datetime Series (no `.values` tz-aware pitfall)
- `perp_options` dict computed at module level and passed into fragment as `multi_symbols` + `perp_options` -- avoids re-loading inside fragment on each auto-refresh tick

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hook `ruff-format` reformatted both files on first commit attempt (standard pattern in this codebase). Re-staged and committed cleanly on second attempt.
- Pre-commit stash conflict: unstaged modified files from `refactor/strip-cmc-prefix-add-venue-id` branch conflicted with hook stash on the 14_perps.py commit; the hook resolved itself by allowing the commit through after the second stash attempt.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `pages/14_perps.py` ready; needs to be registered in `app.py` sidebar (Plan 05)
- Query pattern established for Plans 02-04 (portfolio placeholder, regime heatmap, AMA inspector)
- All 6 perps query functions verified importable and lint-clean

---
*Phase: 84-dashboard-perps-portfolio-regimes*
*Completed: 2026-03-23*
