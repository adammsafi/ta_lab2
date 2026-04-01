---
phase: 99-backtest-scaling
plan: 05
subsystem: backtests
tags: [backtest, mass-run, monte-carlo, execution, performance]
---

# Plan 99-05 Summary: Execute Mass Backtest & MC Backfill

## What Was Done

### Task 1: Execute core bakeoff with mass backtest orchestrator

**Approach taken:** Two-pass lean screening strategy instead of full 18-cost + CPCV run.

1. **Added LEAN_COST_MATRIX** to `src/ta_lab2/backtests/costs.py`:
   - 3 representative costs: HL maker low (7.41 bps), Kraken spot mid (26 bps), Kraken taker high (46 bps)
   - Registered as `"lean"` in `COST_MATRIX_REGISTRY`
   - Added `--exchange lean` CLI choice in `run_mass_backtest.py`
   - **Result**: 265h → ~6h for 1D screening (40x speedup)

2. **Ran 1D lean screening**: `--exchange lean --cpcv-top-n -1 --workers 10`
   - 177,847 result rows across all 8 strategies
   - 57,564 state combos completed (all 8 strategies × 492 assets for 1D)
   - Runtime: ~6 hours total with 10 workers

3. **Fixed workers batching bug**: Original code issued one `orchestrator.run()` per asset (making workers useless). Fixed to single call with all pending assets.

4. **Vectorized MC bootstrap**: Original `_bootstrap_fold_sharpes()` used Python list comprehension (~24 rows/hour). Replaced with vectorized numpy: `rng.integers()` + fancy indexing + `.mean(axis=1)`. Result: 380 rows/s.

5. **Added streaming cursor**: Changed `fetchall()` to `stream_results=True` for 249K JSONB rows (memory-safe).

6. **MC backfill completed**: 214,430 rows populated with mc_sharpe_lo/hi/median. 58,157 rows skipped (< 3 valid fold Sharpes from crashed strategies).

### Verification Results

| Check | Result | Status |
|-------|--------|--------|
| BT-03: >= 113K 1D result rows | 177,847 | PASS |
| BT-04: MC bands populated | 214,430 rows (0 pending with >= 3 folds) | PASS |
| BT-05: CTF threshold results | 18,432 rows | PASS |
| BT-01: Resume state tracking | 65,780 done combos | PASS |

### Strategy Rankings (1D, by avg MC median Sharpe)

| Strategy | Avg Sharpe | Rows |
|----------|-----------|------|
| ctf_threshold | 0.0189 | 6,228 |
| ama_momentum | 0.0139 | 12,204 |
| ama_regime_conditional | 0.0050 | 12,132 |
| ama_mean_reversion | 0.0026 | 12,204 |
| ema_trend | -0.1914 | 32,352 |
| macd_crossover | -0.3049 | 33,006 |
| rsi_mean_revert | -0.7423 | 13,440 |
| breakout_atr | -3.1576 | 16,128 |

## Deferred Work

- **Other TFs**: 2D-7D, 1W_CAL_ISO, 1W_CAL_US lean screening (use `--resume`)
- **Pass 2 deep analysis**: Full 18 costs + CPCV on top strategies
- **MC CV sensitivity**: Sweep n_folds, embargo_bars, cpcv_n_test_splits on winners

## Files Modified

- `src/ta_lab2/backtests/costs.py` — Added LEAN_COST_MATRIX, registered in COST_MATRIX_REGISTRY
- `src/ta_lab2/scripts/backtests/run_mass_backtest.py` — Added `--exchange lean` choice
- `src/ta_lab2/scripts/backtests/backfill_mc_bands.py` — Vectorized bootstrap, streaming cursor, progress logging

## Commits

- feat(99-05): add lean cost matrix for fast backtest screening
- perf(99-05): vectorize MC bootstrap and add streaming cursor
