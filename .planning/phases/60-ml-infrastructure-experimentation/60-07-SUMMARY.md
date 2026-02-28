---
phase: 60-ml-infrastructure-experimentation
plan: "07"
subsystem: ml
tags: [lightgbm, regime-routing, concept-drift, optuna, tpe, purged-cv, cli, argparse, sqlalchemy, double-ensemble]

# Dependency graph
requires:
  - phase: 60-02
    provides: ExperimentTracker with log_run() for experiment persistence
  - phase: 60-05
    provides: RegimeRouter.fit/predict, load_regimes(), NullPool CLI pattern
  - phase: 60-06
    provides: DoubleEnsemble.fit/predict/get_model_info()

provides:
  - run_regime_routing.py CLI: purged CV comparison of RegimeRouter vs single global model
  - run_double_ensemble.py CLI: purged CV comparison of DoubleEnsemble vs static LGBMClassifier
  - run_optuna_sweep.py CLI: Optuna TPE sweep with grid-comparison efficiency analysis

affects:
  - "Any plan in phase 60 or later that runs ML experiments and needs CLI entry points"
  - "Signal generator integration (regime routing extends existing regime_enabled flag)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Adaptive window guard: min(window_size, max(len(X_tr)//2, 10)) prevents DoubleEnsemble crash on short folds"
    - "Cumulative-max efficiency metric: np.maximum.accumulate(trial_values) to find trials-to-99%-optimal"
    - "Batch regime load: single SQL query for all asset_ids avoids N+1 loop in run_regime_routing"
    - "Stash pattern for pre-commit hooks: unstage unrelated files to prevent mixed-line-ending failures"

key-files:
  created:
    - src/ta_lab2/scripts/ml/run_regime_routing.py
    - src/ta_lab2/scripts/ml/run_double_ensemble.py
    - src/ta_lab2/scripts/ml/run_optuna_sweep.py
  modified: []

key-decisions:
  - "run_regime_routing: batch-loads cmc_regimes for all asset_ids in one SQL query (not per-asset loop)"
  - "run_regime_routing: per-regime CV breakdown within each fold (not just overall accuracy)"
  - "run_double_ensemble: adaptive effective window_size per fold — avoids crash when fold is shorter than window_size"
  - "run_optuna_sweep: --grid-comparison uses cumulative-max (not trial-by-trial) to find trials-to-99%-optimal"
  - "run_optuna_sweep: optuna.logging.set_verbosity(WARNING) always, regardless of --verbose flag"
  - "Optuna storage=None default: in-memory study; --storage enables SQLite/PostgreSQL for resumable sweeps"

patterns-established:
  - "Empty fold guard pattern: len(train_idx) < 2 or len(test_idx) < 2 skip before any model call"
  - "Single-class fold guard: len(np.unique(y_tr)) < 2 skip prevents LightGBM/RF binary classification error"
  - "Batch regime join: (id, ts) tuple lookup via pandas MultiIndex for O(1) per-row regime assignment"
  - "Grid comparison pattern: compute full grid size as product of |values| per param, compare to cummax convergence"

# Metrics
duration: 6min
completed: 2026-02-28
---

# Phase 60 Plan 07: Regime Routing, DoubleEnsemble, and Optuna Sweep CLI Scripts Summary

**Three production-ready CLI scripts: regime-routed purged CV comparison, DoubleEnsemble vs static baseline comparison, and Optuna TPE hyperparameter sweep with grid-efficiency analysis — all logging to cmc_ml_experiments**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-02-28T14:50:44Z
- **Completed:** 2026-02-28T14:56:52Z
- **Tasks:** 2/2
- **Files created:** 3

## Accomplishments

- `run_regime_routing.py`: loads cmc_features + cmc_regimes, builds binary labels from ret_arith, evaluates RegimeRouter vs single global model via PurgedKFoldSplitter; prints per-regime accuracy breakdown; `--log-experiment` logs both runs to ExperimentTracker with `regime_routing=True/False` and `regime_performance` JSONB
- `run_double_ensemble.py`: evaluates DoubleEnsemble (sliding-window LGBM with sample reweighting) vs static LGBMClassifier baseline via same PurgedKFold; adaptive `eff_window = min(window_size, max(len(X_tr)//2, 10))` prevents crash on short training folds; `--log-experiment` logs delta_vs_static in notes column
- `run_optuna_sweep.py`: creates Optuna study with TPEsampler(seed=42), runs `n_trials` with purged CV objective; `--grid-comparison` computes full grid size (256 = 4x4x4x4 for the 4-param space), cumulative-max convergence to 99%-threshold, and efficiency ratio; `--storage` enables resumable SQLite/PostgreSQL studies; `--log-experiment` logs best params + `optuna_n_trials` + `optuna_best_params` to ExperimentTracker

## Task Commits

Note: run_regime_routing.py and run_double_ensemble.py were committed as part of the 60-08 docs commit from a prior session that ran in parallel. run_optuna_sweep.py was committed in this session.

1. **Task 1: Create regime routing and DoubleEnsemble CLI scripts** - committed in `6c5bcbcb` (docs 60-08, prior session)
2. **Task 2: Create Optuna sweep CLI script** - `198d2559` (feat)

## Files Created/Modified

- `src/ta_lab2/scripts/ml/run_regime_routing.py` - CLI: loads cmc_features + cmc_regimes; purged CV comparison RegimeRouter vs global; per-regime breakdown; ExperimentTracker logging
- `src/ta_lab2/scripts/ml/run_double_ensemble.py` - CLI: purged CV comparison DoubleEnsemble vs static LGBMClassifier; adaptive window size guard; ExperimentTracker logging
- `src/ta_lab2/scripts/ml/run_optuna_sweep.py` - CLI: Optuna TPE sweep; purged CV objective; grid-comparison efficiency analysis; ExperimentTracker logging

## Decisions Made

- **Batch regime load**: `run_regime_routing` loads cmc_regimes for all asset_ids in a single SQL query, then does a `(id, ts)` tuple lookup via pandas MultiIndex. No N+1 loop per row.
- **Adaptive window size**: In `run_double_ensemble`, each CV fold gets `eff_window = min(window_size, max(len(X_tr)//2, 10))` so DoubleEnsemble never crashes when the training fold is shorter than the configured window_size.
- **Optuna verbosity always WARNING**: `optuna.logging.set_verbosity(optuna.logging.WARNING)` is set unconditionally — even `--verbose` only affects the Python logger, not Optuna's internal output.
- **Grid comparison via cumulative-max**: `np.maximum.accumulate(trial_values)` gives the best-seen value after each trial, enabling an honest measurement of how many trials were actually needed to reach 99% of the final best — rather than cherry-picking a lucky early trial.
- **`--storage None` default**: In-memory study by default (no SQLite artifact left behind). Callers who want resumable studies must explicitly pass `--storage sqlite:///optuna.db`.

## Deviations from Plan

None — all three scripts were created exactly as specified.

## Issues Encountered

- Pre-commit hooks (ruff-format + mixed-line-ending) reformatted files on first commit attempts. Fixed by re-staging the reformatted files. Pre-commit also failed on unstaged .planning files (STATE.md) with mixed-line-ending hook — resolved by unstaging unrelated files before commit.
- Discovery that run_regime_routing.py and run_double_ensemble.py were already committed in a prior session's 60-08 docs commit. Only run_optuna_sweep.py needed a new commit in this session.

## User Setup Required

None — no external service configuration required.
- `--log-experiment` requires a live PostgreSQL database with `cmc_features` and `cmc_ml_experiments` tables
- `--storage sqlite:///optuna.db` optionally persists Optuna study for resumable sweeps (no setup required beyond the flag)

## Next Phase Readiness

- All three MLINFRA requirements satisfied: MLINFRA-03 (regime routing CLI), MLINFRA-04 (DoubleEnsemble CLI), MLINFRA-06 (Optuna optimization CLI)
- All three scripts can be invoked immediately against production `cmc_features` + `cmc_regimes` data
- Experiment logging to cmc_ml_experiments is wired and ready for all three scripts
- Phase 60 Wave 3 (plans 07) complete — only plan 09 (if any) or phase closeout remains

---
*Phase: 60-ml-infrastructure-experimentation*
*Completed: 2026-02-28*
