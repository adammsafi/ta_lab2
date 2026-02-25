-- cmc_fills: Individual fill events for orders.
-- Each row is one execution event. An order may have 1..N fill rows.
-- Reference DDL -- actual migration is in alembic/versions/9e692eb7b762_order_fill_store.py

CREATE TABLE public.cmc_fills (
    fill_id           UUID        NOT NULL DEFAULT gen_random_uuid(),
    filled_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- FK to parent order
    order_id          UUID        NOT NULL,

    -- Fill details
    fill_qty          NUMERIC     NOT NULL,
    fill_price        NUMERIC     NOT NULL,
    fee_amount        NUMERIC     NOT NULL DEFAULT 0,
    fee_currency      TEXT,

    -- Routing
    side              TEXT        NOT NULL,
    exchange          TEXT        NOT NULL,

    -- External IDs
    exchange_fill_id  TEXT,

    -- Lot tracking for cost basis
    lot_id            UUID        NOT NULL DEFAULT gen_random_uuid(),

    CONSTRAINT pk_cmc_fills PRIMARY KEY (fill_id),

    CONSTRAINT fk_fills_order_id
        FOREIGN KEY (order_id) REFERENCES public.cmc_orders (order_id),

    CONSTRAINT chk_fills_side
        CHECK (side IN ('buy', 'sell')),
    CONSTRAINT chk_fills_qty_pos
        CHECK (fill_qty > 0),
    CONSTRAINT chk_fills_price_pos
        CHECK (fill_price > 0),
    CONSTRAINT chk_fills_fee_nn
        CHECK (fee_amount >= 0)
);

-- Query pattern: "all fills for an order sorted by time"
CREATE INDEX idx_fills_order_id
    ON public.cmc_fills (order_id, filled_at);

-- Partial index: exchange deduplication
CREATE INDEX idx_fills_exchange_fill
    ON public.cmc_fills (exchange_fill_id)
    WHERE exchange_fill_id IS NOT NULL;

-- Time-ordered access for recent fills
CREATE INDEX idx_fills_filled_at
    ON public.cmc_fills (filled_at DESC);

COMMENT ON TABLE public.cmc_fills IS
    'Individual fill events. One row per execution event; an order may have 1..N fill rows.';
