-- alter_returns_tables_multi_window_zscore.sql
--
-- Rename existing z-score columns from single-window to _365 suffix,
-- then add _30 and _90 window variants.
--
-- Applies to all 11 returns tables (5 bar + 6 EMA).

BEGIN;

-- ============================================================
-- BAR RETURNS TABLES (5)
-- ============================================================

-- Helper: bar z-score columns are:
--   canonical: ret_arith_zscore, delta_ret_arith_zscore, ret_log_zscore, delta_ret_log_zscore
--   roll:      ret_arith_roll_zscore, delta_ret_arith_roll_zscore, ret_log_roll_zscore, delta_ret_log_roll_zscore

-- --- cmc_returns_bars_multi_tf ---
ALTER TABLE public.cmc_returns_bars_multi_tf RENAME COLUMN ret_arith_zscore            TO ret_arith_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf RENAME COLUMN delta_ret_arith_zscore      TO delta_ret_arith_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf RENAME COLUMN ret_log_zscore              TO ret_log_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf RENAME COLUMN delta_ret_log_zscore        TO delta_ret_log_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf RENAME COLUMN ret_arith_roll_zscore       TO ret_arith_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf RENAME COLUMN delta_ret_arith_roll_zscore TO delta_ret_arith_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf RENAME COLUMN ret_log_roll_zscore         TO ret_log_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf RENAME COLUMN delta_ret_log_roll_zscore   TO delta_ret_log_roll_zscore_365;

ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS ret_arith_zscore_30             double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore_30       double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS ret_log_zscore_30               double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS delta_ret_log_zscore_30         double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore_30        double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore_30  double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS ret_log_roll_zscore_30          double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore_30    double precision;

ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS ret_arith_zscore_90             double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore_90       double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS ret_log_zscore_90               double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS delta_ret_log_zscore_90         double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore_90        double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore_90  double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS ret_log_roll_zscore_90          double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore_90    double precision;

-- --- cmc_returns_bars_multi_tf_cal_us ---
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us RENAME COLUMN ret_arith_zscore            TO ret_arith_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us RENAME COLUMN delta_ret_arith_zscore      TO delta_ret_arith_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us RENAME COLUMN ret_log_zscore              TO ret_log_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us RENAME COLUMN delta_ret_log_zscore        TO delta_ret_log_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us RENAME COLUMN ret_arith_roll_zscore       TO ret_arith_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us RENAME COLUMN delta_ret_arith_roll_zscore TO delta_ret_arith_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us RENAME COLUMN ret_log_roll_zscore         TO ret_log_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us RENAME COLUMN delta_ret_log_roll_zscore   TO delta_ret_log_roll_zscore_365;

ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_arith_zscore_30             double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore_30       double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_log_zscore_30               double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS delta_ret_log_zscore_30         double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore_30        double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore_30  double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_log_roll_zscore_30          double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore_30    double precision;

ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_arith_zscore_90             double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore_90       double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_log_zscore_90               double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS delta_ret_log_zscore_90         double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore_90        double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore_90  double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_log_roll_zscore_90          double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_us ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore_90    double precision;

-- --- cmc_returns_bars_multi_tf_cal_iso ---
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso RENAME COLUMN ret_arith_zscore            TO ret_arith_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso RENAME COLUMN delta_ret_arith_zscore      TO delta_ret_arith_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso RENAME COLUMN ret_log_zscore              TO ret_log_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso RENAME COLUMN delta_ret_log_zscore        TO delta_ret_log_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso RENAME COLUMN ret_arith_roll_zscore       TO ret_arith_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso RENAME COLUMN delta_ret_arith_roll_zscore TO delta_ret_arith_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso RENAME COLUMN ret_log_roll_zscore         TO ret_log_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso RENAME COLUMN delta_ret_log_roll_zscore   TO delta_ret_log_roll_zscore_365;

ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_arith_zscore_30             double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore_30       double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_log_zscore_30               double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS delta_ret_log_zscore_30         double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore_30        double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore_30  double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_log_roll_zscore_30          double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore_30    double precision;

ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_arith_zscore_90             double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore_90       double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_log_zscore_90               double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS delta_ret_log_zscore_90         double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore_90        double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore_90  double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_log_roll_zscore_90          double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore_90    double precision;

-- --- cmc_returns_bars_multi_tf_cal_anchor_us ---
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us RENAME COLUMN ret_arith_zscore            TO ret_arith_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us RENAME COLUMN delta_ret_arith_zscore      TO delta_ret_arith_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us RENAME COLUMN ret_log_zscore              TO ret_log_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us RENAME COLUMN delta_ret_log_zscore        TO delta_ret_log_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us RENAME COLUMN ret_arith_roll_zscore       TO ret_arith_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us RENAME COLUMN delta_ret_arith_roll_zscore TO delta_ret_arith_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us RENAME COLUMN ret_log_roll_zscore         TO ret_log_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us RENAME COLUMN delta_ret_log_roll_zscore   TO delta_ret_log_roll_zscore_365;

ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_arith_zscore_30             double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore_30       double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_log_zscore_30               double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS delta_ret_log_zscore_30         double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore_30        double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore_30  double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_log_roll_zscore_30          double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore_30    double precision;

ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_arith_zscore_90             double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore_90       double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_log_zscore_90               double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS delta_ret_log_zscore_90         double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore_90        double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore_90  double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_log_roll_zscore_90          double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore_90    double precision;

-- --- cmc_returns_bars_multi_tf_cal_anchor_iso ---
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso RENAME COLUMN ret_arith_zscore            TO ret_arith_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso RENAME COLUMN delta_ret_arith_zscore      TO delta_ret_arith_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso RENAME COLUMN ret_log_zscore              TO ret_log_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso RENAME COLUMN delta_ret_log_zscore        TO delta_ret_log_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso RENAME COLUMN ret_arith_roll_zscore       TO ret_arith_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso RENAME COLUMN delta_ret_arith_roll_zscore TO delta_ret_arith_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso RENAME COLUMN ret_log_roll_zscore         TO ret_log_roll_zscore_365;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso RENAME COLUMN delta_ret_log_roll_zscore   TO delta_ret_log_roll_zscore_365;

ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_arith_zscore_30             double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore_30       double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_log_zscore_30               double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS delta_ret_log_zscore_30         double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore_30        double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore_30  double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_log_roll_zscore_30          double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore_30    double precision;

ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_arith_zscore_90             double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS delta_ret_arith_zscore_90       double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_log_zscore_90               double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS delta_ret_log_zscore_90         double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_arith_roll_zscore_90        double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS delta_ret_arith_roll_zscore_90  double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_log_roll_zscore_90          double precision;
ALTER TABLE public.cmc_returns_bars_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS delta_ret_log_roll_zscore_90    double precision;


-- ============================================================
-- EMA RETURNS TABLES (6)
-- ============================================================

-- Helper: EMA z-score columns are:
--   canonical: ret_arith_ema_zscore, ret_arith_ema_bar_zscore, ret_log_ema_zscore, ret_log_ema_bar_zscore
--   roll:      ret_arith_ema_roll_zscore, ret_arith_ema_bar_roll_zscore, ret_log_ema_roll_zscore, ret_log_ema_bar_roll_zscore

-- --- cmc_returns_ema_multi_tf ---
ALTER TABLE public.cmc_returns_ema_multi_tf RENAME COLUMN ret_arith_ema_zscore          TO ret_arith_ema_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf RENAME COLUMN ret_arith_ema_bar_zscore      TO ret_arith_ema_bar_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf RENAME COLUMN ret_log_ema_zscore            TO ret_log_ema_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf RENAME COLUMN ret_log_ema_bar_zscore        TO ret_log_ema_bar_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf RENAME COLUMN ret_arith_ema_roll_zscore     TO ret_arith_ema_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf RENAME COLUMN ret_arith_ema_bar_roll_zscore TO ret_arith_ema_bar_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf RENAME COLUMN ret_log_ema_roll_zscore       TO ret_log_ema_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf RENAME COLUMN ret_log_ema_bar_roll_zscore   TO ret_log_ema_bar_roll_zscore_365;

ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore_30           double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore_30       double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_log_ema_zscore_30             double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore_30         double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore_30      double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore_30  double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore_30        double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore_30    double precision;

ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore_90           double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore_90       double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_log_ema_zscore_90             double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore_90         double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore_90      double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore_90  double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore_90        double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore_90    double precision;

-- --- cmc_returns_ema_multi_tf_u ---
ALTER TABLE public.cmc_returns_ema_multi_tf_u RENAME COLUMN ret_arith_ema_zscore          TO ret_arith_ema_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_u RENAME COLUMN ret_arith_ema_bar_zscore      TO ret_arith_ema_bar_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_u RENAME COLUMN ret_log_ema_zscore            TO ret_log_ema_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_u RENAME COLUMN ret_log_ema_bar_zscore        TO ret_log_ema_bar_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_u RENAME COLUMN ret_arith_ema_roll_zscore     TO ret_arith_ema_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_u RENAME COLUMN ret_arith_ema_bar_roll_zscore TO ret_arith_ema_bar_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_u RENAME COLUMN ret_log_ema_roll_zscore       TO ret_log_ema_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_u RENAME COLUMN ret_log_ema_bar_roll_zscore   TO ret_log_ema_bar_roll_zscore_365;

ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore_30           double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore_30       double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_log_ema_zscore_30             double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore_30         double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore_30      double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore_30  double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore_30        double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore_30    double precision;

ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore_90           double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore_90       double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_log_ema_zscore_90             double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore_90         double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore_90      double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore_90  double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore_90        double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore_90    double precision;

-- --- cmc_returns_ema_multi_tf_cal_us ---
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us RENAME COLUMN ret_arith_ema_zscore          TO ret_arith_ema_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us RENAME COLUMN ret_arith_ema_bar_zscore      TO ret_arith_ema_bar_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us RENAME COLUMN ret_log_ema_zscore            TO ret_log_ema_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us RENAME COLUMN ret_log_ema_bar_zscore        TO ret_log_ema_bar_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us RENAME COLUMN ret_arith_ema_roll_zscore     TO ret_arith_ema_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us RENAME COLUMN ret_arith_ema_bar_roll_zscore TO ret_arith_ema_bar_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us RENAME COLUMN ret_log_ema_roll_zscore       TO ret_log_ema_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us RENAME COLUMN ret_log_ema_bar_roll_zscore   TO ret_log_ema_bar_roll_zscore_365;

ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore_30           double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore_30       double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_log_ema_zscore_30             double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore_30         double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore_30      double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore_30  double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore_30        double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore_30    double precision;

ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore_90           double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore_90       double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_log_ema_zscore_90             double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore_90         double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore_90      double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore_90  double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore_90        double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_us ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore_90    double precision;

-- --- cmc_returns_ema_multi_tf_cal_iso ---
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso RENAME COLUMN ret_arith_ema_zscore          TO ret_arith_ema_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso RENAME COLUMN ret_arith_ema_bar_zscore      TO ret_arith_ema_bar_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso RENAME COLUMN ret_log_ema_zscore            TO ret_log_ema_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso RENAME COLUMN ret_log_ema_bar_zscore        TO ret_log_ema_bar_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso RENAME COLUMN ret_arith_ema_roll_zscore     TO ret_arith_ema_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso RENAME COLUMN ret_arith_ema_bar_roll_zscore TO ret_arith_ema_bar_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso RENAME COLUMN ret_log_ema_roll_zscore       TO ret_log_ema_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso RENAME COLUMN ret_log_ema_bar_roll_zscore   TO ret_log_ema_bar_roll_zscore_365;

ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore_30           double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore_30       double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_log_ema_zscore_30             double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore_30         double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore_30      double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore_30  double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore_30        double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore_30    double precision;

ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore_90           double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore_90       double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_log_ema_zscore_90             double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore_90         double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore_90      double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore_90  double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore_90        double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_iso ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore_90    double precision;

-- --- cmc_returns_ema_multi_tf_cal_anchor_us ---
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us RENAME COLUMN ret_arith_ema_zscore          TO ret_arith_ema_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us RENAME COLUMN ret_arith_ema_bar_zscore      TO ret_arith_ema_bar_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us RENAME COLUMN ret_log_ema_zscore            TO ret_log_ema_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us RENAME COLUMN ret_log_ema_bar_zscore        TO ret_log_ema_bar_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us RENAME COLUMN ret_arith_ema_roll_zscore     TO ret_arith_ema_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us RENAME COLUMN ret_arith_ema_bar_roll_zscore TO ret_arith_ema_bar_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us RENAME COLUMN ret_log_ema_roll_zscore       TO ret_log_ema_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us RENAME COLUMN ret_log_ema_bar_roll_zscore   TO ret_log_ema_bar_roll_zscore_365;

ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore_30           double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore_30       double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_log_ema_zscore_30             double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore_30         double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore_30      double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore_30  double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore_30        double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore_30    double precision;

ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore_90           double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore_90       double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_log_ema_zscore_90             double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore_90         double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore_90      double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore_90  double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore_90        double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_us ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore_90    double precision;

-- --- cmc_returns_ema_multi_tf_cal_anchor_iso ---
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso RENAME COLUMN ret_arith_ema_zscore          TO ret_arith_ema_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso RENAME COLUMN ret_arith_ema_bar_zscore      TO ret_arith_ema_bar_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso RENAME COLUMN ret_log_ema_zscore            TO ret_log_ema_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso RENAME COLUMN ret_log_ema_bar_zscore        TO ret_log_ema_bar_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso RENAME COLUMN ret_arith_ema_roll_zscore     TO ret_arith_ema_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso RENAME COLUMN ret_arith_ema_bar_roll_zscore TO ret_arith_ema_bar_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso RENAME COLUMN ret_log_ema_roll_zscore       TO ret_log_ema_roll_zscore_365;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso RENAME COLUMN ret_log_ema_bar_roll_zscore   TO ret_log_ema_bar_roll_zscore_365;

ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore_30           double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore_30       double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_log_ema_zscore_30             double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore_30         double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore_30      double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore_30  double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore_30        double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore_30    double precision;

ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_zscore_90           double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_zscore_90       double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_log_ema_zscore_90             double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_log_ema_bar_zscore_90         double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_roll_zscore_90      double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_arith_ema_bar_roll_zscore_90  double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_log_ema_roll_zscore_90        double precision;
ALTER TABLE public.cmc_returns_ema_multi_tf_cal_anchor_iso ADD COLUMN IF NOT EXISTS ret_log_ema_bar_roll_zscore_90    double precision;

COMMIT;
