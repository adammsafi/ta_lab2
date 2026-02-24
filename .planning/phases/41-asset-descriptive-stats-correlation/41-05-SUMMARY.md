---
phase: 41-asset-descriptive-stats-correlation
plan: "05"
subsystem: dashboard
tags: [streamlit, plotly, heatmap, correlation, descriptive-stats, dashboard, sqlalchemy]

# Dependency graph
requires:
  - phase: 41-01
    provides: "cmc_asset_stats, cmc_corr_latest materialized view, cmc_cross_asset_corr"
  - phase: 39-dashboard
    provides: "Dashboard patterns: db.py, charts.py, queries/, pages/ structure"
provides:
  - "asset_stats.py: 4 cached query functions for asset stats and correlation"
  - "4_asset_stats.py: Streamlit page with stats table, correlation heatmap, and time-series explorer"
  - "charts.py: build_correlation_heatmap (symmetric NxN, RdBu, zmid=0) and build_stat_timeseries_chart"
affects:
  - "41-06 and future phases that extend the dashboard"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Symmetric NxN correlation matrix built from long-format (symbol_a, symbol_b, value) DataFrame"
    - "PostgreSQL reserved word 'window' double-quoted in all raw SQL: \"window\""
    - "DISTINCT ON (id) subquery for latest-per-asset stats fetch"
    - "Plotly go.Heatmap with RdBu colorscale, zmid=0, zmin=-1, zmax=1 for correlation display"
    - "Empty data handled via st.info before chart render to prevent crashes"

key-files:
  created:
    - src/ta_lab2/dashboard/queries/asset_stats.py
    - src/ta_lab2/dashboard/pages/4_asset_stats.py
  modified:
    - src/ta_lab2/dashboard/charts.py
    - src/ta_lab2/dashboard/app.py

key-decisions:
  - "Double-quoted 'window' in all raw SQL — PostgreSQL reserved word from 41-01 design"
  - "Sidebar filters (TF + window) drive both stats table and heatmap section simultaneously"
  - "Page registered in app.py under new 'Analytics' navigation group (not 'Research')"
  - "load_asset_symbols uses ttl=3600 (asset list rarely changes); all other functions use ttl=300"
  - "Heatmap diagonal set to 1.0 explicitly; off-diagonal mirrors lower triangle for symmetry"

patterns-established:
  - "Pattern: sidebar filters for TF + window shared across all sections of a single page"
  - "Pattern: build_correlation_heatmap accepts any long-format corr_df, selects metric by column name"

# Metrics
duration: 3min
completed: "2026-02-24"
---

# Phase 41 Plan 05: Asset Stats Dashboard Page Summary

**Asset stats + correlation dashboard: 4 cached query functions (NullPool), symmetric RdBu heatmap via go.Heatmap, and interactive Streamlit page with TF/window sidebar filters**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-24T16:51:57Z
- **Completed:** 2026-02-24T16:54:53Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Created `src/ta_lab2/dashboard/queries/asset_stats.py` with 4 cached query functions:
  - `load_asset_stats_latest` — DISTINCT ON subquery for latest snapshot per asset
  - `load_corr_latest` — queries `cmc_corr_latest` materialized view with double-quoted `"window"`
  - `load_asset_stats_timeseries` — full time series indexed by ts
  - `load_asset_symbols` — id→symbol map with 1-hour TTL
- Added `build_correlation_heatmap` to `charts.py`:
  - Builds symmetric N×N matrix from long-format (symbol_a, symbol_b, value) rows
  - Plotly `go.Heatmap` with `colorscale="RdBu"`, `zmid=0`, `zmin=-1`, `zmax=1`
  - Text annotations at 2 decimal places
- Added `build_stat_timeseries_chart` to `charts.py`:
  - Simple `go.Scatter` line chart with `plotly_dark` template
- Created `src/ta_lab2/dashboard/pages/4_asset_stats.py` with 3 sections:
  - Section 1: Latest stats table with multiselect column filter (defaults to 252-window stats), formatted to 4 decimal places, CSV download
  - Section 2: Correlation heatmap with Pearson/Spearman radio toggle, raw table expander, HTML download
  - Section 3: Per-asset rolling stat time-series (expandable, asset + stat column selectors)
- Registered page in `app.py` under new `"Analytics"` navigation group

## Task Commits

Each task was committed atomically:

1. **Task 1: Create asset_stats query module** - `49eb6852` (feat)
2. **Task 2: Add correlation heatmap to charts.py and create dashboard page** - `4efde56e` (feat)

## Files Created/Modified

- `src/ta_lab2/dashboard/queries/asset_stats.py` — 4 cached query functions; double-quoted "window" in raw SQL
- `src/ta_lab2/dashboard/charts.py` — Added build_correlation_heatmap + build_stat_timeseries_chart
- `src/ta_lab2/dashboard/pages/4_asset_stats.py` — Full 3-section dashboard page
- `src/ta_lab2/dashboard/app.py` — Added Analytics section with new page registration

## Decisions Made

- **Navigation group "Analytics"**: The new page is distinct from pure research/IC work (which lives under "Research"), so registered under a new "Analytics" group in `app.py`.
- **Symmetric matrix construction**: Long-format corr rows only store the lower triangle (CHECK id_a < id_b); the heatmap builder mirrors each value to both `mat[ia][ib]` and `mat[ib][ia]` for visual symmetry.
- **Diagonal = 1.0**: Self-correlation is always 1; explicitly set so the diagonal doesn't appear as a gap.
- **Double-quoted "window"**: Carried forward from 41-01 pattern — all raw SQL must quote this PostgreSQL reserved word.
- **load_asset_symbols TTL=3600**: Assets change rarely; longer cache avoids pointless DB hits on every page rerun.

## Deviations from Plan

None — plan executed exactly as written.

## Authentication Gates

None.

## Issues Encountered

Pre-commit hooks (ruff-format + mixed-line-ending) auto-fixed line endings and formatting on both commits. Fixed by re-staging the hook-modified files before re-committing. No code logic changes resulted.

## Next Phase Readiness

- Dashboard page is live; requires data in `cmc_asset_stats` and `cmc_corr_latest` to render
- Run `python -m ta_lab2.scripts.desc_stats.refresh_cmc_asset_stats --ids all` to populate stats
- Run the cross-asset correlation refresh (41-03) and `REFRESH MATERIALIZED VIEW cmc_corr_latest` to populate heatmap
- Phase 41-06 can proceed immediately (no blockers from this plan)

---
*Phase: 41-asset-descriptive-stats-correlation*
*Completed: 2026-02-24*
