-- =============================================================================
-- File: sql/snapshots/20251213__bars_snapshots.sql
-- Purpose:
--   Snapshot / checkpoint helpers for 2025-12-13.
--
-- Philosophy:
--   - Snapshot tables are immutable checkpoints you can diff against later.
--   - Keep snapshot creation statements together so “what did we freeze?” is obvious.
-- =============================================================================

-- -----------------------------------------------------------------------------
-- Snapshot: cmc_price_bars_multi_tf
-- -----------------------------------------------------------------------------
CREATE TABLE public.cmc_price_bars_multi_tf_snapshot_20251213
AS
SELECT *
FROM public.cmc_price_bars_multi_tf;

-- Add a primary key so joins/diffs are fast and semantics match “real” table.
ALTER TABLE public.cmc_price_bars_multi_tf_snapshot_20251213
  ADD CONSTRAINT cmc_price_bars_multi_tf_snapshot_20251213_pkey
  PRIMARY KEY (id, tf, bar_seq);

-- -----------------------------------------------------------------------------
-- Snapshot: cmc_price_bars_multi_tf_cal_anchor_iso
-- -----------------------------------------------------------------------------
CREATE TABLE public.cmc_price_bars_multi_tf_cal_anchor_iso_snapshot_20251213
AS
SELECT *
FROM public.cmc_price_bars_multi_tf_cal_anchor_iso;

-- -----------------------------------------------------------------------------
-- OPTIONAL: truncate helpers (dangerous)
-- -----------------------------------------------------------------------------
-- Use these only when you are intentionally resetting tables to rebuild.
-- Consider wrapping in a transaction when running interactively.

-- TRUNCATE public.cmc_price_bars_multi_tf_cal_anchor_iso;
-- TRUNCATE public.cmc_price_bars_multi_tf_cal_iso;
-- TRUNCATE TABLE public.cmc_price_bars_multi_tf;
