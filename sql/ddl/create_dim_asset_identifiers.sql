-- Cross-reference table for external asset identifiers
-- Maps dim_assets.id to external IDs: CMC, CUSIP, FIGI, ISIN, etc.
-- Supports time-varying identifiers (valid_from/valid_to) for cases
-- like CUSIP changes during corporate actions.

CREATE TABLE IF NOT EXISTS public.dim_asset_identifiers (
    id          INTEGER       NOT NULL,
    id_type     TEXT          NOT NULL,
    id_value    TEXT          NOT NULL,
    is_primary  BOOLEAN       DEFAULT FALSE,
    valid_from  DATE,
    valid_to    DATE,
    created_at  TIMESTAMPTZ   DEFAULT NOW(),
    PRIMARY KEY (id, id_type, id_value),
    CONSTRAINT fk_dim_asset_identifiers_asset
        FOREIGN KEY (id) REFERENCES public.dim_assets(id)
);

-- Fast lookup by external identifier
CREATE INDEX IF NOT EXISTS ix_dai_type_value
  ON public.dim_asset_identifiers (id_type, id_value);
