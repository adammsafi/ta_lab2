---
phase: 41-asset-descriptive-stats-correlation
plan: 02
subsystem: database
tags: [pandas, rolling-stats, kurtosis, sharpe, drawdown, multiprocessing, sqlalchemy, psycopg2]

# Dependency graph
requires:
  - phase: 41-01
    provides: "cmc_asset_stats, cmc_asset_stats_state DB tables (Alembic migration)"
  - phase: 27-regime-pipeline
    provides: "refresh_utils.py pattern (parse_ids, resolve_db_url), DimTimeframe.tf_days()"
provides:
  - "refresh_cmc_asset_stats.py: rolling descriptive stats for all assets/TFs"
  - "desc_stats package with watermark-based incremental refresh and multiprocessing"
affects:
  - 41-03-cross-asset-correlation
  - future-research-phases

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Rolling stats with min_periods=window for strict NULL policy (no partial windows)"
    - "scoped DELETE + INSERT write pattern per (id, tf)"
    - "Watermark read with tz_convert('UTC') for Windows tz pitfall safety"
    - "NullPool per worker process, explicit db_url threading to avoid URL masking"

key-files:
  created:
    - src/ta_lab2/scripts/desc_stats/__init__.py
    - src/ta_lab2/scripts/desc_stats/refresh_cmc_asset_stats.py
  modified: []

key-decisions:
  - "kurt_pearson = kurt_fisher + 3.0 (pandas .kurt() returns Fisher/excess, normal=0)"
  - "sharpe_ann = sharpe_raw * sqrt(365.0 / tf_days) for TF-adaptive annualization"
  - "max_dd_from_ath uses expanding window (not rolling) - tracks lifetime ATH continuously"
  - "Watermark lookback = max(windows) * tf_days * 1.5 calendar days to capture full rolling context"
  - "Pass explicit db_url to _process_one (not str(engine.url) which masks the password)"

patterns-established:
  - "Tz-safe watermark: pd.Timestamp(row[0]).tz_convert('UTC') if tzinfo else .tz_localize('UTC')"
  - "Use .tolist() on tz-aware DatetimeSeries for Python datetime objects (avoids FutureWarning)"

# Metrics
duration: 14min
completed: 2026-02-24
---

# Phase 41 Plan 02: Asset Descriptive Stats Refresh Summary

**Per-asset rolling stats engine (8 stats x 4 windows) with watermark-based incremental refresh, writing 5613 rows for BTC/1D in 2.4s**

## Performance

- **Duration:** 14 min
- **Started:** 2026-02-24T16:42:40Z
- **Completed:** 2026-02-24T16:56:40Z
- **Tasks:** 1
- **Files modified:** 2

## Accomplishments

- Created `src/ta_lab2/scripts/desc_stats/` package with `refresh_cmc_asset_stats.py`
- Computes 32 windowed stats (8 stats x 4 windows: 30/60/90/252 bars) + 2 non-windowed per (id, tf)
- Strict NULL policy: exactly `window - 1` NULLs per window (verified: 29/59/89/251 NULL rows for w=30/60/90/252)
- Watermark-based incremental refresh via `cmc_asset_stats_state` (0 rows on second run)
- Multiprocessing with NullPool per worker and `--workers` CLI flag

## Task Commits

Each task was committed atomically:

1. **Task 1: Create desc_stats package and refresh_cmc_asset_stats.py** - `21fde057` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/scripts/desc_stats/__init__.py` - Package marker (empty)
- `src/ta_lab2/scripts/desc_stats/refresh_cmc_asset_stats.py` - Rolling stats computation + CLI + watermark refresh

## Decisions Made

- Used `pandas .rolling(window=W, min_periods=W)` for strict NULL enforcement (no partial windows per spec)
- `kurt_pearson = kurt_fisher + 3.0`: pandas `.kurt()` returns Fisher convention (excess/normal=0), so Pearson = Fisher + 3
- `sharpe_ann = sharpe_raw * sqrt(365.0 / tf_days)`: annualizes with TF-adaptive factor from `dim_timeframe.tf_days_nominal`
- `max_dd_from_ath` uses expanding window (`eq.cummax()`) - tracks all-time-high since inception, not just trailing window
- Watermark lookback: `max(windows) * tf_days * 1.5` calendar days ensures full rolling context for continuity
- Passed explicit `db_url` string through to `get_tf_days()` instead of `str(engine.url)` — SQLAlchemy masks the password in `str()` representation causing authentication failures in worker subprocesses
- Used `.tolist()` on tz-aware DatetimeSeries (instead of `dt.to_pydatetime()`) to avoid pandas FutureWarning

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed SQLAlchemy URL password masking in worker processes**

- **Found during:** Task 1 (first run test)
- **Issue:** `get_tf_days(tf, str(engine.url))` masked the password (`postgres:***`) causing auth failures in workers
- **Fix:** Changed `_process_one(engine, task)` signature to `_process_one(engine, db_url, task)` and passed explicit `db_url` from the caller chain
- **Files modified:** `refresh_cmc_asset_stats.py`
- **Verification:** Script ran successfully after fix
- **Committed in:** `21fde057`

**2. [Rule 1 - Bug] Fixed tz-aware timestamp handling in watermark read**

- **Found during:** Task 1 (second run / incremental test)
- **Issue:** `pd.Timestamp(row[0], tz="UTC")` fails when `row[0]` from DB already has tzinfo (e.g., `-05:00` offset)
- **Fix:** Check `.tzinfo` and use `.tz_convert("UTC")` if set, `.tz_localize("UTC")` otherwise
- **Files modified:** `refresh_cmc_asset_stats.py`
- **Verification:** Incremental refresh ran cleanly with 0 rows on second pass
- **Committed in:** `21fde057`

---

**Total deviations:** 2 auto-fixed (both Rule 1 - Bug)
**Impact on plan:** Both fixes essential for correctness. No scope creep.

## Issues Encountered

None beyond the two auto-fixed bugs documented above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `cmc_asset_stats` populated and queryable; ready for cross-asset correlation (41-03)
- `cmc_asset_stats_state` watermark works correctly; incremental refresh tested
- Run full asset population: `python -m ta_lab2.scripts.desc_stats.refresh_cmc_asset_stats --ids all --tf 1D --workers 4`

---
*Phase: 41-asset-descriptive-stats-correlation*
*Completed: 2026-02-24*
