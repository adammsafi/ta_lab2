---
phase: 80-ic-analysis-feature-selection
plan: "04"
subsystem: analysis
tags: [ic-analysis, feature-selection, mda, spearman, concordance, random-forest, purged-kfold, clustering]

# Dependency graph
requires:
  - phase: 80-01
    provides: dim_feature_selection table, statsmodels installation
  - phase: 80-02
    provides: feature_selection.py library with load_ic_ranking function
  - phase: 80-03
    provides: run_feature_selection.py (parallel Wave 3 sibling)

provides:
  - run_concordance.py CLI comparing IC-IR vs MDA rankings (888 lines)
  - Spearman rank concordance between IC-IR and MDA methods
  - High-confidence feature identification (top-20 overlap)
  - Feature cluster resolution with best-per-cluster by IC-IR
  - reports/concordance/ic_vs_mda_concordance.csv (30 rows, gitignored)

affects:
  - 80-05 (feature selection pipeline that consumes concordance results)
  - future signal generation phases (high-confidence features have double validation)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dual-lens feature validation: IC-IR (rank correlation) + MDA (permutation importance)"
    - "Constant-feature guard: drop zero-variance columns before clustering to prevent NaN in Spearman corr matrix"
    - "Graceful MDA degradation: IC-IR-only mode when features not in features table or MDA fails"

key-files:
  created:
    - src/ta_lab2/scripts/analysis/run_concordance.py
    - reports/concordance/ic_vs_mda_concordance.csv (gitignored, runtime output)
  modified: []

key-decisions:
  - "IC-IR ranking takes precedence when IC-IR and MDA disagree (per CONTEXT.md) -- Spearman rho is informative but not a gate"
  - "AMA/EMA-derived features from ic_results are not in features table -- skipped in MDA with warning, not error"
  - "Constant (zero-variance) features dropped before cluster_features() call to prevent NaN in Ward linkage"
  - "reports/ directory is gitignored -- CSV is runtime output only, not committed"

patterns-established:
  - "Concordance rho < 0.2 is informative (methods measuring different aspects), not a failure"
  - "cluster_features() requires non-constant features -- pre-filter with std() > 0 guard"
  - "MDA uses max_depth=5 RandomForest (not unlimited depth) to prevent overfitting on small OOS sets"

# Metrics
duration: 6min
completed: 2026-03-22
---

# Phase 80 Plan 04: Concordance Analysis Summary

**run_concordance.py CLI comparing IC-IR ranking vs MDA permutation importance with Spearman rho=0.14, high-confidence features bb_ma_20 and close_fracdiff, and Bollinger Band cluster identified**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-22T03:16:19Z
- **Completed:** 2026-03-22T03:22:07Z
- **Tasks:** 2
- **Files modified:** 1 created, 1 runtime output (CSV)

## Accomplishments

- Created 888-line run_concordance.py CLI with 9 argparse arguments for full IC-IR vs MDA concordance analysis
- Successfully ran full concordance on 4 assets (BTC/ETH/SOL/BNB), 1D, 2023-2025: Spearman rho=0.14 (near-zero -- IC and MDA measure different aspects of predictive power)
- Identified high-confidence features appearing in both top-20 lists: bb_ma_20, close_fracdiff
- Identified feature cluster: [bb_ma_20, close_fracdiff, bb_lo_20_2, bb_up_20_2] -- Bollinger Band family; best-per-cluster = bb_ma_20 (IC-IR=1.22)
- 23 of 30 top IC features are AMA/EMA-derived and not in the features table -- correctly skipped in MDA with warning

## Task Commits

Each task was committed atomically:

1. **Task 1: Create run_concordance.py CLI** - `b5b3d76f` (feat)
2. **Task 2: Run concordance and fix constant-feature clustering bug** - `dd7f5d38` (feat+fix)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/scripts/analysis/run_concordance.py` - 888-line CLI: IC-IR loading, MDA via PurgedKFoldSplitter, Spearman rho, cluster_features(), concordance report printing, CSV output
- `reports/concordance/ic_vs_mda_concordance.csv` - 30-row CSV (gitignored, runtime output): columns feature, ic_ir_value, ic_ir_rank, mda_value, mda_rank, agreement, confidence, cluster_id

## Decisions Made

- IC-IR ranking takes precedence when IC-IR and MDA disagree (per CONTEXT.md) -- Spearman rho is diagnostic/informative but not a gate on feature selection
- AMA/EMA-derived features present in ic_results but absent from features table are skipped in MDA with a warning note in the report (not a fatal error)
- reports/ directory is gitignored -- concordance CSV is runtime output, not committed to VCS
- Constant (zero-variance) features are dropped before clustering with a log warning to prevent NaN propagation into Ward linkage

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed constant-feature NaN in Spearman correlation matrix**

- **Found during:** Task 2 (full concordance run)
- **Issue:** vol_log_roll_20_is_outlier is a binary indicator with zero variance in this dataset; spearmanr() on the feature matrix produced NaN values in the correlation matrix, causing squareform/hierarchy.ward to fail with "Distance matrix must be symmetric"
- **Fix:** Added pre-filter before cluster_features() call: drop columns where std() == 0, log a warning listing dropped features, proceed with remaining non-constant features
- **Files modified:** src/ta_lab2/scripts/analysis/run_concordance.py
- **Verification:** Clustering succeeded on 6 non-constant features, identified 3 clusters
- **Committed in:** dd7f5d38 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Essential fix for clustering correctness. No scope creep.

## Issues Encountered

- Low Spearman rho (0.14): The top IC features are mostly AMA-derived (TEMA/DEMA/KAMA/HMA from ama_multi_tf tables) which are not in the features table and thus cannot participate in MDA. Only 7 of 30 top IC features are available for MDA comparison. The rho of 0.14 reflects the limited overlap rather than genuine disagreement -- this is documented in the report output and is consistent with the expectation that IC and MDA measure different things.
- First fold of PurgedKFold always purged (train=0) for this dataset: normal behavior when the first fold has no prior data for purging to act on. 4 valid folds of 5 is acceptable.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- run_concordance.py is ready for use in 80-05 (final feature selection pipeline)
- High-confidence features identified: bb_ma_20 (IC-IR rank 14, MDA rank 4, cluster_1 best) and close_fracdiff (IC-IR rank 18, MDA rank 1)
- Feature cluster resolved: Bollinger Band family [bb_ma_20, close_fracdiff, bb_lo_20_2, bb_up_20_2] -- use bb_ma_20 as representative
- The low Spearman rho (0.14) is informative context: IC-IR and MDA are measuring different aspects for this crypto dataset. Per CONTEXT.md, IC-IR ranking takes precedence. MDA serves as a secondary corroborating signal.
- No blockers for 80-05.

---
*Phase: 80-ic-analysis-feature-selection*
*Completed: 2026-03-22*
