-- psr_results: Detailed Probabilistic Sharpe Ratio (PSR) formula outputs
--
-- Stores full formula inputs and outputs for PSR, Deflated Sharpe Ratio (DSR),
-- and Minimum Track Record Length (MinTRL) per backtest run.
-- One row per (run_id, formula_version) -- the unique constraint prevents
-- duplicate computations for the same run under the same formula.
--
-- NOTE: This file is reference DDL for documentation only.
--       The actual migration is managed by Alembic revision 5f8223cfbf06.
--       Do NOT execute this file directly in production -- use `alembic upgrade head`.

CREATE TABLE IF NOT EXISTS public.psr_results (
    result_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES public.cmc_backtest_runs(run_id) ON DELETE CASCADE,

    -- Formula identification
    formula_version     TEXT NOT NULL,              -- e.g. 'lopez_de_prado_v1'

    -- Primary outputs
    psr                 NUMERIC,                    -- Probabilistic Sharpe Ratio (0..1 probability)
    dsr                 NUMERIC,                    -- Deflated Sharpe Ratio (PSR adjusted for multiple testing)
    min_trl_bars        INTEGER,                    -- Minimum Track Record Length in bars
    min_trl_days        INTEGER,                    -- Minimum Track Record Length in calendar days

    -- Sharpe ratio inputs / intermediates
    sr_hat              NUMERIC,                    -- Observed/estimated Sharpe ratio (annualised)
    sr_star             NUMERIC,                    -- Benchmark Sharpe ratio used in PSR denominator
    n_obs               INTEGER,                    -- Number of return observations used

    -- Distributional moments (inputs to the PSR formula)
    skewness            NUMERIC,                    -- Third standardised moment of returns
    kurtosis_pearson    NUMERIC,                    -- Fourth standardised moment (Pearson, excess = kurtosis - 3)

    -- Return source flag
    return_source       TEXT,                       -- 'portfolio' | 'trade_reconstruction'

    -- Audit timestamp
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_psr_results_run_version UNIQUE (run_id, formula_version)
);

CREATE INDEX IF NOT EXISTS idx_psr_results_run_id
    ON public.psr_results(run_id);

COMMENT ON TABLE public.psr_results IS
'Detailed PSR/DSR/MinTRL formula outputs for each backtest run. '
'One row per (run_id, formula_version). Stores full audit trail of '
'distributional inputs (skewness, kurtosis) alongside computed probabilities.';

COMMENT ON COLUMN public.psr_results.formula_version IS
'Identifies the formula implementation used (e.g. ''lopez_de_prado_v1''). '
'Allows multiple formula variants to coexist for the same run.';

COMMENT ON COLUMN public.psr_results.psr IS
'Probabilistic Sharpe Ratio: probability that the true SR >= sr_star '
'given observed sr_hat, n_obs, skewness and kurtosis. Range: [0, 1].';

COMMENT ON COLUMN public.psr_results.dsr IS
'Deflated Sharpe Ratio: PSR adjusted for the expected maximum SR across '
'multiple strategy trials (multiple-testing correction). Range: [0, 1].';

COMMENT ON COLUMN public.psr_results.min_trl_bars IS
'Minimum Track Record Length (bars) for PSR >= 0.95 at the observed SR.';

COMMENT ON COLUMN public.psr_results.min_trl_days IS
'Minimum Track Record Length (calendar days) for PSR >= 0.95 at the observed SR.';

COMMENT ON COLUMN public.psr_results.sr_hat IS
'Annualised Sharpe ratio estimated from the backtest return series.';

COMMENT ON COLUMN public.psr_results.sr_star IS
'Benchmark Sharpe ratio (reference level) used as the threshold in PSR.';

COMMENT ON COLUMN public.psr_results.skewness IS
'Third standardised central moment of the backtest return distribution. '
'Negative skew (left tail) reduces PSR; positive skew increases it.';

COMMENT ON COLUMN public.psr_results.kurtosis_pearson IS
'Fourth standardised central moment (Pearson definition; normal = 3). '
'Excess kurtosis (fat tails) reduces PSR.';

COMMENT ON COLUMN public.psr_results.return_source IS
'Indicates whether returns were computed at portfolio level or reconstructed '
'from individual trade records. Affects distributional moment estimates.';
