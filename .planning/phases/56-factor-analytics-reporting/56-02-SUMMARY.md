---
phase: 56-factor-analytics-reporting
plan: "02"
subsystem: analysis
tags: [quantstats, tear-sheet, html-report, benchmark, btc, portfolio-analytics]

# Dependency graph
requires:
  - phase: 55-feature-signal-evaluation
    provides: cmc_features table with BTC 1D close prices used for benchmark loading
provides:
  - quantstats>=0.0.81 installed and importable
  - src/ta_lab2/analysis/quantstats_reporter.py with generate_tear_sheet() and _load_btc_benchmark_returns()
  - analytics optional dependency group in pyproject.toml
affects:
  - 56-07 (wires quantstats_reporter into backtest pipeline)
  - any plan producing portfolio returns that needs an HTML tear sheet

# Tech tracking
tech-stack:
  added: [quantstats==0.0.81, seaborn==0.13.2, tabulate==0.9.0]
  patterns:
    - "Lazy import pattern: import quantstats inside function body to make it optional dependency"
    - "Conditional tz-strip: check series.index.tz is not None before tz_localize(None) to avoid double-strip TypeError"
    - "Empty-result guard: return None (not empty Series) from benchmark loader to prevent QuantStats errors"

key-files:
  created:
    - src/ta_lab2/analysis/quantstats_reporter.py
  modified:
    - pyproject.toml

key-decisions:
  - "Lazy import of quantstats inside generate_tear_sheet() body — keeps quantstats optional; ImportError logs warning and returns None"
  - "benchmark=None path calls qs.reports.html() WITHOUT benchmark kwarg (not benchmark=None) to avoid QuantStats internal errors"
  - "_load_btc_benchmark_returns returns None on empty DataFrame AND on empty pct_change result — two distinct guards"
  - "BTC_ID=1 hardcoded as module-level constant (CoinMarketCap canonical ID for Bitcoin)"
  - "periods_per_year=365 for crypto (continuous trading, no weekends off)"

patterns-established:
  - "Tear sheet generation: _load_btc_benchmark_returns -> None check -> generate_tear_sheet(benchmark=None|Series)"
  - "tz normalization for QuantStats: pd.to_datetime(utc=True).dt.tz_localize(None) for DB timestamps; _strip_tz() for Series"

# Metrics
duration: 2min
completed: 2026-02-28
---

# Phase 56 Plan 02: QuantStats Reporter Summary

**QuantStats 0.0.81 installed with `analytics` optional group; `quantstats_reporter.py` delivers `generate_tear_sheet()` wrapping `qs.reports.html` with benchmark=None safety and BTC pct_change loader from `cmc_features`.**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-28T06:25:40Z
- **Completed:** 2026-02-28T06:27:58Z
- **Tasks:** 2/2
- **Files modified:** 2

## Accomplishments

- Installed quantstats==0.0.81 (with seaborn, tabulate, yfinance transitive deps) and added `analytics` optional group to `pyproject.toml`
- Created `quantstats_reporter.py` (185 lines) with `generate_tear_sheet()`, `_load_btc_benchmark_returns()`, and `_strip_tz()` helpers
- Implemented all CRITICAL safety requirements: benchmark=None path, empty-result guard returning None, conditional tz-strip, lazy import with graceful ImportError fallback

## Task Commits

Each task was committed atomically:

1. **Task 1: Install QuantStats and update pyproject.toml** - `4325f808` (chore)
2. **Task 2: Create quantstats_reporter.py module** - `b53c7f4e` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `pyproject.toml` - Added `analytics = ["quantstats>=0.0.81"]` optional dependency group after `validation` group
- `src/ta_lab2/analysis/quantstats_reporter.py` - Reporter module: `generate_tear_sheet()`, `_load_btc_benchmark_returns()`, `_strip_tz()`

## Decisions Made

- **Lazy import**: `import quantstats as qs` placed inside `generate_tear_sheet()` function body so QuantStats remains optional. Missing installation logs a warning and returns None rather than raising.
- **benchmark kwarg omission**: When benchmark_returns is None, call `qs.reports.html(ret, **common_kwargs)` without the `benchmark` keyword rather than `benchmark=None` to avoid potential QuantStats internal errors.
- **Double-guard for None**: `_load_btc_benchmark_returns()` returns None on (a) empty DataFrame from DB query and (b) empty Series after pct_change().dropna(), covering edge cases with only 1 row of price data.
- **periods_per_year=365**: Crypto trades 365 days/year; use 365 not 252 (equity convention).

## Deviations from Plan

None - plan executed exactly as written.

Note: ruff-format pre-commit hook reformatted the multi-line `pd.read_sql(...)` call after initial commit attempt. Re-staged and committed the reformatted file; final result passes all hooks.

## Issues Encountered

Pre-commit hook (ruff-format) reformatted `pd.read_sql(sql, conn, params={...})` from single-line to multi-line on first commit attempt. Fixed by re-staging the hook-modified file and committing again. Not a deviation — standard hook behavior.

## User Setup Required

None - no external service configuration required. QuantStats installed locally.

## Next Phase Readiness

- `generate_tear_sheet()` is ready for Plan 07 to wire into the backtest pipeline
- `_load_btc_benchmark_returns()` requires a live SQLAlchemy engine and populated `cmc_features` table with BTC 1D data
- No blockers for Phase 56 continuation plans (03–07)

---
*Phase: 56-factor-analytics-reporting*
*Completed: 2026-02-28*
