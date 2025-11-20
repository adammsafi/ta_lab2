CREATE OR REPLACE VIEW public.cmc_price_with_emas AS
SELECT
    p.id,
    p.timeclose AS bar_ts,
    p.close,
    p.volume,
    p.marketcap,
    ae.tf,
    ae.tf_days,
    ae.ts     AS ema_ts,
    ae.period,
    ae.ema
FROM public.cmc_price_histories7 p
LEFT JOIN public.all_emas ae
    ON ae.id = p.id
   AND ae.ts = p.timeclose;
