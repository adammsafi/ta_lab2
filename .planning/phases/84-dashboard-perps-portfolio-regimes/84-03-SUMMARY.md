---
phase: 84-dashboard-perps-portfolio-regimes
plan: "03"
subsystem: ui
tags: [streamlit, plotly, ama, kama, dema, hma, tema, ema, efficiency-ratio, dashboard]

# Dependency graph
requires:
  - phase: 84-01
    provides: dim_ama_params table and ama_multi_tf_u populated
  - phase: 83-dashboard-backtest-signal-pages
    provides: dashboard page patterns, charts.py utilities, queries/research.py

provides:
  - queries/ama.py with 3 cached query functions (load_ama_params_catalogue, load_ama_curves, load_ema_for_comparison)
  - pages/17_ama_inspector.py: full AMA/EMA Inspector page with auto-refresh

affects:
  - 84-04
  - 84-05
  - any future dashboard phases that inspect AMA behavior

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "@st.fragment(run_every=N) pattern for auto-refreshing dashboard sections"
    - "dim_ama_params JOIN in AMA queries for human-readable labels instead of raw params_hash"
    - "Conditional ER chart: render only when indicator==KAMA, suppress with st.info for DEMA/HMA/TEMA"
    - "Cross-asset comparison via dual y-axis (yaxis2 overlaying='y', side='right') for price-normalized assets"

key-files:
  created:
    - src/ta_lab2/dashboard/queries/ama.py
    - src/ta_lab2/dashboard/pages/17_ama_inspector.py
  modified: []

key-decisions:
  - "load_ama_params_catalogue ttl=3600 (dimension data rarely changes, 18 rows)"
  - "load_ama_curves always filters roll=false and alignment_source='multi_tf' to avoid 170M row scan"
  - "er column only rendered when indicator==KAMA -- NULL for DEMA/HMA/TEMA by design"
  - "ema_multi_tf_u uses ema column (not ema_value) in load_ema_for_comparison -- different from load_ema_overlays alias"
  - "Cross-asset comparison uses yaxis2 with overlaying='y' for dual price-normalized chart"

patterns-established:
  - "AMA Inspector: sidebar outside fragment, content inside @st.fragment(run_every=900)"
  - "Comparison view toggle: Overlay vs Side by Side via st.radio in sidebar"
  - "Derivative toggles: st.multiselect(['d1','d2','d1_roll','d2_roll'], default=['d1','d2'])"

# Metrics
duration: 4min
completed: 2026-03-23
---

# Phase 84 Plan 03: AMA/EMA Inspector Summary

**AMA/EMA Inspector page with efficiency ratio (KAMA only), derivative curves, and adaptive vs fixed EMA comparison, using dim_ama_params for human-readable labels**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-23T16:34:52Z
- **Completed:** 2026-03-23T16:39:06Z
- **Tasks:** 2
- **Files created:** 2

## Accomplishments

- Created `queries/ama.py` with 3 cached query functions: `load_ama_params_catalogue` (ttl=3600), `load_ama_curves` (with dim_ama_params JOIN for labels), `load_ema_for_comparison` (canonical alignment_source='multi_tf')
- Created `pages/17_ama_inspector.py` (741 lines) with two modes: Per-Asset Deep Dive (4 sections) and Cross-Asset Comparison
- ER chart conditionally rendered for KAMA only with `st.info` informational message for DEMA/HMA/TEMA
- Period presets (Short/Medium/Long/Custom), derivative toggles, Overlay vs Side-by-Side comparison views, @st.fragment(run_every=900) auto-refresh

## Task Commits

Each task was committed atomically:

1. **Task 1: Create queries/ama.py with AMA/EMA query functions** - `481b858b` (feat)
2. **Task 2: Create pages/17_ama_inspector.py -- AMA/EMA Inspector page** - `e68f249a` (feat)

**Plan metadata:** (included in SUMMARY + STATE commit)

_Note: Both commits required a re-stage after ruff-format reformatted the files (standard pattern in this codebase)._

## Files Created/Modified

- `src/ta_lab2/dashboard/queries/ama.py` -- 3 cached query functions for AMA/EMA inspector; joins dim_ama_params for human labels; filters ama_multi_tf_u by indicator+alignment_source+roll to avoid 170M row scans
- `src/ta_lab2/dashboard/pages/17_ama_inspector.py` -- Full AMA/EMA Inspector page: Per-Asset Deep Dive (value curves, derivatives, ER, AMA vs EMA) and Cross-Asset Comparison mode; 741 lines; @st.fragment(run_every=900)

## Decisions Made

- `load_ama_params_catalogue` ttl=3600 (dimension data, 18 rows, rarely changes)
- `load_ama_curves` always filters `roll=false` and `alignment_source='multi_tf'` -- required to avoid scanning all 170M rows in ama_multi_tf_u
- `er` column conditionally rendered only when `indicator == "KAMA"` -- er is NULL for DEMA/HMA/TEMA by design (not a missing-data case)
- `load_ema_for_comparison` uses `ema` column name (not aliased as `ema_value`) -- differs from `load_ema_overlays` which aliases for build_candlestick_chart compatibility; AMA Inspector page reads `ema` directly
- Cross-asset comparison uses `yaxis2` with `overlaying='y'` and `side='right'` for dual price-normalized chart (assets at different price scales)

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered

- ruff-format reformatted both files on first commit attempt (multi-arg function calls reshaped) -- re-staged and committed clean (standard pattern in this codebase)

## User Setup Required

None -- no external service configuration required. AMA/EMA data must be populated by running the AMA refresh pipeline.

## Next Phase Readiness

- AMA/EMA Inspector page ready for use once ama_multi_tf_u and dim_ama_params are populated
- query layer (`queries/ama.py`) available for reuse by other pages or plans in Phase 84
- Pattern established for conditional ER rendering; reusable for other indicator-specific chart logic

---
*Phase: 84-dashboard-perps-portfolio-regimes*
*Completed: 2026-03-23*
