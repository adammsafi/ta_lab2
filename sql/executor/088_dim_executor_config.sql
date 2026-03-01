-- dim_executor_config: Strategy execution parameters for the paper trade executor.
-- One row per active strategy configuration.
-- Reference DDL -- actual migration is in alembic/versions/225bf8646f03_paper_trade_executor.py

CREATE TABLE public.dim_executor_config (
    -- Surrogate primary key
    config_id               SERIAL          NOT NULL,

    -- Audit timestamps
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),

    -- Identity
    config_name             TEXT            NOT NULL,   -- unique human label
    signal_type             TEXT            NOT NULL,
    signal_id               INTEGER         NOT NULL,   -- FK to dim_signals.signal_id
    is_active               BOOLEAN         NOT NULL DEFAULT TRUE,

    -- Execution target
    exchange                TEXT            NOT NULL DEFAULT 'paper',
    environment             TEXT            NOT NULL DEFAULT 'sandbox',

    -- Position sizing
    sizing_mode             TEXT            NOT NULL DEFAULT 'fixed_fraction',
    position_fraction       NUMERIC         NOT NULL DEFAULT 0.10,
    max_position_fraction   NUMERIC         NOT NULL DEFAULT 0.20,
    initial_capital         NUMERIC         NOT NULL DEFAULT 100000,

    -- Fill simulation
    fill_price_mode         TEXT            NOT NULL DEFAULT 'next_bar_open',
    slippage_mode           TEXT            NOT NULL DEFAULT 'lognormal',
    slippage_base_bps       NUMERIC         NOT NULL DEFAULT 3.0,
    slippage_noise_sigma    NUMERIC         NOT NULL DEFAULT 0.5,
    volume_impact_factor    NUMERIC         NOT NULL DEFAULT 0.1,

    -- Execution quality simulation
    rejection_rate          NUMERIC         NOT NULL DEFAULT 0.0,
    partial_fill_rate       NUMERIC         NOT NULL DEFAULT 0.0,
    execution_delay_bars    INTEGER         NOT NULL DEFAULT 0,

    -- Incremental processing watermark
    last_processed_signal_ts TIMESTAMPTZ,

    -- Scheduling
    cadence_hours           NUMERIC         NOT NULL DEFAULT 26.0,

    CONSTRAINT pk_dim_executor_config    PRIMARY KEY (config_id),
    CONSTRAINT uq_exec_config_name       UNIQUE (config_name),

    CONSTRAINT chk_exec_config_signal_type
        CHECK (signal_type IN ('ema_crossover', 'rsi_mean_revert', 'atr_breakout')),
    CONSTRAINT chk_exec_config_exchange
        CHECK (exchange IN ('paper', 'coinbase', 'kraken')),
    CONSTRAINT chk_exec_config_environment
        CHECK (environment IN ('sandbox', 'production')),
    CONSTRAINT chk_exec_config_sizing_mode
        CHECK (sizing_mode IN ('fixed_fraction', 'regime_adjusted', 'signal_strength')),
    CONSTRAINT chk_exec_config_initial_capital
        CHECK (initial_capital > 0),
    CONSTRAINT chk_exec_config_position_fraction
        CHECK (position_fraction > 0 AND position_fraction <= 1),
    CONSTRAINT chk_exec_config_fill_price_mode
        CHECK (fill_price_mode IN ('next_bar_open', 'exchange_mid')),
    CONSTRAINT chk_exec_config_slippage_mode
        CHECK (slippage_mode IN ('zero', 'fixed', 'lognormal')),
    CONSTRAINT chk_exec_config_rejection_rate
        CHECK (rejection_rate >= 0 AND rejection_rate <= 1),
    CONSTRAINT chk_exec_config_partial_fill_rate
        CHECK (partial_fill_rate >= 0 AND partial_fill_rate <= 1)
);

-- Fast lookup of active configs
CREATE INDEX idx_exec_config_active
    ON public.dim_executor_config (config_id)
    WHERE is_active = TRUE;

-- Lookup by signal
CREATE INDEX idx_exec_config_signal
    ON public.dim_executor_config (signal_id);

COMMENT ON TABLE public.dim_executor_config IS
    'Strategy execution parameters for the paper trade executor. '
    'One row per named configuration. signal_id links to dim_signals.';

COMMENT ON COLUMN public.dim_executor_config.config_name IS
    'Unique human-readable identifier, e.g. ema_trend_17_77_paper_v1';
COMMENT ON COLUMN public.dim_executor_config.position_fraction IS
    'Fraction of total portfolio value to size each position (0 < f <= 1)';
COMMENT ON COLUMN public.dim_executor_config.cadence_hours IS
    'Minimum hours between executor runs for this config (default 26 = daily with drift tolerance)';
COMMENT ON COLUMN public.dim_executor_config.last_processed_signal_ts IS
    'Watermark: last signal timestamp processed; executor reads signals newer than this value';
