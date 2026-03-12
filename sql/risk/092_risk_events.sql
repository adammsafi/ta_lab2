-- risk_events: Immutable audit log for all risk control events.
-- Rows must never be deleted. All risk actions leave a permanent record here.
-- Reference DDL -- actual migration is in alembic/versions/b5178d671e38_risk_controls.py

CREATE TABLE public.risk_events (
    event_id        UUID        NOT NULL DEFAULT gen_random_uuid(),
    event_ts        TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Event classification
    event_type      TEXT        NOT NULL,
    trigger_source  TEXT        NOT NULL,

    -- Human-readable context
    reason          TEXT        NOT NULL,
    operator        TEXT,

    -- Optional scope (NULL = portfolio-wide event)
    asset_id        INTEGER,
    strategy_id     INTEGER,

    -- Optional linkage to related records
    order_id        UUID,
    override_id     UUID,

    -- Arbitrary JSON payload stored as TEXT
    metadata        TEXT,

    CONSTRAINT pk_risk_events PRIMARY KEY (event_id),

    -- Valid event types
    CONSTRAINT chk_risk_events_type
        CHECK (event_type IN (
            'kill_switch_activated',
            'kill_switch_disabled',
            'position_cap_scaled',
            'position_cap_blocked',
            'daily_loss_stop_triggered',
            'circuit_breaker_tripped',
            'circuit_breaker_reset',
            'override_created',
            'override_applied',
            'override_reverted'
        )),

    -- Valid trigger sources
    CONSTRAINT chk_risk_events_source
        CHECK (trigger_source IN ('manual', 'daily_loss_stop', 'circuit_breaker', 'system'))
);

COMMENT ON TABLE public.risk_events IS
    'Immutable audit log for all risk control events. Never DELETE rows.';

-- Query pattern: "show recent risk events sorted by time"
CREATE INDEX idx_risk_events_ts
    ON public.risk_events (event_ts DESC);

-- Query pattern: "show all kill switch activations"
CREATE INDEX idx_risk_events_type
    ON public.risk_events (event_type, event_ts DESC);

-- Query pattern: "show all risk events for asset X" (partial: skips NULL asset rows)
CREATE INDEX idx_risk_events_asset
    ON public.risk_events (asset_id, event_ts DESC)
    WHERE asset_id IS NOT NULL;
