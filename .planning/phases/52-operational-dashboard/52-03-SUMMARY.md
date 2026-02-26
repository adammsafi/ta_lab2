---
phase: 52-operational-dashboard
plan: "03"
subsystem: ui
tags: [streamlit, plotly, drift-monitor, executor-status, auto-refresh, st-fragment]

# Dependency graph
requires:
  - phase: 52-01
    provides: "4 query modules (drift.py, executor.py, risk.py, trading.py) + 3 chart builders (build_tracking_error_chart, build_equity_overlay_chart, build_pnl_drawdown_chart)"

provides:
  - "Drift Monitor page (8_drift_monitor.py): TE time series chart with threshold lines (DASH-L04), paper vs replay equity overlay, drift summary cards, attribution breakdown expander"
  - "Executor Status page (9_executor_status.py): run log with duration + JSON config_ids parsing, active strategy configs, summary KPIs, failed runs detail"

affects:
  - "52-02 (already completed adjacent wave -- both operational page sets now available)"
  - "app.py wiring if multi-page navigation needs updating"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "@st.fragment(run_every=900) for auto-refresh without full page rerender"
    - "Fragment receives engine + sidebar control values as args; sidebar outside fragment"
    - "Alert banners (warning/error) placed outside fragment so they always render"
    - "Graceful empty-data handling via st.info() at every data load point"

key-files:
  created:
    - src/ta_lab2/dashboard/pages/8_drift_monitor.py
    - src/ta_lab2/dashboard/pages/9_executor_status.py
  modified: []

key-decisions:
  - "Fragment receives sidebar values as arguments (not read inside fragment) to avoid st.sidebar inside fragment restriction"
  - "load_drift_timeseries requires a config_id; when none selected, show info prompt instead of querying"
  - "Risk limits (threshold_5d, threshold_30d) loaded inside fragment so they refresh with new data"
  - "Attribution columns are optional -- detected at runtime via column presence check"
  - "config_ids JSON TEXT parsing done with json.loads fallback to string display"
  - "Duration column computed from finished_at - started_at as timedelta, formatted as seconds"

patterns-established:
  - "Auto-refresh pattern: @st.fragment(run_every=AUTO_REFRESH_SECONDS) with AUTO_REFRESH_SECONDS = 900 at module level"
  - "Sidebar outside fragment, values passed as function args into fragment"
  - "try/except wrapping every data load with st.warning on failure (not st.error -- page remains usable)"

# Metrics
duration: 8min
completed: 2026-02-25
---

# Phase 52 Plan 03: Drift Monitor and Executor Status Pages Summary

**Two operational Streamlit pages with auto-refresh: Drift Monitor with TE time series + threshold lines (DASH-L04) + equity overlay, and Executor Status with run log, KPIs, and failed runs detail**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-25T16:58:47Z
- **Completed:** 2026-02-25T17:06:20Z
- **Tasks:** 2
- **Files modified:** 2 (created)

## Accomplishments

- Drift Monitor page (316 lines): tracking error time series with 5d/30d threshold lines satisfying DASH-L04, paper vs replay equity overlay, 4-card summary KPIs, attribution breakdown expander, alert banners for drift_paused and trading halted states
- Executor Status page (276 lines): 4 KPI cards for latest run, active strategies config table, full run history with duration/config_ids parsing/status formatting, failed runs expander with error messages
- Both pages use `@st.fragment(run_every=900)` for 15-minute auto-refresh without full page rerenders

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Drift Monitor page (8_drift_monitor.py)** - `44b95e0a` (feat)
2. **Task 2: Create Executor Status page (9_executor_status.py)** - `853a6133` (feat)

**Plan metadata:** (see docs commit below)

## Files Created/Modified

- `src/ta_lab2/dashboard/pages/8_drift_monitor.py` - Drift Monitor page: TE chart, equity overlay, summary cards, attribution breakdown, alert banners
- `src/ta_lab2/dashboard/pages/9_executor_status.py` - Executor Status page: run log, config summary, KPIs, failed runs expander

## Decisions Made

- Sidebar controls are placed outside the `@st.fragment` because Streamlit prohibits `st.sidebar` calls inside fragments. Sidebar values are passed as function arguments into the fragment.
- `load_drift_timeseries` requires a `config_id`; when no config is selected (empty dim_executor_config), show an informational prompt rather than querying with NULL.
- Risk limit thresholds (5d/30d) are loaded inside the fragment so they refresh alongside the timeseries data.
- Attribution columns (attr_fee_delta, etc.) are detected at runtime -- the column list is filtered to what actually exists in the returned DataFrame, gracefully degrading to an info message.
- `config_ids` TEXT JSON is parsed with `json.loads`, falling back to raw string display on parse failure.
- Run duration is computed as `finished_at - started_at` total_seconds, formatted as "{N}s".

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-commit hooks (ruff-format + mixed-line-ending) reformatted both files after initial write due to CRLF line endings from the Write tool on Windows. Both files were re-staged and committed successfully after hook reformatting.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 4 operational pages are now complete: Trading Monitor (6), Risk & Controls (7), Drift Monitor (8), Executor Status (9)
- Phase 52 Wave 2 complete; ready for app.py wiring (52-02 if not yet done) or phase completion
- Pages will show "No data yet" info messages until drift monitor scripts and executor runs populate the underlying tables

---
*Phase: 52-operational-dashboard*
*Completed: 2026-02-25*
