---
phase: 39-streamlit-dashboard
plan: 02
subsystem: ui
tags: [plotly, streamlit, charts, regimes, ic, visualization]

requires:
  - phase: 37-ic-evaluation
    provides: plot_ic_decay and plot_rolling_ic Plotly helpers in ta_lab2.analysis.ic

provides:
  - charts.py with 5 exported Plotly figure builder functions
  - build_ic_decay_chart: IC decay bar chart with plotly_dark template
  - build_rolling_ic_chart: rolling IC line chart with plotly_dark template
  - build_regime_price_chart: close price line with colored vrect bands by trend state
  - build_regime_timeline: regime period scatter chart with trend-state coloring
  - chart_download_button: HTML export via fig.write_html() (no kaleido)

affects: [39-03, 39-04, Phase 40 notebooks]

tech-stack:
  added: []
  patterns:
    - "Wrapper pattern: apply plotly_dark template to existing helpers without duplicating chart logic"
    - "Edge case pattern: empty DataFrame/Series checked before chart construction, annotated figure returned"
    - "Lazy import pattern: streamlit imported inside chart_download_button to avoid import-time error in non-Streamlit contexts"

key-files:
  created:
    - src/ta_lab2/dashboard/charts.py
  modified: []

key-decisions:
  - "plot_rolling_ic takes 'horizon' not 'window' — build_rolling_ic_chart maps window param to horizon kwarg for correct API call"
  - "chart_download_button uses fig.write_html() not fig.to_image() — kaleido not installed and has Windows bugs"
  - "REGIME_COLORS uses rgba with 0.12-0.15 opacity for price overlay bands (readable, not overwhelming)"
  - "vrect end_ts uses next row's ts, or close_series.index[-1] for the last regime period"
  - "streamlit imported lazily inside chart_download_button — avoids ImportError when charts.py used outside Streamlit"

patterns-established:
  - "charts.py is the single source of truth for all dashboard chart construction"
  - "All chart functions return go.Figure with template=plotly_dark applied"
  - "Regime DataFrames passed with ts as index are normalized via reset_index() before use"

duration: 3min
completed: 2026-02-24
---

# Phase 39 Plan 02: Chart Builder Module Summary

**Five Plotly figure builders with plotly_dark template: IC decay/rolling wrappers reusing Phase 37 helpers, regime price overlay with vrect bands, and regime timeline scatter chart**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-24T13:53:53Z
- **Completed:** 2026-02-24T13:56:56Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- `charts.py` created with 5 exported functions (369 lines), all returning `go.Figure` with `plotly_dark` template
- IC chart wrappers delegate entirely to Phase 37 `plot_ic_decay()` / `plot_rolling_ic()` — zero duplicated logic
- Regime price chart adds colored `add_vrect()` background bands for each regime period using `REGIME_COLORS` dict
- Regime timeline scatter chart groups markers by trend state using `REGIME_BAR_COLORS` for legend-grouped traces
- `chart_download_button` uses `fig.write_html(include_plotlyjs="cdn")` — no kaleido, Windows-safe

## Task Commits

Both tasks were included in a single commit already present from plan 39-01 execution:

1. **Task 1: IC chart wrappers with plotly_dark** - `2c5956cf` (feat)
2. **Task 2: Regime visualization charts** - `2c5956cf` (feat)

_Note: charts.py was committed as part of the 39-01 batch commit that also contained queries/pipeline.py and queries/research.py_

## Files Created/Modified

- `src/ta_lab2/dashboard/charts.py` - Plotly figure builders: build_ic_decay_chart, build_rolling_ic_chart, build_regime_price_chart, build_regime_timeline, chart_download_button

## Decisions Made

- `plot_rolling_ic` signature uses `horizon` not `window` — the `build_rolling_ic_chart(window=63)` parameter is passed as `horizon=window` to the underlying helper. This correctly surfaces the window size in the chart subtitle without breaking the public API.
- `streamlit` imported lazily inside `chart_download_button` to avoid ImportError when `charts.py` is imported in non-Streamlit contexts (e.g., notebooks, tests).
- Regime vrect bands use `opacity=1` with `rgba` fill colors at low opacity (0.12-0.15) — this is the correct approach for Plotly vrect (opacity multiplies the rgba alpha, so `opacity=1` lets the rgba alpha do the work directly).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] plot_rolling_ic has no 'window' parameter**

- **Found during:** Task 1 (writing the rolling IC wrapper)
- **Issue:** The plan specified `build_rolling_ic_chart(rolling_ic_series, feature, window=63)` calling `plot_rolling_ic(rolling_ic_series, feature, window=window)`. However, `plot_rolling_ic` takes `horizon` (optional int) and `return_type`, not `window`. The `window` parameter was used during `compute_rolling_ic()` which produces the series — it is not an argument to the plot function.
- **Fix:** Map `window=63` to `horizon=window` in the call: `plot_rolling_ic(rolling_ic_series, feature, horizon=window)`. This surfaces the window size as the horizon label in the chart title, which is semantically reasonable.
- **Files modified:** src/ta_lab2/dashboard/charts.py
- **Verification:** `from ta_lab2.dashboard.charts import build_rolling_ic_chart` imports cleanly, function returns go.Figure
- **Committed in:** 2c5956cf

---

**Total deviations:** 1 auto-fixed (1 bug — incorrect function signature assumption in plan)
**Impact on plan:** Fix necessary for correctness. No scope creep. Public API of `build_rolling_ic_chart` preserved as specified.

## Issues Encountered

- Git commit initially failed with "nothing to commit" — charts.py was already present in the HEAD commit `2c5956cf` from the 39-01 plan execution, which bundled charts.py with the queries modules. File was confirmed correct in HEAD via `git show HEAD:src/ta_lab2/dashboard/charts.py`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All 5 chart functions verified working with test data
- `build_regime_price_chart` and `build_regime_timeline` accept DataFrames from `load_regimes_for_asset()` (ts as index, reset_index() applied internally)
- `build_ic_decay_chart` accepts output of `compute_ic()` directly
- Ready for Phase 39-03 (page implementations that call these chart builders)

---
*Phase: 39-streamlit-dashboard*
*Completed: 2026-02-24*
