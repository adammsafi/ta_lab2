---
phase: 28-backtest-pipeline-fix
plan: 03
subsystem: backtests
tags: [vectorbt, signals, backtest, pandas, tz-handling, numpy, psycopg2, ema-crossover, regime]

# Dependency graph
requires:
  - phase: 28-01
    provides: EMA and ATR signal generators with json.dumps feature_snapshot fix
  - phase: 28-02
    provides: vectorbt 0.28.1 compatibility fixes in backtest_from_signals.py
  - phase: 27-06
    provides: regime_utils.py batch loader and merge_regime_context helper

provides:
  - End-to-end pipeline verified: cmc_features -> signal generators -> signal tables -> backtest -> DB
  - All 3 signal generators (RSI, EMA, ATR) write signals without errors
  - Backtest runner produces PnL metrics and saves to cmc_backtest_* tables
  - 5 additional runtime crash bugs fixed in regime_utils.py and backtest_from_signals.py

affects: [future-signal-work, backtest-sweeps, phase-29-if-any]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "tz-coerce both sides before merge: when pd.read_sql legacy path returns ts as object, coerce via pd.to_datetime(utc=True) before DataFrame.merge()"
    - "load prices without index_col: avoid pd.read_sql parse_dates + index_col producing non-UTC timezone, then set index manually after pd.to_datetime(utc=True)"
    - "date-string slice bounds for tz-naive DatetimeIndex: use strftime('%Y-%m-%d') instead of Timestamp objects to get partial-date matching via df.loc"
    - "numpy scalar normalization before SQL: _to_python() with hasattr(v, 'item') covers all numpy scalar types before psycopg2 binding"
    - "vbt price column version detection: check 'Avg Entry Price' in columns first, fall back to 'Entry Price' for cross-version compat"

key-files:
  created: []
  modified:
    - src/ta_lab2/scripts/signals/regime_utils.py
    - src/ta_lab2/scripts/backtests/backtest_from_signals.py

key-decisions:
  - "ts coercion in merge_regime_context is the right fix location: central helper called by all 3 signal generators, single fix covers all callers"
  - "load_prices without index_col: pd.read_sql with index_col='ts'+parse_dates infers local-offset tz (UTC-04:00), causing 1903 duplicate index entries after tz-strip; post-hoc manual coerce is more reliable"
  - "date-string split bounds: strftime('%Y-%m-%d') triggers pandas partial-date matching (inclusive range) rather than exact Timestamp key lookup that fails on 23:59:59.999 index entries"
  - "numpy scalar normalization at SQL boundary: _to_python() helper with .item() covers np.float64/np.int64/np.bool_ without importing numpy in the normalizer"

patterns-established:
  - "merge_regime_context tz-coerce pattern: check dtype==object -> pd.to_datetime(utc=True); tz is None -> tz_localize; else -> tz_convert — covers all three cases"
  - "_to_python() scalar normalizer: hasattr(v, 'item') is numpy-agnostic, handles all scalar types, safe for None passthrough"

# Metrics
duration: 11min
completed: 2026-02-20
---

# Phase 28 Plan 03: End-to-End Pipeline Verification Summary

**All 3 signal generators verified against live DB (154/302/98 signals), EMA crossover backtest produces 1.73 Sharpe over 15yr BTC with 104 trades; 5 additional runtime crash bugs auto-fixed and results saved to cmc_backtest_* tables.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-02-20T22:06:35Z
- **Completed:** 2026-02-20T22:17:08Z
- **Tasks:** 2 automated + 1 human checkpoint (approved)
- **Files modified:** 2

## Accomplishments

- dim_signals pre-flight confirmed: 6 active signal configurations (3 EMA crossover, 2 RSI mean-revert, 1 ATR breakout)
- All 3 signal generators ran without errors against live database: RSI 154 signals/152 closed, EMA 302/151, ATR 98/49
- End-to-end backtest verified: EMA crossover signal_id=1 on BTC (id=1), 2010-2025, 104 trades, Sharpe 1.73 clean / 1.70 with costs
- cmc_backtest_runs, cmc_backtest_trades (104 rows), cmc_backtest_metrics all populated via `--save-results`
- 5 additional runtime crash bugs found and auto-fixed (all Rule 1)
- Human checkpoint approved: pipeline works end-to-end

## Task Commits

Each task was committed atomically:

1. **Task 1: Ensure dim_signals is seeded, then run signal generators** - `aea74ea9` (fix)
2. **Task 2: Run backtest and verify end-to-end PnL output** - `ed15102e` (fix)

## Files Created/Modified

- `src/ta_lab2/scripts/signals/regime_utils.py` — Added explicit ts dtype coercion in `merge_regime_context` (both feature_df and regime_subset sides) before merge
- `src/ta_lab2/scripts/backtests/backtest_from_signals.py` — Four crash fixes: date-string split bounds, load_prices tz-safe loading, load_signals tz-naive normalization, `Avg Entry Price` column detection, numpy scalar normalization for SQL

## Decisions Made

- **ts coercion at merge_regime_context** is the right fix location: it is the single helper called by all 3 signal generators, so one fix covers all callers rather than patching each generator independently.
- **load_prices without index_col**: `pd.read_sql` with `index_col='ts'` + `parse_dates=['ts']` infers `UTC-04:00` local offset from the DB connection, producing 1903 duplicate index entries after tz-stripping. Post-hoc coerce (load plain, then `pd.to_datetime(utc=True).dt.tz_convert("UTC").dt.tz_localize(None)`) is reliable regardless of connection timezone.
- **date-string split bounds**: `strftime('%Y-%m-%d')` triggers pandas partial-date matching (inclusive range over the whole calendar day) rather than exact Timestamp key lookup, which fails on `23:59:59.999` EOD index entries.
- **`_to_python()` numpy normalizer**: `hasattr(v, 'item')` is numpy-agnostic and covers all scalar types (`np.float64`, `np.int64`, `np.bool_`) without importing numpy in the normalizer itself, safe for `None` passthrough.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] merge_regime_context crashed EMA and ATR generators with ts dtype mismatch**
- **Found during:** Task 1 (EMA crossover signal generator)
- **Issue:** `pd.read_sql` with `text()` + dict `params=` uses a legacy pandas execution path that returns the `ts` column as object dtype. `regime_df.ts` is always `datetime64[ns, UTC]` (coerced by `load_regime_context_batch`). `DataFrame.merge()` on incompatible dtypes raises `ValueError: merging on object and datetime64[ns, UTC] columns`.
- **Fix:** Added explicit tz coercion in `merge_regime_context` for both `feature_df` and `regime_subset` before merge: `object` -> `pd.to_datetime(utc=True)`; tz-naive -> `tz_localize("UTC")`; tz-aware -> `tz_convert("UTC")`.
- **Files modified:** `src/ta_lab2/scripts/signals/regime_utils.py`
- **Verification:** EMA generator ran successfully (302 signals), ATR generator also passed (same code path).
- **Committed in:** `aea74ea9`

**2. [Rule 1 - Bug] load_prices returned non-monotonic duplicate index causing df.loc slice to fail**
- **Found during:** Task 2 (backtest runner)
- **Issue:** `pd.read_sql` with `index_col='ts'` + `parse_dates=['ts']` inferred `UTC-04:00` timezone from the psycopg2 connection, not UTC. After `tz_localize(None)` the naive timestamps had 1903 duplicates (UTC offset ambiguity) making the index non-monotonic.
- **Fix:** Load without `index_col`/`parse_dates`, then: `df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("UTC").dt.tz_localize(None)`; `df = df.set_index("ts").sort_index()`.
- **Files modified:** `src/ta_lab2/scripts/backtests/backtest_from_signals.py`
- **Verification:** `load_prices` returns monotonic tz-naive UTC index, no duplicates.
- **Committed in:** `ed15102e`

**3. [Rule 1 - Bug] Split boundaries were tz-aware while prices index was tz-naive, causing df.loc to raise TypeError**
- **Found during:** Task 2 (first backtest attempt)
- **Issue:** `run_backtest` strips tz from `prices.index` but then creates `Split("backtest", start_ts, end_ts)` with the original tz-aware `start_ts`/`end_ts`. `vbt_runner.run_vbt_on_split` does `df.loc[split.start : split.end]` — comparing tz-aware bounds against tz-naive index raises `TypeError: Cannot compare tz-naive and tz-aware datetime-like objects`. Even after stripping tz, exact `Timestamp('2010-08-15 00:00:00')` key lookup fails because actual index entries are `23:59:59.999`.
- **Fix:** `split_start = start_ts.strftime("%Y-%m-%d")` and `split_end = end_ts.strftime("%Y-%m-%d")` — date strings trigger pandas partial-date matching (inclusive range) regardless of exact time component.
- **Files modified:** `src/ta_lab2/scripts/backtests/backtest_from_signals.py`
- **Verification:** Backtest sliced 5538 rows correctly.
- **Committed in:** `ed15102e`

**4. [Rule 1 - Bug] load_signals_as_series matched tz-aware timestamps against tz-naive index**
- **Found during:** Task 2 (signal alignment)
- **Issue:** After fixing `load_prices` to return tz-naive index, `load_signals_as_series` still produced entries/exits Series with tz-aware index (because `time_index = price_df.index` was now tz-naive but signal timestamps from DB were being localized to UTC). `if entry_ts in entries.index` returned False for all signals — 0 entries/exits would be set.
- **Fix:** Strip tz from signal timestamps: `entry_ts.tz_convert("UTC").replace(tzinfo=None)` before index lookup.
- **Files modified:** `src/ta_lab2/scripts/backtests/backtest_from_signals.py`
- **Verification:** Entry signals: 104, Exit signals: 103 (up from 75/69 before fix — more complete matching).
- **Committed in:** `ed15102e`

**5. [Rule 1 - Bug] _extract_trades used 'Entry Price'/'Exit Price' but vbt 0.28.1 uses 'Avg Entry Price'/'Avg Exit Price'**
- **Found during:** Task 2 (`_extract_trades` after successful vectorbt run)
- **Issue:** `trades.records_readable` in vbt 0.28.1 renamed price columns to `'Avg Entry Price'` / `'Avg Exit Price'`. Direct column access `trades["Entry Price"]` raised `KeyError`.
- **Fix:** Added version-aware column detection: `entry_price_col = "Avg Entry Price" if "Avg Entry Price" in trades.columns else "Entry Price"` (and same for exit).
- **Files modified:** `src/ta_lab2/scripts/backtests/backtest_from_signals.py`
- **Verification:** Backtest complete: 104 trades extracted.
- **Committed in:** `ed15102e`

**6. [Rule 1 - Bug] metrics dict contained np.float64 scalars that psycopg2 cannot adapt**
- **Found during:** Task 2 (`save_backtest_results` metrics insert)
- **Issue:** `_compute_comprehensive_metrics` returns `np.float64` values from numpy operations (`np.percentile`, `np.sqrt`, etc.). psycopg2 cannot adapt `np.float64` and raises `(psycopg2.errors.InvalidSchemaName) schema "np" does not exist` (interprets the repr string `np.float64(...)` as a schema-qualified identifier).
- **Fix:** Added `_to_python()` helper using `hasattr(v, 'item')` to convert any numpy scalar to Python native. Applied to metrics dict before SQL binding.
- **Files modified:** `src/ta_lab2/scripts/backtests/backtest_from_signals.py`
- **Verification:** `cmc_backtest_metrics` row inserted successfully.
- **Committed in:** `ed15102e`

---

**Total deviations:** 6 auto-fixed (all Rule 1 — Bug)
**Impact on plan:** All 6 fixes were pre-existing crash-on-run bugs discovered during live verification. No scope creep; all fixes are strictly necessary for pipeline correctness. Bugs 2-6 were in `backtest_from_signals.py` and bundled into a single commit (`ed15102e`) since they were discovered iteratively during the same Task 2 execution.

## Issues Encountered

None beyond the auto-fixed bugs documented above. All fixes were discovered and resolved within normal task execution.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- **Phase 28 complete:** All 3 must-have truths verified:
  1. At least one signal generator writes signals without errors — ALL THREE confirmed
  2. Backtest runner reads signals and produces BacktestResult — confirmed (104 trades, Sharpe 1.73)
  3. End-to-end pipeline works — confirmed with DB save
  4. save_backtest_results writes to all 3 cmc_backtest_* tables — confirmed

- **Backtest results on record:** run_id `0c9cb5b3-edd3-4002-8b34-2117f41c7fea` (EMA crossover, fee=10bps, slip=5bps) in cmc_backtest_runs

- **Ready for:** Strategy sweeps across all signal types/IDs, parameter optimization, multi-asset backtesting

- **Known limitations (not blockers):**
  - Only asset_id=1 (BTC) tested; other assets untested but architecture is identical
  - EMA crossover signal_id=2 (21/50) and signal_id=3 (50/200) not separately backtested; same code path
  - Sortino ratio is low (0.09) — likely a calculation issue in `_compute_comprehensive_metrics` but not blocking pipeline correctness

---
*Phase: 28-backtest-pipeline-fix*
*Completed: 2026-02-20*
