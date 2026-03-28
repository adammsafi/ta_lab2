---
phase: 83-dashboard-backtest-signal-pages
verified: 2026-03-23T14:04:03Z
status: gaps_found
score: 13/15 must-haves verified
gaps:
  - truth: "User can see signal strength score (0-100) for active signals"
    status: partial
    reason: >
      compute_signal_strength() correctly uses .get() defensive access
      but feature_snapshot is NOT in _SIGNAL_COLUMNS in signals.py.
      Column is never fetched; page always falls back to strength=50.
    artifacts:
      - path: "src/ta_lab2/dashboard/queries/signals.py"
        issue: >
          _SIGNAL_COLUMNS (lines 36-51) omits s.feature_snapshot.
          Column exists in DB but never fetched. Page falls back to 50.
    missing:
      - "Add s.feature_snapshot to _SIGNAL_COLUMNS in queries/signals.py"
  - truth: "Trade table shows regime context per trade"
    status: partial
    reason: >
      Trade table renders with MAE/MFE but regime_key silently dropped.
      load_closed_signals_for_strategy omits s.regime_key from SELECT.
    artifacts:
      - path: "src/ta_lab2/dashboard/queries/backtest.py"
        issue: >
          load_closed_signals_for_strategy SELECT (lines 318-336) omits
          s.regime_key. Column exists in all 3 signal tables.
    missing:
      - "Add s.regime_key to SELECT in load_closed_signals_for_strategy"
human_verification:
  - test: "Verify all new pages render without runtime errors"
    expected: "Backtest Results, Signal Browser, Asset Hub all load without exceptions"
    why_human: "Cannot verify Streamlit rendering without running the app"
  - test: "Verify OHLCV candlestick replaces close line in Research Explorer"
    expected: "Regime Analysis shows OHLCV candlestick with vrect bands not close line"
    why_human: "Visual replacement can only be confirmed by running the app"
  - test: "Verify chart HTML download buttons produce downloadable files"
    expected: "Download buttons save .html files that open as interactive Plotly charts"
    why_human: "Browser download behavior requires human confirmation"
---

# Phase 83: Dashboard Backtest Signal Pages Verification Report

**Phase Goal:** Dashboard surfaces backtest results and live signal state so the user can monitor strategy performance and signal activity without SQL
**Verified:** 2026-03-23T14:04:03Z
**Status:** gaps_found
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Backtest query functions return filtered DataFrames from strategy_bakeoff_results | VERIFIED | backtest.py: 7 functions, all use text() with server-side WHERE, JOIN dim_assets for symbol |
| 2 | Signal query functions return active signals and signal history from all three signal tables | VERIFIED | signals.py: UNION ALL across 3 tables in load_active_signals and load_signal_history |
| 3 | Candlestick chart builder produces OHLCV chart with EMA overlays, volume/RSI subplots, optional regime vrect bands | VERIFIED | charts.py lines 1122-1354: 3-row make_subplots, go.Candlestick, add_vrect with regimes_df |
| 4 | Equity sparkline builder produces compact cumulative return charts from fold_metrics_json | VERIFIED | charts.py lines 1357-1444: build_equity_sparkline with fold_metrics list input |
| 5 | User can view a leaderboard of strategies ranked by Sharpe with PSR/DSR badges | VERIFIED | 11_backtest_results.py: Leaderboard view with column_config for PSR/DSR, sorted by sharpe_mean DESC |
| 6 | User can switch between strategy-first, asset-first, and leaderboard views | VERIFIED | st.radio with 3 options, all three branches implemented in fragment |
| 7 | User can see cost scenario comparison table for any strategy+asset pair | VERIFIED | load_bakeoff_cost_matrix() called, pivot table rendered as st.dataframe |
| 8 | User can see equity sparkline thumbnails showing cumulative returns per fold | VERIFIED | Strategy-First view renders top-3-per-strategy sparklines; MC section has sparkline + download |
| 9 | User can see Monte Carlo Sharpe CI summary card | VERIFIED | Bootstrap CI with 1000 resamples, st.metric cards for mean/CI lower/upper |
| 10 | User can see trade table with MAE/MFE for closed signals | VERIFIED | compute_mae_mfe() called, mae/mfe columns formatted as pct. regime_key absent (separate gap) |
| 11 | Charts have HTML download buttons | VERIFIED | chart_download_button on sparkline (backtest), timeline (signal browser), heatmap, candlestick (asset hub) |
| 12 | User can see all currently active signals across all three signal generators | VERIFIED | load_active_signals() UNION ALL, position_state=open filter |
| 13 | User can switch between dashboard cards, live table, and heatmap grid views | VERIFIED | Three view branches: _render_cards_view, _render_table_view, _render_heatmap_view |
| 14 | User can see signal strength score (0-100) for active signals | PARTIAL | compute_signal_strength() has correct .get() but feature_snapshot not in query; always 50 |
| 15 | OHLCV candlestick with EMA overlays replaces plain close lines in Research Explorer | VERIFIED | 3_research_explorer.py: build_candlestick_chart replaces build_regime_price_chart at line 267 |

**Score:** 13/15 truths verified (2 partial gaps)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/ta_lab2/dashboard/queries/backtest.py` | 7 backtest query functions | VERIFIED | 347 lines, all 7 functions present with server-side filtering |
| `src/ta_lab2/dashboard/queries/signals.py` | 4 signal query functions | VERIFIED | 216 lines, all 4 functions present, UNION ALL pattern confirmed |
| `src/ta_lab2/dashboard/charts.py` | 3 new chart builders appended | VERIFIED | 1569 lines, build_candlestick_chart/build_equity_sparkline/build_signal_timeline_chart present |
| `src/ta_lab2/dashboard/pages/11_backtest_results.py` | min 250 lines, 3 views + MAE/MFE | VERIFIED | 787 lines, all sections present including MAE/MFE trade table |
| `src/ta_lab2/dashboard/pages/12_signal_browser.py` | min 200 lines, 3 views + history | VERIFIED | 668 lines, all views present including heatmap and timeline |
| `src/ta_lab2/dashboard/pages/13_asset_hub.py` | min 150 lines, unified asset view | VERIFIED | 323 lines, 4 sections (candlestick, signals+regime, backtests, quick links) |
| `src/ta_lab2/dashboard/pages/3_research_explorer.py` | Updated with OHLCV candlestick | VERIFIED | build_candlestick_chart called at line 267 with regimes_df parameter |
| `src/ta_lab2/dashboard/queries/research.py` | load_ohlcv_features, load_ema_overlays | VERIFIED | Both present, both @st.cache_data(ttl=300) |
| `src/ta_lab2/dashboard/app.py` | 4 sidebar groups, 3 new pages | VERIFIED | 4 groups (Overview, Analysis, Operations, Monitor), all 3 new pages under Analysis |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| backtest.py | strategy_bakeoff_results | server-side WHERE | WIRED | All 7 functions query FROM public.strategy_bakeoff_results |
| backtest.py | 3 signal tables | _strategy_to_signal_table routing | WIRED | load_closed_signals_for_strategy maps strategy prefix to table |
| signals.py | 3 signal tables UNION ALL | _STRATEGY_TABLE_MAP iteration | WIRED | Both active/history functions use UNION ALL pattern |
| charts.py | go.Candlestick | make_subplots(rows=3) | WIRED | Row 1: Candlestick, Row 2: Volume, Row 3: RSI |
| charts.py | fig.add_vrect for regime bands | regimes_df parameter | WIRED | Lines 1252-1289, row=1 col=1 confirmed |
| 11_backtest_results.py | queries/backtest.py | import 6 query functions | WIRED | Lines 24-31 |
| 11_backtest_results.py | charts.py | import build_equity_sparkline, chart_download_button | WIRED | Line 22 |
| 11_backtest_results.py | analysis.mae_mfe | import compute_mae_mfe, _load_close_prices | WIRED | Line 21 |
| 11_backtest_results.py | st.query_params | URL state persistence | WIRED | Lines 88-94 and 174-177 |
| 12_signal_browser.py | queries/signals.py | import load_active_signals, load_signal_history | WIRED | Lines 31-33 |
| 12_signal_browser.py | charts.py | import build_signal_timeline_chart, chart_download_button | WIRED | Lines 26-28 |
| 12_signal_browser.py | feature_snapshot -> signal_strength | _SIGNAL_COLUMNS needs feature_snapshot | NOT WIRED | feature_snapshot absent from _SIGNAL_COLUMNS; strength always 50 |
| 13_asset_hub.py | queries backtest + signals + research | imports from 3 query layers | WIRED | Lines 22-30 |
| 13_asset_hub.py | charts.py build_candlestick_chart | import and render | WIRED | Called at line 146 with ema_df and regimes_df |
| 3_research_explorer.py | build_candlestick_chart | replaces build_regime_price_chart | WIRED | Called at line 267 with regimes_df=regimes_df |
| app.py | 3 new page files | st.Page() entries in pages dict | WIRED | Lines 51-64, all under Analysis group |
| load_closed_signals_for_strategy | regime_key column | SELECT s.regime_key | NOT WIRED | Column omitted from SELECT; page silently omits from trade table |

### Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| Backtest Results with equity curves, PSR/DSR badges, MC CI, trade table with MAE/MFE, cost breakdown | SATISFIED | All present; regime_key absent from trade table is cosmetic |
| Signal Browser with active signals, history timeline, strength/confidence, filters | PARTIAL | Signal strength always 50 due to missing feature_snapshot in query |
| OHLCV candlestick replacing close lines in Research Explorer | SATISFIED | build_candlestick_chart with regimes_df wired in |
| Query-layer pattern (st.cache_data, _engine prefix) | SATISFIED | All query functions follow pattern confirmed |
| HTML download buttons | SATISFIED | chart_download_button present on all major charts |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/ta_lab2/dashboard/queries/signals.py` | 36-51 | _SIGNAL_COLUMNS omits s.feature_snapshot | Warning | Signal strength always 50; feature_snapshot JSONB never read |
| `src/ta_lab2/dashboard/queries/backtest.py` | 318-336 | load_closed_signals_for_strategy omits s.regime_key | Warning | regime_key never shown in trade table; degrades silently |

No placeholder text, no TODO/FIXME comments, no empty handlers found.
No st.set_page_config() executable calls in page files (docstring mentions only, confirmed via code inspection).

### Human Verification Required

#### 1. All New Pages Load Without Errors

**Test:** Run `streamlit run src/ta_lab2/dashboard/app.py` and navigate to Backtest Results, Signal Browser, and Asset Hub
**Expected:** All three pages render without exceptions. Sidebar shows 4 groups. Leaderboard table visible (may be empty if bakeoff not run). Signal metrics row shows counts.
**Why human:** Cannot verify Streamlit rendering without running the app

#### 2. OHLCV Candlestick Visual Replacement in Research Explorer

**Test:** Navigate to Research Explorer, select any asset with data, scroll to Regime Analysis section
**Expected:** OHLCV candlestick chart (body/wick candles) replaces old plain white close-price line. EMA overlay multiselect visible above chart. Volume bars in row 2. RSI subplot in row 3. Colored regime vrect bands in background.
**Why human:** Visual verification of chart rendering required

#### 3. Chart HTML Download Buttons

**Test:** In Backtest Results with strategy+asset selected click Download equity sparkline. In Signal Browser Heatmap view click Download heatmap chart.
**Expected:** Browser downloads .html files; opening them shows interactive Plotly charts
**Why human:** Browser download behavior requires interactive testing

### Gaps Summary

Two gaps block partial goal achievement, both are query-layer omissions:

**Gap 1 - Signal Strength Not Computed (signals.py):** compute_signal_strength() is correctly implemented
with all defensive .get() accesses for EMA/RSI/ATR components. However, _SIGNAL_COLUMNS in
src/ta_lab2/dashboard/queries/signals.py (lines 36-51) does not include s.feature_snapshot.
The JSONB column exists in the database but is never fetched. The Signal Browser page checks for
the column and falls back to strength=50 for all signals.
Fix: add s.feature_snapshot to _SIGNAL_COLUMNS.

**Gap 2 - Regime Key Missing from Trade Table (backtest.py):** load_closed_signals_for_strategy
in src/ta_lab2/dashboard/queries/backtest.py (lines 318-336) omits s.regime_key from its SELECT
statement. The column exists in all three signal tables (added by sql/regimes/083_alter_signal_tables.sql).
The trade table silently skips the column via column guard, so the table renders but without per-trade
regime context. Fix: add s.regime_key to the SELECT.

Both fixes are single-line additions to query SELECT statements. Neither gap prevents pages from loading
or primary features (leaderboard, cost matrix, Monte Carlo, signal views) from functioning.

---

_Verified: 2026-03-23T14:04:03Z_
_Verifier: Claude (gsd-verifier)_
