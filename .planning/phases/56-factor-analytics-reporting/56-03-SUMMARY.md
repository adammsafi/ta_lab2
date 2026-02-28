---
phase: 56-factor-analytics-reporting
plan: "03"
subsystem: analysis
tags: [quintile, factor-analytics, plotly, cross-sectional, monotonicity, pd.qcut]

# Dependency graph
requires:
  - phase: 56-factor-analytics-reporting
    provides: cmc_features table with 100+ feature columns including rsi_14, ret_arith, vol_30d etc.
provides:
  - Cross-sectional quintile returns engine (compute_quintile_returns)
  - Plotly monotonicity chart builder (build_quintile_returns_chart)
  - CLI for any factor column in cmc_features (run_quintile_sweep.py)
affects:
  - 56-04-PLAN.md (factor scoring, may reference quintile engine)
  - 56-05-PLAN.md (reporting, may embed quintile charts)
  - Future notebooks consuming quintile analysis

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Cross-sectional quintile ranking via groupby('ts')[factor].transform(pd.qcut)
    - SQL injection guard via information_schema column validation before dynamic SQL
    - NullPool engine pattern for one-shot CLI scripts

key-files:
  created:
    - src/ta_lab2/analysis/quintile.py
    - src/ta_lab2/scripts/analysis/run_quintile_sweep.py
  modified: []

key-decisions:
  - "Use pd.qcut on rank(method='first') rather than raw values to handle ties deterministically"
  - "Cross-sectional quintile (across all assets at each ts) not time-series quintile (on single asset)"
  - "Validate factor_col against information_schema before building dynamic SQL to prevent injection"
  - "Drop timestamps where any quintile has NaN fwd_ret to ensure clean cumulative return computation"
  - "Long-short spread defined as Q5 - Q1 (absolute cumulative return difference, not ratio)"

patterns-established:
  - "Quintile pattern: groupby('id').transform(shift) for fwd_ret, groupby('ts').transform(pd.qcut) for quintile"
  - "CLI pattern: _validate_factor_col() raises ValueError with available columns for user guidance"

# Metrics
duration: 3min
completed: 2026-02-28
---

# Phase 56 Plan 03: Quintile Returns Engine Summary

**Cross-sectional quintile group returns engine with Plotly monotonicity chart CLI; ranks all assets by factor score into Q1-Q5 at each timestamp and plots cumulative returns per bucket.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-28T06:26:26Z
- **Completed:** 2026-02-28T06:29:15Z
- **Tasks:** 2
- **Files modified:** 2 (created)

## Accomplishments

- `compute_quintile_returns()` performs true cross-sectional ranking across all assets at each timestamp using `pd.qcut(rank(method='first'), 5)`, then averages forward returns per quintile and returns cumulative growth curves
- `build_quintile_returns_chart()` produces a Plotly figure with 5 colored lines (Q1=red, Q2=orange, Q3=green, Q4=blue, Q5=purple) plus an optional dashed black Q5-Q1 long-short spread line
- `run_quintile_sweep.py` CLI loads all assets from `cmc_features WHERE tf = :tf`, validates the factor column against `information_schema` before building SQL, and saves the Plotly HTML chart with a printed summary of Q1/Q5 final returns and spread

## Task Commits

Each task was committed atomically:

1. **Task 1: Create quintile.py library module** - `9f73a9c8` (feat)
2. **Task 2: Create run_quintile_sweep.py CLI** - `6c74977e` (feat)

**Plan metadata:** (committed with SUMMARY below)

## Files Created/Modified

- `src/ta_lab2/analysis/quintile.py` (310 lines) - Cross-sectional quintile engine: `compute_quintile_returns()` and `build_quintile_returns_chart()`
- `src/ta_lab2/scripts/analysis/run_quintile_sweep.py` (315 lines) - CLI: `--factor`, `--tf`, `--horizon`, `--min-assets`, `--output` flags; outputs Plotly HTML

## Decisions Made

- **pd.qcut on rank not raw values:** `pd.qcut(x.rank(method='first'), 5)` handles ties deterministically via `method='first'`. Using raw values would cause `pd.qcut` to fail or produce unequal buckets on tie-heavy data (e.g. identical RSI values for many assets).
- **Cross-sectional not time-series:** Quintile ranking is across all assets at a single `ts`, not across time for a single asset. This is the correct methodology for factor evaluation.
- **SQL injection guard:** Factor column name validated against `information_schema.columns` via `get_columns()` before building any dynamic SQL string.
- **Long-short spread as absolute difference:** `cumulative_df[5] - cumulative_df[1]` (not ratio) so the spread starts at 0.0 and directly shows dollar-per-unit-invested outperformance.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. Pre-commit hooks (ruff format, mixed-line-ending) reformatted files on both commits; re-staged and committed cleanly on second attempt.

## User Setup Required

None - no external service configuration required. CLI uses existing `resolve_db_url()` and `cmc_features` table.

## Next Phase Readiness

- Quintile engine ready for consumption by Phase 56 notebooks and reporting scripts
- CLI usable immediately: `python -m ta_lab2.scripts.analysis.run_quintile_sweep --factor rsi_14 --tf 1D`
- No blockers

---
*Phase: 56-factor-analytics-reporting*
*Completed: 2026-02-28*
