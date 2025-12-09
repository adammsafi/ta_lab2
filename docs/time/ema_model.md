# ema_model

## Purpose
Define EMA behavior and alpha calculation.

## Alpha Formula
```
alpha = 2 / (span_days + 1)
span_days = tf_days_nominal * period
```

## Diagram

```
dim_timeframe (tf_days_nominal)
        |
        v
dim_period (period)
        |
        v
span_days = product
        |
        v
ema_alpha_lookup
```

## SQL References
- `016_dim_timeframe_period.sql`
- `017_ema_alpha_lookup.sql`
