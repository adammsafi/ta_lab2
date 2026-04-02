-- pnl_attribution: Alpha/beta PnL decomposition
--
-- Decomposes realized PnL into systematic (beta) and idiosyncratic (alpha)
-- components relative to a benchmark. Enables attribution of returns to
-- factor exposure vs actual edge.
--
-- asset_class: 'crypto' (spot), 'perp' (perpetual futures), 'all' (combined)
-- benchmark: 'BTC' (bitcoin), 'SPX' (S&P 500), 'underlying' (asset itself), 'blended'
--
-- Populated by: scripts/executor/compute_pnl_attribution.py (Phase 96)
--
-- Reference DDL -- actual migration is in alembic/versions/o9p0q1r2s3t4_phase96_executor_activation.py

CREATE TABLE IF NOT EXISTS public.pnl_attribution (
    attr_id         SERIAL          PRIMARY KEY,
    computed_at     TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- Attribution period (inclusive)
    period_start    DATE            NOT NULL,
    period_end      DATE            NOT NULL,

    -- Scope
    asset_class     TEXT            NOT NULL,   -- 'crypto', 'perp', 'all'
    benchmark       TEXT            NOT NULL,   -- 'BTC', 'SPX', 'underlying', 'blended'

    -- PnL decomposition (in portfolio basis points or pct)
    total_pnl       NUMERIC,        -- Total realized PnL over period
    beta_pnl        NUMERIC,        -- Systematic component: beta * benchmark_return
    alpha_pnl       NUMERIC,        -- Idiosyncratic component: total_pnl - beta_pnl

    -- Risk-adjusted alpha
    beta            NUMERIC,        -- OLS beta vs benchmark over period
    sharpe_alpha    NUMERIC,        -- Sharpe ratio of alpha_pnl series

    -- Sample size
    n_positions     INTEGER         -- Number of closed positions in period
);

-- Fast lookup by period and asset class
CREATE INDEX IF NOT EXISTS idx_pnl_attribution_period
    ON public.pnl_attribution (period_start, period_end, asset_class);

COMMENT ON TABLE public.pnl_attribution IS
'Alpha/beta PnL decomposition against benchmarks. '
'Separates systematic beta exposure from idiosyncratic alpha over calendar periods.';

COMMENT ON COLUMN public.pnl_attribution.asset_class IS
'Scope of attribution: crypto (spot), perp (perpetual futures), all (combined)';

COMMENT ON COLUMN public.pnl_attribution.benchmark IS
'Benchmark for beta computation: BTC, SPX (via FRED), underlying (each asset vs itself), blended';

COMMENT ON COLUMN public.pnl_attribution.alpha_pnl IS
'Idiosyncratic PnL component: total_pnl - beta * benchmark_return. Core edge measure.';

COMMENT ON COLUMN public.pnl_attribution.sharpe_alpha IS
'Sharpe ratio of daily alpha_pnl time series over the period. Measures quality of edge.';
