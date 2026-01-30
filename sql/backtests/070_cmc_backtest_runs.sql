-- cmc_backtest_runs: Backtest run metadata
--
-- Stores metadata for each backtest run including configuration, date range,
-- versioning, and summary metrics. Links to detailed trades and metrics tables.
-- Supports reproducibility validation via feature and parameter hashing.

CREATE TABLE IF NOT EXISTS public.cmc_backtest_runs (
    run_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    signal_type         TEXT NOT NULL,          -- 'ema_crossover', 'rsi_mean_revert', 'atr_breakout'
    signal_id           INTEGER NOT NULL,       -- FK to dim_signals
    asset_id            INTEGER NOT NULL,       -- Asset backtested

    -- Date range
    start_ts            TIMESTAMPTZ NOT NULL,
    end_ts              TIMESTAMPTZ NOT NULL,

    -- Configuration
    cost_model          JSONB NOT NULL,         -- {fee_bps, slippage_bps, funding_bps_day}
    signal_params_hash  TEXT NOT NULL,          -- Hash of signal params for caching
    feature_hash        TEXT,                   -- Hash of features at run time

    -- Versioning for reproducibility
    signal_version      TEXT NOT NULL,
    vbt_version         TEXT NOT NULL,
    run_timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Results summary
    total_return        NUMERIC,
    sharpe_ratio        NUMERIC,
    max_drawdown        NUMERIC,
    trade_count         INTEGER,

    created_at          TIMESTAMPTZ DEFAULT now(),

    FOREIGN KEY (signal_id) REFERENCES public.dim_signals(signal_id)
);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_signal
    ON public.cmc_backtest_runs(signal_type, signal_id);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_asset
    ON public.cmc_backtest_runs(asset_id);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_params_hash
    ON public.cmc_backtest_runs(signal_params_hash);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_timestamp
    ON public.cmc_backtest_runs(run_timestamp DESC);

COMMENT ON TABLE public.cmc_backtest_runs IS
'Backtest run metadata with configuration, versioning, and summary metrics. Each run represents a single signal strategy backtest on one asset over a date range.';

COMMENT ON COLUMN public.cmc_backtest_runs.cost_model IS
'JSON cost configuration: {fee_bps, slippage_bps, funding_bps_day}. Enables clean vs realistic PnL comparison.';

COMMENT ON COLUMN public.cmc_backtest_runs.signal_params_hash IS
'SHA256 hash of signal parameters from dim_signals. Enables caching and change detection.';

COMMENT ON COLUMN public.cmc_backtest_runs.feature_hash IS
'SHA256 hash of feature data used in backtest. Enables reproducibility validation.';
