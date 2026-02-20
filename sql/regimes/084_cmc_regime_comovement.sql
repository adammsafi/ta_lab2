-- cmc_regime_comovement: Pairwise EMA comovement statistics
--
-- Tracks alignment, sign agreement, and lead-lag relationships between pairs
-- of EMA series per asset/timeframe. Refreshed alongside the regime pipeline.
-- Supports regime labeling (are fast/slow EMAs moving together?) and research.

CREATE TABLE IF NOT EXISTS public.cmc_regime_comovement (
    -- Primary key
    id                  INTEGER         NOT NULL,
    tf                  TEXT            NOT NULL DEFAULT '1D',
    ema_a               TEXT            NOT NULL,   -- e.g. 'close_ema_20'
    ema_b               TEXT            NOT NULL,   -- e.g. 'close_ema_50'

    -- Comovement metrics (computed over trailing window)
    correlation         DOUBLE PRECISION NULL,      -- Spearman correlation between EMA levels
    sign_agree_rate     DOUBLE PRECISION NULL,      -- Fraction of bars where sign(dEMA_a) == sign(dEMA_b)
    best_lead_lag       INTEGER         NULL,       -- Lag (bars) maximizing cross-corr; positive = b leads a
    best_lead_lag_corr  DOUBLE PRECISION NULL,      -- Cross-correlation value at best_lead_lag
    n_obs               INTEGER         NULL,       -- Number of observations used in computation

    -- Metadata
    computed_at         TIMESTAMPTZ     NOT NULL DEFAULT now(),

    PRIMARY KEY (id, tf, ema_a, ema_b, computed_at)
);

-- Index for per-asset comovement queries (most recent snapshot)
CREATE INDEX IF NOT EXISTS idx_cmc_regime_comovement_id_tf
    ON public.cmc_regime_comovement (id, tf);

COMMENT ON TABLE public.cmc_regime_comovement IS
'Pairwise EMA comovement stats: correlation, sign agreement, and lead-lag per asset/TF. Refreshed alongside regimes. Supports regime labeling and EMA alignment analytics.';

COMMENT ON COLUMN public.cmc_regime_comovement.ema_a IS
'First EMA series identifier, e.g. ''close_ema_20''. Matches column names in cmc_ema_multi_tf_u.';

COMMENT ON COLUMN public.cmc_regime_comovement.ema_b IS
'Second EMA series identifier, e.g. ''close_ema_50''. Matches column names in cmc_ema_multi_tf_u.';

COMMENT ON COLUMN public.cmc_regime_comovement.sign_agree_rate IS
'Fraction of bars (0.0-1.0) where the daily delta of EMA_a and EMA_b have the same sign. 1.0 = always aligned, 0.5 = random.';

COMMENT ON COLUMN public.cmc_regime_comovement.best_lead_lag IS
'Lag in bars that maximises the cross-correlation. Positive means EMA_b leads EMA_a (EMA_b changes first).';

COMMENT ON COLUMN public.cmc_regime_comovement.computed_at IS
'Timestamp when this comovement snapshot was computed. Part of PK to retain history across refreshes.';
