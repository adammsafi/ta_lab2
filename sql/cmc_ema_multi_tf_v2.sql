CREATE TABLE IF NOT EXISTS cmc_ema_multi_tf_v2 (
    id          BIGINT      NOT NULL,
    ts          TIMESTAMPTZ NOT NULL,
    tf          TEXT        NOT NULL,
    period      INTEGER     NOT NULL,
    ema         DOUBLE PRECISION NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    d1          DOUBLE PRECISION,
    d2          DOUBLE PRECISION,
    tf_days     INTEGER     NOT NULL,
    roll        BOOLEAN     NOT NULL,
    d1_roll     DOUBLE PRECISION,
    d2_roll     DOUBLE PRECISION,

    PRIMARY KEY (id, ts, tf, period)
);

CREATE INDEX IF NOT EXISTS cmc_ema_multi_tf_v2__id_tf_period_ts_idx
    ON cmc_ema_multi_tf_v2 (id, tf, period, ts);
