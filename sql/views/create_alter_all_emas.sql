-- sql/views/create_alter_all_emas.sql
-- Recreate all_emas view with consistent column names and include *_cal.

BEGIN;

-- Drop dependent views first if they exist, then all_emas itself.
DROP VIEW IF EXISTS public.cmc_price_with_emas_d1d2;
DROP VIEW IF EXISTS public.cmc_price_with_emas;
DROP VIEW IF EXISTS public.all_emas;

CREATE VIEW public.all_emas AS
    -- Daily EMAs (tf = '1D')
    SELECT
        d.id,
        d.ts,
        d.tf,
        d.tf_days,
        d.period,
        d.ema,
        d.d1_roll AS d1,
        d.d2_roll AS d2,
        d.d1      AS d1_close,
        d.d2      AS d2_close,
        d.roll
    FROM public.cmc_ema_daily d

    UNION ALL

    -- Multi-timeframe EMAs (original table)
    SELECT
        m.id,
        m.ts,
        m.tf,
        m.tf_days,
        m.period,
        m.ema,
        m.d1_roll AS d1,
        m.d2_roll AS d2,
        m.d1      AS d1_close,
        m.d2      AS d2_close,
        m.roll
    FROM public.cmc_ema_multi_tf m

    UNION ALL

    -- Multi-timeframe EMAs (calibrated table)
    SELECT
        c.id,
        c.ts,
        c.tf,
        c.tf_days,
        c.period,
        c.ema,
        c.d1_roll AS d1,
        c.d2_roll AS d2,
        c.d1      AS d1_close,
        c.d2      AS d2_close,
        c.roll
    FROM public.cmc_ema_multi_tf_cal c;

COMMIT;
