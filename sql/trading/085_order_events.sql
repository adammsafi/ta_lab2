-- order_events: Immutable audit trail of order state machine transitions.
-- One row per status change. Never updated, only inserted.
-- Reference DDL -- actual migration is in alembic/versions/9e692eb7b762_order_fill_store.py

CREATE TABLE public.order_events (
    event_id     UUID        NOT NULL DEFAULT gen_random_uuid(),
    event_ts     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- FK to order being tracked
    order_id     UUID        NOT NULL,

    -- State transition
    from_status  TEXT,         -- NULL for initial 'created' event
    to_status    TEXT        NOT NULL,

    -- Optional context
    reason       TEXT,
    fill_id      UUID,         -- set when transition triggered by a fill

    CONSTRAINT pk_order_events PRIMARY KEY (event_id),

    CONSTRAINT fk_events_order_id
        FOREIGN KEY (order_id) REFERENCES public.orders (order_id),

    -- Validates the same 7 statuses as chk_orders_status
    CONSTRAINT chk_events_to_status
        CHECK (to_status IN ('created', 'submitted', 'partial_fill', 'filled',
                             'cancelled', 'rejected', 'expired'))
);

-- Query pattern: "full history for an order in chronological order"
CREATE INDEX idx_events_order_id
    ON public.order_events (order_id, event_ts);

-- Time-ordered access for recent events
CREATE INDEX idx_events_ts
    ON public.order_events (event_ts DESC);

COMMENT ON TABLE public.order_events IS
    'Immutable audit trail of order state machine transitions. '
    'One row per status change. Never updated, only appended.';
