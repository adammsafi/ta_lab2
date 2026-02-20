-- Add regime_key column to all 3 signal tables
--
-- regime_key records the active market regime at signal entry time.
-- NULL means regime was not computed when the signal was generated.
-- Idempotent: ADD COLUMN IF NOT EXISTS is safe to re-run.

ALTER TABLE public.cmc_signals_ema_crossover
    ADD COLUMN IF NOT EXISTS regime_key TEXT;

ALTER TABLE public.cmc_signals_rsi_mean_revert
    ADD COLUMN IF NOT EXISTS regime_key TEXT;

ALTER TABLE public.cmc_signals_atr_breakout
    ADD COLUMN IF NOT EXISTS regime_key TEXT;

COMMENT ON COLUMN public.cmc_signals_ema_crossover.regime_key IS
'Active regime at signal entry time. NULL if regime not computed. Matches regime_key in cmc_regimes.';

COMMENT ON COLUMN public.cmc_signals_rsi_mean_revert.regime_key IS
'Active regime at signal entry time. NULL if regime not computed. Matches regime_key in cmc_regimes.';

COMMENT ON COLUMN public.cmc_signals_atr_breakout.regime_key IS
'Active regime at signal entry time. NULL if regime not computed. Matches regime_key in cmc_regimes.';
