---
phase: 39
plan: "04"
name: research-explorer-page
subsystem: dashboard-ui
tags: [streamlit, plotly, ic-scores, regime-analysis, research-explorer]

dependency_graph:
  requires:
    - "39-01"  # skeleton + DB + query modules
    - "39-02"  # charts.py with build_ic_decay_chart, build_regime_price_chart, build_regime_timeline
  provides:
    - "Research Explorer page (3_research_explorer.py) -- Mode A complete"
    - "Interactive IC score table with CSV download"
    - "IC decay bar chart with plotly_dark and arith/log radio selector"
    - "Price chart with colored regime background bands"
    - "Regime timeline scatter chart colored by trend state"
  affects:
    - "39-03"  # market overview page (parallel, same wave)

tech_stack:
  added: []
  patterns:
    - "st.cache_data with _engine prefix for SQLAlchemy engine caching"
    - "theme=None on all st.plotly_chart calls to enforce plotly_dark"
    - "Section-level try/except with st.error()/st.warning() for resilient rendering"
    - "Empty-state guards (st.info / st.stop) before every chart render"

key_files:
  created:
    - src/ta_lab2/dashboard/pages/3_research_explorer.py
  modified: []

decisions:
  - id: D1
    decision: "No rolling IC chart on this page"
    rationale: "build_rolling_ic_chart requires a pre-computed rolling IC Series (not directly available from cmc_ic_results); IC decay chart covers the primary use case"
    alternatives: ["Add rolling IC chart with on-the-fly computation -- deferred to future plan"]
  - id: D2
    decision: "Full IC table sorted by |IC| descending (not by feature name)"
    rationale: "Users scanning for strongest predictors benefit from IC-sorted view; feature alphabetical sort is available via the Streamlit column sort"
  - id: D3
    decision: "IC Scores table uses friendly column order not DB column order"
    rationale: "horizon, return_type, regime_col/label, ic, ic_p_value first -- matches how an analyst reads the table"

metrics:
  duration: "2 min"
  completed: "2026-02-24"
  tasks_completed: 2
  tasks_total: 2
  lines_written: 285
---

# Phase 39 Plan 04: Research Explorer Page Summary

**One-liner:** Interactive Research Explorer with IC score table, IC decay bar chart (plotly_dark), and regime timeline/price overlay for selected asset+TF+feature.

## What Was Built

Replaced the placeholder `3_research_explorer.py` with a full 285-line Research Explorer page implementing Mode A (Research Explorer) of the Streamlit Dashboard.

**Key sections:**

1. **Selection controls (3 columns)**
   - Asset dropdown from `dim_assets` (ordered by symbol)
   - Timeframe dropdown from `dim_timeframe` (ordered by `tf_days_nominal`, defaults to "1D")
   - Feature search text input with live substring filtering
   - Feature selectbox populated from `cmc_ic_results` distinct features

2. **IC Score Table**
   - Loads `cmc_ic_results` for selected `asset_id` + `tf` via `load_ic_results()`
   - Filters to the selected feature
   - Displays in friendly column order: horizon, return_type, regime_col, regime_label, ic, ic_p_value, ic_t_stat, ic_ir, turnover, n_obs, computed_at
   - CSV download button: `ic_{symbol}_{tf}_{feature}.csv`

3. **IC Decay Chart**
   - `st.radio` for arith/log return type selection
   - `build_ic_decay_chart(feature_ic, selected_feature, return_type=return_type)` from charts.py
   - `st.plotly_chart(fig, theme=None)` to enforce plotly_dark
   - HTML download button via `chart_download_button()`

4. **Regime Analysis**
   - Price chart with colored vrect bands per regime period (`build_regime_price_chart`)
   - Regime timeline scatter colored by Up/Down/Sideways (`build_regime_timeline`)
   - Both rendered with `theme=None` and HTML download buttons
   - Empty state messages when price/regime data not populated

5. **All Features IC Summary**
   - Full `ic_df` sorted by `|ic|` descending across all features
   - CSV download: `ic_full_{symbol}_{tf}.csv`

## Commits

| Hash | Message |
|------|---------|
| bff38280 | feat(39-04): implement Research Explorer page with IC scores and regime charts |

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

All 24 checks passed:
- Syntax OK (Python AST parse)
- No `st.set_page_config()` call (only in docstring comment)
- All 6 query functions imported from `ta_lab2.dashboard.queries.research`
- All 4 chart functions imported from `ta_lab2.dashboard.charts`
- All 3 `st.plotly_chart` calls include `theme=None`
- 3-column layout with asset/TF/feature search
- IC Scores, IC Decay, Regime Analysis, All Features IC Summary sections present
- CSV + HTML download buttons present
- 285 lines (well above 150 minimum)
