-- cmc_regime_stats: Pre-computed per-regime performance statistics
--
-- Aggregates historical return distribution per (asset, timeframe, regime_key).
-- Used by signal generators for regime-aware position sizing and by dashboards
-- for regime profiling without expensive on-the-fly aggregations.

CREATE TABLE IF NOT EXISTS public.cmc_regime_stats (
    -- Primary key
    id                  INTEGER         NOT NULL,
    tf                  TEXT            NOT NULL DEFAULT '1D',
    regime_key          TEXT            NOT NULL,

    -- Regime frequency stats
    n_bars              INTEGER         NOT NULL DEFAULT 0,   -- Total bars in this regime
    pct_of_history      DOUBLE PRECISION NULL,               -- Fraction of total bars (0-1)

    -- Return distribution (1-day forward returns during this regime)
    avg_ret_1d          DOUBLE PRECISION NULL,   -- Mean 1D return
    std_ret_1d          DOUBLE PRECISION NULL,   -- Std dev of 1D returns (volatility proxy)

    -- Metadata
    computed_at         TIMESTAMPTZ     DEFAULT now(),

    PRIMARY KEY (id, tf, regime_key)
);

COMMENT ON TABLE public.cmc_regime_stats IS
'Pre-computed regime performance statistics per asset/TF/regime. Refreshed alongside cmc_regimes. Used for regime-aware position sizing and dashboard analytics.';

COMMENT ON COLUMN public.cmc_regime_stats.pct_of_history IS
'Fraction of total bars (across all regimes) where this regime was active. Sums to ~1.0 across all regime_key values for a given (id, tf).';

COMMENT ON COLUMN public.cmc_regime_stats.avg_ret_1d IS
'Mean 1-day forward return observed during bars where this regime was active.';

COMMENT ON COLUMN public.cmc_regime_stats.std_ret_1d IS
'Standard deviation of 1-day forward returns during this regime. Proxy for intra-regime volatility.';
