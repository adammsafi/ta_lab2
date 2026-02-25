---
phase: 43-exchange-integration
plan: "03"
subsystem: connectivity
tags: [kraken, hmac, sha512, authenticated-api, exchange, orders, signing]

# Dependency graph
requires:
  - phase: 43-01
    provides: ExchangeConfig dataclass for credential management
provides:
  - KrakenExchange with full HMAC-SHA512 authenticated endpoint support
  - _sign() implementing exact Kraken signing algorithm (nonce+urlencode -> SHA256 -> HMAC-SHA512 -> base64)
  - _private_post() with millisecond nonce, error-checking, InvalidRequestError on Kraken errors
  - _requires_auth() guard raising AuthenticationError without credentials
  - get_account_balances, get_open_orders, place_market_order, place_limit_order, cancel_order
affects:
  - 43-04 (Coinbase adapter - parallel pattern reference)
  - 43-05 (paper trading engine - will call KrakenExchange methods)
  - future signal pipeline integration

# Tech tracking
tech-stack:
  added: [stdlib hmac, stdlib hashlib, stdlib base64, stdlib urllib.parse]
  patterns: [HMAC-SHA512 Kraken signing pattern, _requires_auth guard pattern, _private_post POST abstraction]

key-files:
  created: []
  modified: [src/ta_lab2/connectivity/kraken.py]

key-decisions:
  - "Used PUBLIC_URL + PRIVATE_URL + BASE_URL (backward compat) as class attributes"
  - "config: ExchangeConfig = None in constructor; config credentials override positional params"
  - "Millisecond nonce: str(int(time.time() * 1000)) matches Kraken docs"
  - "_private_post raises InvalidRequestError on non-empty result['error'] list"
  - "get_account_balances filters out zero-balance assets"
  - "cancel_order returns dict even though CancelOrder result is not used (status always 'cancelled')"

patterns-established:
  - "_requires_auth(): single-call auth guard reused across all 5 private methods"
  - "_private_post(endpoint, data): centralized nonce+sign+error handling for all private endpoints"
  - "Kraken signing: encoded=(nonce+urlencode(data)).encode(); message=urlpath+sha256(encoded); hmac.new(b64decode(secret),message,sha512)"

# Metrics
duration: 3min
completed: 2026-02-25
---

# Phase 43 Plan 03: Kraken Private Endpoints Summary

**HMAC-SHA512 signing infrastructure added to KrakenExchange with 5 authenticated endpoints (balance, open orders, market/limit order placement, cancel); all existing public methods preserved unchanged.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-25T03:38:01Z
- **Completed:** 2026-02-25T03:40:51Z
- **Tasks:** 1/1
- **Files modified:** 1

## Accomplishments

- Added `_sign()` implementing the exact Kraken HMAC-SHA512 algorithm: `(nonce+urlencode) -> SHA256 -> prepend urlpath -> HMAC-SHA512 -> base64`
- Added `_private_post()` as a centralized handler for all private POSTs: injects millisecond nonce, signs, checks `result['error']`, returns `result['result']`
- Implemented all 5 authenticated methods: `get_account_balances`, `get_open_orders`, `place_market_order`, `place_limit_order`, `cancel_order`
- Integrated `ExchangeConfig` via optional `config` parameter in constructor (credentials override positional args)
- All existing public methods (`get_ticker`, `get_order_book`, `get_historical_klines`) preserved byte-for-byte

## Task Commits

1. **Task 1: Add HMAC-SHA512 signing infrastructure to Kraken adapter** - `c3816e24` (feat)

## Files Created/Modified

- `src/ta_lab2/connectivity/kraken.py` - Updated from 158 lines to 412 lines; added HMAC-SHA512 signing, 5 private endpoint implementations, ExchangeConfig integration; 0 NotImplementedError remains

## Decisions Made

- **PUBLIC_URL / PRIVATE_URL / BASE_URL triple**: Added `PUBLIC_URL` and `PRIVATE_URL` per the plan; kept `BASE_URL` unchanged so existing public methods that reference `self.BASE_URL` continue to work without any modification.
- **Config credential priority**: When `ExchangeConfig` is provided, its credentials take precedence over positional `api_key`/`api_secret` params. This lets callers always use the config pattern while still supporting direct construction.
- **Zero-balance filtering in `get_account_balances`**: Only returns assets where `float(balance) > 0`. This matches normal usage (Kraken returns all assets including those with zero).
- **`cancel_order` return value**: Kraken's `CancelOrder` result (`count`/`pending`) is discarded; always returns `{"order_id": order_id, "status": "cancelled"}` for interface consistency.
- **No `@handle_api_errors` on private methods**: Private methods use `_requires_auth()` and `_private_post()` which raise typed exceptions directly. Wrapping with the decorator would mask the `AuthenticationError` as a `BadResponseError` on parse failure.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Pre-commit hook (trailing-whitespace) modified the file after first `git add`, requiring a second `git add` + commit attempt. Resolved automatically.

## User Setup Required

External services require manual configuration before authenticated endpoints can be called live:

- `API_KEY`: From Kraken Settings -> API -> Create New Key (copy API Key field)
- `API_SECRET`: From Kraken Settings -> API -> Create New Key (copy Private Key, base64-encoded)
- Required permissions: Query Funds + Create & Modify Orders + Cancel/Close Orders
- Dashboard: https://www.kraken.com/u/security/api

Credentials can be provided directly or via `ExchangeConfig.from_env_file('kraken', 'kraken.env')`.

Note: Kraken has no spot testnet. All integration tests must use mocks.

## Next Phase Readiness

- `KrakenExchange` now fully implements all 8 abstract methods from `ExchangeInterface` with no `NotImplementedError` remaining
- Ready for Plan 43-04 (Coinbase adapter) — same pattern: `_sign` + `_private_post` + `_requires_auth`
- Ready for Plan 43-05 (paper trading engine) — can call `KrakenExchange.place_market_order` / `place_limit_order` with real credentials

---
*Phase: 43-exchange-integration*
*Completed: 2026-02-25*
