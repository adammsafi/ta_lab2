-- dim_risk_state: Single-row live state for kill switch and circuit breaker.
-- The CHECK(state_id=1) constraint enforces that only one row can ever exist.
-- Reference DDL -- actual migration is in alembic/versions/b5178d671e38_risk_controls.py

CREATE TABLE public.dim_risk_state (
    state_id                        INTEGER     NOT NULL DEFAULT 1,
    trading_state                   TEXT        NOT NULL DEFAULT 'active',

    -- Kill switch audit columns (populated when halted)
    halted_at                       TIMESTAMPTZ,
    halted_reason                   TEXT,
    halted_by                       TEXT,

    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Daily loss tracking
    day_open_portfolio_value        NUMERIC,
    last_day_open_date              DATE,

    -- Per-asset/strategy circuit breaker state (JSON stored as TEXT)
    -- cb_consecutive_losses: {"asset_id:strategy_id": <count>}
    cb_consecutive_losses           TEXT        NOT NULL DEFAULT '{}',
    -- cb_breaker_tripped_at: {"asset_id:strategy_id": "<iso-timestamp>"}
    cb_breaker_tripped_at           TEXT        NOT NULL DEFAULT '{}',

    -- Portfolio-level circuit breaker state
    cb_portfolio_consecutive_losses INTEGER     NOT NULL DEFAULT 0,
    cb_portfolio_breaker_tripped_at TIMESTAMPTZ,

    CONSTRAINT pk_dim_risk_state PRIMARY KEY (state_id),

    -- Valid state values
    CONSTRAINT chk_risk_state_trading
        CHECK (trading_state IN ('active', 'halted')),

    -- Enforce single-row invariant
    CONSTRAINT chk_risk_state_single
        CHECK (state_id = 1)
);

COMMENT ON TABLE public.dim_risk_state IS
    'Single-row live state table for kill switch and circuit breaker. Enforced single-row via CHECK(state_id=1).';

-- Seed the single required row
INSERT INTO public.dim_risk_state (state_id)
VALUES (1)
ON CONFLICT (state_id) DO NOTHING;
