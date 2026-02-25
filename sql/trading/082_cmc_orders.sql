-- cmc_orders: Master order record for the paper trading OMS.
-- Each row represents one order's full lifecycle from creation to terminal state.
-- Reference DDL -- actual migration is in alembic/versions/9e692eb7b762_order_fill_store.py

CREATE TABLE public.cmc_orders (
    order_id           UUID        NOT NULL DEFAULT gen_random_uuid(),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Source linkage
    paper_order_uuid   UUID,
    signal_id          INTEGER,

    -- Asset and routing
    asset_id           INTEGER     NOT NULL,
    pair               TEXT        NOT NULL,
    exchange           TEXT        NOT NULL,

    -- Order specification
    side               TEXT        NOT NULL,
    order_type         TEXT        NOT NULL,
    quantity           NUMERIC     NOT NULL,
    limit_price        NUMERIC,
    stop_price         NUMERIC,
    time_in_force      TEXT,
    expires_at         TIMESTAMPTZ,

    -- Order state
    status             TEXT        NOT NULL DEFAULT 'created',
    filled_qty         NUMERIC     NOT NULL DEFAULT 0,
    remaining_qty      NUMERIC     NOT NULL,
    avg_fill_price     NUMERIC,

    -- Environment and external IDs
    environment        TEXT        NOT NULL DEFAULT 'sandbox',
    client_order_id    TEXT,
    exchange_order_id  TEXT,

    CONSTRAINT pk_cmc_orders PRIMARY KEY (order_id),

    -- Validation constraints
    CONSTRAINT chk_orders_side
        CHECK (side IN ('buy', 'sell')),
    CONSTRAINT chk_orders_order_type
        CHECK (order_type IN ('market', 'limit', 'stop')),
    CONSTRAINT chk_orders_status
        CHECK (status IN ('created', 'submitted', 'partial_fill', 'filled',
                          'cancelled', 'rejected', 'expired')),
    CONSTRAINT chk_orders_tif
        CHECK (time_in_force IS NULL OR time_in_force IN ('GTC', 'GTD', 'IOC')),
    CONSTRAINT chk_orders_environment
        CHECK (environment IN ('sandbox', 'production')),
    CONSTRAINT chk_orders_quantity_pos
        CHECK (quantity > 0),
    CONSTRAINT chk_orders_remaining_nn
        CHECK (remaining_qty >= 0)
);

-- Query pattern: "show all open orders for asset X sorted by time"
CREATE INDEX idx_orders_asset_status
    ON public.cmc_orders (asset_id, status, created_at DESC);

-- Partial index: link orders back to signal that triggered them
CREATE INDEX idx_orders_signal
    ON public.cmc_orders (signal_id)
    WHERE signal_id IS NOT NULL;

-- Partial index: cross-reference paper order registry
CREATE INDEX idx_orders_paper_order
    ON public.cmc_orders (paper_order_uuid)
    WHERE paper_order_uuid IS NOT NULL;

-- Partial index: deduplication against exchange ack
CREATE INDEX idx_orders_exchange_order
    ON public.cmc_orders (exchange_order_id)
    WHERE exchange_order_id IS NOT NULL;

COMMENT ON TABLE public.cmc_orders IS
    'Master order record. One row per order lifecycle from creation to terminal state.';
