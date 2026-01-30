-- cmc_backtest_metrics: Comprehensive backtest performance metrics
--
-- Stores detailed performance metrics for each backtest run.
-- Links to parent backtest run via run_id foreign key.
-- Includes return metrics, risk-adjusted metrics, drawdown stats, and trade statistics.

CREATE TABLE IF NOT EXISTS public.cmc_backtest_metrics (
    metric_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES public.cmc_backtest_runs(run_id) ON DELETE CASCADE,

    -- Return metrics
    total_return        NUMERIC,                -- Total return over backtest period
    cagr                NUMERIC,                -- Compound annual growth rate

    -- Risk-adjusted metrics
    sharpe_ratio        NUMERIC,                -- Sharpe ratio (annualized)
    sortino_ratio       NUMERIC,                -- Sortino ratio (downside deviation)
    calmar_ratio        NUMERIC,                -- Calmar ratio (CAGR / max drawdown)

    -- Drawdown metrics
    max_drawdown        NUMERIC,                -- Maximum drawdown (negative percentage)
    max_drawdown_duration_days INTEGER,         -- Longest drawdown period in days

    -- Trade statistics
    trade_count         INTEGER,                -- Total number of trades
    win_rate            NUMERIC,                -- Percentage of winning trades
    profit_factor       NUMERIC,                -- Gross profit / gross loss
    avg_win             NUMERIC,                -- Average winning trade (percentage)
    avg_loss            NUMERIC,                -- Average losing trade (percentage)
    avg_holding_period_days NUMERIC,            -- Average days in position

    -- Risk metrics
    var_95              NUMERIC,                -- Value at Risk 95% (daily)
    expected_shortfall  NUMERIC,                -- CVaR (Conditional Value at Risk)

    created_at          TIMESTAMPTZ DEFAULT now(),

    CONSTRAINT unique_run_metrics UNIQUE (run_id)
);

CREATE INDEX IF NOT EXISTS idx_backtest_metrics_run
    ON public.cmc_backtest_metrics(run_id);

CREATE INDEX IF NOT EXISTS idx_backtest_metrics_sharpe
    ON public.cmc_backtest_metrics(sharpe_ratio DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS idx_backtest_metrics_calmar
    ON public.cmc_backtest_metrics(calmar_ratio DESC NULLS LAST);

COMMENT ON TABLE public.cmc_backtest_metrics IS
'Comprehensive performance metrics for backtest runs. One row per backtest run with detailed risk/return statistics.';

COMMENT ON COLUMN public.cmc_backtest_metrics.sharpe_ratio IS
'Annualized Sharpe ratio: (mean return - risk_free_rate) / std_dev * sqrt(periods_per_year).';

COMMENT ON COLUMN public.cmc_backtest_metrics.sortino_ratio IS
'Sortino ratio uses downside deviation instead of total volatility, penalizing downside risk more.';

COMMENT ON COLUMN public.cmc_backtest_metrics.calmar_ratio IS
'Calmar ratio: CAGR / abs(max_drawdown). Measures return per unit of downside risk.';

COMMENT ON COLUMN public.cmc_backtest_metrics.profit_factor IS
'Profit factor: sum(winning_trades) / sum(losing_trades). Values > 1 indicate profitable strategy.';

COMMENT ON COLUMN public.cmc_backtest_metrics.var_95 IS
'Value at Risk at 95% confidence: 5th percentile of daily returns distribution.';

COMMENT ON COLUMN public.cmc_backtest_metrics.expected_shortfall IS
'Expected Shortfall (CVaR): Mean of returns below VaR threshold. Tail risk measure.';
