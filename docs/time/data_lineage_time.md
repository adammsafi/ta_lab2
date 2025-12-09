# data_lineage_time

```
cmc_price_histories7
    |
    v
cmc_ema_daily
    |
    v
cmc_ema_multi_tf
    |
    v
ema_alpha_lookup + dim_timeframe + dim_period
    |
    v
returns, vol, trend, regimes
```
