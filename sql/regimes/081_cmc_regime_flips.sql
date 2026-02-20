-- cmc_regime_flips: Regime transition events per asset/timeframe/layer
--
-- Records every regime change (flip) at each layer. Enables analysis of
-- how frequently regimes transition and how long each regime persists.

CREATE TABLE IF NOT EXISTS public.cmc_regime_flips (
    -- Primary key
    id                  INTEGER         NOT NULL,
    ts                  TIMESTAMPTZ     NOT NULL,   -- Timestamp of the flip event
    tf                  TEXT            NOT NULL DEFAULT '1D',
    layer               TEXT            NOT NULL,   -- 'L0', 'L1', 'L2', 'composite'

    -- Transition details
    old_regime          TEXT            NULL,       -- NULL on first-ever regime assignment
    new_regime          TEXT            NOT NULL,

    -- Duration of the previous regime (bars) before this flip
    duration_bars       INTEGER         NULL,

    -- Metadata
    updated_at          TIMESTAMPTZ     DEFAULT now(),

    PRIMARY KEY (id, ts, tf, layer)
);

-- Index for per-asset flip history queries
CREATE INDEX IF NOT EXISTS idx_cmc_regime_flips_id_tf_layer
    ON public.cmc_regime_flips (id, tf, layer);

COMMENT ON TABLE public.cmc_regime_flips IS
'Regime transition events (flips) per asset/timeframe/layer. One row per regime change. duration_bars = bars the old regime persisted before this flip.';

COMMENT ON COLUMN public.cmc_regime_flips.layer IS
'Which regime layer flipped: L0 (monthly), L1 (weekly), L2 (daily), or composite (resolved policy).';

COMMENT ON COLUMN public.cmc_regime_flips.duration_bars IS
'Number of bars the old_regime persisted before transitioning to new_regime. NULL on first assignment.';
