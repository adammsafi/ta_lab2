---
phase: 52-operational-dashboard
plan: 01
subsystem: dashboard
tags: [streamlit, plotly, sqlalchemy, pandas, dashboard, query-modules]

# Dependency graph
requires:
  - phase: 39-streamlit-dashboard
    provides: existing dashboard foundation (db.py, charts.py, queries/ pattern)
  - phase: 44-paper-executor
    provides: cmc_positions, cmc_fills, cmc_orders tables
  - phase: 45-live-execution
    provides: cmc_executor_run_log, dim_executor_config tables
  - phase: 46-risk-engine
    provides: dim_risk_state, dim_risk_limits, cmc_risk_events tables
  - phase: 47-drift-guard
    provides: cmc_drift_metrics, v_drift_summary materialized view

provides:
  - 4 new query modules in queries/: trading.py, risk.py, drift.py, executor.py
  - 10 cached query functions with _engine prefix and @st.cache_data TTLs
  - 3 new Plotly chart builders in charts.py: build_pnl_drawdown_chart, build_tracking_error_chart, build_equity_overlay_chart
  - make_subplots import added to charts.py for dual-panel layouts

affects:
  - 52-02 (Trading page), 52-03 (Risk & Controls page), 52-04 (Drift Monitor page), 52-05 (Executor Status page) — all 4 pages consume these modules

# Tech tracking
tech-stack:
  added: []
  patterns:
    - _engine underscore prefix for @st.cache_data unhashable-engine bypass
    - .tolist() for Plotly x-axis dates to avoid tz-aware .values pitfall (MEMORY.md)
    - make_subplots shared_xaxes=True for stacked dual-panel charts
    - Empty DataFrame guard with fig.add_annotation before data traces

key-files:
  created:
    - src/ta_lab2/dashboard/queries/trading.py
    - src/ta_lab2/dashboard/queries/risk.py
    - src/ta_lab2/dashboard/queries/drift.py
    - src/ta_lab2/dashboard/queries/executor.py
  modified:
    - src/ta_lab2/dashboard/charts.py

key-decisions:
  - "TTLs follow research spec: 60s risk_state, 120s positions/fills/events/run_log, 300s limits/drift/config/pnl"
  - ".tolist() on datetime columns for Plotly x-axis (not .values) to avoid Windows tz-naive stripping"
  - "Exception handling at page level not query level, consistent with existing pipeline.py pattern"
  - "load_open_positions uses correlated subquery for latest regime per asset (avoids fan-out from GROUP BY)"

patterns-established:
  - "Operational query modules: module docstring + from __future__ import annotations + pandas/streamlit/sqlalchemy text imports"
  - "All query functions: @st.cache_data(ttl=N), _engine as first param, pd.to_datetime(utc=True) on timestamps"
  - "Chart builders: accept DataFrame, return go.Figure, handle empty input with annotation, plotly_dark template"
  - "Stacked dual-panel charts: make_subplots(rows=2, shared_xaxes=True, row_heights=[0.65, 0.35], vertical_spacing=0.05)"

# Metrics
duration: 3min
completed: 2026-02-25
---

# Phase 52 Plan 01: Operational Dashboard Foundation Summary

**4 query modules (10 cached functions) + 3 Plotly chart builders providing the complete data access layer for all 4 operational dashboard pages**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-25T23:50:12Z
- **Completed:** 2026-02-25T23:53:33Z
- **Tasks:** 2
- **Files modified:** 5 (4 created, 1 modified)

## Accomplishments

- Created `queries/trading.py` with `load_open_positions` (regime-joined), `load_recent_fills`, `load_daily_pnl_series` (with cumulative PnL, peak equity, drawdown_pct computed columns)
- Created `queries/risk.py` with `load_risk_state` (single-row dict, 60s TTL), `load_risk_limits`, `load_risk_events` (filterable by days + event_type)
- Created `queries/drift.py` with `load_drift_timeseries`, `load_drift_summary` (from v_drift_summary materialized view), `load_executor_configs`
- Created `queries/executor.py` with `load_executor_run_log` and `load_executor_config`
- Extended `charts.py` with `build_pnl_drawdown_chart` (2-panel make_subplots), `build_tracking_error_chart` (TE 5d+30d with threshold hlines), `build_equity_overlay_chart` (paper vs replay PIT)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create 4 operational query modules** - `b2a5c9e2` (feat)
2. **Task 2: Add operational chart builders to charts.py** - `cf748e5b` (feat)

## Files Created/Modified

- `src/ta_lab2/dashboard/queries/trading.py` - Positions (with regime label via correlated subquery), fills, daily PnL series queries
- `src/ta_lab2/dashboard/queries/risk.py` - Risk state dict, limits dict, events DataFrame queries
- `src/ta_lab2/dashboard/queries/drift.py` - Drift timeseries, drift summary, executor configs queries
- `src/ta_lab2/dashboard/queries/executor.py` - Executor run log and config queries
- `src/ta_lab2/dashboard/charts.py` - Added make_subplots import + 3 operational chart builder functions

## Decisions Made

- **Correlated subquery for latest regime**: `load_open_positions` uses `WHERE r.ts = (SELECT MAX(ts) FROM cmc_regimes WHERE id = p.asset_id AND tf = '1D')` as a correlated subquery rather than a JOIN with GROUP BY to avoid fan-out when a position has multiple regime timestamps on the same day.
- **Exception handling at page level**: No try/except inside query functions; consistent with existing `queries/pipeline.py` pattern. Pages handle exceptions and show `st.error()`.
- **`.tolist()` for Plotly x-axis dates**: Follows MEMORY.md critical warning about `series.values` stripping tz on Windows. Applied to all 3 chart builders.
- **TTLs exactly as specified**: 60s risk_state (safety-critical), 120s positions/fills/events/run_log (executor cadence), 300s limits/drift/pnl/config (rarely changing).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hook `mixed-line-ending` triggered on initial commit of query modules (Windows CRLF). Hook auto-fixed line endings; re-staged and committed successfully on second attempt. No code changes required.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 4 query modules importable and ready for consumption by operational pages
- Chart builders tested for import correctness; ready for use in page files
- Plan 52-02 (Trading page) can immediately import from `queries/trading.py` and use `build_pnl_drawdown_chart`
- Plans 52-03 through 52-05 similarly unblocked

---
*Phase: 52-operational-dashboard*
*Completed: 2026-02-25*
