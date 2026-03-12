-- ml_experiments: ML experiment run tracking
--
-- Stores metadata for each ML experiment run including model type, hyperparameters,
-- feature set used, cross-validation method, OOS metrics, and feature importances.
-- Foundational table for MLINFRA-05: all ML modules (feature importance, regime routing,
-- DoubleEnsemble, Optuna) log their results here.
-- Extends the backtest_runs pattern to cover ML model training runs.

CREATE TABLE IF NOT EXISTS public.ml_experiments (
    experiment_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_name            TEXT NOT NULL,
    model_type          TEXT NOT NULL,
    model_params        JSONB NOT NULL,
    feature_set         TEXT[] NOT NULL,
    feature_set_hash    TEXT NOT NULL,
    cv_method           TEXT NOT NULL,
    cv_n_splits         INTEGER,
    cv_embargo_frac     NUMERIC,
    label_method        TEXT,
    label_params        JSONB,
    train_start         TIMESTAMPTZ NOT NULL,
    train_end           TIMESTAMPTZ NOT NULL,
    asset_ids           INTEGER[] NOT NULL,
    tf                  TEXT NOT NULL,
    oos_accuracy        NUMERIC,
    oos_sharpe          NUMERIC,
    oos_precision       NUMERIC,
    oos_recall          NUMERIC,
    oos_f1              NUMERIC,
    n_oos_folds         INTEGER,
    mda_importances     JSONB,
    sfi_importances     JSONB,
    optuna_study_name   TEXT,
    optuna_n_trials     INTEGER,
    optuna_best_params  JSONB,
    regime_routing      BOOLEAN DEFAULT FALSE,
    regime_performance  JSONB,
    created_at          TIMESTAMPTZ DEFAULT now(),
    duration_seconds    NUMERIC,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_ml_experiments_model_type
    ON public.ml_experiments(model_type);

CREATE INDEX IF NOT EXISTS idx_ml_experiments_created_at
    ON public.ml_experiments(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_ml_experiments_asset_ids
    ON public.ml_experiments USING GIN (asset_ids);

CREATE INDEX IF NOT EXISTS idx_ml_experiments_feature_set_hash
    ON public.ml_experiments(feature_set_hash);

COMMENT ON TABLE public.ml_experiments IS
'ML experiment run tracking: model type, hyperparameters, feature set, CV method, OOS metrics, and feature importances. All Phase 60 ML modules (MDA/SFI, regime routing, DoubleEnsemble, Optuna) log results here.';

COMMENT ON COLUMN public.ml_experiments.experiment_id IS
'UUID primary key, auto-generated. Used as the stable reference for each experiment run.';

COMMENT ON COLUMN public.ml_experiments.run_name IS
'Human-readable run label (e.g., "lgbm_1d_btc_purged_v1"). Not required to be unique.';

COMMENT ON COLUMN public.ml_experiments.model_type IS
'Model family identifier: lgbm, random_forest, double_ensemble, regime_routed, etc.';

COMMENT ON COLUMN public.ml_experiments.model_params IS
'Full hyperparameter dict as JSONB. Enables reproducibility and parameter-performance comparison.';

COMMENT ON COLUMN public.ml_experiments.feature_set IS
'Array of feature column names used in training. Ordered list matches model feature order.';

COMMENT ON COLUMN public.ml_experiments.feature_set_hash IS
'SHA256 of sorted feature_set joined by comma. Enables fast lookup of runs with identical feature sets.';

COMMENT ON COLUMN public.ml_experiments.cv_method IS
'Cross-validation method: purged_kfold, cpcv, walk_forward, etc.';

COMMENT ON COLUMN public.ml_experiments.cv_embargo_frac IS
'Fractional embargo width between train and test folds (e.g., 0.01 = 1%). NULL for methods without embargo.';

COMMENT ON COLUMN public.ml_experiments.label_method IS
'Target label construction method: triple_barrier, fixed_horizon, triple_barrier_meta, etc.';

COMMENT ON COLUMN public.ml_experiments.label_params IS
'Parameters for label construction as JSONB (e.g., {pt: 0.02, sl: 0.01, t1_days: 5}).';

COMMENT ON COLUMN public.ml_experiments.oos_accuracy IS
'Mean OOS accuracy across all CV folds. NULL if not computed.';

COMMENT ON COLUMN public.ml_experiments.oos_sharpe IS
'Mean OOS Sharpe ratio across all CV folds. NULL if not computed.';

COMMENT ON COLUMN public.ml_experiments.oos_precision IS
'Mean OOS precision (positive predictive value) across CV folds.';

COMMENT ON COLUMN public.ml_experiments.oos_recall IS
'Mean OOS recall (sensitivity) across CV folds.';

COMMENT ON COLUMN public.ml_experiments.oos_f1 IS
'Mean OOS F1 score across CV folds.';

COMMENT ON COLUMN public.ml_experiments.mda_importances IS
'Mean Decrease Accuracy importances as JSONB {feature_name: score}. NULL if MDA not run.';

COMMENT ON COLUMN public.ml_experiments.sfi_importances IS
'Single Feature Importance scores as JSONB {feature_name: score}. NULL if SFI not run.';

COMMENT ON COLUMN public.ml_experiments.optuna_study_name IS
'Optuna study name if hyperparameters were tuned via Optuna. NULL otherwise.';

COMMENT ON COLUMN public.ml_experiments.optuna_n_trials IS
'Number of Optuna trials completed. NULL if Optuna not used.';

COMMENT ON COLUMN public.ml_experiments.optuna_best_params IS
'Best hyperparameter dict found by Optuna as JSONB. NULL if Optuna not used.';

COMMENT ON COLUMN public.ml_experiments.regime_routing IS
'TRUE if per-regime sub-models were used (TRA pattern via regimes labels).';

COMMENT ON COLUMN public.ml_experiments.regime_performance IS
'Per-regime OOS accuracy as JSONB {regime_label: accuracy}. NULL if regime_routing is FALSE.';

COMMENT ON COLUMN public.ml_experiments.duration_seconds IS
'Wall-clock training + evaluation duration in seconds.';

COMMENT ON COLUMN public.ml_experiments.notes IS
'Free-text notes about this run (e.g., observations, known issues, next steps).';
