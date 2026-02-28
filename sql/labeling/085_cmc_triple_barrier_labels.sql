-- DDL: cmc_triple_barrier_labels
-- Phase 57: Advanced Labeling & CV
-- Reference: AFML Ch.3 (Lopez de Prado, 2018)
--
-- Stores triple barrier labels for each (asset, tf, event_start) combination.
-- Each row captures a labeled event: the label start (t0), barrier hit time (t1),
-- the profit/stop/timeout outcome (bin), and the vol-scaled barrier parameters
-- used to generate it.
--
-- The unique constraint (uq_triple_barrier_key) allows upsert semantics so
-- labels can be recomputed with different barrier multipliers without conflicts.
--
-- Labels:
--   bin = +1  -> profit target (pt) hit first
--   bin = -1  -> stop loss (sl) hit first
--   bin =  0  -> vertical barrier (timeout) hit first, or no barrier reached
--
-- barrier_type: 'pt', 'sl', 'vb' (vertical barrier)
--
-- ASCII-only comments used throughout (Windows cp1252 safety).

CREATE TABLE IF NOT EXISTS cmc_triple_barrier_labels (
    label_id        UUID        NOT NULL DEFAULT gen_random_uuid(),
    asset_id        INTEGER     NOT NULL,
    tf              TEXT        NOT NULL,
    t0              TIMESTAMPTZ NOT NULL,
    t1              TIMESTAMPTZ,
    pt_multiplier   NUMERIC     NOT NULL,
    sl_multiplier   NUMERIC     NOT NULL,
    vertical_bars   INTEGER     NOT NULL,
    daily_vol       NUMERIC,
    target          NUMERIC,
    ret             NUMERIC,
    bin             SMALLINT,
    barrier_type    TEXT,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_triple_barrier_labels PRIMARY KEY (label_id),
    CONSTRAINT uq_triple_barrier_key UNIQUE (
        asset_id, tf, t0, pt_multiplier, sl_multiplier, vertical_bars
    )
);

-- Fast lookup by asset, timeframe, and event start
CREATE INDEX IF NOT EXISTS idx_triple_barrier_asset_tf_t0
    ON cmc_triple_barrier_labels (asset_id, tf, t0);
