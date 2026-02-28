# Phase 43: Exchange Integration - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Connect to exchange APIs for paper trading — authenticated access for BTC/ETH spot on two venues, price feed comparison against DB bar data, and paper order format translation. Scope expansion: two venues (Coinbase + Kraken) instead of the roadmap's "one venue."

**Existing infrastructure:** `src/ta_lab2/connectivity/` already has 6 exchange adapters (Binance, Coinbase, Kraken, Bitfinex, Bitstamp, Hyperliquid) with public API methods implemented (`get_ticker`, `get_order_book`, `get_historical_klines`). Factory pattern, error decorator, custom exception hierarchy, and test suite all in place. Authenticated methods are stubbed (`NotImplementedError`).

**Requirements:** EXCH-01, EXCH-02, EXCH-03

</domain>

<decisions>
## Implementation Decisions

### Exchange venue selection
- **Two venues:** Coinbase AND Kraken get full authenticated access (scope expansion from "one venue")
- Implement HMAC signing + authenticated endpoints for both: `get_account_balances`, `get_open_orders`, `place_limit_order`, `place_market_order`, `cancel_order`
- Coinbase: API key + secret + passphrase (already in adapter constructor kwargs)
- Kraken: HMAC-SHA512 signing with nonce
- Other 4 adapters (Binance, Bitfinex, Bitstamp, Hyperliquid): Standardize public APIs to consistent interface, keep maintained but no auth implementation
- **Testnet:** Both modes required — testnet/sandbox for development, production with paper guard for live comparison
- **Transport:** REST polling for Phase 43. WebSocket support deferred to a future phase

### Price feed design
- **Granularity:** Daily close comparison for Phase 43, but design the architecture to handle intraday snapshots, hourly spot checks, and real-time streaming later
- **Storage:** New `exchange_price_feed` table with (exchange, pair, ts, price, source, ...). Clean separation from TVC data
- **Discrepancy threshold:** Adaptive, based on asset volatility (e.g., scale with `std_ret_30` from `cmc_asset_stats`). Log all comparisons, flag rows exceeding threshold
- **Scheduling:** Both standalone script (own CLI with `--interval`, `--pairs`, `--exchanges`) AND integration into `run_daily_refresh.py` for daily close check

### Paper order adapter
- **Input:** Both modes — batch reads from `cmc_signals` table AND in-memory dict API for single-signal translation
- **Order types:** Market + Limit + Stop (full coverage)
- **Format:** Normalized canonical order format as primary output. Per-exchange translator via `.to_exchange(name)` method shows the exact JSON payload that would be sent to the exchange API
- **Logging:** Lightweight `paper_orders` table (id, ts, exchange, pair, side, order_type, qty, price, stop_price, status='paper', signal_id, ...). Phase 44 can migrate or replace this table

### Auth & credential management
- **Credential store:** Per-exchange .env files (e.g., `coinbase.env`, `kraken.env`). Gitignored. Separate from `db_config.env`
- **Key management:** Single API key pair per exchange (sufficient for paper trading phase)
- **Environment switching:** `ExchangeConfig` dataclass encapsulating venue, environment (testnet/production), credentials. Pass to factory function
- **Validation:** Validate credentials on adapter initialization — call lightweight endpoint (e.g., account status) to verify API key permissions and connectivity

### Claude's Discretion
- Exact HMAC signing implementation per exchange
- `exchange_price_feed` table DDL column details beyond the core fields
- Canonical order format field names and structure
- `paper_orders` table exact DDL
- How to gracefully degrade when `cmc_asset_stats` is empty (for adaptive threshold)
- ExchangeConfig dataclass field names and validation logic
- Test structure for authenticated endpoints (mocking strategy)

</decisions>

<specifics>
## Specific Ideas

- Existing connectivity module at `src/ta_lab2/connectivity/` is the foundation — extend, don't replace
- Existing `ExchangeInterface` ABC in `base.py` defines the contract — authenticated methods just need implementation
- Factory in `factory.py` already supports all 6 exchanges — extend with `ExchangeConfig` parameter
- Error decorator in `decorators.py` already handles HTTP 401/403 → `AuthenticationError` — signing should make this path work correctly
- `.env.example` already defines all credential env var names — per-exchange .env files follow same naming
- Adaptive threshold ties into Phase 41's `cmc_asset_stats` table (`std_ret_30` column)

</specifics>

<deferred>
## Deferred Ideas

- WebSocket support for real-time streaming — future phase (post-Phase 43)
- Intraday/hourly price feed scheduling — design for it, implement daily only in Phase 43
- Full order management (amend, OCO, bracket orders) — Phase 44/45 scope
- Multi-key management (read-only + trading keys) — future enhancement
- Rate limiting / backoff logic — could be Phase 43 but left to Claude's discretion on scope

</deferred>

---

*Phase: 43-exchange-integration*
*Context gathered: 2026-02-24*
