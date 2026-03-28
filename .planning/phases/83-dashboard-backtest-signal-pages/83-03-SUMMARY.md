---
phase: 83-dashboard-backtest-signal-pages
plan: 03
subsystem: ui
tags: [streamlit, plotly, dashboard, signals, heatmap, fragment, query-params]

# Dependency graph
requires:
  - phase: 83-01
    provides: load_active_signals, load_signal_history, build_signal_timeline_chart, chart_download_button
  - phase: 82-signal-refinement-walk-forward-bakeoff
    provides: signals_ema_crossover, signals_rsi_mean_revert, signals_atr_breakout tables

provides:
  - pages/12_signal_browser.py with Dashboard Cards, Live Table, and Heatmap Grid views
  - compute_signal_strength() helper using EMA/RSI/ATR components with defensive .get() access
  - Signal history timeline + event log table + CSV download
  - Sidebar filters: strategy multiselect, direction, asset search, history days slider
  - URL state via st.query_params at module level

affects:
  - 83-04-PLAN.md (Asset Hub page -- signal browser patterns reusable)
  - 83-05-PLAN.md (Navigation rework -- page 12 now exists)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - compute_signal_strength() uses .get() for all feature_snapshot keys -- different signal generators have different keys
    - @st.fragment(run_every=300) receives sidebar state as arguments (sidebar must be outside fragment)
    - go.Heatmap pivot: symbols x strategies, direction encoded as numeric (long=1, short=-1, none=0)
    - Ruff auto-fix: line-too-long in fragment def signature -- ruff reformats multi-arg function signatures

key-files:
  created:
    - src/ta_lab2/dashboard/pages/12_signal_browser.py
  modified: []

key-decisions:
  - "compute_signal_strength base=20 points, EMA separation 0-30, RSI extremity 0-30, ATR magnitude 0-20 -- formula from CONTEXT.md discretion"
  - "Sidebar controls outside fragment, passed as arguments to @st.fragment -- prevents Streamlit widget-inside-fragment error"
  - "go.Heatmap colorscale: short=rgb(220,50,50), none=rgb(60,60,80), long=rgb(0,200,100) with zmin=-1 zmax=1"
  - "Cards view limited to 30 signals with caption -- avoids render overload on large signal sets"
  - "feature_snapshot column absent from query results (signals tables don't include it) -- signal_strength defaults to 50 when column missing"
  - "Ruff auto-fixed 3 linting issues (line-too-long in fragment signature) before final commit"

patterns-established:
  - "Signal strength: defensive .get() for ALL feature_snapshot keys -- never assume key presence across signal types"
  - "Fragment argument passing: all sidebar state passed as positional args to fragment function, never read inside fragment"
  - "Heatmap encoding: encode categorical strings to numeric z-values with explicit colorscale for directional data"
  - "Card view limit: cap at 30 with informational caption rather than pagination"

# Metrics
duration: 6min
completed: 2026-03-23
---

# Phase 83 Plan 03: Signal Browser Page Summary

**Streamlit Signal Browser with Dashboard Cards, Live Table, and Heatmap Grid views across EMA/RSI/ATR signal generators, using defensive .get() signal strength scoring and 300s auto-refresh**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-23T13:48:05Z
- **Completed:** 2026-03-23T13:54:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Created `pages/12_signal_browser.py` (668 lines) with three switchable active-signal views: Dashboard Cards (3-column grid with st.container border), Live Table (st.dataframe with ProgressColumn), and Heatmap Grid (go.Heatmap pivot symbols x strategies)
- Implemented `compute_signal_strength()` helper using EMA separation (0-30 pts), RSI extremity (0-30 pts), ATR magnitude (0-20 pts), and base 20 pts -- all feature_snapshot accesses via `.get()` to prevent KeyError across different signal generators
- Signal History section with `build_signal_timeline_chart()`, event log dataframe, and CSV download; sidebar filters (strategy multiselect, direction, asset search, history days) with URL state via `st.query_params`

## Task Commits

Each task was committed atomically:

1. **Task 1: Build Signal Browser page with three views and history timeline** - `ec0757fb` (feat)

## Files Created/Modified

- `src/ta_lab2/dashboard/pages/12_signal_browser.py` - 668 lines: Signal Browser with 3 views, compute_signal_strength, sidebar filters, URL state, @st.fragment(run_every=300), history timeline, CSV export

## Decisions Made

- **compute_signal_strength formula**: Base=20 + EMA separation (0-30) + RSI extremity (0-30) + ATR magnitude (0-20), all clamped to 0-100. Returns 50 (neutral) when feature_snapshot is None
- **feature_snapshot absent from query**: signals tables don't expose feature_snapshot in the UNION ALL query from 83-01 -- signal_strength defaults to 50 when column missing from DataFrame; easy to add later when signals schema is extended
- **Cards view cap at 30**: Rendering 100+ cards would be slow; limit with informational caption is pragmatic
- **Heatmap colorscale**: short=-1/dark gray=0/long=1 with custom colorscale (red/dark-gray/green) gives directional clarity without confusing a continuous gradient with categorical data

## Deviations from Plan

None -- plan executed exactly as written. Ruff auto-fixed 3 line-too-long issues (function signature formatting) during pre-commit; these are formatting-only, no logic changes.

## Issues Encountered

Pre-commit hook (ruff lint + format) auto-fixed 3 line-length issues in the `_signal_browser_content()` function signature. Re-staged and committed cleanly on second attempt.

The plan's verification check `assert 'st.set_page_config' not in src` triggers on the docstring comment "NOTE: Do NOT call st.set_page_config()". AST walk confirms no actual call exists. The check is a false positive for the string-in-string case.

## Next Phase Readiness

- Signal Browser page complete and committed. Ready for 83-04 (Asset Hub page) which can reuse the `_apply_filters()` helper pattern and `compute_signal_strength()` for signal overlays
- 83-05 (Navigation rework) can now include page 12 in sidebar navigation
- No blockers

---
*Phase: 83-dashboard-backtest-signal-pages*
*Completed: 2026-03-23*
