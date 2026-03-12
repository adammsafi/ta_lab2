CREATE TABLE IF NOT EXISTS ema_multi_tf_cal_anchor_stats (
    id          BIGSERIAL PRIMARY KEY,
    table_name  TEXT        NOT NULL,
    test_name   TEXT        NOT NULL,
    asset_id    INTEGER     NOT NULL,
    tf          TEXT        NOT NULL,
    period      INTEGER     NOT NULL,
    status      TEXT        NOT NULL,  -- 'ok' | 'warn' | 'error'
    actual      DOUBLE PRECISION,
    expected    DOUBLE PRECISION,
    extra       JSONB,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ema_multi_tf_cal_anchor_stats_pk
    ON ema_multi_tf_cal_anchor_stats (
        table_name,
        test_name,
        asset_id,
        tf,
        period,
        ingested_at
    );
