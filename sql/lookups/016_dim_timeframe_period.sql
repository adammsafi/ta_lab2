CREATE TABLE IF NOT EXISTS dim_timeframe_period (
    tf               text REFERENCES dim_timeframe(tf),
    period           integer REFERENCES dim_period(period),
    span_days        integer NOT NULL,
    PRIMARY KEY (tf, period)
);

INSERT INTO dim_timeframe_period (tf, period, span_days)
SELECT tf, p.period, tf_days_nominal * p.period AS span_days
FROM dim_timeframe tf
CROSS JOIN dim_period p
ORDER BY tf, p.period
ON CONFLICT (tf,period) DO NOTHING;
