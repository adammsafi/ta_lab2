---
phase: 57-advanced-labeling-cv
plan: "05"
subsystem: labeling
tags: [meta-labeling, random-forest, purged-kfold, sklearn, afml, triple-barrier, trade-probability, position-sizing]

# Dependency graph
requires:
  - phase: 57-advanced-labeling-cv/57-01
    provides: cmc_triple_barrier_labels table, triple_barrier.py labeler library
  - phase: 57-advanced-labeling-cv/57-03
    provides: BTC has 5612 triple barrier labels with pt=1.0/sl=1.0/vb=10
  - phase: 36-psr-purged-k-fold
    provides: PurgedKFoldSplitter in src/ta_lab2/backtests/cv.py
provides:
  - MetaLabeler class (RF + StandardScaler + balanced_subsample) in src/ta_lab2/labeling/meta_labeler.py
  - run_meta_labeling.py CLI: full meta-labeling pipeline from signals + labels to trade probabilities
  - MetaLabeler exported from labeling/__init__.py
  - construct_meta_labels() static method: y={0,1} from primary_side * barrier_bin > 0
  - CV evaluation using PurgedKFoldSplitter (no data leakage, embargo_frac=0.01)
affects:
  - 57-06 (CPCV Sharpe distribution uses same CV infrastructure)
  - future signal scoring / position sizing (trade_probability -> position size)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Meta-labeling pattern: primary model gives direction, secondary RF predicts if direction is correct"
    - "Meta-label construction: y = (primary_side * barrier_bin > 0).astype(int)"
    - "NaN-robust scaling: StandardScaler inside MetaLabeler._prepare(), drops NaN rows with logging"
    - "CV with PurgedKFoldSplitter: actual_folds = min(n_folds, n_aligned // 10) to avoid tiny folds"
    - "Merge alignment: pd.merge(labels, signals.rename(signal_ts->t0), on='t0', how='inner') -- NOT index join (mismatched index names produce 0 rows)"

key-files:
  created:
    - src/ta_lab2/labeling/meta_labeler.py
    - src/ta_lab2/scripts/labeling/run_meta_labeling.py
  modified:
    - src/ta_lab2/labeling/__init__.py

key-decisions:
  - "Use pd.merge(on='t0') not .join() for label/signal alignment: join with mismatched index names (t0 vs signal_ts) produced 0 rows silently"
  - "balanced_subsample class_weight chosen over balanced: rebalances per bootstrap sample, better recall/precision tradeoff on imbalanced financial labels"
  - "23 meta-feature columns: bar returns + vol estimators + TA indicators (no boolean outlier flags -- RF handles imbalance via class_weight)"
  - "actual_folds = min(n_folds, n_aligned // 10) prevents PurgedKFoldSplitter from producing tiny folds with < 5 test samples"
  - "Embargo frac=0.01 (1% of sample): minimal embargo matching cv.py default, avoids over-purging on small samples"

patterns-established:
  - "MetaLabeler._prepare(X, y, fit) handles NaN drop + scaler fit/transform in one call"
  - "MetaLabeler.evaluate() returns dict with accuracy/precision/recall/f1/auc/n_samples/n_pos for fold logging"
  - "run_meta_labeling scores ALL signal entries (not just aligned subset) via load_features_for_timestamps(all_signal_ts)"

# Metrics
duration: 7min
completed: 2026-02-28
---

# Phase 57 Plan 05: Meta-Labeling Pipeline Summary

**RandomForest meta-labeler (RF + StandardScaler + balanced_subsample) with PurgedKFoldSplitter CV producing trade_probability scores in [0,1] for all signal entries, persisted to cmc_meta_label_results**

## Performance

- **Duration:** ~7 min
- **Started:** 2026-02-28T07:22:30Z
- **Completed:** 2026-02-28T07:28:55Z
- **Tasks:** 2/2 complete
- **Files modified:** 3

## Accomplishments

- Implemented MetaLabeler class (195 lines): RF + StandardScaler wrapper with fit/predict_proba/predict/evaluate/feature_importance methods and construct_meta_labels() static method
- Created run_meta_labeling.py CLI (570+ lines): full pipeline from triple barrier labels + primary signals -> meta-labels -> CV evaluation -> final model -> cmc_meta_label_results
- Dry-run verification on BTC (ema_crossover): 151 aligned samples, mean CV AUC=0.5133, per-fold metrics logged, top-5 features identified (adx_14, rsi_14, vol_log_roll_20, macd_hist_12_26_9, vol_gk_20_zscore)
- Fixed silent alignment bug: `pd.merge(on='t0')` instead of index join (mismatched index names t0 vs signal_ts produced 0 rows)

## Task Commits

Each task was committed atomically:

1. **Task 1: MetaLabeler library class** - `727daba0` (feat)
2. **Task 2: run_meta_labeling.py CLI script** - `b5d14be8` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/labeling/meta_labeler.py` - MetaLabeler class: fit/predict_proba/predict/evaluate/feature_importance + static construct_meta_labels()
- `src/ta_lab2/scripts/labeling/run_meta_labeling.py` - CLI pipeline: precondition checks, data loading, merge alignment, CV, final fit, scoring, DB persist
- `src/ta_lab2/labeling/__init__.py` - Added MetaLabeler import and __all__ export

## Decisions Made

1. **pd.merge vs .join() for alignment:** Using `labels_indexed.join(signals_indexed, how='inner')` produced 0 rows because pandas `join()` requires matching index names -- `labels_df` index was named `t0`, `signals_df` index was named `signal_ts`. Fixed by renaming `signal_ts -> t0` in the signals frame and using `pd.merge(on='t0', how='inner')`.

2. **balanced_subsample over balanced:** `class_weight='balanced_subsample'` rebalances at each bootstrap sample rather than globally. Better for financial data where profitable trades are a minority -- reduces overfitting to the majority class compared to static `'balanced'`.

3. **23 feature columns:** Selected numeric-only columns spanning returns (6), volatility (9), and TA indicators (8). Excluded boolean outlier flags because RF handles skewed distributions natively via class_weight; outlier flags are redundant and add noise.

4. **actual_folds cap:** `actual_folds = min(n_folds, n_aligned // 10)` ensures minimum 10 training samples per fold. Without this cap, PurgedKFoldSplitter with embargo can produce empty training sets on small aligned samples.

5. **Score ALL signals, not just aligned:** The final model scores all signal entries via `load_features_for_timestamps(all_signal_ts)`. This gives trade_probability for every open position, even those without a matched barrier label (e.g., recent signals where labels haven't been computed yet).

## CV Results (BTC, ema_crossover, dry-run)

| Fold | AUC   | Precision | Recall | F1    | N test |
|------|-------|-----------|--------|-------|--------|
| 2    | 0.451 | 0.464     | 0.929  | 0.619 | 30     |
| 3    | 0.525 | 0.467     | 0.538  | 0.500 | 30     |
| 4    | 0.604 | 0.650     | 0.765  | 0.703 | 30     |
| 5    | 0.474 | 0.684     | 0.619  | 0.650 | 30     |

**Mean AUC: 0.51** -- marginally above random (expected: meta-labeling requires sufficient label quality and feature alignment to show strong signal; 151 samples is on the small side).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed silent zero-row merge using pd.merge instead of DataFrame.join**

- **Found during:** Task 2 verification (dry-run showed 0 aligned, then fixed to 151)
- **Issue:** `labels_indexed.join(signals_indexed, how='inner')` produced 0 rows because the two DataFrames had different index names (`t0` vs `signal_ts`). pandas `join()` requires both DataFrames to have the same index name for index-on-index joining, otherwise it performs a column join that finds no matches.
- **Fix:** Renamed `signal_ts -> t0` in the signals DataFrame before merge, then used `pd.merge(labels_df, signals_df, on='t0', how='inner')`. Produces correct 151 aligned rows.
- **Files modified:** `src/ta_lab2/scripts/labeling/run_meta_labeling.py`
- **Verification:** Dry-run on BTC logs "151 aligned (signal, label) pairs"
- **Committed in:** b5d14be8 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - Bug)
**Impact on plan:** Critical fix -- without it, zero rows would be aligned and no model would train. No scope creep.

## Issues Encountered

- Pre-commit hooks (ruff-format + mixed-line-ending) reformatted both files on first commit attempt. Re-staged and recommitted without logic changes. Standard Windows workflow.
- f-string conditional formatting `{oob:.4f if ... else 'N/A'}` raised ValueError in Python 3.12 -- fixed to `oob_str = f'{oob:.4f}' if oob else 'N/A'` before the f-string.

## User Setup Required

None - no external service configuration required. DB tables cmc_triple_barrier_labels and cmc_meta_label_results already exist from Phase 57-01 Alembic migration.

## Next Phase Readiness

- MetaLabeler is ready: `from ta_lab2.labeling import MetaLabeler` works
- run_meta_labeling.py is ready: full pipeline including DB write (remove --dry-run to persist)
- To score BTC ema_crossover and write to DB:
  `python -m ta_lab2.scripts.labeling.run_meta_labeling --ids 1 --signal-type ema_crossover`
- Phase 57-06 (CPCV Sharpe distribution) can use same PurgedKFoldSplitter infrastructure
- No blockers

---
*Phase: 57-advanced-labeling-cv*
*Completed: 2026-02-28*
