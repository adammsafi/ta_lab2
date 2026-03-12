-- DDL: meta_label_results
-- Phase 57: Advanced Labeling & CV
-- Reference: AFML Ch.10 (Lopez de Prado, 2018) -- Meta-Labeling
--
-- Stores meta-label outcomes for each (asset, tf, signal_type, event_start) combination.
-- Each row links a primary signal's prediction (primary_side) to a secondary model
-- that predicts whether to take the trade (meta_label) and with what confidence
-- (trade_probability).
--
-- Primary model (signal generator) determines direction (+1 long / -1 short).
-- Meta-model (RandomForest) predicts: 1=take the trade, 0=skip.
--
-- The unique constraint (uq_meta_label_key) uses model_version to allow
-- multiple model versions for the same signal without conflict.
--
-- Meta-label values:
--   meta_label = 1  -> take the trade
--   meta_label = 0  -> do not take the trade
--
-- ASCII-only comments used throughout (Windows cp1252 safety).

CREATE TABLE IF NOT EXISTS meta_label_results (
    result_id           UUID        NOT NULL DEFAULT gen_random_uuid(),
    asset_id            INTEGER     NOT NULL,
    tf                  TEXT        NOT NULL,
    signal_type         TEXT        NOT NULL,
    t0                  TIMESTAMPTZ NOT NULL,
    t1_from_barrier     TIMESTAMPTZ,
    primary_side        SMALLINT    NOT NULL,
    meta_label          SMALLINT,
    trade_probability   NUMERIC,
    model_version       TEXT,
    n_estimators        INTEGER,
    feature_set         TEXT,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_meta_label_results PRIMARY KEY (result_id),
    CONSTRAINT uq_meta_label_key UNIQUE (
        asset_id, tf, signal_type, t0, model_version
    )
);

-- Fast lookup by asset, timeframe, signal type, and event start
CREATE INDEX IF NOT EXISTS idx_meta_label_asset_signal
    ON meta_label_results (asset_id, tf, signal_type, t0);
