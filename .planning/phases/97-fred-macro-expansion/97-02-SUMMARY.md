---
phase: 97-fred-macro-expansion
plan: 02
subsystem: database
tags: [postgres, alembic, pandas, cross-asset, fred, correlation, btc, equity, vol-regime, divergence]

# Dependency graph
requires:
  - phase: 97-01
    provides: "SP500/NASDAQCOM/DJIA columns in fred_macro_features + equity feature pipeline"
  - phase: 70-cross-asset
    provides: "compute_crypto_macro_corr, upsert_crypto_macro_corr, crypto_macro_corr_regimes table"
provides:
  - "crypto_macro_corr_regimes PK extended to (date, asset_id, macro_var, window)"
  - "compute_btc_equity_corr() computing 3 equity vars x 4 windows = 12 BTC-equity series per date"
  - "equity_vol_regime (calm/elevated/crisis) from 21d realized vol of SP500/NASDAQ/DJIA"
  - "vix_agreement_flag cross-validating equity vol regime vs VIX-derived regime"
  - "divergence_zscore and divergence_flag via 63d rolling z-score of realized-vol vs VIX spread"
  - "Tier-1 asset filter applied to XAGG-04 (compute_crypto_macro_corr)"
  - "Sign-flip alerts filtered to window=60 only (no multi-window spam)"
  - "XAGG-05 wired into refresh_cross_asset_agg.py pipeline"
affects:
  - "phase 97-03 and beyond: divergence signals available for macro signal generation"
  - "dashboard phases: equity vol regime and BTC-equity corr queryable by window"
  - "risk gates: divergence_flag can gate position sizing during equity-crypto divergence"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "PostgreSQL reserved word quoting: 'window' must be double-quoted in all SQL (INSERT, SELECT, ON CONFLICT)"
    - "Multi-window upsert pattern: single upsert_crypto_macro_corr() handles both 60d legacy rows and new equity rows"
    - "venue_id=1 filter on returns_bars_multi_tf_u to avoid multi-venue duplicate rows for single-asset queries"
    - "Post-hoc vectorized z-score: compute row-level values in inner loop, replace with vectorized pass afterward"

key-files:
  created:
    - "alembic/versions/q1r2s3t4u5v6_phase97_crypto_macro_corr_schema.py"
    - ".planning/phases/97-fred-macro-expansion/97-02-SUMMARY.md"
  modified:
    - "src/ta_lab2/macro/cross_asset.py"
    - "configs/cross_asset_config.yaml"
    - "src/ta_lab2/scripts/macro/refresh_cross_asset_agg.py"

key-decisions:
  - "window column in PK (not separate table): simplest extension of existing schema; ON CONFLICT (date, asset_id, macro_var, window) covers both old 60d rows and new multi-window rows"
  - "backward-compat default window=60 in upsert: callers that pass DataFrames without window column (old XAGG-04 path) get window=60 automatically"
  - "'window' double-quoted in all SQL: PostgreSQL reserved word; pandas column name stays unquoted"
  - "venue_id=1 filter on BTC returns: returns_bars_multi_tf_u has one row per (date, venue_id); querying without venue filter returns duplicates causing roll_corr dimension mismatch"
  - "equity correlation uses .diff() not pct_change() for correlation series (matching vix/dxy XAGG-04 pattern), but pct_change(fill_method=None) for realized vol computation"
  - "sign-flip alerts filtered to window=60: 4 windows x 3 vars would 12x the alert volume"

patterns-established:
  - "Pattern: Quote reserved words in dynamic SQL f-strings using _q() helper in upsert functions"
  - "Pattern: Post-hoc vectorized z-score pass over grouped result_df (more efficient than per-row in inner loop)"
  - "Pattern: Use .values[i] with enumerate(all_index) instead of .get(dt) for scalar extraction from rolling series to avoid Series-return on union indices"

# Metrics
duration: 10min
completed: 2026-03-31
---

# Phase 97 Plan 02: Multi-Window BTC-Equity Correlation Summary

**Multi-window BTC-equity rolling correlation (30/60/90/180d) with equity vol regime (calm/elevated/crisis), VIX cross-validation, and divergence z-score signals stored in crypto_macro_corr_regimes via extended (date, asset_id, macro_var, window) PK**

## Performance

- **Duration:** 10 min
- **Started:** 2026-03-31T10:42:59Z
- **Completed:** 2026-03-31T10:53:27Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Alembic migration q1r2s3t4u5v6 adds `window` to PK and 7 new signal columns, backfilling existing rows with window=60
- `compute_btc_equity_corr()` produces 4,272 rows for 3 equity vars x 4 windows with vol regime, VIX agreement, and divergence signals
- `upsert_crypto_macro_corr()` upgraded with multi-column ON CONFLICT target, reserved-word quoting, and backward-compat default window=60
- Tier-1 asset filter + window column added to XAGG-04; sign-flip alerts gated to window=60 only; XAGG-05 wired into refresh pipeline

## Task Commits

1. **Task 1: Alembic migration for crypto_macro_corr_regimes schema** - `cf5e6672` (feat)
2. **Task 2: Multi-window correlation + vol regime + divergence + config + wiring** - `9d4fa985` (feat)

**Plan metadata:** (created in this commit)

## Files Created/Modified

- `alembic/versions/q1r2s3t4u5v6_phase97_crypto_macro_corr_schema.py` - Migration: window in PK + 7 new columns
- `src/ta_lab2/macro/cross_asset.py` - WARMUP_DAYS=210, _rolling_zscore_series(), compute_btc_equity_corr(), updated upsert/alerts/XAGG-04
- `configs/cross_asset_config.yaml` - btc_equity section with corr_windows, vol_regime_thresholds, divergence threshold
- `src/ta_lab2/scripts/macro/refresh_cross_asset_agg.py` - Import + XAGG-05 block calling compute_btc_equity_corr()

## Decisions Made

- `window` column double-quoted in SQL: PostgreSQL reserved word; pandas keeps unquoted column name `window`; `_q()` helper applied consistently in upsert
- venue_id=1 filter on BTC returns: `returns_bars_multi_tf_u` stores one row per (id, venue_id, timestamp); without the filter the union index produces duplicate timestamps causing `roll_corr.get(dt)` to return a Series rather than scalar
- Post-hoc vectorized z-score: computed in grouped loop after all row dicts assembled, avoids recalculating macro series alignment per-row
- Backward-compat default `window=60`: existing XAGG-04 callers that don't include `window` in their DataFrame get 60 injected automatically before upsert

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `Series.get(dt)` returning Series on union DatetimeIndex**
- **Found during:** Task 2 (testing compute_btc_equity_corr)
- **Issue:** `roll_corr.get(dt)` returned a Series (not scalar) when the index contained duplicate timestamps from multi-venue data; `_to_python()` then failed calling `.item()` on a multi-element Series
- **Fix:** Replaced per-date `.get(dt)` access pattern with `enumerate(all_index)` + `.values[i]` for direct positional access to numpy arrays
- **Files modified:** `src/ta_lab2/macro/cross_asset.py`
- **Verification:** compute_btc_equity_corr() produced 4,272 rows without error
- **Committed in:** `9d4fa985` (Task 2 commit)

**2. [Rule 1 - Bug] Fixed `window` SQL reserved word syntax error**
- **Found during:** Task 2 (upsert_crypto_macro_corr testing)
- **Issue:** `INSERT INTO ... (date, asset_id, macro_var, window, ...)` caused PostgreSQL syntax error because `window` is a reserved keyword; same for ON CONFLICT clause
- **Fix:** Added `_q()` helper that double-quotes reserved words in SQL strings; applied to `cols_str`, `set_clause`, and the ON CONFLICT target
- **Files modified:** `src/ta_lab2/macro/cross_asset.py`
- **Verification:** Upsert of 4,272 rows succeeded; `psycopg2.errors.SyntaxError` gone
- **Committed in:** `9d4fa985` (Task 2 commit)

**3. [Rule 1 - Bug] Fixed duplicate BTC rows from multi-venue returns table**
- **Found during:** Task 2 (debugging zero-row output)
- **Issue:** `returns_bars_multi_tf_u` had two rows per date for BTC (venue_id=1 and venue_id=2); after btc_df.set_index("date") the `all_index` union had correct length but the original `roll_corr` computation was silently returning all NaN due to the pivot producing duplicate-indexed series
- **Fix:** Added `AND venue_id = 1` filter to the BTC returns SQL query
- **Files modified:** `src/ta_lab2/macro/cross_asset.py`
- **Verification:** 4,272 non-null rows computed after fix (was 0 before)
- **Committed in:** `9d4fa985` (Task 2 commit)

**4. [Rule 1 - Bug] Fixed `pct_change()` deprecation warning**
- **Found during:** Task 2 (test run output)
- **Issue:** Pandas deprecated `fill_method='pad'` default in `Series.pct_change()`; produces FutureWarning and will break in future pandas version
- **Fix:** Changed `.pct_change()` to `.pct_change(fill_method=None)` in two places in `compute_btc_equity_corr()`
- **Files modified:** `src/ta_lab2/macro/cross_asset.py`
- **Verification:** No FutureWarning in test run after fix
- **Committed in:** `9d4fa985` (Task 2 commit)

---

**Total deviations:** 4 auto-fixed (all Rule 1 - Bug)
**Impact on plan:** All auto-fixes were necessary for correctness. No scope creep. The core design (multi-window corr, vol regime, divergence, upsert) implemented exactly as specified.

## Issues Encountered

- SP500/NASDAQCOM/DJIA data in `fred_macro_features` only starts 2025-02-19 (the Phase 97-01 output). Testing with dates before this returned empty results; used `start_date='2025-02-19'` for validation runs. As FRED sync accumulates more history this window will extend.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `crypto_macro_corr_regimes` now contains 4,272 BTC-equity rows across 3 equity vars x 4 windows
- `equity_vol_regime`, `vix_agreement_flag`, `divergence_zscore`, `divergence_flag` all populated
- `divergence_flag=True` currently at ~308 rows (7.2% of equity corr rows) -- plausible signal rate
- XAGG-05 is wired into `refresh_cross_asset_agg.py` and will auto-compute on each daily refresh
- As more SP500/NASDAQ/DJIA history accumulates from FRED VM sync, the 30d/60d/90d/180d windows will fill in historical rows automatically on the next `--full` refresh run

---
*Phase: 97-fred-macro-expansion*
*Completed: 2026-03-31*
