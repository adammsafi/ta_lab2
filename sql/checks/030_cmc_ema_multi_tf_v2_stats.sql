CREATE TABLE IF NOT EXISTS ema_multi_tf_v2_stats (
    table_name   TEXT        NOT NULL,
    test_name    TEXT        NOT NULL,
    asset_id     INTEGER     NOT NULL,
    tf           TEXT        NOT NULL,
    period       INTEGER     NOT NULL,
    status       TEXT        NOT NULL, -- e.g. 'ok', 'warn', 'error'
    actual       DOUBLE PRECISION,
    expected     DOUBLE PRECISION,
    extra        JSONB,
    ingested_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ema_multi_tf_v2_stats_tbl_test_idx
    ON ema_multi_tf_v2_stats (table_name, test_name);

CREATE INDEX IF NOT EXISTS ema_multi_tf_v2_stats_asset_tf_period_idx
    ON ema_multi_tf_v2_stats (asset_id, tf, period);

CREATE INDEX IF NOT EXISTS ema_multi_tf_v2_stats_ingested_at_idx
    ON ema_multi_tf_v2_stats (ingested_at);
