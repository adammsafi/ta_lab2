# ARCHITECTURE

## Time & Timeframes
- See `dim_timeframe.md` for dimension definition.
- See `trading_sessions.md` for market calendar rules.
- See `time_model_overview.md` for conceptual layering.

## Integration Points
- EMA computations join dim_timeframe for tf_days_nominal.
- Multi-TF EMA relies on (tf,period) mapping.
- Returns & volatility use tf_days_nominal for windows.
- Regime models depend on consistent calendar alignment.

## Where week starts/ends
Defined in trading_sessions.md per session_id.
calendar_anchor WEEKS use that definition.