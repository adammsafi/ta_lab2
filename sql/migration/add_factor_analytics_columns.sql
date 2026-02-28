-- =============================================================================
-- Phase 56: Factor Analytics Reporting -- Reference DDL
-- =============================================================================
-- This file documents all schema additions introduced in Phase 56.
-- It is REFERENCE ONLY -- Alembic migration files are the authoritative source.
-- Do not execute this file directly; use: alembic upgrade head
--
-- Migration chain:
--   30eac3660488 (perps_readiness)
--   -> a1b2c3d4e5f6 (add_rank_ic_to_ic_results)
--   -> b2c3d4e5f6a1 (add_mae_mfe_to_trades)
--   -> c3d4e5f6a1b2 (add_mc_ci_to_metrics)
--   -> d4e5f6a1b2c3 (add_cs_norms_to_features)
--
-- Total: 13 new nullable columns across 5 tables
-- =============================================================================


-- =============================================================================
-- Migration 1: a1b2c3d4e5f6 -- add_rank_ic_to_ic_results
-- Table: cmc_ic_results (1 new column)
-- =============================================================================

ALTER TABLE public.cmc_ic_results
    ADD COLUMN rank_ic NUMERIC;

COMMENT ON COLUMN public.cmc_ic_results.rank_ic IS
    'Spearman rank IC (explicit label for the Spearman IC already stored in the ic'
    ' column). Backfilled from ic on migration; populated independently by future'
    ' evaluators that compute rank and Pearson separately.';

-- Backfill from existing ic values
UPDATE public.cmc_ic_results
SET rank_ic = ic
WHERE rank_ic IS NULL;


-- =============================================================================
-- Migration 2: b2c3d4e5f6a1 -- add_mae_mfe_to_trades
-- Table: cmc_backtest_trades (2 new columns)
-- =============================================================================

ALTER TABLE public.cmc_backtest_trades
    ADD COLUMN mae NUMERIC;

COMMENT ON COLUMN public.cmc_backtest_trades.mae IS
    'Maximum Adverse Excursion: worst intra-trade return vs entry price.'
    ' Expressed as a decimal fraction (e.g. -0.05 = -5%).'
    ' NULL until computed by the MAE/MFE analyzer in Phase 56.';

ALTER TABLE public.cmc_backtest_trades
    ADD COLUMN mfe NUMERIC;

COMMENT ON COLUMN public.cmc_backtest_trades.mfe IS
    'Maximum Favorable Excursion: best intra-trade return vs entry price.'
    ' Expressed as a decimal fraction (e.g. 0.10 = +10%).'
    ' NULL until computed by the MAE/MFE analyzer in Phase 56.';


-- =============================================================================
-- Migration 3: c3d4e5f6a1b2 -- add_mc_ci_to_metrics
-- Tables: cmc_backtest_metrics (4 new columns) + cmc_backtest_runs (1 new column)
-- =============================================================================

ALTER TABLE public.cmc_backtest_metrics
    ADD COLUMN mc_sharpe_lo NUMERIC;

COMMENT ON COLUMN public.cmc_backtest_metrics.mc_sharpe_lo IS
    'Monte Carlo 5th percentile Sharpe ratio (lower bound of 95% CI).'
    ' Computed from N=1000 block-bootstrap resamples of daily returns.'
    ' NULL until computed by Phase 56 MC analyzer.';

ALTER TABLE public.cmc_backtest_metrics
    ADD COLUMN mc_sharpe_hi NUMERIC;

COMMENT ON COLUMN public.cmc_backtest_metrics.mc_sharpe_hi IS
    'Monte Carlo 95th percentile Sharpe ratio (upper bound of 95% CI).'
    ' Computed from N=1000 block-bootstrap resamples of daily returns.'
    ' NULL until computed by Phase 56 MC analyzer.';

ALTER TABLE public.cmc_backtest_metrics
    ADD COLUMN mc_sharpe_median NUMERIC;

COMMENT ON COLUMN public.cmc_backtest_metrics.mc_sharpe_median IS
    'Monte Carlo median Sharpe ratio across all resamples.'
    ' More robust than point estimate for noisy return series.'
    ' NULL until computed by Phase 56 MC analyzer.';

ALTER TABLE public.cmc_backtest_metrics
    ADD COLUMN mc_n_samples INTEGER;

COMMENT ON COLUMN public.cmc_backtest_metrics.mc_n_samples IS
    'Number of Monte Carlo resamples used to compute CI bounds.'
    ' Typically 1000. NULL until MC analysis is run.';

ALTER TABLE public.cmc_backtest_runs
    ADD COLUMN tearsheet_path TEXT;

COMMENT ON COLUMN public.cmc_backtest_runs.tearsheet_path IS
    'File path to the QuantStats HTML tear sheet generated for this run.'
    ' Relative to project root or absolute path depending on config.'
    ' NULL if tear sheet generation was skipped.';


-- =============================================================================
-- Migration 4: d4e5f6a1b2c3 -- add_cs_norms_to_features
-- Table: cmc_features (6 new columns)
-- CS-norms computed PARTITION BY (ts, tf) across all assets at each timestamp.
-- =============================================================================

ALTER TABLE public.cmc_features
    ADD COLUMN ret_arith_cs_zscore DOUBLE PRECISION;

COMMENT ON COLUMN public.cmc_features.ret_arith_cs_zscore IS
    'Cross-sectional z-score of ret_arith.'
    ' Computed PARTITION BY (ts, tf) across all assets at each timestamp.'
    ' z = (ret_arith - mean) / std. NULL when fewer than 3 assets have data.';

ALTER TABLE public.cmc_features
    ADD COLUMN ret_arith_cs_rank DOUBLE PRECISION;

COMMENT ON COLUMN public.cmc_features.ret_arith_cs_rank IS
    'Cross-sectional percentile rank of ret_arith in [0, 1].'
    ' Computed PARTITION BY (ts, tf) via scipy.stats.rankdata with method=average.'
    ' 1.0 = highest return in cross-section. NULL when fewer than 3 assets have data.';

ALTER TABLE public.cmc_features
    ADD COLUMN rsi_14_cs_zscore DOUBLE PRECISION;

COMMENT ON COLUMN public.cmc_features.rsi_14_cs_zscore IS
    'Cross-sectional z-score of rsi_14.'
    ' Computed PARTITION BY (ts, tf) across all assets at each timestamp.'
    ' z = (rsi_14 - mean) / std. NULL when fewer than 3 assets have data.';

ALTER TABLE public.cmc_features
    ADD COLUMN rsi_14_cs_rank DOUBLE PRECISION;

COMMENT ON COLUMN public.cmc_features.rsi_14_cs_rank IS
    'Cross-sectional percentile rank of rsi_14 in [0, 1].'
    ' Computed PARTITION BY (ts, tf) via scipy.stats.rankdata with method=average.'
    ' 1.0 = highest RSI in cross-section. NULL when fewer than 3 assets have data.';

ALTER TABLE public.cmc_features
    ADD COLUMN vol_parkinson_20_cs_zscore DOUBLE PRECISION;

COMMENT ON COLUMN public.cmc_features.vol_parkinson_20_cs_zscore IS
    'Cross-sectional z-score of vol_parkinson_20.'
    ' Computed PARTITION BY (ts, tf) across all assets at each timestamp.'
    ' z = (vol_parkinson_20 - mean) / std. NULL when fewer than 3 assets have data.';

ALTER TABLE public.cmc_features
    ADD COLUMN vol_parkinson_20_cs_rank DOUBLE PRECISION;

COMMENT ON COLUMN public.cmc_features.vol_parkinson_20_cs_rank IS
    'Cross-sectional percentile rank of vol_parkinson_20 in [0, 1].'
    ' Computed PARTITION BY (ts, tf) via scipy.stats.rankdata with method=average.'
    ' 1.0 = highest vol in cross-section. NULL when fewer than 3 assets have data.';


-- =============================================================================
-- Downgrade reference (reverse order, for documentation)
-- =============================================================================
-- To remove all Phase 56 changes (via Alembic): alembic downgrade 30eac3660488
--
-- Manual equivalent (reverse migration order):
--
-- -- Migration 4 reverse
-- ALTER TABLE public.cmc_features
--     DROP COLUMN IF EXISTS vol_parkinson_20_cs_rank,
--     DROP COLUMN IF EXISTS vol_parkinson_20_cs_zscore,
--     DROP COLUMN IF EXISTS rsi_14_cs_rank,
--     DROP COLUMN IF EXISTS rsi_14_cs_zscore,
--     DROP COLUMN IF EXISTS ret_arith_cs_rank,
--     DROP COLUMN IF EXISTS ret_arith_cs_zscore;
--
-- -- Migration 3 reverse
-- ALTER TABLE public.cmc_backtest_runs
--     DROP COLUMN IF EXISTS tearsheet_path;
-- ALTER TABLE public.cmc_backtest_metrics
--     DROP COLUMN IF EXISTS mc_n_samples,
--     DROP COLUMN IF EXISTS mc_sharpe_median,
--     DROP COLUMN IF EXISTS mc_sharpe_hi,
--     DROP COLUMN IF EXISTS mc_sharpe_lo;
--
-- -- Migration 2 reverse
-- ALTER TABLE public.cmc_backtest_trades
--     DROP COLUMN IF EXISTS mfe,
--     DROP COLUMN IF EXISTS mae;
--
-- -- Migration 1 reverse
-- ALTER TABLE public.cmc_ic_results
--     DROP COLUMN IF EXISTS rank_ic;
