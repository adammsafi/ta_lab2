---
phase: 60-ml-infrastructure-experimentation
plan: "05"
subsystem: ml
tags: [regime-routing, feature-importance, mda, sfi, purged-cv, sklearn, lightgbm, cli, argparse, sqlalchemy]

# Dependency graph
requires:
  - phase: 60-02-ml-infrastructure-experimentation
    provides: ExperimentTracker with log_run() for experiment persistence
  - phase: 60-04-ml-infrastructure-experimentation
    provides: compute_mda, compute_sfi, cluster_features from feature_importance.py

provides:
  - RegimeRouter class (src/ta_lab2/ml/regime_router.py) with fit(), predict(), predict_proba(), get_regime_stats()
  - load_regimes() SQL helper reading cmc_regimes L2 labels with UTC-aware timestamps
  - run_feature_importance.py CLI with MDA/SFI ranking on cmc_features, CSV output, ExperimentTracker logging
  - scripts/ml package init

affects:
  - 60-06-double-ensemble (uses RegimeRouter as routing layer)
  - 60-07-optuna-sweep (uses run_feature_importance results for feature selection)
  - signal generators (regime routing extends existing regime_enabled flag)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RegimeRouter: always clone base_model per regime + __global__ (sklearn.base.clone)"
    - "RegimeRouter: always pass DataFrame slices (X.iloc[mask]) to model.fit/predict"
    - "RegimeRouter: global fallback trained on ALL data; per-regime only if n >= min_samples"
    - "load_regimes: pd.to_datetime(utc=True) for ts column (MEMORY.md Windows pitfall)"
    - "run_feature_importance: NullPool engine for CLI scripts"
    - "run_feature_importance: lgbm ImportError caught gracefully, falls back to RandomForest"
    - "run_feature_importance: ret_arith excluded from feature columns (label source)"
    - "run_feature_importance: ffill().dropna() before building X to handle sparse features"

key-files:
  created:
    - src/ta_lab2/ml/regime_router.py
    - src/ta_lab2/scripts/ml/__init__.py
    - src/ta_lab2/scripts/ml/run_feature_importance.py
  modified: []

key-decisions:
  - "RegimeRouter always trains __global__ fallback on all data — never None, never missing"
  - "min_samples=30 default: regimes with < 30 training samples route to __global__ instead of a fragile sub-model"
  - "load_regimes returns pd.Series with 'Unknown' fill for NULL l2_label rows (no NaN propagation)"
  - "run_feature_importance excludes ret_arith from X (target leakage prevention)"
  - "t1_series built as ts + 1 day (1 bar) — conservative label-end for PurgedKFold"
  - "CLI uses NullPool (no connection pooling for single-process CLI scripts)"
  - "lgbm fallback: graceful ImportError → RF instead of hard crash on environments without LightGBM"

patterns-established:
  - "Regime router pattern: fit per-regime sub-models; __global__ always trained as safety net"
  - "CLI pattern: NullPool engine + argparse + logging.basicConfig in main()"
  - "Feature exclusion pattern: _EXCLUDE_COLS frozenset for PK, raw OHLCV, alignment metadata"

# Metrics
duration: 4min
completed: "2026-02-28"
---

# Phase 60 Plan 05: Regime Router and Feature Importance CLI Summary

**RegimeRouter dispatching per-regime sub-models from cmc_regimes L2 labels; run_feature_importance.py CLI running MDA/SFI on cmc_features columns with purged CV and ExperimentTracker logging**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-02-28T14:44:55Z
- **Completed:** 2026-02-28T14:48:08Z
- **Tasks:** 2/2
- **Files created:** 3

## Accomplishments

- `load_regimes()`: SQL query on `public.cmc_regimes` with UTC-aware timestamps, NaN-safe 'Unknown' fill
- `RegimeRouter.fit()`: trains per-regime sub-models via `sklearn.base.clone`; regimes with < `min_samples` fall back to `__global__`; always trains `__global__` on all data
- `RegimeRouter.predict()` / `predict_proba()`: groups rows by regime, dispatches to sub-model or `__global__` for unseen/low-sample regimes
- `RegimeRouter.get_regime_stats()`: returns fitted_regimes, fallback_regimes, sample_counts dict
- `scripts/ml/__init__.py`: package init
- `run_feature_importance.py` CLI: 10 argparse arguments; loads `cmc_features` via NullPool; excludes PK/OHLCV columns; builds binary labels from `ret_arith`; builds `t1_series` for PurgedKFold; runs `compute_mda` and/or `compute_sfi`; prints top 20 + bottom 10; optional CSV; optional ExperimentTracker logging

## Task Commits

Each task was committed atomically:

1. **Task 1: Create RegimeRouter module** — `d9337843` (feat)
2. **Task 2: Create feature importance CLI script** — `9ecb9f4b` (feat)

## Files Created/Modified

- `src/ta_lab2/ml/regime_router.py` — RegimeRouter class + load_regimes(); 372 lines
- `src/ta_lab2/scripts/ml/__init__.py` — ML scripts package init
- `src/ta_lab2/scripts/ml/run_feature_importance.py` — CLI: 449 lines, 10 args, MDA/SFI/both modes

## Decisions Made

- `__global__` fallback always trained on 100% of data — prevents any unseen-regime crash at predict time
- `min_samples=30` as default threshold — matches AFML recommendation for minimum reliable model estimate
- `ret_arith` removed from feature columns before running MDA/SFI (it is the label source — including it would be target leakage)
- `t1_series = ts + 1 day` — conservative 1-bar label window; callers can customize if needed
- `NullPool` for CLI scripts — no idle connections held between CLI invocations
- `lgbm` ImportError falls back silently to RF — the tool works in environments without LightGBM installed

## Deviations from Plan

None — plan executed exactly as written. All 3 artifacts created with specified exports, key links, and must-have truths satisfied.

## Issues Encountered

- Pre-commit hooks (ruff-format + mixed-line-ending) reformatted both files after initial write — re-staged and committed cleanly on second attempt. No logic changes from linter.

## User Setup Required

None — no external service configuration required.
- `run_feature_importance.py --log-experiment` requires a live PostgreSQL database with `cmc_features` and `cmc_ml_experiments` tables
- `cmc_ml_experiments` is created automatically on first use via `tracker.ensure_table()`

## Next Phase Readiness

- `RegimeRouter` is ready for use in 60-06 (DoubleEnsemble) and any signal generator that needs regime routing
- `run_feature_importance.py` can be invoked immediately against production `cmc_features` data
- `load_regimes()` ready for any script that needs to join regime labels to bar data

---
*Phase: 60-ml-infrastructure-experimentation*
*Completed: 2026-02-28*
