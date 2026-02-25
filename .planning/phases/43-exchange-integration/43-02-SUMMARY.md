---
phase: 43-exchange-integration
plan: 02
subsystem: connectivity
tags: [coinbase, jwt, es256, advanced-trade-api, cryptography, rest]

# Dependency graph
requires:
  - phase: 43-01
    provides: ExchangeConfig dataclass for credential loading and sandbox flag
provides:
  - Coinbase Advanced Trade API adapter with JWT ES256 authentication
  - All 8 ExchangeInterface methods fully implemented (public + authenticated)
  - Sandbox/production environment switching via ExchangeConfig.is_sandbox
affects: [43-03, 43-04, 43-05, paper-trading, live-trading]

# Tech tracking
tech-stack:
  added: [PyJWT (ES256), cryptography (load_pem_private_key)]
  patterns:
    - Per-request JWT signing (fresh JWT per API call, 2-min expiry)
    - Bearer token authentication header injection
    - ExchangeConfig integration for credential + sandbox resolution

key-files:
  created: []
  modified:
    - src/ta_lab2/connectivity/coinbase.py

key-decisions:
  - "Fresh JWT per request (not cached): simpler, avoids clock-skew edge cases at cost of negligible CPU"
  - "market_market_ioc for market orders: quote_size for BUY, base_size for SELL (Coinbase asymmetry)"
  - "limit_limit_gtc with post_only=False for limit orders: standard GTC behavior"
  - "cancel_order wraps single order_id in list for batch_cancel endpoint (API contract)"
  - "Sandbox host = api-sandbox.coinbase.com, production = api.coinbase.com"

patterns-established:
  - "JWT ES256 signing: _build_jwt(method, path) -> token used in _authenticated_request"
  - "AuthenticationError raised immediately when api_key/api_secret absent (no network round-trip)"

# Metrics
duration: 2min
completed: 2026-02-24
---

# Phase 43 Plan 02: Coinbase Advanced Trade Adapter Summary

**Coinbase adapter fully rewritten from deprecated Pro API to Advanced Trade API with JWT ES256 per-request signing via PyJWT + cryptography, all 8 ExchangeInterface methods implemented**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-25T03:38:10Z
- **Completed:** 2026-02-25T03:40:24Z
- **Tasks:** 1/1
- **Files modified:** 1

## Accomplishments

- Replaced old Pro API (`api.exchange.coinbase.com`) with Advanced Trade API (`api.coinbase.com`)
- Implemented ES256 JWT auth: `_build_jwt(method, path)` produces signed tokens with sub, iss=cdp, nbf, exp, uri, kid, nonce claims
- Implemented all 8 ExchangeInterface methods: 3 public (ticker, order book, klines) + 5 authenticated (balances, open orders, market order, limit order, cancel)
- ExchangeConfig integration: credentials + sandbox/production routing resolved at construction time
- Sandbox environment routes to `api-sandbox.coinbase.com`

## Task Commits

Each task was committed atomically:

1. **Task 1: Rewrite Coinbase adapter with Advanced Trade API + JWT auth** - `841ec789` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `src/ta_lab2/connectivity/coinbase.py` - Full rewrite: Advanced Trade API adapter, 480 lines, JWT ES256 auth, all 8 methods

## Decisions Made

- **Fresh JWT per request** rather than caching: avoids clock-skew issues, CPU overhead negligible for trading frequency
- **market_market_ioc asymmetry**: BUY uses `quote_size` (spend X USD), SELL uses `base_size` (sell X BTC) — matches Coinbase API contract
- **limit_limit_gtc + post_only=False**: standard GTC limit order without maker-only restriction
- **batch_cancel wrapping**: `cancel_order(id)` wraps single ID in `[id]` list to match the batch endpoint contract
- **ExchangeConfig constructor resolution**: config values applied first, direct constructor args override (allows partial config usage)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Ruff pre-commit hook auto-fixed 3 lint issues and reformatted the file on first commit attempt. Re-staged and committed successfully on second attempt. No code logic was affected.

## User Setup Required

To use authenticated endpoints, credentials must be provided:

```python
from ta_lab2.connectivity.coinbase import CoinbaseExchange
from ta_lab2.connectivity.exchange_config import ExchangeConfig

config = ExchangeConfig.from_env_file(
    venue='coinbase',
    env_file='path/to/coinbase.env',
    environment='production'  # or 'sandbox'
)
# coinbase.env must contain:
#   API_KEY=organizations/xxx/apiKeys/yyy
#   API_SECRET=-----BEGIN EC PRIVATE KEY-----\n...\n-----END EC PRIVATE KEY-----

exchange = CoinbaseExchange(config=config)
balances = exchange.get_account_balances()
```

## Next Phase Readiness

- Coinbase adapter ready for 43-03 (Kraken adapter or factory wiring)
- JWT auth pattern established and tested; other authenticated adapters can follow same pattern
- No blockers

---
*Phase: 43-exchange-integration*
*Completed: 2026-02-24*
