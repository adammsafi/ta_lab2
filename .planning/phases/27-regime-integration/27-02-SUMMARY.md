---
phase: 27
plan: 02
subsystem: regime-integration
tags: [regime, ema-pivot, data-loader, sqlalchemy, pandas]

dependency_graph:
  requires:
    - cmc_price_bars_multi_tf (daily bar table)
    - cmc_price_bars_multi_tf_cal_iso (calendar bar table)
    - cmc_price_bars_multi_tf_cal_us (calendar bar table US variant)
    - cmc_ema_multi_tf_u (daily EMA table)
    - cmc_ema_multi_tf_cal_iso (calendar EMA table)
    - cmc_ema_multi_tf_cal_us (calendar EMA table US variant)
  provides:
    - regime_data_loader.py with pivot, bar loading, and EMA loading utilities
    - src/ta_lab2/scripts/regimes/ package init
  affects:
    - 27-03: refresh_cmc_regimes.py will call load_regime_input_data()
    - 27-04 onwards: all regime scripts depend on this data loading layer

tech_stack:
  added: []
  patterns:
    - long-to-wide EMA pivot with int-based numeric sort order
    - time_close AS ts aliasing for calendar bar tables
    - alignment_source filter for daily EMA deduplication
    - graceful empty-result handling with typed empty DataFrames

key_files:
  created:
    - src/ta_lab2/scripts/regimes/__init__.py
    - src/ta_lab2/scripts/regimes/regime_data_loader.py
  modified: []

decisions:
  - id: D01
    description: "Cast period to int before sorting column names to avoid alphabetic trap ('200' < '50')"
    rationale: "DB returns INTEGER but defensive int() cast ensures close_ema_20 < close_ema_50 < close_ema_200 column ordering always"
  - id: D02
    description: "Use pivot_table with aggfunc='first' instead of pivot to handle unexpected duplicates"
    rationale: "If alignment_source filter leaks duplicates, pivot_table silently deduplicates vs plain pivot raising ValueError"
  - id: D03
    description: "Merge bars and EMAs with how='left' and skip merge if either side is empty"
    rationale: "Preserve all bar rows even when EMAs are missing for some timestamps; skip merge entirely when one side is empty to avoid column issues"

metrics:
  duration: "3 min"
  completed: "2026-02-20"
  tasks_completed: 1
  tasks_total: 1
---

# Phase 27 Plan 02: Regime Data Loader Summary

**One-liner:** EMA pivot (long->wide, numeric sort) + bar/EMA DB loaders with time_close aliasing and alignment_source deduplication filter.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Create regime_data_loader.py with EMA pivot and bar loading | 64cd667d | src/ta_lab2/scripts/regimes/__init__.py, src/ta_lab2/scripts/regimes/regime_data_loader.py |

## What Was Built

### `src/ta_lab2/scripts/regimes/__init__.py`
Package init that exports the four public functions from `regime_data_loader.py`.

### `src/ta_lab2/scripts/regimes/regime_data_loader.py`
Five functions bridging the PostgreSQL feature pipeline to the regime labeler interface:

**`pivot_emas_to_wide(ema_df, periods, price_col="close")`**
- Filters long-format EMA DataFrame to the specified periods
- Pivots from (id, ts, period, ema) to (id, ts, close_ema_20, close_ema_50, ...)
- CRITICAL: Casts period values to `int` before sorting — ensures `close_ema_20 < close_ema_50 < close_ema_200`, not `'200' < '50'` (alphabetic trap)
- Uses `aggfunc='first'` in `pivot_table` to handle unexpected duplicates gracefully
- Returns empty DataFrame with correct typed columns on empty input (not crashes)

**`load_bars_for_tf(engine, asset_id, tf, cal_scheme="iso")`**
- Routes to `cmc_price_bars_multi_tf` for `tf='1D'`
- Routes to `cmc_price_bars_multi_tf_cal_{scheme}` for `tf='1W'` or `tf='1M'`
- CRITICAL: Calendar bar tables use `time_close` (not `ts`) — always aliased: `SELECT time_close AS ts ...`
- Ensures ts is tz-aware UTC via `pd.to_datetime(utc=True)`

**`load_emas_for_tf(engine, asset_id, tf, periods, cal_scheme="iso")`**
- Routes to `cmc_ema_multi_tf_u` for `tf='1D'` with `alignment_source = 'multi_tf'` filter
- CRITICAL: Without `alignment_source` filter, the daily EMA table returns duplicates per (id, ts, period) because `alignment_source` is NOT in the PK
- Routes to `cmc_ema_multi_tf_cal_{scheme}` for `tf='1W'` or `tf='1M'` (unique by PK, no filter needed)

**`load_and_pivot_emas(engine, asset_id, tf, periods, price_col="close", cal_scheme="iso")`**
- Convenience wrapper: calls `load_emas_for_tf` then `pivot_emas_to_wide`

**`load_regime_input_data(engine, asset_id, cal_scheme="iso")`**
- Master function loading all 3 TF datasets for a single asset
- EMA periods: Monthly=[12,24,48], Weekly=[20,50,200], Daily=[20,50,100]
- Merges bars + EMAs on (id, ts) with `how='left'` for each TF
- Returns dict: `{"monthly": df, "weekly": df, "daily": df}`
- Each DataFrame has: id, ts, open, high, low, close, volume, close_ema_N, ...
- Ready to pass directly to `label_layer_monthly()`, `label_layer_weekly()`, `label_layer_daily()`

## Verification Results

All verification checks passed:

1. `pivot_emas_to_wide` produces `['close_ema_20', 'close_ema_50', 'close_ema_200']` in correct numeric order
2. Empty input DataFrame returns empty DataFrame with correct column names (not crashes)
3. String period values ('20', '50', '200') are correctly cast to int and sorted numerically
4. No-match period filter returns empty DataFrame with expected columns
5. `ValueError` raised for invalid `tf` before any DB query
6. `ValueError` raised for invalid `cal_scheme` before any DB query
7. Empty `periods=[]` returns empty DataFrame without hitting DB
8. Module imports cleanly: `from ta_lab2.scripts.regimes.regime_data_loader import load_bars_for_tf, load_and_pivot_emas, load_regime_input_data`

## Deviations from Plan

None - plan executed exactly as written.

The only notable implementation choice was using `aggfunc='first'` in `pivot_table` (instead of plain `pivot`) to handle unexpected duplicates gracefully if the `alignment_source` filter ever leaks duplicates. This was a defensive improvement within the scope of the task, not a deviation.

## Next Phase Readiness

Plan 27-03 (`refresh_cmc_regimes.py`) can now call:
```python
data = load_regime_input_data(engine, asset_id=asset_id, cal_scheme="iso")
monthly, weekly, daily = data["monthly"], data["weekly"], data["daily"]
```

The DataFrames returned have the exact column names (`close_ema_12`, `close_ema_20`, etc.) expected by `label_layer_monthly()`, `label_layer_weekly()`, and `label_layer_daily()` in `labels.py`.
