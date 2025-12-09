# trading_sessions

Defines market-specific calendar behavior.

## SQL Reference
Future table: `sql/lookups/020_trading_sessions.sql`

## Purpose
- Determine WEEK_END (per-country/per-market)
- Determine EOM behavior for irregular holidays
- Define session groups (crypto vs equities vs foreign markets)

## Diagram

```
asset -> session_id -> (week_start_dow, week_end_dow)
                               |
                            WEEK_END anchor for *_CAL TFs
```

## Fields
- session_id
- description
- timezone
- week_start_dow
- week_end_dow

## Example
| asset | session | week_end_dow |
|-------|---------|---------------|
| BTC   | crypto_24_7 | 7 |
| MSTR  | us_equities | 5 |
