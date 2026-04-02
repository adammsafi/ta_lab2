---
phase: 100-ml-signal-combination
plan: "01"
subsystem: ml
tags: [lightgbm, lgbm-ranker, cross-sectional, purged-cv, spearman-ic, ndcg, xgboost, shap, feature-selection, ctf]

requires:
  - phase: 92-ctf-ic-analysis-feature-selection
    provides: dim_ctf_feature_selection table with 615 active CTF features
  - phase: 98-ctf-graduation
    provides: CTF features promoted to features table columns

provides:
  - CrossSectionalRanker class in ml/ranker.py with load_features/cross_validate/train_full/log_results
  - CLI script scripts/ml/run_lgbm_ranker.py with --tf/--venue-id/--n-splits/--embargo-frac/--train-full/--dry-run
  - Initial CV results: Mean IC=0.0217, IC-IR=0.7435, NDCG=0.8122 (4 folds, 126 features, 7 assets)
  - Experiment logged to ml_experiments (experiment_id=e024414d-b56e-437e-b6e1-0d17f6356c91)

affects:
  - 100-02 (SHAP analysis needs self.model_ from CrossSectionalRanker.train_full)
  - 100-03 (meta-label filter references CrossSectionalRanker and run_lgbm_ranker patterns)

tech-stack:
  added:
    - xgboost>=3.2.0 (ml_ranking optional extra in pyproject.toml)
    - shap>=0.51.0 (ml_ranking optional extra in pyproject.toml)
  patterns:
    - Panel CV on unique timestamps: build t1_series on unique ts, expand period indices to row indices
    - LGBMRanker requires integer labels: use rank(method='first')-1 not pct rank
    - IC evaluation uses actual forward_return (not integer rank) for Spearman correlation
    - NDCG evaluation uses integer ranks as relevance grades

key-files:
  created:
    - src/ta_lab2/ml/ranker.py
    - src/ta_lab2/scripts/ml/run_lgbm_ranker.py
  modified:
    - pyproject.toml (added [ml_ranking] optional extra with xgboost + shap)
    - .gitignore (added models/ directory)

key-decisions:
  - "dim_ctf_feature_selection (not dim_feature_selection.source) is the correct table for CTF features -- dim_feature_selection has no source column"
  - "ret_arith from features table (not returns_bars_multi_tf which does not exist as a base table) used for forward returns"
  - "LGBMRanker labels must be integer: _build_rank_target returns rank(method='first')-1 not pct rank"
  - "Panel CV: t1_series built on unique timestamps using .tolist() to preserve UTC tz (MEMORY.md pitfall)"
  - "IC evaluation uses actual forward_return for Spearman; NDCG uses integer ranks as relevance grades"
  - "Fold 0 skipped by purger (aggressive purge on first fold is expected for PurgedKFold with 5-fold split)"

patterns-established:
  - "Panel CV pattern: unique_ts.tolist() -> DatetimeIndex -> t1_series; split on periods; expand to rows"
  - "LGBMRanker integer label pattern: groupby('ts')['forward_return'].rank(method='first', ascending=True) - 1"
  - "NaN imputation: astype(float) to convert None->nan, then nanmedian fill per column"

duration: 21min
completed: "2026-04-01"
---

# Phase 100 Plan 01: ML Signal Combination Summary

**LGBMRanker cross-sectional ranker trained on 126 CTF features with 5-fold purged CV: Mean IC=0.0217, IC-IR=0.74, NDCG=0.81**

## Performance

- **Duration:** 21 min
- **Started:** 2026-04-01T21:49:40Z
- **Completed:** 2026-04-01T22:10:55Z
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

- CrossSectionalRanker class with lazy LightGBM import, panel purged CV, and ExperimentTracker integration
- Panel-aware PurgedKFoldSplitter usage: operates on unique timestamps to avoid duplicate index issues
- CLI script with dry-run, train-full, and experiment logging modes
- Initial CV results: Mean IC=0.0217, IC-IR=0.7435, NDCG=0.8122 over 4 valid folds
- xgboost>=3.2.0 and shap>=0.51.0 added as [ml_ranking] optional extras

## Task Commits

Each task was committed atomically:

1. **Task 1: Install xgboost+shap deps and create CrossSectionalRanker** - `0f4574d4` (feat)
2. **Task 2: Create CLI script and run initial training** - `23878d08` (feat)

## Files Created/Modified

- `src/ta_lab2/ml/ranker.py` - CrossSectionalRanker class: load_features, cross_validate, train_full, log_results
- `src/ta_lab2/scripts/ml/run_lgbm_ranker.py` - CLI: dry-run + full CV + optional train_full + pickle
- `pyproject.toml` - Added [ml_ranking] optional extra: xgboost>=3.2.0, shap>=0.51.0
- `.gitignore` - Added models/ directory for pickle artifacts

## Decisions Made

- **dim_ctf_feature_selection vs dim_feature_selection:** The plan specified `dim_feature_selection WHERE source='ctf_ic_promoted'` but that column doesn't exist. Actual CTF features are in `dim_ctf_feature_selection` (615 active rows from Phase 92). Used the correct table.
- **ret_arith from features table:** Plan referenced `returns_bars_multi_tf` which doesn't exist as a base table (only `_u` and `_state` variants). Used `ret_arith` column already in features table, shifted -1 per asset for forward return.
- **Integer labels for LGBMRanker:** LGBMRanker requires integer relevance grades. Changed `_build_rank_target` from `rank(pct=True)` to `rank(method='first', ascending=True) - 1`.
- **Panel CV approach:** PurgedKFoldSplitter requires monotonically increasing t1_series index. Row-level panel ts has duplicates (7 assets per day). Solution: build t1_series on unique timestamps (T periods), split at period level, expand back to rows.
- **MEMORY.md tz fix:** Used `.tolist()` not `.values` on UTC-aware DatetimeSeries to preserve tz for t1_series index and values, avoiding tz-naive vs tz-aware comparison error in PurgedKFoldSplitter.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed dim_feature_selection query: source column does not exist**
- **Found during:** Task 2 (first dry-run attempt)
- **Issue:** Plan specified `WHERE source='ctf_ic_promoted'` but dim_feature_selection has no `source` column
- **Fix:** Query `dim_ctf_feature_selection WHERE tier='active'` (correct table for CTF features from Phase 92)
- **Files modified:** src/ta_lab2/ml/ranker.py
- **Verification:** Dry-run completed loading 23,176 rows with 126 CTF features
- **Committed in:** 23878d08 (Task 2 commit)

**2. [Rule 1 - Bug] Fixed returns table name: returns_bars_multi_tf does not exist**
- **Found during:** Task 2 (second dry-run attempt)
- **Issue:** Plan referenced `returns_bars_multi_tf` which is not a base table (only `_u` unified and `_state` tables exist)
- **Fix:** Use `ret_arith` column already in features table, shifted -1 per asset for forward return
- **Files modified:** src/ta_lab2/ml/ranker.py
- **Verification:** Forward return computed correctly, NaN last-bar rows dropped
- **Committed in:** 23878d08 (Task 2 commit)

**3. [Rule 1 - Bug] Fixed LGBMRanker label type: float percentile rank rejected**
- **Found during:** Task 2 (first full CV run)
- **Issue:** LightGBM fatal error: "label should be int type (met 0.500000) for ranking task"
- **Fix:** Changed `_build_rank_target` to return integer ordinal ranks (0-based) via `rank(method='first') - 1`
- **Files modified:** src/ta_lab2/ml/ranker.py
- **Verification:** LGBMRanker training completed without error across 4 valid folds
- **Committed in:** 23878d08 (Task 2 commit)

**4. [Rule 1 - Bug] Fixed tz-naive vs tz-aware TypeError in PurgedKFoldSplitter**
- **Found during:** Task 2 (second full CV run)
- **Issue:** `Series.values` on UTC-aware DatetimeSeries strips timezone; comparison of tz-naive index against tz-aware t1 values fails with TypeError
- **Fix:** Used `.tolist()` to get tz-aware Timestamp objects, built DatetimeIndex consistently UTC-aware for both index and values
- **Files modified:** src/ta_lab2/ml/ranker.py
- **Verification:** PurgedKFoldSplitter ran 5 folds (1 skipped by purge, 4 completed)
- **Committed in:** 23878d08 (Task 2 commit)

---

**Total deviations:** 4 auto-fixed (all Rule 1 bugs)
**Impact on plan:** All fixes were correctness-critical. No scope creep. Final implementation matches plan intent.

## Issues Encountered

- Fold 0 consistently skipped: first fold has no training data after aggressive purge (expected behavior for 5-fold purged CV on 5,000+ periods where fold 1 = early dates with no pre-history to train on)
- All-NaN column warning: some CTF feature columns have all-NaN for early bars; nanmedian warns but fills with NaN -> 0 imputation handles gracefully

## Next Phase Readiness

- `CrossSectionalRanker.self.model_` (LGBMRanker fitted on last CV fold) is available for Plan 100-02 SHAP analysis
- Use `--train-full` flag to get full-data model before SHAP
- ml_experiments row exists with experiment_id=e024414d-b56e-437e-b6e1-0d17f6356c91
- IC=0.0217 is modest positive signal; NDCG=0.81 is high (expected for ranker on 7-asset universe)

---
*Phase: 100-ml-signal-combination*
*Completed: 2026-04-01*
