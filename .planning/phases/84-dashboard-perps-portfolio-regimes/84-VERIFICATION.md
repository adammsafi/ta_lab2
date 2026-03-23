---
phase: 84-dashboard-perps-portfolio-regimes
verified: 2026-03-23T19:20:12Z
status: human_needed
score: 17/17 automated must-haves verified
human_verification:
  - test: Navigate to Perps page and verify top perps table loads
    expected: Table shows 15 rows with symbol volume funding rate OI mark price; top 3 as metric cards
    why_human: Requires live hyperliquid.hl_assets data with day_ntl_vlm populated
  - test: On Perps page use inline Funding Rate Analysis dropdown default BTC
    expected: plotly_dark line chart with zero reference line; y-axis labeled 8h Funding Rate
    why_human: Requires live hl_funding_rates data
  - test: On Perps page verify funding heatmap with assets as rows and dates as columns
    expected: go.Heatmap with RdBu colorscale zmid=0; 20 assets visible; cell text in pct format
    why_human: Pivot rendering and colorscale direction require visual inspection
  - test: On Perps page select BTC in the Daily Candles section
    expected: 2-row subplot candlestick on top OI area fill below; no rangeslider
    why_human: Requires live hl_candles and hl_open_interest data
  - test: Navigate to Portfolio and verify banner treemap/bar toggle area/table toggle
    expected: Construction banner visible; all 4 view combinations render non-empty output
    why_human: Mock data rendering and chart toggle interaction
  - test: Navigate to Regime Heatmap and verify 4 metric cards heatmap and comovement caption
    expected: Cards show total assets and pct Up/Down/Sideways; comovement caption says NOT cross-asset
    why_human: Requires live regimes data; visual colorscale confirmation
  - test: On Regime Heatmap toggle Show all assets
    expected: Heatmap row count grows beyond 30 to show all assets in regimes table
    why_human: Toggle interaction and visual row count check
  - test: Navigate to AMA Inspector with KAMA then switch to DEMA
    expected: KAMA shows ER chart with 0.3/0.7 reference lines. DEMA shows info message only.
    why_human: Requires live ama_multi_tf_u data; conditional rendering visual check
  - test: On AMA Inspector switch to Cross-Asset Comparison mode and select ETH
    expected: Second selectbox in sidebar; two asset traces on same chart with dual y-axis
    why_human: Mode toggle and dual y-axis rendering
  - test: Verify all 13 pre-existing pages still load without errors
    expected: No regressions in Landing Pipeline Research Asset Stats Experiments Trading Risk etc.
    why_human: Full app regression requires UI walkthrough
---

# Phase 84: Dashboard -- Perps, Portfolio and Regimes Verification Report

**Phase Goal:** Add 4 new dashboard pages (Perps, Portfolio, Regime Heatmap, AMA Inspector) to the Streamlit dashboard.
**Verified:** 2026-03-23T19:20:12Z
**Status:** human_needed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | User sees top 15 perps by volume with funding OI mark price | VERIFIED | load_hl_top_perps(limit=15) in _top_perps_section; cols symbol volume_24h funding_rate oi_base oi_usd mark_price max_leverage |
| 2 | User can select a perp and view funding rate time series | VERIFIED | Single-asset tab calls load_hl_funding_history; go.Scatter with add_hline(y=0) |
| 3 | User sees funding heatmap assets x days color-coded | VERIFIED | load_hl_funding_heatmap -> pivot_table -> go.Heatmap(colorscale=RdBu zmid=0) |
| 4 | User can select any of 190 perps and view daily candlestick | VERIFIED | perp_options dict from full perp list; go.Candlestick with rangeslider_visible=False |
| 5 | User can overlay up to 5 assets for funding comparison | VERIFIED | st.multiselect(max_selections=5) -> load_hl_funding_history(multi_asset_ids) -> one trace per asset |
| 6 | Perps page auto-refreshes every 15 min | VERIFIED | Three @st.fragment(run_every=AUTO_REFRESH_SECONDS) at lines 105 219 461; AUTO_REFRESH_SECONDS=900 |
| 7 | User sees cross-asset regime heatmap | VERIFIED | load_regime_all_assets -> _STATE_ENCODING pivot -> go.Heatmap with _HEATMAP_COLORSCALE from REGIME_BAR_COLORS |
| 8 | User can toggle between compact strip and paginated timeline | VERIFIED | st.radio with Compact Strip / Paginated Detail; compact uses heatmap paginated shows flip dataframe |
| 9 | User sees regime stats cards and per-asset detail | VERIFIED | load_regime_stats_summary -> 4 st.metric cards (total assets pct Up/Down/Sideways); expandable stats table |
| 10 | User views EMA comovement with NOT cross-asset caption | VERIFIED | load_regime_comovement -> st.dataframe; caption at line 452 says This is NOT cross-asset correlation. |
| 11 | Top 30 default with expand-to-all toggle | VERIFIED | st.toggle(Show all assets); top-30 at lines 294-306; all-assets at line 288 |
| 12 | Regime Heatmap auto-refreshes every 15 min | VERIFIED | @st.fragment(run_every=AUTO_REFRESH_SECONDS) at line 201 |
| 13 | User sees AMA curves with toggleable d1/d2/d1_roll/d2_roll | VERIFIED | load_ama_curves -> loop over ama_df labels; st.multiselect with d1/d2/d1_roll/d2_roll options |
| 14 | ER chart for KAMA only suppressed for DEMA/HMA/TEMA | VERIFIED | if indicator != KAMA: st.info(Efficiency Ratio is only computed for KAMA...) at line 392 |
| 15 | User can compare AMA vs fixed EMA overlay or side-by-side | VERIFIED | load_ema_for_comparison called; st.radio(Comparison View Overlay/Side by Side) |
| 16 | AMA labels from dim_ama_params not raw params_hash | VERIFIED | SQL JOINs dim_ama_params at ama.py line 62; page loops ama_df[label] not params_hash |
| 17 | Portfolio placeholder with mock data and Phase 86 banner | VERIFIED | st.info(...Phase 86...) at lines 72-76; numpy.random.default_rng(42) at line 116; 4x TODO(Phase-86) |

**Score:** 17/17 truths automated-verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| src/ta_lab2/dashboard/queries/perps.py | 6 cached HL query functions | VERIFIED | 175 lines; all 6 exports: load_hl_perp_list load_hl_top_perps load_hl_funding_history load_hl_funding_heatmap load_hl_candles load_hl_oi_timeseries |
| src/ta_lab2/dashboard/pages/14_perps.py | Perps page min 150 lines | VERIFIED | 566 lines; 3 fragments 4 sections |
| src/ta_lab2/dashboard/queries/regimes.py | 4 cached regime query functions | VERIFIED | 155 lines; all 4 exports: load_regime_all_assets load_regime_stats_summary load_regime_flips_recent load_regime_comovement |
| src/ta_lab2/dashboard/pages/16_regime_heatmap.py | Regime Heatmap page min 150 lines | VERIFIED | 506 lines; 1 fragment 4 sections |
| src/ta_lab2/dashboard/queries/ama.py | 3 cached AMA query functions | VERIFIED | 139 lines; all 3 exports: load_ama_params_catalogue load_ama_curves load_ema_for_comparison |
| src/ta_lab2/dashboard/pages/17_ama_inspector.py | AMA Inspector page min 150 lines | VERIFIED | 742 lines; 1 fragment 2 modes |
| src/ta_lab2/dashboard/pages/15_portfolio.py | Portfolio placeholder min 120 lines | VERIFIED | 464 lines; 1 fragment mock data placeholder banner |
| src/ta_lab2/dashboard/app.py | 4 new pages registered | VERIFIED | Lines 81 86 91 96 -- all 4 paths and titles confirmed |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| pages/14_perps.py | queries/perps.py | import all 6 functions | WIRED | Lines 23-30 import all 6 query functions |
| pages/14_perps.py | hyperliquid schema | load_hl_* calls in 3 fragments | WIRED | Fragment calls at lines 188 436 561 invoke query functions |
| queries/perps.py | hyperliquid.hl_* | cross-schema SQL | WIRED | 13 occurrences of hyperliquid. prefix; hl_open_interest for OI not hl_oi_snapshots |
| pages/16_regime_heatmap.py | queries/regimes.py | import all 4 functions | WIRED | Lines 33-38; all 4 called inside _render_regime_content |
| queries/regimes.py | public.regimes | split_part SQL | WIRED | split_part(r.l2_label - 1) AS trend_state at lines 39-40; no direct trend_state column |
| pages/17_ama_inspector.py | queries/ama.py | import all 3 functions | WIRED | Lines 27-31; all called inside _ama_inspector_content |
| pages/17_ama_inspector.py | queries/research.py | import load_asset_list load_tf_list | WIRED | Line 32; used for sidebar asset/tf dropdowns |
| queries/ama.py | ama_multi_tf_u + dim_ama_params | JOIN + alignment/roll filters | WIRED | JOIN at lines 62-63; alignment_source=multi_tf and roll=false at lines 67-68 |
| pages/15_portfolio.py | ta_lab2.dashboard.db | import get_engine reserved | WIRED | Line 29 noqa F401; Phase 86 wiring hook |
| app.py | pages/14_perps.py | st.Page registration | WIRED | Line 81 title=Perps |
| app.py | pages/15_portfolio.py | st.Page registration | WIRED | Line 86 title=Portfolio |
| app.py | pages/16_regime_heatmap.py | st.Page registration | WIRED | Line 91 title=Regime Heatmap |
| app.py | pages/17_ama_inspector.py | st.Page registration | WIRED | Line 96 title=AMA Inspector |

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Plan 84-01: Hyperliquid Perps page | SATISFIED | 6 query functions + 4-section page + 3 auto-refresh fragments |
| Plan 84-02: Regime Heatmap page | SATISFIED | 4 query functions + split_part trend_state + top-30/all toggle |
| Plan 84-03: AMA/EMA Inspector page | SATISFIED | 3 query functions + conditional ER + cross-asset comparison mode |
| Plan 84-04: Portfolio placeholder | SATISFIED | Mock data + construction banner + 4x TODO(Phase-86) markers |
| Plan 84-05: app.py registration | SATISFIED | All 4 pages in Analysis group with correct titles and Material icons |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| pages/15_portfolio.py | 29 | get_engine unused import noqa F401 | Info | Intentional -- reserved for Phase 86 wiring |
| pages/15_portfolio.py | 113 126 144 406 | TODO(Phase-86) comments | Info | Intentional placeholder markers expected per plan |

No blocker or warning anti-patterns found. All production code paths have real implementations.

### Human Verification Required

All automated structural checks passed. The following 10 tests require a running Streamlit dashboard with live database connectivity.

#### 1. Perps Page -- Top Perps Table

**Test:** Navigate to the Perps page; observe the landing table above the Funding Rate Analysis section
**Expected:** Up to 15 rows with symbol, volume in dollar-M format, funding rate percentage, OI base, OI USD, mark price, max leverage; top 3 as st.metric cards
**Why human:** Requires live hyperliquid.hl_assets with day_ntl_vlm populated

#### 2. Perps Page -- Single-Asset Funding Chart

**Test:** Use the inline Asset dropdown (default BTC) under Funding Rate Analysis; check Single Asset tab
**Expected:** plotly_dark line chart with dashed zero reference line; y-axis labeled 8h Funding Rate
**Why human:** Requires hl_funding_rates data

#### 3. Perps Page -- Funding Heatmap

**Test:** Observe the Funding Rate Heatmap section
**Expected:** go.Heatmap with RdBu colorscale; negative funding red positive blue; cell text in percentage format
**Why human:** Colorscale direction and cell text require visual inspection

#### 4. Perps Page -- Candle Chart with OI

**Test:** Select BTC in the Daily Candles section
**Expected:** 2-row subplot with candlestick on top and OI area fill below; no rangeslider visible
**Why human:** Conditional 2-row make_subplots layout requires visual confirmation

#### 5. Portfolio Page -- Toggles and Mock Data

**Test:** Navigate to Portfolio; toggle Treemap/Stacked Bar and Area Chart/Table
**Expected:** Construction banner visible; all 4 view combinations render non-empty charts or tables
**Why human:** Interactive widget toggles and chart rendering

#### 6. Regime Heatmap -- Cards Heatmap Comovement

**Test:** Navigate to Regime Heatmap; observe metric cards and comovement section
**Expected:** 4 metric cards with non-zero counts; heatmap uses green/gray/red colorscale; comovement caption says NOT cross-asset correlation
**Why human:** Requires live regimes data; visual colorscale confirmation

#### 7. Regime Heatmap -- Expand Toggle

**Test:** Toggle Show all assets
**Expected:** Heatmap row count increases beyond 30 to show all assets with regime data
**Why human:** Toggle interaction and visual row count check

#### 8. AMA Inspector -- KAMA ER and DEMA Suppression

**Test:** Open AMA Inspector with KAMA; verify ER section; switch to DEMA
**Expected:** KAMA shows ER line chart with Choppy 0.3 and Trending 0.7 reference lines. DEMA shows info message only no chart.
**Why human:** Requires live ama_multi_tf_u data; conditional rendering visual check

#### 9. AMA Inspector -- Cross-Asset Comparison Mode

**Test:** Switch mode to Cross-Asset Comparison; select ETH as second asset
**Expected:** Second selectbox appears in sidebar; chart shows two asset traces with dual y-axis
**Why human:** Mode toggle and dual y-axis rendering

#### 10. Full Regression -- Existing Pages

**Test:** Click through all 13 pre-existing dashboard pages
**Expected:** No Python exceptions or Streamlit errors on any existing page
**Why human:** App-wide regression requires full UI walkthrough

### Gaps Summary

No gaps found. All 5 plans have SUMMARY.md files. All 17 must-have truths verified. All 8 required artifacts exist and are substantive (139-742 lines). All 13 key links are wired. No blocker anti-patterns. Phase goal achievement is structurally complete; only live UI testing remains.

---

*Verified: 2026-03-23T19:20:12Z*
*Verifier: Claude (gsd-verifier)*
