CREATE OR REPLACE VIEW public.all_emas AS
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

    -- Multi-timeframe EMAs
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
    FROM public.cmc_ema_multi_tf m;
