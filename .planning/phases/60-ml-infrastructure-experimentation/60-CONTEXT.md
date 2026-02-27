# Phase 60: ML Infrastructure & Experimentation - Context

**Gathered:** 2026-02-26
**Status:** Not started
**Depends on:** Phase 57 (Purged CV), Phase 59 (Expanded feature set), Phase 55 (Feature experimentation framework)

<domain>
## Phase Boundary

Build the ML experimentation layer — config-driven factor definitions, feature importance ranking, adaptive models that route by regime, concept drift handling, and experiment tracking. This is the capstone phase that ties together the evaluation infrastructure (55-56), validation methods (57), and expanded features (59) into a unified ML workflow.

**Source:** `.planning/research/quant_finance_ecosystem_review.md` — Tier 2 (expression engine) + Tier 3 (feature importance, regime routing, concept drift, experiment tracking, Optuna) from Qlib (37.8k stars), MLFinLab (4.6k stars), Jesse (7.5k stars).

**Note:** This phase transitions ta_lab2 from classical TA-only strategies toward ML-augmented strategies. The v0.9.0 feature experimentation framework (Phase 38) provides the foundation; this phase extends it with production-grade ML tooling.

</domain>

<scope>
## Scope

### Expression Engine for Factors (from Qlib)
- Config-driven factor definitions as strings parsed at runtime:
  ```yaml
  factors:
    macd_signal: "EMA($close, 12) / EMA($close, 26) - 1"
    momentum_5d: "Ref($close, 0) / Ref($close, 5) - 1"
    vol_ratio: "Std($close, 5) / Std($close, 20)"
  ```
- YAML registry — no Python code changes per experiment
- Operators: Ref, Delta, Mean, Std, EMA, WMA, Rank, Corr, Slope, Rsquare, Skew, Kurt, Min, Max, arithmetic, conditional
- Extends v0.9.0 feature experimentation framework (`features.yaml`)
- Enables rapid factor experimentation: define → compute → IC evaluate → promote/deprecate

### MDA/SFI Feature Importance (from MLFinLab)
- **Mean Decrease Accuracy (MDA)**: Permutation-based, OOS, works with any classifier
  - Uses PurgedKFold internally for valid importance estimates
  - `mean_decrease_accuracy(model, X, y, cv_gen, clustered_subsets)`
  - Clustered FI: group correlated features (e.g., multiple EMA periods) to address substitution effects
- **Single Feature Importance (SFI)**: Each feature trained alone — eliminates all substitution
  - `single_feature_importance(clf, X, y, cv_gen)`
  - Reveals genuinely independent vs redundant features
- Goal: rank all 112+ `cmc_features` columns by OOS predictive contribution

### Regime-Routed Models — TRA Pattern (from Qlib)
- `cmc_regimes` L0-L2 labels route samples to specialized sub-models per regime:
  - Sideways regime → mean-reversion model (RSI-based)
  - Trending regime → momentum model (EMA crossover)
  - High-vol regime → reduced sizing or flat
- Temporal Routing Adaptor architecture: router network selects expert
- Backtest: per-regime sub-model ensemble vs single model baseline
- Extends existing `regime_enabled` flag in signal generators to full model routing

### Concept Drift Models (from Qlib)
- **DoubleEnsemble**: Explicitly handles concept drift via double ensemble across time
  - Ensemble of models trained on different time windows
  - Weights adapt as distribution shifts
- **ADARNN**: Adaptive RNN for non-stationary time series
  - Hidden states adapt to changing distributions
  - Designed for regime shifts (bull/bear cycles)
- At least one model trained and evaluated with purged CV; compared to static baseline

### Experiment Tracking (from Qlib — MLflow pattern)
- Lightweight PostgreSQL-backed experiment manager (not full MLflow deployment)
- Links per experiment run: hyperparameter config, metrics, artifacts, timestamps
- Extends `cmc_backtest_runs` with:
  - Full parameter config JSON
  - Feature set used
  - CV method and fold count
  - Model type and hyperparameters
- Queryable comparison dashboard: parameter → performance mapping
- Reproducibility: any experiment re-runnable from stored config

### Optuna + Ray Optimization (from Jesse)
- Replace grid search with Tree-structured Parzen Estimator (TPE)
- `optuna.create_study(direction='maximize')` with Sharpe/Calmar/Sortino objectives
- Distributed via Ray workers for parallel trial evaluation
- Resumable: results persisted to SQLite/PostgreSQL
- Anti-overfitting: combine with CPCV from Phase 57
- Demonstrated efficiency gain: same or better parameters in fewer trials than grid search

</scope>

<requirements>
## Requirements

- MLINFRA-01: Expression engine parsing factor strings from YAML registry
- MLINFRA-02: MDA/SFI feature importance with purged CV and clustered FI
- MLINFRA-03: Regime-routed models using `cmc_regimes` L0-L2 labels
- MLINFRA-04: At least one concept drift model (DoubleEnsemble or ADARNN) trained and evaluated
- MLINFRA-05: Experiment tracking with full config + metrics persistence
- MLINFRA-06: Optuna optimization replacing grid search with documented efficiency gain

</requirements>

<success_criteria>
## Success Criteria

1. Expression engine parses factor strings from YAML, evaluates against OHLCV data, and produces feature columns without Python code changes
2. MDA feature importance report ranks all `cmc_features` columns by OOS predictive contribution; top/bottom features documented
3. Regime-routed strategy backtested: per-regime sub-model vs single model; improvement in Sharpe or drawdown documented
4. At least one concept drift model (DoubleEnsemble or ADARNN) trained and evaluated with purged CV; compared to static model baseline
5. Experiment tracker persists full config + metrics for every run; queryable comparison dashboard shows parameter→performance mapping
6. Optuna optimization produces better parameters than grid search on at least 1 strategy with documented efficiency gain

</success_criteria>
