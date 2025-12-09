# time_model_overview

## Layers
1. **tf_day base geometry**: pure spans (1D, 21D, 252D)
2. **semantic TFs**: 1W, 2W (tf_day labels)
3. **calendar TFs**: 1W_CAL, 1M_CAL, 1Y_CAL
4. **roll flags**: roll = true at anchor points
5. **periods**: applied inside tf_day horizons to create alpha mapping
6. **multi-TF products**: roll vs non-roll views

## Data Flow
price → cmc_ema_daily(tf_day) → cmc_ema_multi_tf(tf,period) → features/trend/returns/vol.

## DST considerations
- Weekly anchor uses trading_sessions; DST irrelevant for daily bars.
- Intraday future work: adjust next_bar timestamp with timezone offsets.

## Conceptual Diagram
tf_day -> semantic alias -> calendar anchor -> roll policy