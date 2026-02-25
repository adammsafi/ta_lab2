-- cmc_risk_overrides: Discretionary position override store.
-- Supports sticky (persist across signals) and non-sticky (apply once) overrides.
-- Full audit trail: reverted_at/revert_reason track override lifecycle.
-- Reference DDL -- actual migration is in alembic/versions/b5178d671e38_risk_controls.py

CREATE TABLE public.cmc_risk_overrides (
    override_id     UUID        NOT NULL DEFAULT gen_random_uuid(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Scope: which asset and strategy this override applies to
    asset_id        INTEGER     NOT NULL,
    strategy_id     INTEGER     NOT NULL,

    -- Who created it and why
    operator        TEXT        NOT NULL,
    reason          TEXT        NOT NULL,

    -- What the system wanted to do and what the operator decided instead
    system_signal   TEXT        NOT NULL,
    override_action TEXT        NOT NULL,

    -- Sticky overrides persist beyond a single signal evaluation
    sticky          BOOLEAN     NOT NULL DEFAULT FALSE,

    -- Application and reversal audit trail
    applied_at      TIMESTAMPTZ,
    reverted_at     TIMESTAMPTZ,
    revert_reason   TEXT,

    CONSTRAINT pk_cmc_risk_overrides PRIMARY KEY (override_id)
);

COMMENT ON TABLE public.cmc_risk_overrides IS
    'Discretionary position overrides with sticky/non-sticky support. Full audit trail.';

-- Query pattern: "find active (non-reverted) overrides for asset+strategy"
CREATE INDEX idx_overrides_active
    ON public.cmc_risk_overrides (asset_id, strategy_id)
    WHERE reverted_at IS NULL;
