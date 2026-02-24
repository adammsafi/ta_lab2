---
phase: 40
plan: 02
subsystem: notebooks
tags: [jupyter, plotly, matplotlib, ic, information-coefficient, purged-kfold, regime, backtest, vectorbt, rsi]

dependency-graph:
  requires:
    - 37-ic-evaluation  # compute_ic, batch_compute_ic, plot_ic_decay, plot_rolling_ic, compute_rolling_ic, load_regimes_for_asset, compute_ic_by_regime
    - 36-psr-purged-k-fold  # PurgedKFoldSplitter, _fold_boundaries
    - 27-regime-integration  # cmc_regimes table, load_regimes_for_asset
    - 28-backtest-pipeline-fix  # run_vbt_on_split, CostModel, Split, ResultRow
    - 40-01  # helpers.py (get_engine, load_features, load_regimes, validate_asset_data)
  provides:
    - notebooks/02_evaluate_features.ipynb  # IC evaluation, purged K-fold demo, regime A/B backtest notebook
  affects:
    - 40-03  # 03_run_experiments.ipynb can reference IC patterns shown here

tech-stack:
  added: []
  patterns:
    - tz-aware train_start/train_end via pd.to_datetime(START_DATE, utc=True) before IC calls
    - tz-naive strip at vectorbt boundary via _strip_tz() helper
    - t1_series construction as Series(index=feat_index, values=[feat_index[min(i+h, n-1)] for i in range(n)])
    - PurgedKFoldSplitter.split(X_dummy) with np.zeros((n,1)) dummy array
    - matplotlib horizontal bar chart for split visualization via rle-style block grouping
    - Regime filter as entries_base & ~is_downtrend (boolean mask from ffill-aligned trend_state)
    - try/except Exception block wrapping all vectorbt calls
    - _fold_boundaries exported helper used directly in split visualization

file-tracking:
  created:
    - notebooks/02_evaluate_features.ipynb
  modified: []

decisions:
  - id: rsi-for-regime-ab
    description: Used rsi_14 (available in cmc_features) for regime A/B backtest rather than EMA crossover — RSI mean-reversion is a natural fit for testing regime filtering (downtrend blocks contrarian buys)
  - id: tz-strip-helper
    description: _strip_tz() helper strips tz.localize(None) at the vectorbt boundary — single function covers both features_df and entry/exit Series to avoid repeated in-line tz manipulation
  - id: t1-series-min-clip
    description: t1_series uses min(i + LABEL_HORIZON, n-1) to clip the last few bars — avoids IndexError at series tail; last bars all get t1 = last_ts which is correct (their labels cannot extend beyond data)
  - id: matplotlib-rle-blocks
    description: Split visualization uses run-length encoding (rle-style while loop) to group consecutive same-class bars into single barh calls — prevents O(n) barh calls which would be slow for 1800+ bar series
  - id: batch-ic-curated-cols
    description: Batch IC uses a curated candidate column list filtered to available columns with a fallback to first 5 numeric cols — avoids crashes when any candidate column is missing from the DB

metrics:
  duration: "~8 minutes"
  completed: "2026-02-24"
---

# Phase 40 Plan 02: Evaluate Features Notebook Summary

**One-liner:** 44-cell IC evaluation notebook with Spearman IC decay (7 horizons), vectorized rolling IC, purged K-fold split visualization (5 folds, purge+embargo coloring), and RSI regime A/B backtest comparison using run_vbt_on_split.

## What Was Built

### `notebooks/02_evaluate_features.ipynb`

44-cell tutorial notebook (26 markdown + 18 code). The analytical core of the notebook series, covering three distinct analytical techniques.

**Cell structure:**

| # | Type | Content |
|---|------|---------|
| 1 | MD | Title, intro, table of contents |
| 2 | MD | Prerequisites (tables, CLI, EMA note) |
| 3 | Code | Setup — sys.path, imports, ta_lab2 version |
| 4 | MD | Parameters section description |
| 5 | Code | ASSET_ID, TF, dates, HORIZONS, RETURN_TYPES, ROLLING_WINDOW, N_SPLITS, EMBARGO_FRAC |
| 6 | MD | DB connection section |
| 7 | Code | engine + validate_asset_data + load_features + close extraction + train_start/train_end tz-aware |
| 8 | MD | Part 1 header + IC intro (interpretation table, boundary masking explanation) |
| 9 | MD | Single feature IC section |
| 10 | Code | compute_ic(rsi_14, close, train_start, train_end, horizons, return_types) |
| 11 | MD | IC table column descriptions |
| 12 | MD | IC decay chart section + what to look for |
| 13 | Code | plot_ic_decay for arith + log returns |
| 14 | MD | IC decay reading guide |
| 15 | MD | Rolling IC section |
| 16 | Code | compute_rolling_ic + plot_rolling_ic (horizon=5, window=63) |
| 17 | MD | IC-IR interpretation guide |
| 18 | MD | Batch IC section |
| 19 | Code | batch_compute_ic on curated feature subset |
| 20 | Code | pivot_table + styled IC decay table with RdYlGn gradient |
| 21 | MD | Batch IC reading guide |
| 22 | MD | Part 2 header + purged K-fold intro (standard vs purged KFold diagram) |
| 23 | Code | PurgedKFoldSplitter build + t1_series construction + splits generation |
| 24 | MD | Split visualization description (color key) |
| 25 | Code | Matplotlib horizontal bar chart: train/test/purge/embargo per fold |
| 26 | MD | Split chart reading guide |
| 27 | MD | Fold statistics section |
| 28 | Code | fold_stats_df with n_train/n_test/n_purge_embargo/pct/test_dates |
| 29 | MD | Part 3 header + regime A/B intro |
| 30 | Code | load_regimes_for_asset + HAS_REGIMES flag + trend distribution |
| 31 | MD | RSI signal generation description |
| 32 | Code | entries_base (rsi < 30) + exits (rsi > 70) |
| 33 | MD | Regime filter description |
| 34 | Code | regime_trend aligned + ffill + is_downtrend mask + entries_regime |
| 35 | MD | Run backtests section + tz-naive requirement note |
| 36 | Code | try/except vbt block: _strip_tz, CostModel, Split, run_vbt_on_split x2 |
| 37 | MD | Comparison table metric descriptions |
| 38 | Code | styled comparison DataFrame (highlight_better function) + delta summary |
| 39 | MD | A/B reading guide + caveats |
| 40 | MD | Regime-conditional IC section |
| 41 | Code | compute_ic_by_regime (trend_state, horizons[:4]) |
| 42 | Code | regime pivot table + styled IC with RdYlGn gradient |
| 43 | MD | Regime IC interpretation |
| 44 | MD | Summary + next steps + CLI commands + Streamlit tip |

## Verification Results

| Check | Result |
|-------|--------|
| Valid JSON | PASS |
| Total cells >= 30 | PASS — 44 cells |
| `import helpers` present | PASS |
| `from ta_lab2.analysis.ic import` present | PASS |
| `from ta_lab2.backtests.cv import PurgedKFoldSplitter` present | PASS |
| `from ta_lab2.backtests.vbt_runner import run_vbt_on_split` present | PASS — Cell 36 |
| `CostModel` and `Split` imported | PASS — same import line |
| `compute_ic` with train_start/train_end tz-aware | PASS — pd.to_datetime(utc=True) in Cell 7 |
| `plot_ic_decay` used | PASS — Cell 13 |
| `compute_rolling_ic` + `plot_rolling_ic` | PASS — Cell 16 |
| `batch_compute_ic` used | PASS — Cell 19 |
| Purged K-fold shows 5 folds | PASS — N_SPLITS=5, Cell 25 |
| Purge/embargo zones visualized | PASS — matplotlib bar chart with 4-color legend |
| Regime A/B uses RSI signals | PASS — rsi_14 < 30 entry / rsi_14 > 70 exit |
| Vectorbt wrapped in try/except | PASS — Cell 36 |
| run_vbt_on_split (NOT run_backtest) | PASS |

## Deviations from Plan

None — plan executed exactly as written.

## Key Design Decisions

1. **RSI for regime A/B**: Used `rsi_14` from `cmc_features` as the signal feature — available without joining `cmc_ema_multi_tf_u`, making the notebook simpler and self-contained from a single feature table.

2. **tz-aware train_start/train_end**: `pd.to_datetime(START_DATE, utc=True)` called in Cell 7 rather than in each IC call — single canonical source for the train bounds, consistent across all IC sections.

3. **`_strip_tz()` helper**: Defined inline in Cell 36 to strip timezone from DataFrames and Series before vectorbt — cleaner than repeating `.tz_localize(None)` four times for features/entries/exits/entries_regime.

4. **`t1_series` with `min(i+h, n-1)` clip**: The last `LABEL_HORIZON` bars cannot have their labels extend beyond the data — clipping to `n-1` is correct and prevents IndexError.

5. **Matplotlib RLE-style blocks for split viz**: Instead of one `barh` call per bar, groups consecutive same-class bars into single `barh` calls via a run-length encoding loop — correct and performant for large series.

6. **Graceful `HAS_REGIMES` guard**: All regime-dependent cells check `HAS_REGIMES` flag and print actionable messages when no regime data exists — notebook runs end-to-end even without `cmc_regimes` populated.

## Next Phase Readiness

Phase 40 Plan 03 (`03_run_experiments.ipynb`) can proceed immediately:
- `helpers.py` provides all required data loading utilities
- IC analysis patterns are established (compute_ic, batch_compute_ic)
- Purged K-fold patterns are demonstrated (PurgedKFoldSplitter, t1_series construction)
- No blockers
