CREATE TABLE IF NOT EXISTS cmc_ema_multi_tf_u (
    id               INTEGER          NOT NULL,
    ts               TIMESTAMPTZ      NOT NULL,
    tf               TEXT             NOT NULL,   -- e.g. '1D', '3D', '1W', '1M', etc., FK to dim_timeframe.timeframe_code
    period           INTEGER          NOT NULL,   -- EMA period in units of tf
    ema              DOUBLE PRECISION NOT NULL,
    ema_bar          DOUBLE PRECISION,            -- bar-space EMA (canonical bar close price)
    is_partial_end   BOOLEAN,                     -- FALSE = canonical bar close, TRUE = inter-bar daily snapshot
    tf_days          INTEGER,                     -- derived from dim_timeframe but stored denormalized
    roll             BOOLEAN          NOT NULL DEFAULT false,
    ingested_at      TIMESTAMPTZ      NOT NULL DEFAULT now(),

    -- metadata about the alignment origin
    -- e.g. 'multi_tf', 'multi_tf_cal_us', 'multi_tf_cal_anchor_iso', etc.
    alignment_source TEXT             NOT NULL DEFAULT 'unknown',

    PRIMARY KEY (id, ts, tf, period)
);

ALTER TABLE cmc_ema_multi_tf_u
ADD CONSTRAINT cmc_ema_multi_tf_u_tf_fkey
FOREIGN KEY (tf) REFERENCES dim_timeframe(tf);
