-- 018_migrate_ema_alpha_lut_to_view.sql
--
-- Step 0: ensure ema_alpha_lookup exists (017 must have been run)
-- (you can comment this block out if you don't want the safety check)

DO $$
BEGIN
    IF to_regclass('public.ema_alpha_lookup') IS NULL THEN
        RAISE EXCEPTION 'ema_alpha_lookup does not exist. Run 017_ema_alpha_lookup.sql first.';
    END IF;
END
$$;

-- Step 1: rename the old table so we keep its data around
-- (only do this once; subsequent runs will hit the IF check and skip)

DO $$
BEGIN
    IF to_regclass('public.ema_alpha_lut') IS NOT NULL
       AND to_regclass('public.ema_alpha_lut_old') IS NULL THEN
        ALTER TABLE public.ema_alpha_lut
            RENAME TO ema_alpha_lut_old;
    END IF;
END
$$;

-- Step 2: create a backwards-compatible VIEW named ema_alpha_lut
-- with the same columns as the old table, backed by ema_alpha_lookup.

CREATE OR REPLACE VIEW public.ema_alpha_lut AS
SELECT
    l.tf,
    l.tf_days,
    l.period,
    l.alpha_bar,
    l.effective_days,
    l.alpha_daily_eq
FROM public.ema_alpha_lookup l;
