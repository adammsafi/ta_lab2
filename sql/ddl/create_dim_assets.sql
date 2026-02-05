-- Create dim_assets table from dim_sessions WHERE asset_class = 'CRYPTO'
-- Purpose: Define asset scope for baseline capture (Phase 25)
-- Pattern: CREATE TABLE AS SELECT with IF NOT EXISTS guard

CREATE TABLE IF NOT EXISTS public.dim_assets AS
SELECT DISTINCT id, asset_class, symbol
FROM public.dim_sessions
WHERE asset_class = 'CRYPTO'
ORDER BY id;

ALTER TABLE public.dim_assets
  ADD CONSTRAINT dim_assets_pkey PRIMARY KEY (id);
