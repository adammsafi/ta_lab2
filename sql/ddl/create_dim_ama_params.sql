-- create_dim_ama_params.sql
-- Creates:
--   public.dim_ama_params (AMA parameter lookup table)
--
-- Maps params_hash -> human-readable parameter values.
-- Populated when an AMA indicator+params combination is first computed.
--
-- PK: (indicator, params_hash)
-- Example rows:
--   ('KAMA', 'kama_10_2_30', '{"er_period":10,"fast":2,"slow":30}', 'KAMA canonical')
--   ('KAMA', 'kama_5_2_15',  '{"er_period":5,"fast":2,"slow":15}',  'KAMA fast')
--   ('DEMA', 'dema_21',      '{"period":21}',                        'DEMA 21')
--   ('HMA',  'hma_50',       '{"period":50}',                        'HMA 50')

BEGIN;

CREATE TABLE IF NOT EXISTS public.dim_ama_params (
    indicator   text        NOT NULL,
    params_hash text        NOT NULL,
    params_json jsonb       NOT NULL,
    label       text,
    created_at  timestamptz NOT NULL DEFAULT now(),

    PRIMARY KEY (indicator, params_hash)
);

-- Allow queries like: SELECT * FROM dim_ama_params WHERE indicator = 'KAMA'
CREATE INDEX IF NOT EXISTS ix_dim_ama_params_indicator
ON public.dim_ama_params (indicator);

COMMIT;
