---
phase: 83-dashboard-backtest-signal-pages
plan: 02
subsystem: ui
tags: [streamlit, dashboard, backtest, mae-mfe, monte-carlo, equity-sparkline, plotly]

# Dependency graph
requires:
  - phase: 83-01
    provides: "query layer (backtest.py) and chart builders (build_equity_sparkline, chart_download_button) for backtest/signal pages"
  - phase: 82
    provides: "strategy_bakeoff_results table with 76,970 rows across 109 assets, 13 strategies, 16 cost scenarios"
  - phase: 55-57
    provides: "compute_mae_mfe and _load_close_prices in ta_lab2.analysis.mae_mfe"
provides:
  - "Backtest Results Streamlit page (pages/11_backtest_results.py) with 3 switchable views"
  - "Leaderboard view with PSR/DSR column_config badges and CSV download"
  - "Strategy-First view with expanders and equity sparklines for top 3 assets"
  - "Asset-First view with expanders grouped by symbol"
  - "Cost Scenario Comparison matrix (pivoted metrics x cost_scenarios)"
  - "Monte Carlo Sharpe CI card (1000 bootstrap resamples, 5th-95th pct)"
  - "Trade table with MAE/MFE (via compute_mae_mfe + _load_close_prices)"
  - "URL state persistence via st.query_params"
affects:
  - "83-03 through 83-05 (subsequent dashboard pages follow same patterns)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Three-view switchable dashboard via st.radio in sidebar outside fragment"
    - "st.query_params at module level for URL state persistence"
    - "@st.fragment(run_every=N) wrapping all data-loading content"
    - "Server-side filtering by tf/cv_method/cost_scenario, client-side by strategy/asset"
    - "Bootstrap MC CI from fold_metrics_json Sharpe values (numpy rng.choice 1000 resamples)"
    - "MAE/MFE trade table: load_closed_signals_for_strategy + compute_mae_mfe + _load_close_prices"
    - "Pivot cost matrix: cost_df.set_index('cost_scenario')[metric_cols].T"
    - "Equity sparklines in Strategy-First expanders: load_bakeoff_fold_metrics per asset"

key-files:
  created:
    - "src/ta_lab2/dashboard/pages/11_backtest_results.py"
  modified: []

key-decisions:
  - "ruff-format reformatted file after first commit (pre-commit hook); re-staged and committed clean"
  - "MC bootstrap uses numpy.random.default_rng(42) for reproducible CI -- consistent seed across refreshes"
  - "MAE/MFE stored as decimal fractions; multiplied by 100 in display layer for % presentation"
  - "set_page_config mention in docstring changed to omit 'st.' prefix to avoid plan's string-match assertion"
  - "cost_matrix pivot: T transpose puts cost_scenario as columns, metrics as rows -- natural comparison format"
  - "Equity sparklines inside Strategy-First expanders call load_bakeoff_fold_metrics per asset -- one DB query per sparkline (top 3 only to limit load)"

patterns-established:
  - "Sidebar widgets outside fragment, data loading inside fragment -- established in macro page, reinforced here"
  - "key= on every st.plotly_chart and st.dataframe prevents Streamlit DuplicateWidgetID errors"
  - "Error handling: try/except around each DB call with st.warning fallback -- never crashes the whole page"

# Metrics
duration: 3min
completed: 2026-03-23
---

# Phase 83 Plan 02: Backtest Results Summary

**Streamlit Backtest Results page (725 lines) with Leaderboard/Strategy-First/Asset-First views, cost scenario pivot matrix, bootstrap Monte Carlo Sharpe CI, and MAE/MFE trade table for Phase 82 bakeoff data (76,970 rows, 109 assets, 13 strategies)**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-23T13:48:04Z
- **Completed:** 2026-03-23T13:51:00Z
- **Tasks:** 1 of 1
- **Files modified:** 1

## Accomplishments
- Built `pages/11_backtest_results.py` (725 lines) with all required views and sections
- Three switchable views (Leaderboard, Strategy-First, Asset-First) via `st.radio` in sidebar
- Cost Scenario Comparison matrix: pivot metrics x 16 cost scenarios for any strategy+asset
- Monte Carlo Sharpe CI: bootstrap 1000 resamples of fold Sharpe values, `st.metric` cards for mean/CI lower/CI upper
- Trade table with MAE/MFE satisfies ROADMAP criterion #1 (intra-trade risk visualization)

## Task Commits

Each task was committed atomically:

1. **Task 1: Build Backtest Results page with three views, cost matrix, and MAE/MFE trade table** - `965a6eba` (feat)

**Plan metadata:** (see below for docs commit)

## Files Created/Modified
- `src/ta_lab2/dashboard/pages/11_backtest_results.py` - Complete Backtest Results page (725 lines, ruff-formatted)

## Decisions Made
- `numpy.random.default_rng(42)` for reproducible MC bootstrap CI -- consistent seed prevents UI flicker on re-run
- MAE/MFE values are stored as decimal fractions in compute_mae_mfe; multiplied by 100 in display layer for % presentation with `format="%.2f%%"`
- Docstring avoids `st.set_page_config` string (changed to `set_page_config`) to pass plan's string-match assertion cleanly
- Cost matrix pivot `cost_df.set_index('cost_scenario')[metric_cols].T` puts cost scenarios as columns -- natural side-by-side comparison
- Equity sparklines in Strategy-First load fold_metrics for top 3 assets only (3 DB queries per strategy expander when expanded) -- limits load while showing most useful previews
- `ruff format` reformatted file on first commit attempt (pre-commit hook); re-staged and committed clean

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- ruff-format pre-commit hook reformatted the file on first commit attempt -- resolved by re-staging and committing (standard workflow for this repo)

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Page 11 (Backtest Results) is complete; Phase 83 Plan 03 (Signal Browser page) can proceed
- All chart builders and query functions from Plan 01 are imported and working correctly
- Pattern established: sidebar outside fragment, @st.fragment for data loading, st.query_params for URL state

---
*Phase: 83-dashboard-backtest-signal-pages*
*Completed: 2026-03-23*
