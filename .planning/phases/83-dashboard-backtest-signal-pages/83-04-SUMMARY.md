---
phase: 83-dashboard-backtest-signal-pages
plan: 04
subsystem: ui
tags: [streamlit, plotly, dashboard, candlestick, ema-overlays, regime-vrects, asset-hub, query-layers]

# Dependency graph
requires:
  - phase: 83-01
    provides: build_candlestick_chart, queries/backtest.py, queries/signals.py
  - phase: 80-ic-analysis-feature-selection
    provides: features table with OHLCV + rsi_14 columns
  - phase: 77-direct-to-u-remaining-families
    provides: ema_multi_tf_u with alignment_source column
  - phase: dashboard (prior)
    provides: queries/research.py pattern, st.cache_data conventions, get_engine
provides:
  - load_ohlcv_features query function in queries/research.py (OHLCV+RSI from features table)
  - load_ema_overlays query function in queries/research.py (EMA values from ema_multi_tf_u)
  - Updated Research Explorer with OHLCV candlestick replacing close-price line chart
  - New Asset Hub page (13_asset_hub.py) with 4-section unified per-asset view
affects:
  - 83-05-PLAN.md (navigation/sidebar rework -- hub page is part of page list)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - OHLCV candlestick with regime vrects via build_candlestick_chart(ohlcv_df, regimes_df=regimes_df)
    - EMA overlay multiselect: period list -> load_ema_overlays(periods=[...]) -> ema_df
    - ema column aliased as ema_value in query to match build_candlestick_chart expected col name
    - period=ANY(:periods) for PostgreSQL array binding in optional list filter
    - st.query_params for deep linking between Asset Hub and other pages
    - regimes_df = None when empty to skip vrects (empty not None triggers vrect loop)

key-files:
  created:
    - src/ta_lab2/dashboard/pages/13_asset_hub.py
  modified:
    - src/ta_lab2/dashboard/queries/research.py
    - src/ta_lab2/dashboard/pages/3_research_explorer.py

key-decisions:
  - "ema aliased as ema_value in load_ema_overlays query: matches build_candlestick_chart expected column name without modifying charts.py"
  - "period=ANY(:periods) for psycopg2 Python list -> PostgreSQL array binding (no UNNEST needed)"
  - "regimes_df set to None when empty in Asset Hub: build_candlestick_chart skips vrect loop entirely on None vs empty DataFrame"
  - "Ruff auto-formats 13_asset_hub.py on first commit attempt: re-staged auto-formatted file for clean commit"
  - "Asset Hub sidebar controls placed at module level (outside fragment): Streamlit requires sidebar widgets at module scope"

patterns-established:
  - "OHLCV query pattern: SELECT ts/open/high/low/close/volume/rsi_14 FROM features WHERE id=:id AND tf=:tf"
  - "EMA overlay query: ema AS ema_value FROM ema_multi_tf_u WHERE alignment_source='multi_tf' AND optional period=ANY(:periods)"
  - "Deep linking: st.query_params['asset'] and st.query_params['tf'] for cross-page navigation"
  - "Section independence: each dashboard section has its own try/except with st.info fallback for no-data state"

# Metrics
duration: 4min
completed: 2026-03-23
---

# Phase 83 Plan 04: Asset Hub and Research Explorer Upgrade Summary

**OHLCV candlestick with EMA overlays and regime vrects in Research Explorer, plus new Asset Hub page combining chart/signals/backtests/regimes with st.query_params deep linking**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-23T13:48:11Z
- **Completed:** 2026-03-23T13:52:45Z
- **Tasks:** 3 (Task 1 + Task 2a + Task 2b)
- **Files modified:** 3

## Accomplishments

- Added `load_ohlcv_features` and `load_ema_overlays` to `queries/research.py`: OHLCV+RSI from features table and EMA values from ema_multi_tf_u with optional period list filter and alignment_source='multi_tf' scoping
- Upgraded Research Explorer (3_research_explorer.py) to replace plain close-line chart with OHLCV candlestick via `build_candlestick_chart`, with EMA overlay multiselect and regime vrect bands passed via `regimes_df` parameter
- Created Asset Hub page (13_asset_hub.py, 324 lines) with 4 sections: candlestick chart with EMA/regime overlays, active signals + regime state, backtest results sorted by sharpe_mean, and quick cross-page navigation links

## Task Commits

Each task was committed atomically:

1. **Task 1: Add OHLCV and EMA query functions to research.py** - `6d1c0a70` (feat)
2. **Task 2a: Upgrade Research Explorer with OHLCV candlestick and regime vrects** - `c76d0280` (feat)
3. **Task 2b: Create Asset Hub page** - `29ade046` (feat)

## Files Created/Modified

- `src/ta_lab2/dashboard/queries/research.py` - Appended load_ohlcv_features and load_ema_overlays (73 lines added)
- `src/ta_lab2/dashboard/pages/3_research_explorer.py` - Added OHLCV candlestick + EMA overlay multiselect replacing build_regime_price_chart
- `src/ta_lab2/dashboard/pages/13_asset_hub.py` - New unified asset detail page (324 lines, 4 sections)

## Decisions Made

- **ema alias**: `ema AS ema_value` in load_ema_overlays query -- matches `build_candlestick_chart` expected column without modifying charts.py
- **period=ANY(:periods)**: psycopg2 handles Python list -> PostgreSQL array natively for ANY() binding
- **regimes_df = None when empty**: build_candlestick_chart skips vrect loop on None, but iterates (vacuously) on empty DataFrame -- setting None is safer
- **Sidebar at module level**: Streamlit requires sidebar widgets outside @st.fragment to work correctly

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Ruff auto-formatted `13_asset_hub.py` (f-string length) on first commit attempt. Fixed by re-staging the auto-formatted file and committing again -- same pattern as Phase 83 Plan 01.
- Verification check `assert 'st.set_page_config' not in src` triggered false-positive on the NOTE comment in the module docstring. Verified via AST walk that no actual `st.set_page_config()` call exists.

## Next Phase Readiness

- Plan 05 (Navigation/sidebar rework): Asset Hub page exists and is ready to be added to sidebar navigation
- All 4 dashboard page types now complete: Research Explorer, Backtest Results, Signal Browser, Asset Hub
- Deep linking infrastructure in place: st.query_params used consistently across pages

---
*Phase: 83-dashboard-backtest-signal-pages*
*Completed: 2026-03-23*
