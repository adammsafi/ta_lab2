---
phase: 103
plan: 01
subsystem: features/indicators
tags: [indicators, technical-analysis, ichimoku, hurst, vidya, frama, ta-expansion]
requires: [indicators.py helpers (_ema, _sma, _tr, _ensure_series, _return)]
provides: [20 new indicator functions in indicators_extended.py]
affects: [103-02 (registry integration), 103-03 (feature pipeline)]
tech-stack:
  added: []
  patterns: [rolling-apply for recursive indicators, variance-scaling hurst, explicit-loop adaptive MAs]
key-files:
  created:
    - src/ta_lab2/features/indicators_extended.py
  modified: []
decisions:
  - "VIDYA and FRAMA use explicit Python loops — cannot be vectorized due to state dependency on prior result"
  - "Hurst inner function extracted as module-level _hurst_inner for testability and clean rolling.apply usage"
  - "Aroon uses N+1 rolling window per StockCharts spec (window=25 -> roll=26)"
  - "Vortex does not use prev_close (only prev_high/prev_low needed for VM calculation)"
  - "KST uses standard parameters: ROC(10,13,14,15) / SMA(10,13,14,9) / weights(1,2,3,4)"
metrics:
  duration: 2m 42s
  completed: 2026-04-01
---

# Phase 103 Plan 01: Traditional TA Expansion — Indicators Implementation Summary

**One-liner:** 20 new TA indicator functions (Ichimoku through Coppock) in indicators_extended.py reusing existing helpers

## What Was Built

A single new module `src/ta_lab2/features/indicators_extended.py` exporting 20 technical indicator functions plus two shared helpers (`_tp`, `_wma`). All 20 functions follow the exact same API convention as `indicators.py`: `(obj, window/params, *, col_args, out_col/out_cols, inplace)`.

### Shared Helpers
- `_tp(high, low, close)` — typical price (H+L+C)/3, used by CCI, CMF, VWAP
- `_wma(s, n)` — weighted moving average with linear weights 1..n, used by Coppock

### Batch 1 (Ichimoku through Hurst)
| # | Function | Output | Key Detail |
|---|----------|--------|-----------|
| 1 | `ichimoku` | 5-col DataFrame | Span A/B NOT forward-shifted; chikou=close.shift(26) |
| 2 | `williams_r` | Series | -100*(HH-close)/(HH-LL) |
| 3 | `keltner` | 4-col DataFrame | mid=EMA(20), bands=+/-2*ATR(10), width=(upper-lower)/mid |
| 4 | `cci` | Series | Mean absolute deviation (NOT std), 0.015 scaling factor |
| 5 | `elder_ray` | 2-col DataFrame | bull=high-EMA, bear=low-EMA |
| 6 | `force_index` | 2-col DataFrame | fi_1=close.diff()*vol; fi_13=EMA(fi_1,13) |
| 7 | `vwap` | 2-col DataFrame | Rolling window (NOT cumulative); +deviation from VWAP |
| 8 | `cmf` | Series | MFM*vol / sum(vol), Chaikin Money Flow |
| 9 | `chaikin_osc` | Series | EMA(ADL,3) - EMA(ADL,10) |
| 10 | `hurst` | Series | Variance-scaling polyfit, min_periods=100, 101 non-null on n=200 |

### Batch 2 (VIDYA through Coppock)
| # | Function | Output | Key Detail |
|---|----------|--------|-----------|
| 11 | `vidya` | Series | Explicit loop; CMO-scaled EWM alpha |
| 12 | `frama` | Series | Explicit loop; fractal dimension D -> alpha clipped [0.01, 1.0] |
| 13 | `aroon` | 3-col DataFrame | N+1 rolling window; aroon_up, aroon_dn, aroon_osc |
| 14 | `trix` | 2-col DataFrame | Triple EMA, % rate of change + signal EMA |
| 15 | `ultimate_osc` | Series | 4*avg7 + 2*avg14 + avg28 / 7, true high/low vs prev_close |
| 16 | `vortex` | 2-col DataFrame | VI+/VI- from directional movements / sum(TR) |
| 17 | `emv` | 2-col DataFrame | emv_1 (raw) + emv_14 (SMA smoothed) |
| 18 | `mass_index` | Series | EMA(HL)/EMA(EMA(HL)) ratio sum over 25 bars |
| 19 | `kst` | 2-col DataFrame | 4-ROC weighted sum + 9-bar SMA signal |
| 20 | `coppock` | Series | ROC(14)+ROC(11) combined via WMA(10) |

## Verification Results

Both verification scripts passed on synthetic OHLCV data (n=200, seed=42):
- Batch 1: all 10 functions produce valid output; Hurst non-null count: 101
- Batch 2: all 10 functions produce valid output; `len(__all__) == 20`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Unused variable `prev_close` in vortex function**

- **Found during:** Task 2 (pre-commit ruff lint)
- **Issue:** `prev_close = close.shift(1)` was assigned but not used — vortex only needs `prev_high` and `prev_low` for VM+/VM- calculation
- **Fix:** Removed the unused `prev_close` assignment
- **Files modified:** `src/ta_lab2/features/indicators_extended.py`
- **Commit:** cfa38110

None other — plan executed with one minor lint fix.

## Next Phase Readiness

- Phase 103-02 (registry integration) can proceed immediately
- All 20 functions are importable from `ta_lab2.features.indicators_extended`
- No new library dependencies introduced
- API is fully consistent with `indicators.py` convention for drop-in integration
