-- strategy_parity: Live vs backtest Sharpe ratio comparison
--
-- Compares live executor performance (fill-based and MTM) against backtest
-- Sharpe ratios over rolling windows. Used to detect performance decay
-- and trigger investigation alerts when parity ratios drop below thresholds.
--
-- Populated by: scripts/executor/compute_strategy_parity.py (Phase 96)
-- Alert threshold: ratio_fill < 0.8 or ratio_mtm < 0.8 triggers Telegram alert
--
-- Reference DDL -- actual migration is in alembic/versions/o9p0q1r2s3t4_phase96_executor_activation.py

CREATE TABLE IF NOT EXISTS public.strategy_parity (
    parity_id           SERIAL          PRIMARY KEY,
    computed_at         TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- Strategy identifier (config_name from dim_executor_config)
    strategy            TEXT            NOT NULL,

    -- Rolling window in calendar days
    window_days         INTEGER         NOT NULL,

    -- Live performance: fill-based (actual trade PnL) vs MTM (mark-to-market)
    live_sharpe_fill    NUMERIC,
    live_sharpe_mtm     NUMERIC,

    -- Backtest reference Sharpe (from backtest_metrics for same strategy)
    bt_sharpe           NUMERIC,

    -- Parity ratios: live / backtest (target >= 0.8)
    ratio_fill          NUMERIC,
    ratio_mtm           NUMERIC,

    -- Sample sizes
    n_fills             INTEGER,    -- Number of closed fills in window
    n_mtm_days          INTEGER     -- Number of MTM observation days in window
);

-- Fast lookup: most recent parity per strategy
CREATE INDEX IF NOT EXISTS idx_strategy_parity_strategy_ts
    ON public.strategy_parity (strategy, computed_at DESC);

COMMENT ON TABLE public.strategy_parity IS
'Live vs backtest Sharpe ratio comparison per strategy and rolling window. '
'ratio_fill = live_sharpe_fill / bt_sharpe; target >= 0.8. '
'Triggers investigation alert when ratio drops below threshold.';

COMMENT ON COLUMN public.strategy_parity.strategy IS
'Strategy config_name from dim_executor_config, e.g. ema_trend_17_77_paper_v1';

COMMENT ON COLUMN public.strategy_parity.window_days IS
'Rolling evaluation window in calendar days (e.g. 30, 90, 180)';

COMMENT ON COLUMN public.strategy_parity.ratio_fill IS
'live_sharpe_fill / bt_sharpe -- parity ratio for fill-based live performance';

COMMENT ON COLUMN public.strategy_parity.ratio_mtm IS
'live_sharpe_mtm / bt_sharpe -- parity ratio for mark-to-market live performance';
