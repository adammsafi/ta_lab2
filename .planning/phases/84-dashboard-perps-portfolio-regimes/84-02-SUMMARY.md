---
phase: 84-dashboard-perps-portfolio-regimes
plan: "02"
subsystem: ui
tags: [streamlit, dashboard, regimes, plotly, heatmap, fragment]

# Dependency graph
requires:
  - phase: 83-dashboard-backtest-signal-pages
    provides: dashboard page pattern, fragment auto-refresh, charts.py color constants
  - phase: 27-regimes
    provides: regimes, regime_flips, regime_stats, regime_comovement tables

provides:
  - Regime query layer (4 cached functions in queries/regimes.py)
  - Regime Heatmap page (pages/16_regime_heatmap.py) with cross-asset regime visualization
  - Overview metrics (total assets, % Up/Down/Sideways distribution)
  - Cross-asset heatmap top-30 default with expand-to-all toggle
  - Compact strip chart and paginated flip log dual-view timeline
  - EMA comovement table with clarifying "not cross-asset" caption

affects:
  - Phase 84 plans 03-05 (subsequent dashboard pages can reference heatmap page as precedent)
  - Any future regime-related dashboard features

# Tech tracking
tech-stack:
  added: []
  patterns:
    - REGIME_BAR_COLORS colorscale used to build custom Plotly Heatmap colorscale
    - split_part(l2_label, '-', 1) in SQL for trend_state derivation (no column in table)
    - AUTO_REFRESH_SECONDS constant with @st.fragment(run_every=AUTO_REFRESH_SECONDS)
    - pivot_table for week-binned regime heatmap; pivot for compact strip
    - st.dataframe with column_config for typed display of comovement data

key-files:
  created:
    - src/ta_lab2/dashboard/queries/regimes.py
    - src/ta_lab2/dashboard/pages/16_regime_heatmap.py
  modified: []

key-decisions:
  - "trend_state derived via split_part(l2_label, '-', 1) in SQL -- regimes table has no trend_state column"
  - "REGIME_BAR_COLORS from charts.py used to build _HEATMAP_COLORSCALE -- consistent color constants across dashboard"
  - "regime_comovement displayed as st.dataframe (NOT network graph) -- only 21 rows (7 assets x 3 EMA pairs); not feasible as network"
  - "Weekly binning for heatmap x-axis: mode per (symbol, week) reduces noise vs daily"
  - "AUTO_REFRESH_SECONDS=900 constant for fragment run_every; sidebar controls passed as function args"

patterns-established:
  - "Heatmap encoding: Up=1, Sideways=0, Down=-1 with custom colorscale from REGIME_BAR_COLORS"
  - "Sidebar controls outside fragment, passed as arguments to avoid widget-inside-fragment error"

# Metrics
duration: 4min
completed: "2026-03-23"
---

# Phase 84 Plan 02: Regime Heatmap Summary

**Cross-asset regime heatmap page with 4 cached SQL queries, Plotly heatmap (Up/Sideways/Down encoded 1/0/-1), compact strip + flip log timeline, and per-asset EMA comovement table.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-23T16:33:59Z
- **Completed:** 2026-03-23T16:38:20Z
- **Tasks:** 2
- **Files modified:** 2 created

## Accomplishments

- Built `queries/regimes.py` with 4 `@st.cache_data(ttl=900)` query functions covering all_assets, stats_summary, flips_recent, and comovement
- Built `pages/16_regime_heatmap.py` (506 lines) with overview cards, cross-asset heatmap, dual-view timeline, and EMA comovement table
- Correctly derived trend_state via `split_part(l2_label, '-', 1)` in SQL -- the regimes table has no trend_state column
- EMA comovement correctly displayed as a simple table with explicit "NOT cross-asset" caption

## Task Commits

Each task was committed atomically:

1. **Task 1: Create queries/regimes.py with 4 cached regime query functions** - `8a1b44eb` (feat)
2. **Task 2: Create pages/16_regime_heatmap.py -- Regime Heatmap dashboard page** - `0016f3c0` (feat)

**Plan metadata:** (docs commit below)

## Files Created/Modified

- `src/ta_lab2/dashboard/queries/regimes.py` - 4 cached query functions: load_regime_all_assets, load_regime_stats_summary, load_regime_flips_recent, load_regime_comovement
- `src/ta_lab2/dashboard/pages/16_regime_heatmap.py` - Regime Heatmap page with 4 sections and @st.fragment(run_every=900) auto-refresh

## Decisions Made

- **trend_state via split_part**: SQL derives trend_state as `split_part(r.l2_label, '-', 1)`. The regimes table has no trend_state column -- this is the canonical derivation method.
- **REGIME_BAR_COLORS as colorscale source**: Built `_HEATMAP_COLORSCALE` from `REGIME_BAR_COLORS` constants imported from charts.py. Consistent color semantics across all regime visualizations in the dashboard.
- **regime_comovement as table only**: Only 21 rows (7 assets x 3 EMA pairs). A network graph is infeasible. Displayed as `st.dataframe` with a clarifying caption: "This is NOT cross-asset correlation."
- **Weekly binning for heatmap**: Regime states binned to weekly frequency using `.dt.to_period("W")` and mode aggregation. Reduces noise vs daily granularity while preserving trend visibility.
- **AUTO_REFRESH_SECONDS constant**: Used `AUTO_REFRESH_SECONDS = 900` constant instead of literal `900` in `@st.fragment(run_every=...)`. Consistent with standard Python constant naming; ruff-format preserved this correctly.
- **ruff-format pre-commit hook**: Reformatted file on first commit (long line in `display_comov` DataFrame column list). Re-staged and committed clean -- standard pattern from Phase 83.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- ruff-format reformatted the page file on first commit (long line in column config list). Re-staged and committed clean -- standard pattern.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Regime Heatmap page ready at `pages/16_regime_heatmap.py`
- All 4 query functions importable and lint-clean
- Page uses established patterns (fragment, sidebar outside, unique keys, no set_page_config)
- Ready for Phase 84 plans 03-05

---
*Phase: 84-dashboard-perps-portfolio-regimes*
*Completed: 2026-03-23*
