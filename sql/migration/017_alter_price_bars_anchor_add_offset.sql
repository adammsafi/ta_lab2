-- Add bar_anchor_offset column to anchor_us table
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_us
ADD COLUMN bar_anchor_offset INTEGER;

COMMENT ON COLUMN public.cmc_price_bars_multi_tf_cal_anchor_us.bar_anchor_offset
IS 'Days offset from anchor reference date (e.g., 0, 7, 14 for weekly). Original bar_seq value before sequential conversion.';

-- Add bar_anchor_offset column to anchor_iso table
ALTER TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso
ADD COLUMN bar_anchor_offset INTEGER;

COMMENT ON COLUMN public.cmc_price_bars_multi_tf_cal_anchor_iso.bar_anchor_offset
IS 'Days offset from anchor reference date (e.g., 0, 7, 14 for weekly). Original bar_seq value before sequential conversion.';

-- Add index for query performance
CREATE INDEX idx_anchor_us_anchor_offset ON public.cmc_price_bars_multi_tf_cal_anchor_us(id, tf, bar_anchor_offset);
CREATE INDEX idx_anchor_iso_anchor_offset ON public.cmc_price_bars_multi_tf_cal_anchor_iso(id, tf, bar_anchor_offset);
