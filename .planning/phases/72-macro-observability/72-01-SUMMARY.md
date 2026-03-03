---
phase: 72-macro-observability
plan: "01"
subsystem: dashboard
tags: [plotly, streamlit, alembic, postgresql, fred, macro-regime, pandas]

# Dependency graph
requires:
  - phase: 67-macro-regime-classifier
    provides: cmc_macro_regimes table (date, monetary_policy, liquidity, risk_appetite, carry, regime_key, macro_state)
  - phase: 65-fred-pipeline
    provides: fred.series_values table (series_id, date, value)
  - phase: 47-drift-guard
    provides: cmc_drift_metrics table (config_id, metric_date, tracking_error columns)
  - phase: 71-event-risk-gates
    provides: Alembic head a2b3c4d5e6f7 (down_revision for this migration)
provides:
  - "Alembic migration e6f7a8b9c0d1: attr_macro_regime_delta column on cmc_drift_metrics"
  - "Alembic migration e6f7a8b9c0d1: cmc_macro_alert_log table for Telegram throttling"
  - "5 cached dashboard query functions in ta_lab2.dashboard.queries.macro"
  - "MACRO_STATE_COLORS and MACRO_DIMENSION_COLORS color constants in charts.py"
  - "build_macro_regime_timeline: 5-panel Plotly subplot (overlay + 4 dimension vrect bands)"
  - "build_fred_quality_chart: horizontal bar chart with green/orange/red coverage coloring"
affects:
  - "72-02: Macro dashboard page imports from queries/macro.py and charts.py"
  - "72-03: Drift attribution uses attr_macro_regime_delta column"
  - "72-04: Pipeline monitor FRED freshness uses load_fred_freshness"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Underscore-prefixed _engine param for st.cache_data bypass (per drift.py pattern)"
    - "FRED series frequency classification via frozenset lookup (daily/weekly/monthly)"
    - "vrect bands for regime visualization (per build_regime_price_chart pattern)"
    - "make_subplots with shared_xaxes=True for stacked time-aligned panels"

key-files:
  created:
    - alembic/versions/e6f7a8b9c0d1_macro_drift_attribution.py
    - src/ta_lab2/dashboard/queries/macro.py
  modified:
    - src/ta_lab2/dashboard/charts.py

key-decisions:
  - "down_revision = a2b3c4d5e6f7 (Phase 71 head) -- plan stated d5e6f7a8b9c0 but actual head discovered via alembic heads"
  - "FRED freshness thresholds: daily=3d, weekly=10d, monthly=45d (from 72-CONTEXT.md spec)"
  - "Status thresholds: green<=threshold, orange<=threshold*2.4, red>threshold*2.4"
  - "Coverage expected_rows: business days for daily, ISO weeks for weekly, calendar months for monthly"
  - "Timeline panels: row_heights=[0.40, 0.15, 0.15, 0.15, 0.15] with vertical_spacing=0.02"
  - "Transition lines: add_vline on all 5 panels; hover annotation text only on panel 1"

patterns-established:
  - "Macro query functions follow exact drift.py pattern (underscore _engine, ttl=300)"
  - "MACRO_STATE_COLORS / MACRO_DIMENSION_COLORS are module-level constants in charts.py"
  - "build_fred_quality_chart height = max(300, 30*n_rows+80) for readability at any scale"

# Metrics
duration: 9min
completed: 2026-03-03
---

# Phase 72 Plan 01: Macro Observability Data Foundation Summary

**Alembic migration adding attr_macro_regime_delta to cmc_drift_metrics, cmc_macro_alert_log throttle table, 5 cached Streamlit query functions over cmc_macro_regimes + fred.series_values, and Plotly 5-panel macro timeline + FRED coverage bar chart builders**

## Performance

- **Duration:** 9 min
- **Started:** 2026-03-03T16:58:43Z
- **Completed:** 2026-03-03T17:07:52Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Alembic migration `e6f7a8b9c0d1` correctly chains from Phase 71 head `a2b3c4d5e6f7`, adds `attr_macro_regime_delta FLOAT` column and `cmc_macro_alert_log` table
- Five cached query functions in `ta_lab2.dashboard.queries.macro` cover current regime, history, FRED freshness, series quality, and transition log
- Charts.py extended with two color constant dicts and two new chart builders; all existing functions untouched

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration + macro query module** - `fbb20605` (feat)
2. **Task 2: Macro state colors + timeline chart builder** - `dd246569` (feat)

**Plan metadata:** committed with task commits (no separate metadata commit needed)

## Files Created/Modified

- `alembic/versions/e6f7a8b9c0d1_macro_drift_attribution.py` -- Migration adding attr_macro_regime_delta column and cmc_macro_alert_log table
- `src/ta_lab2/dashboard/queries/macro.py` -- 5 cached query functions for macro regime and FRED data
- `src/ta_lab2/dashboard/charts.py` -- Added MACRO_STATE_COLORS, MACRO_DIMENSION_COLORS, build_macro_regime_timeline, build_fred_quality_chart

## Decisions Made

- **Correct Alembic down_revision:** Plan stated `d5e6f7a8b9c0` but `alembic heads` showed actual head was `a2b3c4d5e6f7` (Phase 71). Used discovered head.
- **FRED frequency classification:** DFF, DGS2, DGS10, BAMLH0A0HYM2, VIXCLS, DTWEXBGS = daily; ICSA = weekly; all others monthly. Matches series update cadences.
- **Freshness orange threshold:** `staleness <= threshold * 2.4` -- gives a buffer zone before hard red alert. For daily: orange at 4-7 days, red at 8+.
- **Coverage expected_rows calculation:** Business days (pd.bdate_range) for daily, ISO week count for weekly, calendar months (pd.date_range freq=MS) for monthly.
- **Timeline layout:** 5 panels with 40/15/15/15/15 row heights and 0.02 vertical spacing. Overlay label annotation only on panel 1 for clean layout.
- **vrect end date for last row:** `start_date + pd.Timedelta(days=1)` -- ensures last bar is always visible with a 1-day width.
- **Transition vlines:** `add_vline` on all 5 panels for cross-panel visual alignment; annotation text only on panel 1 to avoid clutter.

## Deviations from Plan

None -- plan executed exactly as written (aside from the IMPORTANT note about discovering the actual Alembic head, which was anticipated).

## Issues Encountered

- **Ruff formatting:** First commit attempt failed because ruff-format reformatted `macro.py` (the `min(100.0, ...)` ternary inside `round()`). Re-staged the formatted file and committed successfully.

## Next Phase Readiness

- All 5 query functions ready for import by the Macro dashboard page (72-02)
- `build_macro_regime_timeline` and `build_fred_quality_chart` ready for use in 72-02
- `attr_macro_regime_delta` column exists in `cmc_drift_metrics` for 72-03 attribution
- `load_fred_freshness` ready for integration into pipeline monitor (72-04)
- No blockers

---
*Phase: 72-macro-observability*
*Completed: 2026-03-03*
