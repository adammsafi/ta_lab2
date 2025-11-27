CREATE OR REPLACE VIEW public.cmc_price_with_emas_d1d2 AS
SELECT
    p.id,
    p.timeclose AS bar_ts,
    p.close,
    p.volume,
    p.marketcap,
    ae.tf,
    ae.tf_days,
    ae.ts        AS ema_ts,
    ae.period,
    ae.ema,
    ae.d1,
    ae.d2,
    ae.d1_close,
    ae.d2_close,
    ae.roll
FROM public.cmc_price_histories7 AS p
LEFT JOIN public.all_emas AS ae
    ON ae.id = p.id
   AND ae.ts = p.timeclose;
