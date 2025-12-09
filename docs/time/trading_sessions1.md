# trading_sessions

## Purpose
Store market-level session rules per asset group.

## Core Fields
- session_id
- name (e.g., crypto_24_7, us_equities)
- week_start_dow (1=Mon...7=Sun)
- week_end_dow
- eom_rule: true/gregorian
- holidays: optional extension.

## Roles
- Defines WEEK_END for calendar weekly frames (1W_CAL etc.)
- Defines how EOM is resolved for markets that close early or skip holidays.
- Provides session group mapping for each asset.

## Asset-level mapping
btc -> crypto_24_7
eth -> crypto_24_7
MSTR -> us_equities
IBIT -> us_equities

## Future
- Region-specific weekends (e.g., Middle East Fri-Sat).
- DST offsets for intraday bars.