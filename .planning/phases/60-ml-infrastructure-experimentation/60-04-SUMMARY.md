---
phase: 60-ml-infrastructure-experimentation
plan: 04
subsystem: ml
tags: [feature-importance, mda, sfi, clustered-fi, purged-cv, spearman, ward-clustering, sklearn, scipy]

# Dependency graph
requires:
  - phase: 57-purged-cv
    provides: PurgedKFoldSplitter for leakage-free CV splits
  - phase: 59-microstructural-features
    provides: expanded cmc_features columns to rank by importance
  - phase: 55-feature-signal-evaluation
    provides: IC evaluation infrastructure (feature shortlist context)
provides:
  - MDA (Mean Decrease Accuracy) feature importance with purged CV
  - SFI (Single Feature Importance) with per-feature isolation
  - cluster_features: Spearman + Ward hierarchical clustering of features
  - compute_clustered_mda: cluster-simultaneous permutation importance
affects: [60-05, 60-06, ml-experiment-tracking, optuna-sweep, regime-routing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MDA: permutation_importance on OOS test folds only (never training data)"
    - "Empty fold guard: if len(train_idx)==0 or len(test_idx)==0: continue"
    - "DataFrame-only model inputs: always X.iloc[idx] not X.values[idx]"
    - "Cluster FI: permute entire cluster simultaneously to avoid substitution effect"
    - "Spearman distance matrix: 1 - abs(corr) symmetrized before squareform"

key-files:
  created:
    - src/ta_lab2/ml/feature_importance.py
  modified: []

key-decisions:
  - "Use sklearn.inspection.permutation_importance rather than hand-rolling permutation loop (uses parallelism, handles n_repeats)"
  - "Always pass DataFrame slices (X.iloc[idx]) to model — not numpy arrays — to avoid LightGBM feature name warnings"
  - "cluster_features handles 2-column spearmanr edge case (returns scalar statistic, not 2D matrix)"
  - "compute_clustered_mda uses random.default_rng(42) per repeat for reproducible cluster permutations"
  - "Empty fold guard placed in both compute_mda and compute_sfi — not in PurgedKFoldSplitter itself"

patterns-established:
  - "Feature importance pattern: compute_mda/compute_sfi both accept (model, X, y, t1_series, n_splits) signature"
  - "Clustered FI pattern: cluster first, then permute entire cluster simultaneously in MDA loop"
  - "Graceful degradation: all functions return zero-filled Series/DataFrame when no valid folds found"

# Metrics
duration: 3min
completed: 2026-02-28
---

# Phase 60 Plan 04: Feature Importance Module Summary

**MDA, SFI, and clustered feature importance module using sklearn permutation_importance + PurgedKFoldSplitter, with Spearman/Ward cluster grouping to address substitution effects**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-02-28T14:30:18Z
- **Completed:** 2026-02-28T14:32:59Z
- **Tasks:** 1/1
- **Files modified:** 1

## Accomplishments

- `compute_mda`: permutation-based OOS importance across purged CV folds using `sklearn.inspection.permutation_importance` on test folds only
- `compute_sfi`: per-feature isolated model training with purged CV; eliminates all substitution effects; returns OOS accuracy as importance
- `cluster_features`: Spearman correlation matrix → Ward linkage → `fcluster` at distance threshold; returns `{cluster_id: [feature_names]}` dict
- `compute_clustered_mda`: permutes entire feature cluster simultaneously per fold, addressing correlated-feature substitution effect; returns DataFrame with cluster_id, features, importance_mean
- All functions include mandatory empty fold guard; verified under heavy-purge (20-day label window on n=30 dataset)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create feature importance module** - `1bd37b54` (feat) — note: file was bundled into 60-01 commit from prior session; content confirmed correct at HEAD

**Plan metadata:** pending (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/ml/feature_importance.py` - MDA, SFI, cluster_features, compute_clustered_mda with AFML Ch.8 docstring; 4 exports confirmed importable

## Decisions Made

- Used `sklearn.inspection.permutation_importance` rather than hand-rolling permutation loop — handles n_repeats, parallelism, multiple scorers internally
- Always pass `X.iloc[train_idx]` / `X.iloc[test_idx]` (DataFrame slices) to model and to `permutation_importance` — avoids LightGBM/sklearn feature-name warnings when DataFrames are expected
- `cluster_features` handles the spearmanr edge case: when X has exactly 2 columns, `spearmanr().statistic` returns a scalar not a 2D matrix; guarded with `if corr.ndim == 0`
- `compute_clustered_mda` uses `numpy.random.default_rng(42)` per repeat for reproducible permutations
- Empty fold guard placed in all three CV-using functions (`compute_mda`, `compute_sfi`, `compute_clustered_mda`) — not inside `PurgedKFoldSplitter` itself, keeping CV logic clean

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] spearmanr scalar return for 2-column DataFrame**

- **Found during:** Task 1 (cluster_features implementation)
- **Issue:** `scipy.stats.spearmanr(X).statistic` returns a 0-d scalar (not 2D array) when X has exactly 2 columns; `squareform` and `np.fill_diagonal` then fail
- **Fix:** Added `if corr.ndim == 0: corr = np.array([[1.0, float(corr)], [float(corr), 1.0]])` after extracting the statistic
- **Files modified:** src/ta_lab2/ml/feature_importance.py
- **Verification:** cluster_features(X[['feat_a', 'feat_b']]) runs without error
- **Committed in:** 1bd37b54

---

**Total deviations:** 1 auto-fixed (1 bug — scipy API edge case)
**Impact on plan:** Edge-case fix essential for correctness with 2-feature DataFrames. No scope creep.

## Issues Encountered

- `feature_importance.py` was already present at HEAD (committed as part of 60-01 session artifact) — no duplicate commit needed; file content confirmed correct via `git show HEAD:src/ta_lab2/ml/feature_importance.py`

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `compute_mda`, `compute_sfi`, `cluster_features`, `compute_clustered_mda` all importable and passing smoke tests
- Ready for 60-05 (regime routing) and 60-06 (DoubleEnsemble) which will use these as evaluation tools
- CLI script `run_feature_importance.py` not yet implemented — will be needed to run against full cmc_features column set
- All functions accept arbitrary sklearn-compatible models — LightGBM and RandomForest both work

---
*Phase: 60-ml-infrastructure-experimentation*
*Completed: 2026-02-28*
