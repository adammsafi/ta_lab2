-- sql/dim/public.session_instants_for_date.sql
-- Week 2: DST-safe session instants (local date/time + tz -> UTC instants)

BEGIN;

CREATE OR REPLACE FUNCTION public.session_instants_for_date(
    _session_date date,
    _timezone text,
    _open_local time,
    _close_local time,
    _is_24h boolean
)
RETURNS TABLE(open_utc timestamptz, close_utc timestamptz)
LANGUAGE plpgsql
AS $$
DECLARE
    open_local_ts  timestamp;
    close_local_ts timestamp;
    open_rt_time   time;
    close_rt_time  time;
BEGIN
    -- 24h: define as [local midnight .. next local midnight)
    IF _is_24h THEN
        open_local_ts  := (_session_date::timestamp + time '00:00');
        close_local_ts := ((_session_date + 1)::timestamp + time '00:00');
    ELSE
        open_local_ts := (_session_date::timestamp + _open_local);

        -- overnight handling (close <= open means close is next day)
        IF _close_local > _open_local THEN
            close_local_ts := (_session_date::timestamp + _close_local);
        ELSE
            close_local_ts := ((_session_date + 1)::timestamp + _close_local);
        END IF;
    END IF;

    -- Interpret local timestamps in the named timezone -> produce UTC timestamptz
    open_utc  := (open_local_ts  AT TIME ZONE _timezone);
    close_utc := (close_local_ts AT TIME ZONE _timezone);

    -- Round-trip validation: local wall time should remain what you asked for.
    open_rt_time  := (open_utc  AT TIME ZONE _timezone)::time;
    close_rt_time := (close_utc AT TIME ZONE _timezone)::time;

    IF NOT _is_24h THEN
        IF open_rt_time <> _open_local THEN
            RAISE EXCEPTION
              'DST round-trip mismatch for open: date=% tz=% requested=% got=% utc=%',
              _session_date, _timezone, _open_local, open_rt_time, open_utc;
        END IF;

        IF close_rt_time <> _close_local THEN
            RAISE EXCEPTION
              'DST round-trip mismatch for close: date=% tz=% requested=% got=% utc=%',
              _session_date, _timezone, _close_local, close_rt_time, close_utc;
        END IF;
    END IF;

    RETURN NEXT;
END;
$$;

COMMIT;
