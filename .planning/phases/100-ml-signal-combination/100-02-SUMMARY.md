---
phase: 100-ml-signal-combination
plan: 02
subsystem: ml
tags: [shap, lightgbm, lgbmranker, feature-importance, interaction-analysis, feature-selection]

# Dependency graph
requires:
  - phase: 100-01
    provides: CrossSectionalRanker with train_full() and LGBMRanker model_

provides:
  - RankerShapAnalyzer class in ml/shap_analysis.py (SHAP values + interaction analysis)
  - run_shap_analysis.py CLI for running analysis and producing reports
  - Top 5 SHAP interaction pairs identified for 1D LGBMRanker
  - shap_interaction_report.md in reports/ml/
  - 'interactions' key in configs/feature_selection.yaml with top 3 pairs

affects:
  - 100-03 (meta-filter uses feature importance context)
  - future feature engineering phases (interaction pairs suggest product/ratio features)

# Tech tracking
tech-stack:
  added: [shap==0.51.0 (already installed)]
  patterns:
    - lazy-import shap inside methods (same as lightgbm in ranker.py)
    - max_samples=500 cap for O(n*f*f) interaction tensor memory safety
    - upper-triangle extraction for symmetric interaction matrix deduplication
    - YAML interactions key written with newline='\n' to avoid CRLF mixed endings

key-files:
  created:
    - src/ta_lab2/ml/shap_analysis.py
    - src/ta_lab2/scripts/ml/run_shap_analysis.py
  modified:
    - src/ta_lab2/ml/ranker.py (Rule 1 bugfix: astype(float) in train_full)
    - configs/feature_selection.yaml (added 'interactions' key with top 3 pairs)

key-decisions:
  - "ranker.py train_full() lacked astype(float) on X; Python None in object-dtype columns crashed np.nanmedian — fixed inline (Rule 1)"
  - "LIKE clause in SQLAlchemy text() requires %% for literal %; single % treated as psycopg2 format placeholder"
  - "dim_feature_selection uses 'rationale' column (not 'notes'); discovered via information_schema.columns query"
  - "shap_interaction_values returns (n,f,f) tensor for LGBMRanker; guard for ndim==4 handles multi-output models defensively"
  - "top_interaction_pairs uses upper triangle only to avoid double-counting symmetric pairs"

patterns-established:
  - "RankerShapAnalyzer: lazy-import shap, max_samples subsample, store shap_values_/interaction_values_/mean_abs_interactions_"
  - "YAML writes with newline='\\n' explicit to prevent CRLF mixed endings on Windows"
  - "dim_feature_selection rationale column updated for SHAP interaction partners via CASE WHEN LIKE '%%SHAP interaction%%'"

# Metrics
duration: 11min
completed: 2026-04-01
---

# Phase 100 Plan 02: SHAP Interaction Analysis Summary

**SHAP TreeExplainer on LGBMRanker identifies bb_ma_20 x close_fracdiff as the dominant interaction pair (strength=0.119) out of 126 features; findings written to feature_selection.yaml 'interactions' key**

## Performance

- **Duration:** 11 min
- **Started:** 2026-04-01T22:14:56Z
- **Completed:** 2026-04-01T22:25:03Z
- **Tasks:** 2 completed
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- RankerShapAnalyzer class with compute_shap_values, compute_interaction_values, top_interaction_pairs, top_shap_features, generate_report, update_feature_selection methods
- Full SHAP analysis run on 1D LGBMRanker (7 assets, 126 features, 23,176 rows): top pair bb_ma_20 x close_fracdiff at strength 0.1192
- Markdown report produced at reports/ml/shap_interaction_report.md with feature importance table and interaction pairs table
- configs/feature_selection.yaml updated with 'interactions' key containing top 3 pairs; dim_feature_selection rationale column updated for interacting features
- Experiment logged to ml_experiments (id=c462dfe3-9fbb-4405-9ccb-9ebed7444f12)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create RankerShapAnalyzer** - `79de13d1` (feat)
2. **Task 2: Create CLI script and run SHAP analysis** - `595c64a7` (feat, includes Rule 1 bugfixes)

## Files Created/Modified

- `src/ta_lab2/ml/shap_analysis.py` - RankerShapAnalyzer class with SHAP values, interaction tensor, report generation, YAML update
- `src/ta_lab2/scripts/ml/run_shap_analysis.py` - CLI: train/load model, run SHAP, print pairs, write report, update YAML, log experiment
- `src/ta_lab2/ml/ranker.py` - Rule 1 bugfix: astype(float) cast on feature matrix in train_full()
- `configs/feature_selection.yaml` - Added 'interactions' key with top 3 feature pairs

## Decisions Made

- **ranker.py astype(float) fix**: train_full() called `df[feature_cols].values` without `.astype(float)`, so object-dtype columns with Python `None` (not `np.nan`) caused `np.nanmedian` TypeError. Fixed with `.astype(float)` to ensure float64 with NaN.
- **LIKE %% escaping**: SQLAlchemy `text()` with psycopg2 requires `%%` for literal `%` in LIKE clauses; single `%` is interpreted as a format placeholder causing ProgrammingError.
- **rationale not notes**: `dim_feature_selection` has a `rationale` column, not `notes`. Discovered via `information_schema.columns` query during execution.
- **YAML newline='\n'**: Python open() on Windows defaults to CRLF; explicit `newline='\n'` prevents mixed line ending failures in pre-commit.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ranker.py train_full() object-dtype crash**
- **Found during:** Task 2 (running the CLI script)
- **Issue:** `df[feature_cols].values` without `.astype(float)` preserves object dtype when any column has Python `None`; `np.nanmedian` raises `TypeError: '<' not supported between instances of 'NoneType' and 'NoneType'`
- **Fix:** Added `.astype(float)` before `.values` in train_full() with explanatory comment
- **Files modified:** `src/ta_lab2/ml/ranker.py`
- **Verification:** train_full() completed successfully; model trained on 23,176 rows in 10.3s
- **Committed in:** `595c64a7` (Task 2 commit)

**2. [Rule 1 - Bug] LIKE clause % escaping in SQLAlchemy text()**
- **Found during:** Task 2 (running --update-yaml)
- **Issue:** `LIKE '%SHAP interaction%'` in `text()` caused psycopg2 ProgrammingError; `%` interpreted as format placeholder
- **Fix:** Changed to `%%SHAP interaction%%` (double percent escaping for psycopg2 via SQLAlchemy text())
- **Files modified:** `src/ta_lab2/ml/shap_analysis.py`
- **Committed in:** `595c64a7` (Task 2 commit)

**3. [Rule 1 - Bug] Wrong column name in dim_feature_selection update**
- **Found during:** Task 2 (running --update-yaml with engine)
- **Issue:** Code referenced `notes` column which does not exist; actual column is `rationale`
- **Fix:** Changed `SET notes =` to `SET rationale =` in update SQL
- **Files modified:** `src/ta_lab2/ml/shap_analysis.py`
- **Committed in:** `595c64a7` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (3 Rule 1 bugs)
**Impact on plan:** All fixes necessary for correct operation. No scope creep.

## Issues Encountered

- YAML written by Python on Windows had mixed CRLF/LF line endings triggering pre-commit failure. Fixed by opening with explicit `newline='\n'` in the fix pass before re-committing.
- reports/ directory is gitignored — report is local artifact only (confirmed by plan: "reports/ is gitignored").

## SHAP Analysis Results

**1D LGBMRanker (7 assets, 126 features, 23,176 rows, 500 subsampled for SHAP)**

**Top 5 Interaction Pairs:**
| Rank | Feature A | Feature B | Strength |
|------|-----------|-----------|---------|
| 1 | bb_ma_20 | close_fracdiff | 0.119191 |
| 2 | close_fracdiff | ret_is_outlier | 0.001731 |
| 3 | bb_ma_20 | ret_is_outlier | 0.001687 |

Note: Only 3 pairs have non-zero interaction (many features have all-NaN values in current feature store — Phase 103/104 TA/derivative features are computed but may not be fully populated for the 7 currently active assets).

**Top SHAP Features:**
| Rank | Feature | Mean|SHAP| |
|------|---------|------------|
| 1 | bb_ma_20 | 0.141081 |
| 2 | close_fracdiff | 0.118716 |
| 3 | ret_is_outlier | 0.003258 |

The model is dominated by 2 features (bb_ma_20 and close_fracdiff), which aligns with Phase 100-01 findings that a small number of features drive IC.

## Next Phase Readiness

- SHAP interaction analysis infrastructure complete; RankerShapAnalyzer ready for reuse when feature store is more populated
- configs/feature_selection.yaml has `interactions` key with top 3 pairs — satisfies ML-02 feedback requirement
- Interaction insight: bb_ma_20 x close_fracdiff is the strongest pair; future feature engineering could create an explicit product feature
- Phase 100-03 (MetaFilter) already complete; no blocking dependencies

---
*Phase: 100-ml-signal-combination*
*Completed: 2026-04-01*
