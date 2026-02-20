-- Migration: drop derivative columns from cmc_ema_multi_tf_u
-- Derivatives belong in cmc_returns_ema_multi_tf_u, not in the base EMA union table.
-- Also adds is_partial_end (was missing from base DDL).

BEGIN;

-- Drop derivative columns (never populated by sync script — always NULL)
ALTER TABLE cmc_ema_multi_tf_u DROP COLUMN IF EXISTS d1;
ALTER TABLE cmc_ema_multi_tf_u DROP COLUMN IF EXISTS d2;
ALTER TABLE cmc_ema_multi_tf_u DROP COLUMN IF EXISTS d1_roll;
ALTER TABLE cmc_ema_multi_tf_u DROP COLUMN IF EXISTS d2_roll;

-- Drop bar-derivative columns (added by prior migration, never populated)
ALTER TABLE cmc_ema_multi_tf_u DROP COLUMN IF EXISTS d1_bar;
ALTER TABLE cmc_ema_multi_tf_u DROP COLUMN IF EXISTS d2_bar;
ALTER TABLE cmc_ema_multi_tf_u DROP COLUMN IF EXISTS roll_bar;
ALTER TABLE cmc_ema_multi_tf_u DROP COLUMN IF EXISTS d1_roll_bar;
ALTER TABLE cmc_ema_multi_tf_u DROP COLUMN IF EXISTS d2_roll_bar;

-- Add columns matching raw EMA table Python get_output_schema()
ALTER TABLE cmc_ema_multi_tf_u ADD COLUMN IF NOT EXISTS ema_bar DOUBLE PRECISION;
ALTER TABLE cmc_ema_multi_tf_u ADD COLUMN IF NOT EXISTS is_partial_end BOOLEAN;

COMMIT;
