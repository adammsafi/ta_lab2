-- Migration: Create cmc_codependence table
-- Date: 2026-02-28
-- Purpose: Pairwise asset codependence measures for Phase 59 (MICRO-05)
--
-- Stores rolling pairwise dependency metrics (correlation, distance correlation,
-- mutual information, variation of information) between asset pairs per
-- timeframe and window size. PK includes computed_at to retain historical
-- snapshots across refreshes.
--
-- Idempotent: safe to re-run (CREATE TABLE/INDEX IF NOT EXISTS).
-- No UTF-8 box-drawing characters (Windows cp1252 safety).

CREATE TABLE IF NOT EXISTS public.cmc_codependence (
    -- Pair identification
    id_a            INTEGER         NOT NULL,
    id_b            INTEGER         NOT NULL,
    tf              TEXT            NOT NULL,
    window_bars     INTEGER         NOT NULL,
    computed_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- Codependence metrics
    pearson_corr        DOUBLE PRECISION,
    distance_corr       DOUBLE PRECISION,
    mutual_info         DOUBLE PRECISION,
    variation_of_info   DOUBLE PRECISION,

    -- Observation count
    n_obs           INTEGER,

    PRIMARY KEY (id_a, id_b, tf, window_bars, computed_at)
);

-- Index for pair lookups (e.g. "show me all windows/TFs for BTC-ETH")
CREATE INDEX IF NOT EXISTS idx_cmc_codependence_pair
    ON public.cmc_codependence (id_a, id_b, tf);

-- Index for latest snapshot queries (e.g. "most recent codependence refresh")
CREATE INDEX IF NOT EXISTS idx_cmc_codependence_computed
    ON public.cmc_codependence (computed_at DESC);

-- Table and column documentation
COMMENT ON TABLE public.cmc_codependence IS
'Pairwise asset codependence metrics: Pearson correlation, distance correlation, mutual information, and variation of information. Computed per (id_a, id_b, tf, window_bars). PK includes computed_at to retain historical snapshots across refreshes.';

COMMENT ON COLUMN public.cmc_codependence.id_a IS
'First asset in the pair (dim_assets.id). By convention id_a < id_b to avoid duplicate pairs.';

COMMENT ON COLUMN public.cmc_codependence.id_b IS
'Second asset in the pair (dim_assets.id). By convention id_a < id_b.';

COMMENT ON COLUMN public.cmc_codependence.tf IS
'Timeframe label matching dim_timeframe.tf (e.g. 1D, 7D).';

COMMENT ON COLUMN public.cmc_codependence.window_bars IS
'Number of bars used for the rolling computation window.';

COMMENT ON COLUMN public.cmc_codependence.computed_at IS
'Timestamp when this codependence snapshot was computed. Part of PK to retain history.';

COMMENT ON COLUMN public.cmc_codependence.pearson_corr IS
'Pearson linear correlation coefficient between asset returns over the window.';

COMMENT ON COLUMN public.cmc_codependence.distance_corr IS
'Distance correlation (Szekely 2007) capturing nonlinear dependence. Range [0,1].';

COMMENT ON COLUMN public.cmc_codependence.mutual_info IS
'Mutual information between discretized return distributions. Higher = more shared info.';

COMMENT ON COLUMN public.cmc_codependence.variation_of_info IS
'Variation of information (metric distance on joint entropy). Lower = more similar.';

COMMENT ON COLUMN public.cmc_codependence.n_obs IS
'Number of overlapping observations used in the computation.';
