CREATE TABLE public.cmc_price_bars_multi_tf_snapshot_20251213
AS
SELECT *
FROM public.cmc_price_bars_multi_tf;

ALTER TABLE public.cmc_price_bars_multi_tf_snapshot_20251213
  ADD CONSTRAINT cmc_price_bars_multi_tf_snapshot_20251213_pkey
  PRIMARY KEY (id, tf, bar_seq);
