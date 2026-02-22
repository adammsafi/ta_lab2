-- Migration: Add alignment_source to feature tables (cmc_vol, cmc_ta, cmc_features)
-- Purpose: Enable unified (_u) table sourcing with alignment_source tracking
-- Existing data gets DEFAULT 'multi_tf' (all current rows come from base tables)

-- ============================================================================
-- cmc_vol
-- ============================================================================

ALTER TABLE public.cmc_vol
    ADD COLUMN IF NOT EXISTS alignment_source TEXT NOT NULL DEFAULT 'multi_tf';

ALTER TABLE public.cmc_vol DROP CONSTRAINT IF EXISTS cmc_vol_pkey;
ALTER TABLE public.cmc_vol ADD PRIMARY KEY (id, ts, tf, alignment_source);

DROP INDEX IF EXISTS idx_cmc_vol_id_tf_ts;
CREATE INDEX IF NOT EXISTS idx_cmc_vol_id_tf_as_ts
ON public.cmc_vol (id, tf, alignment_source, ts DESC);

-- ============================================================================
-- cmc_ta
-- ============================================================================

ALTER TABLE public.cmc_ta
    ADD COLUMN IF NOT EXISTS alignment_source TEXT NOT NULL DEFAULT 'multi_tf';

ALTER TABLE public.cmc_ta DROP CONSTRAINT IF EXISTS cmc_ta_pkey;
ALTER TABLE public.cmc_ta ADD PRIMARY KEY (id, ts, tf, alignment_source);

DROP INDEX IF EXISTS idx_cmc_ta_id_tf_ts;
CREATE INDEX IF NOT EXISTS idx_cmc_ta_id_tf_as_ts
ON public.cmc_ta (id, tf, alignment_source, ts DESC);

-- ============================================================================
-- cmc_features
-- ============================================================================

ALTER TABLE public.cmc_features
    ADD COLUMN IF NOT EXISTS alignment_source TEXT NOT NULL DEFAULT 'multi_tf';

ALTER TABLE public.cmc_features DROP CONSTRAINT IF EXISTS cmc_features_pkey;
ALTER TABLE public.cmc_features ADD PRIMARY KEY (id, ts, tf, alignment_source);

DROP INDEX IF EXISTS idx_cmc_features_id_tf_ts;
CREATE INDEX IF NOT EXISTS idx_cmc_features_id_tf_as_ts
ON public.cmc_features (id, tf, alignment_source, ts DESC);

DROP INDEX IF EXISTS idx_cmc_features_asset_class;
CREATE INDEX IF NOT EXISTS idx_cmc_features_asset_class_as
ON public.cmc_features (asset_class, tf, alignment_source, ts DESC);
