-- positions: Current position per (asset, exchange).
-- Updated on each fill via compute_position_update() (Phase 44-02).
-- Reference DDL -- actual migration is in alembic/versions/9e692eb7b762_order_fill_store.py

CREATE TABLE public.positions (
    -- Composite PK: one position per asset per exchange
    asset_id             INTEGER     NOT NULL,
    exchange             TEXT        NOT NULL,

    -- Position state
    quantity             NUMERIC     NOT NULL DEFAULT 0,
    avg_cost_basis       NUMERIC     NOT NULL DEFAULT 0,

    -- PnL tracking
    realized_pnl         NUMERIC     NOT NULL DEFAULT 0,
    unrealized_pnl       NUMERIC,
    unrealized_pnl_pct   NUMERIC,

    -- Mark price (updated by mark_to_market)
    last_mark_price      NUMERIC,
    last_mark_ts         TIMESTAMPTZ,

    -- Audit linkage
    last_fill_id         UUID,
    last_updated         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_positions PRIMARY KEY (asset_id, exchange),

    -- exchange values: 'aggregate' reserved for v_positions_agg view
    CONSTRAINT chk_positions_exchange
        CHECK (exchange IN ('coinbase', 'kraken', 'paper', 'aggregate'))
);

-- Lookup by asset across all exchanges
CREATE INDEX idx_positions_asset
    ON public.positions (asset_id);

COMMENT ON TABLE public.positions IS
    'Current position per (asset_id, exchange). Updated on each fill. '
    'Composite PK enforces one-row-per-asset-per-exchange invariant.';
