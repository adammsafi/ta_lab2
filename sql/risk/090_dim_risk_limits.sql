-- dim_risk_limits: Runtime-editable risk limit configuration.
-- NULL asset_id/strategy_id means the row applies portfolio-wide.
-- Reference DDL -- actual migration is in alembic/versions/b5178d671e38_risk_controls.py

CREATE TABLE public.dim_risk_limits (
    limit_id                    SERIAL      NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Scope: NULL = portfolio-wide; non-NULL = asset or strategy specific
    asset_id                    INTEGER,
    strategy_id                 INTEGER,

    -- Position sizing caps
    max_position_pct            NUMERIC     NOT NULL DEFAULT 0.15,
    max_portfolio_pct           NUMERIC     NOT NULL DEFAULT 0.80,

    -- Daily loss stop
    daily_loss_pct_threshold    NUMERIC     NOT NULL DEFAULT 0.03,

    -- Circuit breaker configuration
    cb_consecutive_losses_n     INTEGER     NOT NULL DEFAULT 3,
    cb_loss_threshold_pct       NUMERIC     NOT NULL DEFAULT 0.0,
    cb_cooldown_hours           NUMERIC     NOT NULL DEFAULT 24.0,

    -- Override policy
    allow_overrides             BOOLEAN     NOT NULL DEFAULT TRUE,

    CONSTRAINT pk_dim_risk_limits PRIMARY KEY (limit_id),

    -- Value range constraints
    CONSTRAINT chk_risk_limits_max_pos
        CHECK (max_position_pct > 0 AND max_position_pct <= 1),
    CONSTRAINT chk_risk_limits_max_port
        CHECK (max_portfolio_pct > 0 AND max_portfolio_pct <= 1),
    CONSTRAINT chk_risk_limits_daily
        CHECK (daily_loss_pct_threshold > 0 AND daily_loss_pct_threshold <= 1),
    CONSTRAINT chk_risk_limits_n
        CHECK (cb_consecutive_losses_n >= 1),
    CONSTRAINT chk_risk_limits_cooldown
        CHECK (cb_cooldown_hours >= 0)
);

COMMENT ON TABLE public.dim_risk_limits IS
    'Runtime-editable risk limit configuration. NULL asset_id/strategy_id = portfolio-wide defaults.';

-- Seed portfolio-wide default row
INSERT INTO public.dim_risk_limits (asset_id, strategy_id)
VALUES (NULL, NULL);
