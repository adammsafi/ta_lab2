# dim_timeframe

## Purpose
Defines all supported timeframes used in ta_lab2. Separates:
- tf_day horizons (e.g., 1D, 63D, 945D)
- calendar-anchored frames (EOM, EOQ, EOY, WEEK_END)
- semantic aliases (1W, 2W, 1M_CAL)

## Table Fields
- tf (PK)
- base_unit: D,W,M,Y
- tf_qty: quantity of base_unit
- tf_days_nominal: nominal span
- alignment_type: tf_day or calendar
- calendar_anchor: NULL/EOM/EOQ/EOY/WEEK_END
- roll_policy: multiple_of_tf or calendar_anchor
- has_roll_flag
- is_intraday
- sort_order

## Philosophy
tf_day horizons represent pure geometric spans.
Calendar frames impose structure for alignment tests, QoQ, MoM.

## Examples
- 21D = binding of alpha period when tf_day=21.
- 1W_CAL = calendar week end defined per trading_sessions.md
- 1M_CAL = true end-of-month anchor.

## How computation uses dim_timeframe
- EMA selects tf_days_nominal to compute alpha.
- Multi-TF EMA uses (tf,period) to compute final span.
- Returns/volatility group by tf_days_nominal or tf label.

## Future Work
- Intraday TFs: 1H, 4H with anchor 'BAR_END'
- Fiscal calendars per asset
