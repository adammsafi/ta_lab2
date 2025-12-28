-- sql/dim/public.dim_session_instants_for_date.sql
-- Week 2: Session lookup + DST-safe UTC instants for a given local session_date

BEGIN;

CREATE OR REPLACE FUNCTION public.dim_session_instants_for_date(
    _asset_class text,
    _region text,
    _venue text,
    _asset_key_type text,
    _asset_key text,
    _session_type text,
    _session_date date
)
RETURNS TABLE(
    asset_class text,
    region text,
    venue text,
    asset_key_type text,
    asset_key text,
    session_type text,
    session_date date,
    timezone text,
    session_open_local time,
    session_close_local time,
    is_24h boolean,
    open_utc timestamptz,
    close_utc timestamptz
)
LANGUAGE sql
AS $$
  SELECT
    s.asset_class,
    s.region,
    s.venue,
    s.asset_key_type,
    s.asset_key,
    s.session_type,
    _session_date AS session_date,
    s.timezone,
    s.session_open_local,
    s.session_close_local,
    s.is_24h,
    inst.open_utc,
    inst.close_utc
  FROM public.dim_sessions s
  CROSS JOIN LATERAL public.session_instants_for_date(
    _session_date,
    s.timezone,
    s.session_open_local,
    s.session_close_local,
    s.is_24h
  ) inst
  WHERE s.asset_class    = _asset_class
    AND s.region         = _region
    AND s.venue          = _venue
    AND s.asset_key_type = _asset_key_type
    AND s.asset_key      = _asset_key
    AND s.session_type   = _session_type;
$$;

COMMIT;
