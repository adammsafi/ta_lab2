BEGIN;

-- 1) Drop FK that points to any stale/old dim
ALTER TABLE public.cmc_ema_multi_tf_u
  DROP CONSTRAINT IF EXISTS cmc_ema_multi_tf_u_tf_fkey;

-- 2) Add FK to the current authoritative dim_timeframe
ALTER TABLE public.cmc_ema_multi_tf_u
  ADD CONSTRAINT cmc_ema_multi_tf_u_tf_fkey
  FOREIGN KEY (tf)
  REFERENCES public.dim_timeframe (tf)
  ON UPDATE NO ACTION
  ON DELETE NO ACTION;

COMMIT;


-- Audit: find TFs used by EMA sources that are missing in the dim
SELECT DISTINCT e.tf
FROM (
  SELECT tf FROM public.cmc_ema_multi_tf
  UNION
  SELECT tf FROM public.cmc_ema_multi_tf_v2
  UNION
  SELECT tf FROM public.cmc_ema_multi_tf_cal_us
  UNION
  SELECT tf FROM public.cmc_ema_multi_tf_cal_iso
  UNION
  SELECT tf FROM public.cmc_ema_multi_tf_cal_anchor_us
  UNION
  SELECT tf FROM public.cmc_ema_multi_tf_cal_anchor_iso
) e
LEFT JOIN public.dim_timeframe d
  ON d.tf = e.tf
WHERE d.tf IS NULL
ORDER BY e.tf;
