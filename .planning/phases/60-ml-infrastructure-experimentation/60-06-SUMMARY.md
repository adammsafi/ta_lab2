---
phase: 60-ml-infrastructure-experimentation
plan: "06"
subsystem: ml
tags: [lightgbm, concept-drift, ensemble, sliding-window, sample-reweighting, recency-weighting]

# Dependency graph
requires:
  - phase: 60-02
    provides: ExperimentTracker and cmc_ml_experiments DDL that this model can log to

provides:
  - DoubleEnsemble class in src/ta_lab2/ml/double_ensemble.py
  - Sliding-window LightGBM sub-models with configurable window_size and stride
  - Two-round per-window training: baseline + sample-reweighted model
  - Recency-weighted prediction aggregation across sub-models
  - Edge-case handling: single-class windows skipped, short-data global fallback
  - Lazy lightgbm import pattern (module importable before library installed)

affects:
  - "60-07 or later plans that run DoubleEnsemble with ExperimentTracker"
  - "60-04 feature_importance.py integration for MDA/SFI on ensemble predictions"
  - "Any plan in phase 60 that needs a concept-drift-aware baseline model"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy import pattern: import lightgbm inside fit()/predict_proba() so module is importable before library installed"
    - "Two-round sliding-window training: Round 1 baseline -> compute sample weights -> Round 2 reweighted"
    - "Recency weighting: end/n scalar per window, normalised at predict time"
    - "Always-DataFrame pattern: pass pd.DataFrame (not np.ndarray) to LightGBM to retain feature names"

key-files:
  created:
    - src/ta_lab2/ml/double_ensemble.py
  modified: []

key-decisions:
  - "Lazy import for lightgbm: required to match plan spec and keep module importable in environments without lightgbm"
  - "window_size=60, stride=15 as defaults: 60-bar windows give LightGBM sufficient data per window; stride=15 yields ~9-10 sub-models on 200-row datasets"
  - "Recency weight = end/n (not normalised during fit): normalisation deferred to predict_proba() so get_model_info() shows raw relative weights"
  - "Single-class window skip: LightGBM cannot train binary classifier on one-class window; logged at DEBUG level"
  - "Global fallback: when n < window_size, train one model on full dataset rather than raising an error"
  - "Sample weight normalisation: weights / weights.sum() * len(X) preserves effective sample size signal"

patterns-established:
  - "Lazy import pattern for optional heavy dependencies (lightgbm, optuna)"
  - "Always-DataFrame LightGBM contract: enforced via isinstance check with informative TypeError"

# Metrics
duration: 2min
completed: 2026-02-28
---

# Phase 60 Plan 06: DoubleEnsemble Concept Drift Model Summary

**Sliding-window LightGBM ensemble with two-round sample reweighting and recency-weighted prediction, handling concept drift via 60-bar overlapping windows at stride-15 steps**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-02-28T14:39:43Z
- **Completed:** 2026-02-28T14:41:34Z
- **Tasks:** 1/1
- **Files modified:** 1

## Accomplishments

- Created `DoubleEnsemble` class with `fit()`, `predict_proba()`, `predict()`, and `get_model_info()` methods
- Two-round per-window training: Round 1 baseline LGBMClassifier, then sample reweighting to upweight uncertain samples, Round 2 reweighted LGBMClassifier; only Round 2 model is retained
- Recency weighting: each sub-model assigned `recency_weight = end / n`; weights normalised at predict time so later windows have higher influence
- Smoke test passes: 10 sub-models trained on 200-row synthetic dataset, `proba.shape == (200, 2)`, `len(preds) == 200`
- Edge cases handled: single-class windows logged and skipped; datasets shorter than `window_size` fall back to single global model

## Task Commits

1. **Task 1: Create DoubleEnsemble module** - `780a64fd` (feat)

**Plan metadata:** (included in task commit — single-task plan)

## Files Created/Modified

- `src/ta_lab2/ml/double_ensemble.py` - DoubleEnsemble class: sliding-window LightGBM ensemble with sample reweighting and recency-weighted prediction aggregation

## Decisions Made

- **Lazy import for lightgbm**: `import lightgbm as lgb` placed inside `fit()` and `predict_proba()` methods so module is importable even if lightgbm is not installed. ImportError with install instructions raised only at call time.
- **Recency weight = `end / n`**: Later windows (closer to the end of the training period) receive proportionally higher weight. Raw weights stored in `self.models`; normalisation to sum=1 happens in `predict_proba()` to keep `get_model_info()` readable.
- **Single-class window skip**: LightGBM raises an error when all training labels are the same class. Windows with `len(np.unique(y_win)) < 2` are logged at DEBUG level and skipped.
- **Always-DataFrame contract**: `isinstance(X, pd.DataFrame)` check with TypeError enforced in `fit()` and `predict_proba()` to prevent LightGBM feature-name warnings.
- **Default params**: `{'n_estimators': 100, 'num_leaves': 20, 'learning_rate': 0.05, 'verbose': -1}` — conservative settings matching the research document recommendation for short financial time-series windows.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit ruff-format hook reformatted the file on first commit attempt (mixed CRLF/LF line endings on Windows). Fixed by re-staging the reformatted file and committing a second time.

## User Setup Required

None - no external service configuration required. LightGBM 4.6.0 was already installed.

## Next Phase Readiness

- `DoubleEnsemble` is ready for use in any Phase 60 plan that requires a concept drift model
- MLINFRA-04 requirement ("at least one concept drift model trained and evaluated") is satisfied by this module
- To integrate with ExperimentTracker (60-02): call `DoubleEnsemble().fit(X, y)` then `tracker.log_run(model_type='double_ensemble', ...)`
- No blockers for subsequent Wave 2 plans

---
*Phase: 60-ml-infrastructure-experimentation*
*Completed: 2026-02-28*
