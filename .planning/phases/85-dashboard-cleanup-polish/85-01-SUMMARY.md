---
phase: 85
plan: "01"
name: "dashboard-backend-fixes"
subsystem: "dashboard"
tags: ["streamlit", "dashboard", "pipeline", "trading", "drawdown", "navigation"]

dependency-graph:
  requires: ["84-dashboard-perps-portfolio-regimes"]
  provides: ["corrected-drawdown", "dynamic-stats-discovery", "reorganized-navigation"]
  affects: ["85-02", "dashboard/pages/2_pipeline_monitor.py", "dashboard/pages/6_trading.py"]

tech-stack:
  added: []
  patterns:
    - "information_schema auto-discovery for stats tables"
    - "starting-capital-anchored drawdown calculation"
    - "cache tier caption pattern (no decorative sliders)"

key-files:
  created: []
  modified:
    - "src/ta_lab2/dashboard/app.py"
    - "src/ta_lab2/dashboard/queries/pipeline.py"
    - "src/ta_lab2/dashboard/queries/trading.py"

decisions:
  - id: "stats-auto-discovery"
    choice: "information_schema JOIN on status column + LIKE '%\\_stats'"
    rationale: "Excludes asset_stats (no status col) and watermark tables (_stats_state). Zero-maintenance as new stats tables are added."
  - id: "starting-capital-denominator"
    choice: "drawdown_pct = (equity - peak_equity) / starting_capital"
    rationale: "Denominator is always > 0 (starting_capital from dim_executor_config with fallback 100k). Avoids division-by-zero on first trading day."
  - id: "nav-split-analysis-to-research-markets"
    choice: "Analysis group split into Research (6) + Markets (4)"
    rationale: "Phase 84 added 4 market-data pages all crammed into Analysis (10 pages total). Markets group gives Phase 84 pages a logical home."
  - id: "stats-tables-tuple-param"
    choice: "stats_tables parameter is tuple[str, ...] | None for cache hashability"
    rationale: "st.cache_data cannot hash lists; callers that pass explicit lists must use tuple(). Documented in function docstring."

metrics:
  duration: "3 min"
  completed: "2026-03-23"
  tasks-completed: 3
  tasks-total: 3
---

# Phase 85 Plan 01: Dashboard Backend Fixes Summary

**One-liner:** Replaced decorative cache slider with tier caption, auto-discovered stats tables via information_schema, fixed drawdown to use starting capital from dim_executor_config, reorganized nav into Research + Markets groups.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Fix cache TTL sidebar + stats auto-discovery | e70ec279 | app.py, queries/pipeline.py |
| 2 | Fix drawdown with starting capital | 6e63ee31 | queries/trading.py |
| 3 | Reorganize navigation groups | e70ec279 | app.py |

Note: Tasks 1 and 3 both touched app.py and were committed together.

## What Was Built

### Task 1: Sidebar cleanup + pipeline.py stats auto-discovery

**app.py sidebar** -- removed the `st.slider("Cache TTL (s)", ...)` which was decorative (slider had no effect on actual cache TTLs, which are hardcoded per function). Replaced with:
- `st.button("Refresh Now")` (already present, kept)
- `st.caption("Cache tiers: Live 2min | Pipeline 5min | Research 60min")` communicates actual TTL policy

**pipeline.py** -- replaced the hardcoded `_STATS_TABLES` list (6 tables) with:
- `load_stats_tables(_engine)` -- queries `information_schema.tables` JOINed with `information_schema.columns` on `column_name='status'`, filtered to `table_name LIKE '%\_stats'` (raw string to avoid Python escape warning). Returns auto-discovered list sorted alphabetically.
- `load_stats_status()` -- accepts optional `stats_tables: tuple[str, ...] | None` parameter, defaults to `load_stats_tables(_engine)` if None
- `load_alert_history()` -- same optional parameter pattern

### Task 2: Drawdown calculation fix

**queries/trading.py** -- two changes:

1. New `load_starting_capital(_engine)` function (ttl=3600):
   - Queries `SUM(initial_capital)` from active `dim_executor_config` rows
   - `COALESCE(..., 100000.0)` fallback if no active configs
   - Returns `float`

2. Fixed `load_daily_pnl_series(_engine)`:
   - Old: `peak_equity = cumulative_pnl.cummax()` then `drawdown_pct = (cum_pnl - peak) / peak.where(peak != 0, 1)` -- the `.where(peak != 0, 1)` was a hack to avoid division-by-zero on day 1 when cumulative_pnl=0
   - New: `equity = starting_capital + cumulative_pnl`, `peak_equity = equity.cummax()`, `drawdown_pct = (equity - peak_equity) / starting_capital` -- denominator is always a positive constant
   - Added `drawdown_usd = equity - peak_equity` column for dollar-amount KPI display
   - Updated docstring to list all 7 columns including the 2 new ones

### Task 3: Navigation groups reorganization

Split the 10-page "Analysis" group into:
- **Research** (6 pages): Asset Hub, Backtest Results, Signal Browser, Research Explorer, Feature Experiments, Asset Statistics
- **Markets** (4 pages): Perps, Portfolio, Regime Heatmap, AMA Inspector

Overview (1) and Operations (5) and Monitor (1) unchanged. Total pages: 17 (same as before, just reorganized).

## Verification Results

All 7 plan verification checks passed:
1. `python -m py_compile src/ta_lab2/dashboard/app.py` -- exit 0
2. `python -m py_compile src/ta_lab2/dashboard/queries/pipeline.py` -- exit 0
3. `python -m py_compile src/ta_lab2/dashboard/queries/trading.py` -- exit 0
4. `from ta_lab2.dashboard.queries.pipeline import load_stats_tables` -- OK
5. `from ta_lab2.dashboard.queries.trading import load_starting_capital` -- OK
6. `_STATS_TABLES` occurrences in pipeline.py: 0
7. `cache_ttl_display` occurrences in app.py: 0

Additional checks:
- "Research" group count in app.py: 1
- "Markets" group count in app.py: 1
- "Analysis" group count in app.py: 0 (correctly removed)
- ruff lint + ruff format: Passed (pre-commit hooks)

## Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| stats-auto-discovery | `information_schema` JOIN on `status` column + `LIKE '%\_stats'` | Excludes `asset_stats` (no status col), excludes watermark tables. Zero-maintenance. |
| starting-capital-denominator | `drawdown_pct = (equity - peak_equity) / starting_capital` | Constant denominator, never zero. Semantically correct (% of initial capital). |
| nav-split | Analysis → Research + Markets | 10 pages in one group is too many; Markets group logical home for Phase 84 data pages. |
| stats-tables-tuple-param | `tuple[str, ...] \| None` | st.cache_data cannot hash lists. Documented. |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Python SyntaxWarning for `\_` in SQL LIKE string**

- **Found during:** Task 1 verification (compile produced SyntaxWarning)
- **Issue:** `text("""... LIKE '%\_stats' ...""")` -- Python treats `\_` as an unrecognized escape sequence in a regular string (SyntaxWarning in Python 3.12+)
- **Fix:** Changed to raw string `text(r"""...""")` so Python does not interpret `\_` -- the backslash reaches PostgreSQL as intended for LIKE escape
- **Files modified:** `src/ta_lab2/dashboard/queries/pipeline.py`
- **Commit:** e70ec279 (included in Task 1 commit)

## Next Phase Readiness

Plan 85-02 (dashboard frontend polish) can proceed immediately. No blockers. The `load_stats_tables()`, `load_starting_capital()`, and `drawdown_usd` column are all available for use in page files.
