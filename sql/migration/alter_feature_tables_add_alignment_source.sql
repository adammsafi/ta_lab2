-- Migration: Add alignment_source to feature tables (vol, ta, features)
-- Purpose: Enable unified (_u) table sourcing with alignment_source tracking
-- Existing data gets DEFAULT 'multi_tf' (all current rows come from base tables)

-- ============================================================================
-- vol
-- ============================================================================

ALTER TABLE public.vol
    ADD COLUMN IF NOT EXISTS alignment_source TEXT NOT NULL DEFAULT 'multi_tf';

ALTER TABLE public.vol DROP CONSTRAINT IF EXISTS vol_pkey;
ALTER TABLE public.vol ADD PRIMARY KEY (id, ts, tf, alignment_source);

DROP INDEX IF EXISTS idx_vol_id_tf_ts;
CREATE INDEX IF NOT EXISTS idx_vol_id_tf_as_ts
ON public.vol (id, tf, alignment_source, ts DESC);

-- ============================================================================
-- ta
-- ============================================================================

ALTER TABLE public.ta
    ADD COLUMN IF NOT EXISTS alignment_source TEXT NOT NULL DEFAULT 'multi_tf';

ALTER TABLE public.ta DROP CONSTRAINT IF EXISTS ta_pkey;
ALTER TABLE public.ta ADD PRIMARY KEY (id, ts, tf, alignment_source);

DROP INDEX IF EXISTS idx_ta_id_tf_ts;
CREATE INDEX IF NOT EXISTS idx_ta_id_tf_as_ts
ON public.ta (id, tf, alignment_source, ts DESC);

-- ============================================================================
-- features
-- ============================================================================

ALTER TABLE public.features
    ADD COLUMN IF NOT EXISTS alignment_source TEXT NOT NULL DEFAULT 'multi_tf';

ALTER TABLE public.features DROP CONSTRAINT IF EXISTS features_pkey;
ALTER TABLE public.features ADD PRIMARY KEY (id, ts, tf, alignment_source);

DROP INDEX IF EXISTS idx_features_id_tf_ts;
CREATE INDEX IF NOT EXISTS idx_features_id_tf_as_ts
ON public.features (id, tf, alignment_source, ts DESC);

DROP INDEX IF EXISTS idx_features_asset_class;
CREATE INDEX IF NOT EXISTS idx_features_asset_class_as
ON public.features (asset_class, tf, alignment_source, ts DESC);
