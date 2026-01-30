-- cmc_backtest_trades: Individual backtest trade records
--
-- Stores every trade executed during a backtest run.
-- Links to parent backtest run via run_id foreign key.
-- Tracks entry/exit details, position sizing, PnL, and transaction costs.

CREATE TABLE IF NOT EXISTS public.cmc_backtest_trades (
    trade_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES public.cmc_backtest_runs(run_id) ON DELETE CASCADE,

    -- Trade details
    entry_ts            TIMESTAMPTZ NOT NULL,
    entry_price         NUMERIC NOT NULL,
    exit_ts             TIMESTAMPTZ,
    exit_price          NUMERIC,
    direction           TEXT NOT NULL,          -- 'long', 'short'
    size                NUMERIC,                -- Position size (shares/contracts)

    -- Results
    pnl_pct             NUMERIC,                -- Percentage PnL
    pnl_dollars         NUMERIC,                -- Dollar PnL

    -- Costs
    fees_paid           NUMERIC,                -- Total commission fees
    slippage_cost       NUMERIC,                -- Slippage cost

    created_at          TIMESTAMPTZ DEFAULT now(),

    CHECK (direction IN ('long', 'short'))
);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run
    ON public.cmc_backtest_trades(run_id);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_entry_ts
    ON public.cmc_backtest_trades(entry_ts);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_direction
    ON public.cmc_backtest_trades(direction);

COMMENT ON TABLE public.cmc_backtest_trades IS
'Individual trade records from backtest execution. Each row is one complete trade (entry + exit) with PnL and costs.';

COMMENT ON COLUMN public.cmc_backtest_trades.size IS
'Position size in asset units. NULL for fixed percentage sizing.';

COMMENT ON COLUMN public.cmc_backtest_trades.pnl_pct IS
'Percentage return: (exit - entry) / entry for long, (entry - exit) / entry for short.';
