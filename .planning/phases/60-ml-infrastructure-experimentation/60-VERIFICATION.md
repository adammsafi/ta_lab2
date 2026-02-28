---
phase: 60-ml-infrastructure-experimentation
verified: 2026-02-28T15:02:11Z
status: human_needed
score: 4/6 must-haves verified automatically
re_verification: false
human_verification:
  - test: Run run_feature_importance.py on live cmc_features data
    expected: MDA and SFI reports rank all cmc_features columns; top/bottom features documented
    why_human: SC-2 requires top/bottom features documented from an actual DB run.
  - test: Run run_regime_routing.py; compare RegimeRouter vs global model
    expected: RegimeRouter OOS accuracy vs global model comparison printed; per-regime breakdown
    why_human: SC-3 requires improvement documented -- needs actual DB run and result capture.
  - test: Run run_double_ensemble.py; compare DoubleEnsemble to static LGBMClassifier
    expected: Accuracy comparison printed; runs stored in cmc_ml_experiments via --log-experiment
    why_human: SC-4 requires comparison documented -- code is complete but output not yet observed.
  - test: Run run_optuna_sweep.py --grid-comparison; verify efficiency gain documented
    expected: Optuna finds near-optimal in fewer than 256 trials; efficiency ratio printed
    why_human: SC-6 requires documented efficiency gain -- _compute_grid_comparison() wired but must run.
---

# Phase 60: ML Infrastructure and Experimentation Verification Report

**Phase Goal:** Build the ML experimentation layer -- config-driven factor definitions, feature importance ranking, adaptive models that route by regime, concept drift handling, and experiment tracking.
**Verified:** 2026-02-28T15:02:11Z
**Status:** human_needed (2 success criteria fully verified; 4 structurally verified but need live DB runs)
**Re-verification:** No -- initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Expression engine parses factor strings from YAML, evaluates against OHLCV data, produces feature columns without Python code changes | VERIFIED | expression_engine.py has 16 operators; smoke test returns correct pd.Series; FeatureRegistry loads 8 expression-mode features; runner.py dispatches mode=expression to evaluate_expression() |
| 2 | MDA feature importance report ranks all cmc_features columns by OOS predictive contribution; top/bottom features documented | PARTIAL | compute_mda/sfi/cluster_features/compute_clustered_mda exist with real implementations using PurgedKFoldSplitter; run_feature_importance.py CLI wired and smoke-tested; needs live DB run |
| 3 | Regime-routed strategy backtested: per-regime sub-model vs single model; improvement documented | PARTIAL | RegimeRouter trains per-regime sub-models with min_samples=30 guard and global fallback; run_regime_routing.py runs purged CV comparison; smoke test passes; needs live DB run |
| 4 | At least one concept drift model trained with purged CV; compared to static model baseline | PARTIAL | DoubleEnsemble trains sliding-window LightGBM sub-models; run_double_ensemble.py compares vs static LGBMClassifier; smoke test produces 10 sub-models; needs live DB run |
| 5 | Experiment tracker persists full config and metrics for every run; queryable comparison dashboard | VERIFIED | cmc_ml_experiments DDL UUID PK, JSONB params, TEXT[] feature_set, 4 indexes; ExperimentTracker log_run/get_run/list_runs/compare_runs/ensure_table; all 4 CLI scripts wire --log-experiment; Alembic 3caddeff4691 chains from f6a7b8c9d0e1 |
| 6 | Optuna optimization produces better parameters than grid search with documented efficiency gain | PARTIAL | run_optuna_sweep.py creates study with TPE sampler seed=42; _compute_grid_comparison() produces grid_size=256 vs trials-to-99pct ratio; needs live DB run |

**Score:** 2/6 truths fully verified automatically; 4/6 pass structural verification but need live DB runs.

---

## Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| src/ta_lab2/ml/__init__.py | VERIFIED | Exists; package init |
| src/ta_lab2/ml/expression_engine.py | VERIFIED | 244 lines; OPERATOR_REGISTRY 16 ops; evaluate_expression(); validate_expression(); smoke test passes |
| configs/experiments/features.yaml | VERIFIED | 5 expression-mode factors; vol_ratio_expr expands to 4 param variants; lifecycle: experimental |
| sql/ml/095_cmc_ml_experiments.sql | VERIFIED | 129 lines; CREATE TABLE UUID PK, JSONB, TEXT[] feature_set, 4 indexes, COMMENT ON TABLE/columns |
| src/ta_lab2/ml/experiment_tracker.py | VERIFIED | 475 lines; ExperimentTracker log_run/get_run/list_runs/compare_runs/ensure_table; numpy scalar handling; UTC timestamps |
| src/ta_lab2/experiments/registry.py | VERIFIED | mode=expression branch in _validate_compute_spec; _expand_params handles expression mode; error message updated |
| src/ta_lab2/experiments/runner.py | VERIFIED | mode=expression elif dispatches to evaluate_expression() with lazy import at line 569 |
| src/ta_lab2/ml/feature_importance.py | VERIFIED | 457 lines; compute_mda/sfi/cluster_features/compute_clustered_mda; PurgedKFoldSplitter; empty fold guards; smoke test passes |
| src/ta_lab2/ml/regime_router.py | VERIFIED | 373 lines; RegimeRouter fit/predict/predict_proba/get_regime_stats; load_regimes() UTC-aware; min_samples=30; global fallback; smoke test passes |
| src/ta_lab2/scripts/ml/__init__.py | VERIFIED | Exists |
| src/ta_lab2/scripts/ml/run_feature_importance.py | VERIFIED | 449 lines; 10 argparse args; NullPool; loads cmc_features; binary labels from ret_arith; MDA/SFI; top20/bottom10; --log-experiment wired |
| src/ta_lab2/ml/double_ensemble.py | VERIFIED | 397 lines; fit/predict/predict_proba/get_model_info/_compute_sample_weights; lazy LightGBM; sliding windows; recency weighting; 10 sub-models in smoke test |
| src/ta_lab2/scripts/ml/run_regime_routing.py | VERIFIED | 612 lines; purged CV RegimeRouter vs global; per-regime breakdown; --log-experiment wired |
| src/ta_lab2/scripts/ml/run_double_ensemble.py | VERIFIED | 556 lines; DoubleEnsemble vs static LGBMClassifier; adaptive eff_window guard; --log-experiment wired |
| src/ta_lab2/scripts/ml/run_optuna_sweep.py | VERIFIED | 534 lines; Optuna TPE seed=42; purged CV objective; _compute_grid_comparison(); --log-experiment wired |
| alembic/versions/3caddeff4691_ml_experiments_table.py | VERIFIED | down_revision=f6a7b8c9d0e1 valid; op.create_table + 4 indexes + comments; upgrade() and downgrade() present |

---

## Key Link Verification

| From | To | Via | Status |
|------|----|-----|--------|
| expression_engine.py | configs/experiments/features.yaml | evaluate_expression processes dollar-col syntax; FeatureRegistry loads 8 expression-mode features | VERIFIED |
| experiments/registry.py | ml/expression_engine.py | _validate_compute_spec uses inline re.compile + ast.parse for dollar-col validation | VERIFIED |
| experiments/runner.py | ml/expression_engine.py | from ta_lab2.ml.expression_engine import evaluate_expression at line 569 | VERIFIED |
| experiment_tracker.py | cmc_ml_experiments table | parameterized INSERT RETURNING experiment_id; SELECT in get_run/list_runs/compare_runs | VERIFIED |
| feature_importance.py | backtests/cv.py | from ta_lab2.backtests.cv import PurgedKFoldSplitter at module top; used in all 3 CV loops | VERIFIED |
| feature_importance.py | sklearn.inspection.permutation_importance | from sklearn.inspection import permutation_importance; called per fold in compute_mda | VERIFIED |
| regime_router.py | cmc_regimes table | load_regimes() SQL: SELECT ts, l2_label FROM public.cmc_regimes WHERE id=:id AND tf=:tf | VERIFIED |
| run_feature_importance.py | feature_importance.py | from ta_lab2.ml.feature_importance import compute_mda, compute_sfi at line 355 | VERIFIED |
| run_feature_importance.py | experiment_tracker.py | ExperimentTracker + tracker.log_run() in --log-experiment branch | VERIFIED |
| run_regime_routing.py | regime_router.py | from ta_lab2.ml.regime_router import RegimeRouter + router.fit()/predict() | VERIFIED |
| run_double_ensemble.py | double_ensemble.py | from ta_lab2.ml.double_ensemble import DoubleEnsemble + de.fit()/de.predict() | VERIFIED |
| run_optuna_sweep.py | optuna | import optuna + optuna.create_study(sampler=optuna.samplers.TPESampler(seed=42)) | VERIFIED |
| alembic/versions/3caddeff4691 | sql/ml/095_cmc_ml_experiments.sql | op.create_table mirrors DDL; chain: down_revision=f6a7b8c9d0e1_portfolio_tables.py exists | VERIFIED |

---

## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| MLINFRA-01: Config-driven factor definition without Python code changes | SATISFIED | None |
| MLINFRA-02: MDA feature importance ranking of cmc_features | PARTIAL | Needs live DB run to document actual top/bottom feature rankings |
| MLINFRA-03: Regime-routed strategy backtested and compared | PARTIAL | Needs live DB run to document accuracy comparison |
| MLINFRA-04: Concept drift model trained and compared to baseline | PARTIAL | Needs live DB run to document DoubleEnsemble vs static comparison |
| MLINFRA-05: Experiment tracker persists all runs; queryable | SATISFIED | None |
| MLINFRA-06: Optuna optimization with documented efficiency gain | PARTIAL | Needs live DB run to produce efficiency ratio output |

---

## Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| expression_engine.py:131-132 | String _placeholder_ referenced in docstring for ast.parse safety substitution | Info | None -- descriptive documentation, not a feature stub |

No blocker anti-patterns found in any Phase 60 module. No TODO/FIXME/empty handlers/null returns.

---

## Human Verification Required

### 1. MDA/SFI Feature Importance Run (SC-2)

**Test:** Run against live database:

    python -m ta_lab2.scripts.ml.run_feature_importance --asset-ids 1,2 --tf 1D --start 2023-01-01 --end 2025-12-31 --mode both --model rf --output-csv /tmp/phase60_fi.csv --log-experiment

**Expected:** Script completes; prints top 20 and bottom 10 features ranked by MDA and SFI; CSV written; experiment_id logged to cmc_ml_experiments.
**Why human:** Top/bottom features documented requires actual run output with real numbers. Code is complete and smoke-tested.

### 2. Regime Routing Comparison (SC-3)

**Test:** Run against live database:

    python -m ta_lab2.scripts.ml.run_regime_routing --asset-ids 1,2 --tf 1D --start 2023-01-01 --end 2025-12-31 --log-experiment

**Expected:** Comparison table showing RegimeRouter OOS accuracy vs global model; per-regime breakdown; verdict. Both runs logged to cmc_ml_experiments.
**Why human:** SC-3 requires improvement documented. Code is complete and wired; only execution and documentation is outstanding.

### 3. DoubleEnsemble vs Static Baseline (SC-4)

**Test:** Run against live database:

    python -m ta_lab2.scripts.ml.run_double_ensemble --asset-ids 1,2 --tf 1D --start 2023-01-01 --end 2025-12-31 --log-experiment

**Expected:** Comparison table showing DoubleEnsemble vs static LGBMClassifier OOS accuracy; verdict; both runs logged.
**Why human:** SC-4 requires comparison documented. Structural implementation verified; execution evidence missing.

### 4. Optuna Efficiency Gain (SC-6)

**Test:** Run against live database:

    python -m ta_lab2.scripts.ml.run_optuna_sweep --asset-ids 1,2 --tf 1D --start 2023-01-01 --end 2025-12-31 --n-trials 50 --grid-comparison --log-experiment

**Expected:** Best trial params printed; grid comparison shows grid_size=256; trials_to_near_optimal < 256; efficiency ratio printed.
**Why human:** SC-6 requires documented efficiency gain. _compute_grid_comparison() is wired; needs to run on real data.

---

## Gaps Summary

There are no structural gaps. All 16 required artifacts exist with substantive implementations and are
wired correctly. All functional smoke tests pass. optuna 4.7.0 and lightgbm 4.6.0 are installed.
The Alembic migration chain (3caddeff4691 -> f6a7b8c9d0e1 -> e5f6a1b2c3d4) is valid.

The 4 items requiring human verification are execution-evidence gaps: SC-2, SC-3, SC-4, and SC-6
each require running the corresponding CLI script against the live PostgreSQL database to produce
documented output. Each run should take 5-30 minutes depending on data volume.

---

_Verified: 2026-02-28T15:02:11Z_
_Verifier: Claude (gsd-verifier)_
