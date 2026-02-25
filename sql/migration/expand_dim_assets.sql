-- Expand dim_assets for multi-source, multi-asset-class support
-- Adds columns for name, data_source tracking, and timestamps
-- Creates ID sequence starting at 100001 to avoid CMC ID collisions

ALTER TABLE public.dim_assets
  ADD COLUMN IF NOT EXISTS name TEXT,
  ADD COLUMN IF NOT EXISTS data_source TEXT DEFAULT 'CMC',
  ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW(),
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

-- Sequence for auto-assigning IDs to new (non-CMC) assets
-- CMC IDs max out around 28301; starting at 100001 avoids collisions
CREATE SEQUENCE IF NOT EXISTS dim_assets_id_seq START WITH 100001;

-- Index for fast lookups by symbol + asset_class
CREATE INDEX IF NOT EXISTS ix_dim_assets_symbol_class
  ON public.dim_assets (symbol, asset_class);
