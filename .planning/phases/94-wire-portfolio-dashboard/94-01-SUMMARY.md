---
phase: 94-wire-portfolio-dashboard
plan: 01
subsystem: ui
tags: [streamlit, portfolio, dashboard, plotly, sqlalchemy]

# Dependency graph
requires:
  - phase: 86-portfolio-construction
    provides: portfolio_allocations table with optimizer weights
provides:
  - Live portfolio dashboard page querying portfolio_allocations
  - Cached query module for portfolio allocation data
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "COALESCE(ci.symbol, da.symbol) for ticker symbol resolution in dashboard queries"
    - "DISTINCT ON (asset_id) for latest-per-asset allocation queries"

key-files:
  created:
    - src/ta_lab2/dashboard/queries/portfolio.py
  modified:
    - src/ta_lab2/dashboard/pages/15_portfolio.py

key-decisions:
  - "Used COALESCE(cmc_da_info.symbol, dim_assets.symbol) for ticker resolution, matching regimes.py pattern"
  - "Flat treemap layout (no strategy parents) since portfolio_allocations has no strategy column"
  - "Weights displayed as percentages (weight * 100) for all charts; raw 0-1 stored in DB"

patterns-established:
  - "Portfolio query module: _engine pattern, @st.cache_data(ttl=300), text() SQL"

# Metrics
duration: 4min
completed: 2026-03-28
---

# Phase 94 Plan 01: Wire Portfolio Dashboard Summary

**Portfolio dashboard wired to live portfolio_allocations via 3 cached query functions, replacing all numpy.random mock data with optimizer selector and empty-state handling**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-29T01:34:16Z
- **Completed:** 2026-03-29T01:38:30Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created portfolio query module with 3 cached functions (load_available_optimizers, load_latest_allocations, load_allocation_history)
- Rewired 15_portfolio.py from numpy.random mock data to live portfolio_allocations queries
- Added optimizer selector in sidebar with graceful empty-state handling
- Removed all mock data constants, numpy import, and 3 TODO(Phase-86) markers

## Task Commits

Each task was committed atomically:

1. **Task 1: Create portfolio query module** - `ac2093d7` (feat)
2. **Task 2: Wire 15_portfolio.py to live data** - `fc9d1a67` (feat)

## Files Created/Modified
- `src/ta_lab2/dashboard/queries/portfolio.py` - 3 cached query functions for portfolio_allocations
- `src/ta_lab2/dashboard/pages/15_portfolio.py` - Live-data dashboard page (149 additions, 241 deletions)

## Decisions Made
- Used COALESCE(cmc_da_info.symbol, dim_assets.symbol) for proper ticker symbol resolution, matching the pattern in regimes.py and research.py
- Flat treemap (no strategy parent grouping) since portfolio_allocations stores optimizer type, not strategy
- Single green color for bet size bars (no risk tier colors since risk_budget_pct not in portfolio_allocations)
- Portfolio metrics panel replaces risk budget progress bars (NAV, asset count, optimizer name, condition number)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Portfolio dashboard is fully wired to live data
- Page handles empty portfolio_allocations gracefully with informational message
- Closes Break 2 (MEDIUM) from v1.2.0 milestone audit

---
*Phase: 94-wire-portfolio-dashboard*
*Completed: 2026-03-28*
