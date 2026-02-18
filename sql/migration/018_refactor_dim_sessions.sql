ALTER TABLE public.dim_sessions
  DROP CONSTRAINT IF EXISTS dim_sessions_pk;

ALTER TABLE public.dim_sessions
  ADD CONSTRAINT dim_sessions_pk
  PRIMARY KEY (asset_class, region, asset_key_type, asset_key, session_type);


ALTER TABLE public.dim_sessions
  ADD CONSTRAINT dim_sessions_is24h_time_chk
  CHECK (
    (is_24h = TRUE  AND session_open_local IS NOT NULL AND session_close_local IS NOT NULL)
    OR
    (is_24h = FALSE AND session_open_local IS NOT NULL AND session_close_local IS NOT NULL)
  );

-- Optional: constrain session_type values (v1)
ALTER TABLE public.dim_sessions
  ADD CONSTRAINT dim_sessions_session_type_chk
  CHECK (session_type IN ('PRIMARY','PREMARKET','AFTERHOURS','MAINTENANCE'));


ALTER TABLE public.dim_sessions
  ADD COLUMN venue text COLLATE pg_catalog."default" NOT NULL DEFAULT 'UNKNOWN';

-- backfill from your current meaning
UPDATE public.dim_sessions
SET venue = region
WHERE venue = 'UNKNOWN';

-- later, you can repurpose region to true geography safely


ALTER TABLE public.dim_sessions
  DROP CONSTRAINT IF EXISTS dim_sessions_pk;

ALTER TABLE public.dim_sessions
  ADD CONSTRAINT dim_sessions_pk
  PRIMARY KEY (asset_class, region, venue, asset_key_type, asset_key, session_type);

BEGIN;

UPDATE public.dim_sessions
SET region = 'GLOBAL'
WHERE region = 'CMC';

COMMIT;

BEGIN;

UPDATE public.dim_sessions
SET session_open_local = '00:00:00',
    session_close_local = '00:00:00'
WHERE is_24h = TRUE;

COMMIT;

BEGIN;

UPDATE public.dim_sessions
SET venue = 'US_EQUITIES'
WHERE asset_class = 'EQ' AND venue = 'US';

COMMIT;


ALTER TABLE public.dim_sessions
  DROP CONSTRAINT IF EXISTS dim_sessions_pk;

ALTER TABLE public.dim_sessions
  ADD CONSTRAINT dim_sessions_pk
  PRIMARY KEY (asset_class, region, asset_key_type, asset_key, session_type);

SELECT region, venue, COUNT(*)
FROM public.dim_sessions
GROUP BY region, venue
ORDER BY region, venue;

ALTER TABLE public.dim_sessions
  ADD COLUMN IF NOT EXISTS asset_id bigint;

CREATE OR REPLACE VIEW public.vw_dim_sessions_primary AS
SELECT *
FROM public.dim_sessions
WHERE is_primary_for_daily = TRUE;



ALTER TABLE public.dim_sessions
  DROP CONSTRAINT IF EXISTS dim_sessions_pk;

ALTER TABLE public.dim_sessions
  ADD CONSTRAINT dim_sessions_pk
  PRIMARY KEY (asset_class, region, venue, asset_key_type, asset_key, session_type);


CREATE UNIQUE INDEX IF NOT EXISTS uq_dim_sessions_primary_daily
ON public.dim_sessions (asset_class, region, venue, asset_key_type, asset_key)
WHERE is_primary_for_daily = TRUE;


CREATE OR REPLACE VIEW public.vw_dim_sessions_primary AS
SELECT *
FROM public.dim_sessions
WHERE is_primary_for_daily = TRUE;
