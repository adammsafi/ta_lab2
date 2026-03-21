CREATE TABLE public.price_bars_multi_tf_snapshot_20251213
AS
SELECT *
FROM public.price_bars_multi_tf;

ALTER TABLE public.price_bars_multi_tf_snapshot_20251213
  ADD CONSTRAINT price_bars_multi_tf_snapshot_20251213_pkey
  PRIMARY KEY (id, tf, bar_seq);
