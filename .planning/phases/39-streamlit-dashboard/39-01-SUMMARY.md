---
phase: 39-streamlit-dashboard
plan: "01"
subsystem: ui
tags: [streamlit, sqlalchemy, nullpool, dashboard, multipage]

# Dependency graph
requires:
  - phase: 38-feature-experimentation
    provides: cmc_ic_results table and feature pipeline that research queries target
  - phase: 27-regime-pipeline
    provides: cmc_regimes table queried by load_regimes()
provides:
  - Streamlit dashboard package structure (src/ta_lab2/dashboard/)
  - Windows-compatible dark theme config (.streamlit/config.toml)
  - NullPool DB engine singleton (db.py with get_engine())
  - Pipeline Monitor cached query functions (queries/pipeline.py)
  - Research Explorer cached query functions (queries/research.py)
  - Multipage app entrypoint with st.navigation (app.py)
  - Placeholder page files for Plans 03/04 to fill
affects:
  - 39-02 (landing page will import from db.py + query modules)
  - 39-03 (pipeline monitor page imports from queries/pipeline.py)
  - 39-04 (research explorer page imports from queries/research.py)

# Tech tracking
tech-stack:
  added: [streamlit==1.44.0]
  patterns:
    - "_engine prefix pattern: all @st.cache_data query functions accept _engine as first arg so Streamlit skips hashing the engine object"
    - "NullPool singleton: @st.cache_resource get_engine() is the single engine creation point"
    - "Allowlist pattern: stats table names hardcoded, never derived from user input"

key-files:
  created:
    - .streamlit/config.toml
    - src/ta_lab2/dashboard/__init__.py
    - src/ta_lab2/dashboard/db.py
    - src/ta_lab2/dashboard/pages/__init__.py
    - src/ta_lab2/dashboard/pages/1_landing.py
    - src/ta_lab2/dashboard/pages/2_pipeline_monitor.py
    - src/ta_lab2/dashboard/pages/3_research_explorer.py
    - src/ta_lab2/dashboard/queries/__init__.py
    - src/ta_lab2/dashboard/queries/pipeline.py
    - src/ta_lab2/dashboard/queries/research.py
    - src/ta_lab2/dashboard/app.py
  modified: []

key-decisions:
  - "fileWatcherType=poll in config.toml: avoids inotify issues on Windows"
  - "_engine prefix on all query functions: Streamlit's cache_data skips hashing unhashable SQLAlchemy engines when arg is underscore-prefixed"
  - "TTL slider is UX-only: actual cache TTL is fixed at 300s in decorators; Refresh Now button calls st.cache_data.clear()"
  - "split_part(l2_label, '-', 1/2) in SQL for regimes: cmc_regimes has no trend_state/vol_state columns"
  - "tf_days_nominal used for TF ordering in load_tf_list: NOT tf_days"

patterns-established:
  - "Query isolation: each page imports from its own query module (pipeline.py or research.py)"
  - "set_page_config called only in app.py: never in page files"
  - "Allowlist injection safety: stats table names come from a Python list, never user input"

# Metrics
duration: 2min
completed: 2026-02-24
---

# Phase 39 Plan 01: Streamlit App Skeleton Summary

**Streamlit dashboard skeleton with NullPool DB layer, 10 cached query functions across 2 modules, and st.navigation multipage shell for Pipeline Monitor and Research Explorer**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-24T13:13:19Z
- **Completed:** 2026-02-24T13:15:51Z
- **Tasks:** 3
- **Files modified:** 11 created

## Accomplishments

- Dark-theme Windows-compatible Streamlit config with poll-based file watcher
- NullPool engine singleton via @st.cache_resource wrapping resolve_db_url()
- 4 cached pipeline query functions: load_table_freshness, load_stats_status, load_asset_coverage, load_alert_history
- 6 cached research query functions: load_asset_list, load_tf_list, load_ic_results, load_feature_names, load_regimes, load_close_prices
- Multipage app.py with st.navigation (3 sections), shared sidebar with TTL slider and Refresh Now button
- Placeholder pages so app.py runs without errors immediately

## Task Commits

Each task was committed atomically:

1. **Task 1: Windows config + DB layer + package structure** - `ba0d029c` (feat)
2. **Task 2: Pipeline query module + Research query module** - `2c5956cf` (feat)
3. **Task 3: App entrypoint with st.navigation and shared sidebar** - `5b3c685f` (feat)

## Files Created/Modified

- `.streamlit/config.toml` - Windows poll watcher + dark theme
- `src/ta_lab2/dashboard/__init__.py` - Package init
- `src/ta_lab2/dashboard/db.py` - NullPool engine singleton via @st.cache_resource
- `src/ta_lab2/dashboard/pages/__init__.py` - Package init
- `src/ta_lab2/dashboard/pages/1_landing.py` - Placeholder Dashboard Home
- `src/ta_lab2/dashboard/pages/2_pipeline_monitor.py` - Placeholder Pipeline Monitor
- `src/ta_lab2/dashboard/pages/3_research_explorer.py` - Placeholder Research Explorer
- `src/ta_lab2/dashboard/queries/__init__.py` - Package init
- `src/ta_lab2/dashboard/queries/pipeline.py` - 4 cached pipeline query functions
- `src/ta_lab2/dashboard/queries/research.py` - 6 cached research query functions
- `src/ta_lab2/dashboard/app.py` - Streamlit entrypoint with st.navigation + sidebar

## Decisions Made

- Used `fileWatcherType = "poll"` in config.toml to avoid Windows inotify issues
- `_engine` underscore prefix on all query functions: Streamlit's @st.cache_data skips hashing unhashable SQLAlchemy engine objects when the parameter name starts with underscore
- Cache TTL slider in sidebar is UX-only (shows 300s); actual TTL is fixed in @st.cache_data decorators. Refresh Now calls st.cache_data.clear() to force a refresh.
- `split_part(l2_label, '-', 1)` and `split_part(l2_label, '-', 2)` in regimes SQL: cmc_regimes table has no trend_state/vol_state columns, they must be derived from l2_label
- `tf_days_nominal` used in load_tf_list ORDER BY (NOT tf_days -- that column does not exist in dim_timeframe)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-commit hook (mixed-line-ending) auto-fixed CRLF line endings on Windows-created files. Required re-staging fixed files before commit succeeded. This is normal Windows/git behavior, not a code issue.

## User Setup Required

None - no external service configuration required beyond existing DB connection.

## Next Phase Readiness

- All query modules are importable and ready for page files to consume
- `streamlit run src/ta_lab2/dashboard/app.py` starts the app with 3-page navigation
- Plan 02 (landing page) and Plans 03/04 (monitor/research content) can import directly from `ta_lab2.dashboard.db` and `ta_lab2.dashboard.queries.*`
- No blockers

---
*Phase: 39-streamlit-dashboard*
*Completed: 2026-02-24*
