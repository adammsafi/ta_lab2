---
phase: 84-dashboard-perps-portfolio-regimes
plan: "04"
subsystem: ui
tags: [streamlit, plotly, dashboard, portfolio, black-litterman, mock-data]

# Dependency graph
requires:
  - phase: 83-dashboard-backtest-signal-pages
    provides: established page patterns (fragment pattern, sidebar-outside-fragment, plotly_dark, chart_download_button)
  - phase: 84-03
    provides: sidebar group structure (Analysis group that 15_portfolio.py belongs to)
provides:
  - Portfolio Allocation page (pages/15_portfolio.py) with mock data layout
  - Treemap and stacked bar chart toggle for current allocation view
  - Stacked area chart and table toggle for weight history
  - Position sizing horizontal bar chart + per-asset risk budget progress bars
  - Exposure summary dataframe with totals row
  - Phase 86 wiring placeholders (TODO comments + get_engine import)
affects:
  - phase-86-portfolio-construction (will replace mock data with live BL pipeline)
  - sidebar navigation (page visible as 15_Portfolio in Streamlit page list)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "numpy.random.default_rng(42) for reproducible mock data (no UI flicker on re-run)"
    - "@st.fragment(run_every=AUTO_REFRESH_SECONDS) with sidebar controls outside fragment"
    - "TODO(Phase-86) comments mark all mock data replacement points"
    - "get_engine imported but unused (noqa: F401) to reserve DB integration hook"

key-files:
  created:
    - src/ta_lab2/dashboard/pages/15_portfolio.py
  modified: []

key-decisions:
  - "st.info() placeholder banner at top with :material/construction: icon signals Phase 86 dependency clearly"
  - "rng.normal(0, 0.3) weight perturbations on seed=42 base weights: small enough to look realistic, deterministic"
  - "risk_tier_colors computed from risk_used_pct/risk_budget_pct ratio (green<60%, yellow<85%, red>=85%)"
  - "noqa: F401 on get_engine import: linter suppression preserves import for Phase 86 wiring without dead import removal"
  - "strategy_colors dict removed (F841 ruff violation): stacked bar uses Plotly default colorwheel instead"

patterns-established:
  - "Placeholder page pattern: st.info() banner + TODO(Phase-XX) comments + get_engine import reserved for future wiring"

# Metrics
duration: 3min
completed: 2026-03-23
---

# Phase 84 Plan 04: Portfolio Allocation Summary

**Streamlit portfolio allocation placeholder page with treemap/bar toggle, area chart/table weight history, per-asset bet sizing with risk tier colors, and exposure summary -- all mock data ready for Phase 86 BL pipeline wiring**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-23T16:35:19Z
- **Completed:** 2026-03-23T16:38:38Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Created `pages/15_portfolio.py` (466 lines) with complete portfolio page layout
- Treemap (grouped by strategy, colored by weight) and stacked bar toggle for current allocation
- 30-day weight history as stacked area chart (tonexty fill) or formatted table
- Position sizing: horizontal bars with risk tier colors (green/yellow/red) and hover rationale text
- Risk budget utilization: summary metric + per-asset st.progress bars
- Exposure summary dataframe with formatted columns and totals row
- Placeholder info banner with construction icon + four TODO(Phase-86) wiring comments

## Task Commits

Each task was committed atomically:

1. **Task 1: Create pages/15_portfolio.py -- Portfolio Allocation placeholder** - `c6273c35` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified
- `src/ta_lab2/dashboard/pages/15_portfolio.py` - Portfolio Allocation placeholder page with mock data, 466 lines

## Decisions Made
- `strategy_colors` dict removed after ruff F841 violation: stacked bar uses Plotly's default colorwheel
- `noqa: F401` comment on `get_engine` import preserves the Phase 86 wiring hook without triggering unused import lint
- Mock weight perturbations use `rng.normal(0, 0.3)` on realistic base weights (BTC 35%, ETH 25%, etc.) to look plausible without manual tuning
- Risk tier thresholds: <60% used = green, 60-85% = yellow, >=85% = red (matches standard risk budget convention)

## Deviations from Plan

None - plan executed exactly as written. The only adjustment was removing the unused `strategy_colors` dict (which the plan mentioned but did not require to be used for coloring -- ruff F841 compliance).

## Issues Encountered
- ruff-format pre-commit hook reformatted file on first commit (standard pattern: re-staged and committed clean)
- ruff F841 on `strategy_colors` dict: removed unused variable, stacked bar chart uses Plotly default colors (aesthetically equivalent)

## User Setup Required
None - no external service configuration required. Page renders entirely from mock data.

## Next Phase Readiness
- `15_portfolio.py` is ready in the Streamlit page list as "Portfolio"
- Four `TODO(Phase-86)` comments mark exact replacement points:
  - `load_bl_weights(engine)` -- current BL weights
  - `load_position_sizing(engine)` -- bet sizes and risk budget
  - `load_weight_history(engine, days=30)` -- historical weights
  - `load_live_positions(engine)` -- exposure summary
- `get_engine` import reserved (noqa: F401) so Phase 86 can add DB calls with zero import changes

---
*Phase: 84-dashboard-perps-portfolio-regimes*
*Completed: 2026-03-23*
