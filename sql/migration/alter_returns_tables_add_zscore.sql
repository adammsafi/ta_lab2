-- alter_returns_tables_add_zscore.sql
-- Migration: Add z-score + is_outlier columns to all returns tables (bar + EMA).
--
-- Bar returns (5 tables): 8 z-score columns + 1 is_outlier = 9 new columns each
-- EMA returns (6 tables): 8 z-score columns + 1 is_outlier = 9 new columns each
--
-- Z-scores are computed by a post-processing script (refresh_returns_zscore.py),
-- not by the base returns refresh SQL. Columns are nullable; NULL = not yet computed.

BEGIN;

-- ============================================================
-- BAR RETURNS: cmc_returns_bars_multi_tf
-- ============================================================
ALTER TABLE public.cmc_returns_bars_multi_tf
    ADD COLUMN IF NOT EXISTS ret_arith_zscore              double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore        double precision,
    ADD COLUMN IF NOT EXISTS ret_log_zscore                double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_log_zscore          double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore         double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore   double precision,
    ADD COLUMN IF NOT EXISTS ret_log_roll_zscore           double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore     double precision,
    ADD COLUMN IF NOT EXISTS is_outlier                    boolean;

-- ============================================================
-- BAR RETURNS: cmc_returns_bars_multi_tf_cal_us
-- ============================================================
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us
    ADD COLUMN IF NOT EXISTS ret_arith_zscore              double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore        double precision,
    ADD COLUMN IF NOT EXISTS ret_log_zscore                double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_log_zscore          double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore         double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore   double precision,
    ADD COLUMN IF NOT EXISTS ret_log_roll_zscore           double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore     double precision,
    ADD COLUMN IF NOT EXISTS is_outlier                    boolean;

-- ============================================================
-- BAR RETURNS: cmc_returns_bars_multi_tf_cal_iso
-- ============================================================
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso
    ADD COLUMN IF NOT EXISTS ret_arith_zscore              double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore        double precision,
    ADD COLUMN IF NOT EXISTS ret_log_zscore                double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_log_zscore          double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore         double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore   double precision,
    ADD COLUMN IF NOT EXISTS ret_log_roll_zscore           double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore     double precision,
    ADD COLUMN IF NOT EXISTS is_outlier                    boolean;

-- ============================================================
-- BAR RETURNS: cmc_returns_bars_multi_tf_cal_anchor_us
-- ============================================================
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us
    ADD COLUMN IF NOT EXISTS ret_arith_zscore              double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore        double precision,
    ADD COLUMN IF NOT EXISTS ret_log_zscore                double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_log_zscore          double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore         double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore   double precision,
    ADD COLUMN IF NOT EXISTS ret_log_roll_zscore           double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore     double precision,
    ADD COLUMN IF NOT EXISTS is_outlier                    boolean;

-- ============================================================
-- BAR RETURNS: cmc_returns_bars_multi_tf_cal_anchor_iso
-- ============================================================
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso
    ADD COLUMN IF NOT EXISTS ret_arith_zscore              double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore        double precision,
    ADD COLUMN IF NOT EXISTS ret_log_zscore                double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_log_zscore          double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore         double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore   double precision,
    ADD COLUMN IF NOT EXISTS ret_log_roll_zscore           double precision,
    ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore     double precision,
    ADD COLUMN IF NOT EXISTS is_outlier                    boolean;

-- ============================================================
-- EMA RETURNS: cmc_returns_ema_multi_tf
-- ============================================================
ALTER TABLE public.cmc_returns_ema_multi_tf
    ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore          double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore      double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_zscore            double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore        double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore     double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore       double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore   double precision,
    ADD COLUMN IF NOT EXISTS is_outlier                    boolean;

-- ============================================================
-- EMA RETURNS: cmc_returns_ema_multi_tf_u
-- ============================================================
ALTER TABLE public.cmc_returns_ema_multi_tf_u
    ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore          double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore      double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_zscore            double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore        double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore     double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore       double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore   double precision,
    ADD COLUMN IF NOT EXISTS is_outlier                    boolean;

-- ============================================================
-- EMA RETURNS: cmc_returns_ema_multi_tf_cal_us
-- ============================================================
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us
    ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore          double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore      double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_zscore            double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore        double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore     double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore       double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore   double precision,
    ADD COLUMN IF NOT EXISTS is_outlier                    boolean;

-- ============================================================
-- EMA RETURNS: cmc_returns_ema_multi_tf_cal_iso
-- ============================================================
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso
    ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore          double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore      double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_zscore            double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore        double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore     double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore       double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore   double precision,
    ADD COLUMN IF NOT EXISTS is_outlier                    boolean;

-- ============================================================
-- EMA RETURNS: cmc_returns_ema_multi_tf_cal_anchor_us
-- ============================================================
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us
    ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore          double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore      double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_zscore            double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore        double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore     double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore       double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore   double precision,
    ADD COLUMN IF NOT EXISTS is_outlier                    boolean;

-- ============================================================
-- EMA RETURNS: cmc_returns_ema_multi_tf_cal_anchor_iso
-- ============================================================
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso
    ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore          double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore      double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_zscore            double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore        double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore     double precision,
    ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore       double precision,
    ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore   double precision,
    ADD COLUMN IF NOT EXISTS is_outlier                    boolean;

COMMIT;
