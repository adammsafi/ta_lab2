CREATE TABLE IF NOT EXISTS public.cmc_ema_refresh_state (
    id                   INTEGER PRIMARY KEY,
    last_load_ts_daily   TIMESTAMPTZ,
    last_load_ts_multi   TIMESTAMPTZ,
    last_load_ts_cal     TIMESTAMPTZ
);
