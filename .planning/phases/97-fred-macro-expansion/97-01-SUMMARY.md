---
phase: 97-fred-macro-expansion
plan: 01
subsystem: macro
tags: [fred, macro, equity-indices, sp500, nasdaq, djia, feature-engineering, alembic, postgresql]

# Dependency graph
requires:
  - phase: 66-fred-features
    provides: compute_derived_features_66, db_columns allowlist pattern, _RENAME_MAP, forward_fill.py FFILL_LIMITS
  - phase: 96-executor-activation
    provides: Alembic chain head (o9p0q1r2s3t4)
provides:
  - SP500, NASDAQCOM, DJIA series in SERIES_TO_LOAD (21 total)
  - compute_per_series_features_97() function computing 8 derived features per equity index
  - 27 new columns in fred.fred_macro_features (3 raw + 24 derived)
  - Alembic migration p0q1r2s3t4u5 reversibly adding those 27 columns
  - Phase97 equity_indices feature group in refresh_macro_features.py summary output
affects:
  - 97-02: MACRO-02 (equity-crypto divergence) -- depends on sp500/nasdaqcom/djia columns
  - Any downstream dashboard or signal that consumes fred_macro_features

# Tech tracking
tech-stack:
  added: []
  patterns:
    - per-series feature loop: _EQUITY_INDEX_SERIES list drives uniform 8-feature computation per index
    - db_columns allowlist: raw columns covered by list(_RENAME_MAP.values()); only add derived columns explicitly
    - NaN placeholder pattern: when series missing, write float("nan") for all 8 derived cols to keep schema consistent

key-files:
  created:
    - alembic/versions/p0q1r2s3t4u5_phase97_equity_index_columns.py
  modified:
    - src/ta_lab2/macro/fred_reader.py
    - src/ta_lab2/macro/feature_computer.py
    - src/ta_lab2/scripts/macro/refresh_macro_features.py

key-decisions:
  - "Do not duplicate raw columns in db_columns allowlist -- list(_RENAME_MAP.values()) already includes sp500/nasdaqcom/djia; only derived columns need explicit allowlisting"
  - "Use 252-day rolling z-score for equity indices matching _rolling_zscore helper; drawdown uses 252-day rolling max with min_periods=1 to handle sparse early data"
  - "vol_21d uses min_periods=17 (80% of 21) matching DEXJPUS pattern from Phase 66"
  - "ma_ratio uses min_periods=40/160 (80% of 50/200) for graceful partial results"

patterns-established:
  - "Per-series feature loop: _EQUITY_INDEX_SERIES constant + loop avoids copy-paste; future series can be added to the list"
  - "Alembic down_revision chain: p0q1r2s3t4u5 -> o9p0q1r2s3t4 -> n8o9p0q1r2s3"

# Metrics
duration: 6min
completed: 2026-03-31
---

# Phase 97 Plan 01: FRED Macro Expansion - Equity Index Features Summary

**SP500/NASDAQCOM/DJIA added to fred_macro_features with 8 derived features each (ret_1d/5d/21d/63d, vol_21d, drawdown_pct, ma_ratio_50_200d, zscore_252d) via Alembic migration p0q1r2s3t4u5**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-31T10:31:42Z
- **Completed:** 2026-03-31T10:37:58Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added SP500, NASDAQCOM, DJIA to SERIES_TO_LOAD (21 total, was 18) and _RENAME_MAP (21 total)
- Created Alembic migration p0q1r2s3t4u5 adding 27 nullable DOUBLE PRECISION columns to fred.fred_macro_features; reversible via downgrade
- Implemented compute_per_series_features_97() with 8 derived features per equity index using _rolling_zscore helper and DEXJPUS-consistent patterns
- Wired into compute_macro_features() pipeline as Step 3c after Phase 66
- Live refresh: 401 rows upserted, Phase97 equity_indices 27/27 columns populated

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration + SERIES_TO_LOAD + _RENAME_MAP** - `67b572a3` (feat)
2. **Task 2: Compute function + db_columns allowlist + feature group logging** - `80f1944f` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `alembic/versions/p0q1r2s3t4u5_phase97_equity_index_columns.py` - Migration adding 27 columns to fred.fred_macro_features
- `src/ta_lab2/macro/fred_reader.py` - Added SP500, NASDAQCOM, DJIA to SERIES_TO_LOAD; updated docstring (21 series)
- `src/ta_lab2/macro/feature_computer.py` - Added _EQUITY_INDEX_SERIES, compute_per_series_features_97(), Step 3c wire-in, 24 new derived cols in db_columns allowlist; updated _RENAME_MAP (21 entries)
- `src/ta_lab2/scripts/macro/refresh_macro_features.py` - Added Phase97 equity_indices to _FEATURE_GROUPS (27 cols), sp500 to _STALENESS_CHECK_COLS

## Decisions Made

- **db_columns allowlist deduplication:** list(_RENAME_MAP.values()) already includes sp500/nasdaqcom/djia after the rename step. Adding them again in the Phase 97 block causes duplicate DataFrame columns, which pandas represents as a DataFrame when indexed (ambiguous truth value). Fix: only add the 24 derived columns explicitly; raw columns are covered by the rename map values.
- **Drawdown min_periods=1:** Rolling max with min_periods=1 ensures drawdown is computed even with a single observation, producing correct -0.0 at the series start instead of NaN.
- **Reuse _rolling_zscore helper:** zscore_252d uses existing _rolling_zscore(series, 252) with default 80% fill requirement (201 days minimum).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed duplicate raw columns from db_columns allowlist**

- **Found during:** Task 2 verification (dry-run)
- **Issue:** Plan specified adding all 27 columns (3 raw + 24 derived) to the Phase 97 db_columns block. However, the raw columns (sp500, nasdaqcom, djia) are already included via `list(_RENAME_MAP.values())` which heads the db_columns list. The duplicate entries caused `df_derived[keep_cols]` to produce a DataFrame with duplicate columns, making `df["sp500"]` return a DataFrame (not Series), triggering `ValueError: The truth value of a Series is ambiguous` in _print_feature_summary.
- **Fix:** Removed the 3 raw column entries from the Phase 97 block; kept only the 24 derived columns. All 27 still appear in the final output.
- **Files modified:** src/ta_lab2/macro/feature_computer.py
- **Verification:** dry-run shows Phase97 equity_indices 27/27 populated; DB query confirms sp500 values non-NULL
- **Committed in:** 80f1944f (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Essential fix for correctness. No scope change; all 27 columns still delivered.

## Issues Encountered

None beyond the auto-fixed duplicate columns bug above.

## User Setup Required

**VM prerequisite (manual, one-time):** The GCP VM FRED collector must have SP500, NASDAQCOM, and DJIA in its series list. SSH to the VM and verify `~/.fred.env` includes these three series IDs. Without this, `sync_fred_from_vm` will not pull new data for these series beyond what was already in fred.series_values.

The series already had data in fred.series_values at plan execution time (401 rows back to 2025-02-19), confirming the VM was already collecting them. No action needed if data is present.

## Next Phase Readiness

- sp500, nasdaqcom, djia and all 24 derived columns are now in fred.fred_macro_features
- Phase 97-02 (MACRO-02: equity-crypto divergence) can directly query these columns
- FRED data freshness: DFF is 154h old (>48h threshold) -- run sync_fred_from_vm before 97-02 live testing

---
*Phase: 97-fred-macro-expansion*
*Completed: 2026-03-31*
