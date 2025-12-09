# time_model_overview

High-level conceptual map.

## Diagram

```
price data
   |
   v
cmc_ema_daily (tf_day)
   |
   v
cmc_ema_multi_tf (tf, period)
   |
   +--> dim_timeframe join
   |       |
   |       +--> tf_days_nominal
   |       +--> calendar_anchor
   |
   v
features: returns, volatility, trend, regimes
```

## SQL References
- `017_ema_alpha_lookup.sql`
- `dim_timeframe`
- `dim_period`
- `dim_timeframe_period`
