CREATE TABLE IF NOT EXISTS cmc_ema_multi_tf_u (
    id          INTEGER            NOT NULL,
    ts          TIMESTAMPTZ        NOT NULL,
    tf          TEXT               NOT NULL,   -- e.g. '1D', '3D', '1W', '1M', etc., FK to dim_timeframe.timeframe_code
    period      INTEGER            NOT NULL,   -- EMA period in units of tf
    ema         DOUBLE PRECISION   NOT NULL,
    ingested_at TIMESTAMPTZ        NOT NULL DEFAULT now(),

    -- existing diagnostic / diff columns
    d1          DOUBLE PRECISION,
    d2          DOUBLE PRECISION,
    tf_days     INTEGER,                      -- derived from dim_timeframe but stored denormalized
    roll        BOOLEAN            NOT NULL DEFAULT false,
    d1_roll     DOUBLE PRECISION,
    d2_roll     DOUBLE PRECISION,

    -- optional: metadata about the alignment origin
    alignment_source TEXT          NOT NULL DEFAULT 'unknown',
    -- e.g. 'tf_day', 'calendar', 'backfill', etc.

    PRIMARY KEY (id, ts, tf, period)
);

ALTER TABLE cmc_ema_multi_tf_u
ADD CONSTRAINT cmc_ema_multi_tf_u_tf_fkey
FOREIGN KEY (tf) REFERENCES dim_timeframe(tf);
