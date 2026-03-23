---
phase: 83-dashboard-backtest-signal-pages
plan: 01
subsystem: ui
tags: [streamlit, plotly, dashboard, backtest, signals, candlestick, sqlalchemy]

# Dependency graph
requires:
  - phase: 82-signal-refinement-walk-forward-bakeoff
    provides: strategy_bakeoff_results table with 76K rows, signals_ema_crossover/rsi_mean_revert/atr_breakout tables
  - phase: 80-feature-selection
    provides: dim_feature_registry, dim_signals schema
  - phase: dashboard (prior)
    provides: queries/*.py pattern, charts.py pattern, st.cache_data conventions
provides:
  - queries/backtest.py with 7 server-side filtered query functions for strategy_bakeoff_results
  - queries/signals.py with 4 UNION ALL query functions across all 3 signal tables
  - charts.py extended with build_candlestick_chart, build_equity_sparkline, build_signal_timeline_chart
affects:
  - 83-02-PLAN.md (Backtest Results page -- depends on load_bakeoff_leaderboard, load_bakeoff_fold_metrics, build_equity_sparkline, build_candlestick_chart)
  - 83-03-PLAN.md (Signal Browser page -- depends on load_active_signals, load_signal_history, build_signal_timeline_chart)
  - 83-04-PLAN.md (Asset Hub page -- depends on all three chart builders)
  - 83-05-PLAN.md (Navigation / sidebar rework)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - server-side WHERE filtering on 76K+ row bakeoff table (never load full table)
    - UNION ALL across 3 signal tables with identical column list constant
    - make_interval(days => :days) for PostgreSQL interval in parameterized queries
    - fold_metrics_json is JSONB -- psycopg2 auto-deserializes to Python list (no json.loads)
    - .tolist() on ts columns to avoid tz-aware datetime .values pitfall
    - strategy_name prefix routing to correct signal table (ema_*/ama_* -> ema_crossover, rsi_* -> rsi_mean_revert, atr_* -> atr_breakout)
    - add_vrect row=1 col=1 for regime bands on subplot chart (not default full-figure)

key-files:
  created:
    - src/ta_lab2/dashboard/queries/backtest.py
    - src/ta_lab2/dashboard/queries/signals.py
  modified:
    - src/ta_lab2/dashboard/charts.py

key-decisions:
  - "ttl=3600 for bakeoff data (rarely regenerated), ttl=300 for signal data (updates during daily refresh)"
  - "fold_metrics_json JSONB auto-deserialized by psycopg2 -- do NOT json.loads() the result"
  - "UNION ALL column list stored as module constant _SIGNAL_COLUMNS to guarantee identical schema across sub-SELECTs"
  - "strategy_name prefix routing: ema_*/ama_* -> signals_ema_crossover (AMA bakeoff uses EMA signal lifecycle tracking)"
  - "make_interval(days => :days) over INTERVAL string concatenation to prevent SQL injection on days param"
  - "load_signal_strategies returns hardcoded list to avoid DB round-trip for static enum-like values"
  - "build_candlestick_chart: xaxis_rangeslider_visible=False via update_xaxes(rangeslider_visible=False)"
  - "build_equity_sparkline: cumulative sum of fold total_return values (not compounded) -- simple additive for sparkline visualization"
  - "build_signal_timeline_chart: horizontal bars via go.Bar orientation=h with base=[entry_ts]"

patterns-established:
  - "UNION ALL queries: define _SIGNAL_COLUMNS constant to ensure identical sub-SELECT lists"
  - "Signal table routing: frozenset validation before f-string interpolation prevents injection"
  - "Subplot chart: add_vrect with row=1,col=1 explicitly scopes bands to price row only"
  - "Empty DF handling: all chart builders return annotated figure (never crash on empty input)"

# Metrics
duration: 7min
completed: 2026-03-23
---

# Phase 83 Plan 01: Foundation Query Layers and Chart Builders Summary

**Backtest query layer (7 functions, server-side filtering on 76K rows), signal UNION ALL queries (4 functions across 3 tables), and 3 Plotly chart builders (candlestick + regime vrects, equity sparkline, signal timeline) ready for page consumption**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-23T13:37:15Z
- **Completed:** 2026-03-23T13:44:30Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `queries/backtest.py` with 7 cached functions providing server-side filtered access to `strategy_bakeoff_results` (76K+ rows), including fold_metrics_json deserialization and strategy-to-signal-table routing
- Created `queries/signals.py` with 4 functions using UNION ALL across all 3 signal tables, parameterized interval filtering, and dim_signals joins for signal type metadata
- Extended `charts.py` with 3 chart builders: candlestick (3-row subplot with EMA overlays, regime vrects, volume, RSI), equity sparkline (cumulative fold returns), and signal timeline (horizontal bars for entry/exit periods)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create backtest and signal query layers** - `956fd82c` (feat)
2. **Task 2: Add candlestick, equity sparkline, and signal timeline chart builders** - `3e68ba09` (feat)

## Files Created/Modified

- `src/ta_lab2/dashboard/queries/backtest.py` - 7 functions: load_bakeoff_leaderboard, load_bakeoff_for_asset, load_bakeoff_cost_matrix, load_bakeoff_strategies, load_bakeoff_assets, load_bakeoff_fold_metrics, load_closed_signals_for_strategy
- `src/ta_lab2/dashboard/queries/signals.py` - 4 functions: load_active_signals, load_signal_history, load_signal_strategies, load_dim_signals
- `src/ta_lab2/dashboard/charts.py` - Added build_candlestick_chart, build_equity_sparkline, build_signal_timeline_chart (455 lines appended)

## Decisions Made

- **ttl split**: bakeoff data ttl=3600 (rarely regenerated), signal data ttl=300 (updates during daily refresh)
- **fold_metrics_json**: JSONB is auto-deserialized by psycopg2 -- do NOT json.loads() the return value. load_bakeoff_fold_metrics handles both list and dict returns from JSONB column
- **UNION ALL safety**: column list defined as `_SIGNAL_COLUMNS` module constant to guarantee all 3 sub-SELECTs have identical schemas
- **AMA routing**: ama_* strategy names map to signals_ema_crossover because AMA bakeoff reuses EMA signal position lifecycle tracking
- **Interval parameterization**: make_interval(days => :days) instead of INTERVAL string to keep days as a bound parameter
- **Signal strategies list**: load_signal_strategies returns hardcoded list (no DB round-trip) -- signal_type is a static enum-like value
- **Equity sparkline**: additive cumulative sum (not compound return) -- simpler and adequate for fold-level sparkline

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit ruff hook reformatted charts.py after first commit attempt (inline comment spacing and multi-line condition formatting). Fixed by re-staging the auto-formatted file and committing again.

## Next Phase Readiness

All Phase 83 page dependencies satisfied:
- Plan 02 (Backtest Results page): load_bakeoff_leaderboard, build_equity_sparkline, build_candlestick_chart ready
- Plan 03 (Signal Browser page): load_active_signals, load_signal_history, build_signal_timeline_chart ready
- Plan 04 (Asset Hub page): all three chart builders and query functions ready
- Plan 05 (Navigation): no dependencies on this plan

---
*Phase: 83-dashboard-backtest-signal-pages*
*Completed: 2026-03-23*
