-- cmc_order_dead_letter: Dead-letter queue for failed OMS operations.
-- Captures operations that threw exceptions with payload and error context for retry.
-- Reference DDL -- actual migration is in alembic/versions/9e692eb7b762_order_fill_store.py

CREATE TABLE public.cmc_order_dead_letter (
    dlq_id             UUID        NOT NULL DEFAULT gen_random_uuid(),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Operation metadata
    operation_type     TEXT        NOT NULL,

    -- Optional links to affected records
    order_id           UUID,
    fill_id            UUID,

    -- Payload stored as TEXT (not JSONB) for lossless error capture
    payload            TEXT        NOT NULL,

    -- Error details
    error_reason       TEXT        NOT NULL,
    error_stacktrace   TEXT,

    -- Retry state
    status             TEXT        NOT NULL DEFAULT 'pending',
    retry_count        INTEGER     NOT NULL DEFAULT 0,
    retry_after        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT pk_cmc_order_dead_letter PRIMARY KEY (dlq_id),

    CONSTRAINT chk_dlq_operation
        CHECK (operation_type IN ('process_fill', 'promote_order',
                                  'update_position', 'other')),
    CONSTRAINT chk_dlq_status
        CHECK (status IN ('pending', 'retrying', 'succeeded', 'abandoned'))
);

-- Query pattern: "next pending items ready for retry"
CREATE INDEX idx_dlq_status_retry
    ON public.cmc_order_dead_letter (status, retry_after)
    WHERE status = 'pending';

-- Partial index: look up DLQ entries by related order
CREATE INDEX idx_dlq_order_id
    ON public.cmc_order_dead_letter (order_id)
    WHERE order_id IS NOT NULL;

-- Time-ordered access for recent failures
CREATE INDEX idx_dlq_created_at
    ON public.cmc_order_dead_letter (created_at DESC);

COMMENT ON TABLE public.cmc_order_dead_letter IS
    'Dead-letter queue for failed OMS operations. Payload stored as TEXT for lossless error capture. '
    'Retry logic reads pending rows where retry_after <= now().';
