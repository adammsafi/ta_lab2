-- =============================================================================
-- cmc_ic_results -- Information Coefficient evaluation results
-- =============================================================================
-- Reference DDL for the cmc_ic_results table.
-- This file is for documentation only; the actual table is created and managed
-- by the Alembic migration: alembic/versions/c3b718c2d088_ic_results_table.py
--
-- Each row stores the IC of a single feature against a forward return horizon
-- in a specific regime slice over a time-bounded training window.
--
-- Natural key: (asset_id, tf, feature, horizon, return_type, regime_col,
--               regime_label, train_start, train_end)
-- Unique constraint: uq_ic_results_key enforces this at the DB level.
-- =============================================================================

CREATE TABLE IF NOT EXISTS public.cmc_ic_results (
    -- Primary key
    result_id         UUID        NOT NULL DEFAULT gen_random_uuid(),

    -- Asset + timeframe
    asset_id          INTEGER     NOT NULL,
    tf                TEXT        NOT NULL,

    -- Feature name (column name from cmc_features)
    feature           TEXT        NOT NULL,

    -- Forward return horizon in bars
    horizon           INTEGER     NOT NULL,

    -- Forward return horizon in calendar days (horizon * tf_days_nominal)
    horizon_days      INTEGER,

    -- Return type: 'arith' or 'log'
    return_type       TEXT        NOT NULL,

    -- Regime slice key: 'trend_state', 'vol_state', or 'all'
    regime_col        TEXT        NOT NULL,

    -- Regime slice label: e.g. 'Up', 'High', 'all'
    regime_label      TEXT        NOT NULL,

    -- Training window bounds (inclusive, timezone-aware)
    train_start       TIMESTAMPTZ NOT NULL,
    train_end         TIMESTAMPTZ NOT NULL,

    -- IC outputs (nullable: some windows may lack sufficient data)
    ic                NUMERIC,
    ic_t_stat         NUMERIC,
    ic_p_value        NUMERIC,
    ic_ir             NUMERIC,
    ic_ir_t_stat      NUMERIC,
    turnover          NUMERIC,
    n_obs             INTEGER,

    -- Audit timestamp
    computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Constraints
    CONSTRAINT pk_ic_results        PRIMARY KEY (result_id),
    CONSTRAINT uq_ic_results_key    UNIQUE (
        asset_id, tf, feature, horizon, return_type,
        regime_col, regime_label, train_start, train_end
    )
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_ic_results_asset_feature
    ON public.cmc_ic_results (asset_id, tf, feature);

CREATE INDEX IF NOT EXISTS idx_ic_results_computed_at
    ON public.cmc_ic_results (computed_at);

-- Table description
COMMENT ON TABLE public.cmc_ic_results IS
    'IC evaluation results: Spearman IC of each feature vs forward returns, '
    'computed per (asset, tf, feature, horizon, return_type, regime_slice, training_window). '
    'Created by Alembic migration c3b718c2d088 (Phase 37).';
