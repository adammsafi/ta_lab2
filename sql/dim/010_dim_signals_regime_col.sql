-- Add regime_enabled flag to dim_signals
--
-- When FALSE, regime filtering and position sizing are bypassed for this signal.
-- Allows per-signal opt-out from regime logic without code changes.
-- Defaults to TRUE so all existing signals are regime-aware on next refresh.

ALTER TABLE public.dim_signals
    ADD COLUMN IF NOT EXISTS regime_enabled BOOLEAN DEFAULT TRUE;

COMMENT ON COLUMN public.dim_signals.regime_enabled IS
'If FALSE, regime filtering/sizing is skipped for this signal. Defaults TRUE so existing signals participate in regime-aware execution.';
