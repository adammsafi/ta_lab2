-- cmc_regimes: Market regime labels and resolved policy per asset/timeframe
--
-- Stores per-bar regime classification across up to 5 layers (L0-L4).
-- The resolved composite regime_key drives position sizing and order policy
-- for all downstream signal generators.

CREATE TABLE IF NOT EXISTS public.cmc_regimes (
    -- Primary key
    id                  INTEGER         NOT NULL,
    ts                  TIMESTAMPTZ     NOT NULL,
    tf                  TEXT            NOT NULL DEFAULT '1D',

    -- Layer labels (NULL if layer disabled or not computed)
    l0_label            TEXT            NULL,   -- Monthly: e.g. "Up-Low-Normal"
    l1_label            TEXT            NULL,   -- Weekly:  e.g. "Sideways-High-Normal"
    l2_label            TEXT            NULL,   -- Daily:   e.g. "Down-Normal-Normal"
    l3_label            TEXT            NULL,   -- Intraday (auto-disabled unless data available)
    l4_label            TEXT            NULL,   -- Execution (auto-disabled unless data available)

    -- Resolved composite policy (derived from enabled layers)
    regime_key          TEXT            NOT NULL,           -- e.g. "up_low_normal"
    size_mult           DOUBLE PRECISION NOT NULL DEFAULT 1.0,   -- Position size multiplier
    stop_mult           DOUBLE PRECISION NOT NULL DEFAULT 1.5,   -- Stop-loss multiplier
    orders              TEXT            NOT NULL DEFAULT 'mixed', -- 'long', 'short', 'mixed', 'none'
    gross_cap           DOUBLE PRECISION NOT NULL DEFAULT 1.0,   -- Gross exposure cap
    pyramids            BOOLEAN         NOT NULL DEFAULT TRUE,   -- Allow pyramiding

    -- Data budget / layer enablement
    feature_tier        TEXT            NOT NULL DEFAULT 'lite',  -- 'lite', 'standard', 'full'
    l0_enabled          BOOLEAN         NOT NULL DEFAULT FALSE,
    l1_enabled          BOOLEAN         NOT NULL DEFAULT FALSE,
    l2_enabled          BOOLEAN         NOT NULL DEFAULT FALSE,

    -- Reproducibility
    regime_version_hash TEXT            NULL,   -- Hash of regime code + params version

    -- Metadata
    updated_at          TIMESTAMPTZ     DEFAULT now(),

    PRIMARY KEY (id, ts, tf)
);

-- Index for regime lookup by asset + timeframe + regime (stats queries)
CREATE INDEX IF NOT EXISTS idx_cmc_regimes_id_tf_key
    ON public.cmc_regimes (id, tf, regime_key);

-- Index for global regime stats queries (e.g. how common is each regime)
CREATE INDEX IF NOT EXISTS idx_cmc_regimes_key
    ON public.cmc_regimes (regime_key);

-- Index for latest-regime queries (most recent bar per asset/TF)
CREATE INDEX IF NOT EXISTS idx_cmc_regimes_id_tf_ts_desc
    ON public.cmc_regimes (id, tf, ts DESC);

COMMENT ON TABLE public.cmc_regimes IS
'Per-bar market regime labels and resolved trading policy per asset/timeframe. L0=monthly, L1=weekly, L2=daily. regime_key drives position sizing and order direction in signal generators.';

COMMENT ON COLUMN public.cmc_regimes.regime_key IS
'Composite regime label resolved from enabled layers. Used to JOIN against regime policy tables and tag signals.';

COMMENT ON COLUMN public.cmc_regimes.size_mult IS
'Position size multiplier applied to base allocation. 1.0 = normal, <1 = reduced, 0 = flat.';

COMMENT ON COLUMN public.cmc_regimes.feature_tier IS
'Data budget tier that determined which layers were enabled: lite (L2 only), standard (L1+L2), full (L0+L1+L2).';

COMMENT ON COLUMN public.cmc_regimes.regime_version_hash IS
'SHA256 hash of regime module code + parameter set. Enables reproducibility validation across refreshes.';
