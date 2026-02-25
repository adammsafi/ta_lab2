---
phase: 43-exchange-integration
plan: "05"
subsystem: exchange
tags: [exchange, coinbase, kraken, price-feed, discrepancy, adaptive-threshold, cmc_asset_stats]

# Dependency graph
requires:
  - phase: 43-02
    provides: ExchangeConfig dataclass and coinbase.env / kraken.env credential loading
  - phase: 43-03
    provides: CoinbaseExchange and KrakenExchange adapters with get_ticker()
  - phase: 43-04
    provides: CanonicalOrder and PaperOrderLogger for paper trading

provides:
  - Live spot price fetch from Coinbase + Kraken for BTC/USD and ETH/USD
  - Bar close comparison via cmc_price_bars_multi_tf (tf=1D)
  - Adaptive discrepancy threshold from cmc_asset_stats.std_ret_30
  - Snapshot persistence to exchange_price_feed table
  - WARNING log when discrepancy exceeds adaptive threshold
  - --exchange-prices flag in run_daily_refresh.py (standalone, not in --all)

affects:
  - future monitoring / alerting integrations that read exchange_price_feed
  - run_daily_refresh.py consumers who might add scheduled price checks

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Adaptive threshold: 3 * std_ret_30 * 100 from cmc_asset_stats, fallback 5.0%"
    - "Exchange price feed uses NullPool engine and plain INSERT (UUID PK, no conflicts)"
    - "Standalone --exchange-prices flag excluded from --all; run on-demand"
    - "factory.get_exchange() accepts optional config: ExchangeConfig for credential injection"

key-files:
  created:
    - src/ta_lab2/scripts/exchange/__init__.py
    - src/ta_lab2/scripts/exchange/refresh_exchange_price_feed.py
  modified:
    - src/ta_lab2/connectivity/factory.py
    - src/ta_lab2/scripts/run_daily_refresh.py

key-decisions:
  - "Discrepancy uses last_price (fallback mid) vs bar_close; abs value to catch both over/under"
  - "factory.get_exchange() passes config via kwargs to preserve backward compat with **credentials"
  - "--exchange-prices is NOT in --all because live price fetches are on-demand / rate-limited"
  - "TIMEOUT_EXCHANGE_PRICES = 120s (4 fetches from 2 exchanges at ~10s each)"

patterns-established:
  - "Exchange price feed: dry-run skips INSERT but still connects to DB for bar close comparison"
  - "Standalone run_daily_refresh flag pattern: handled before Parse IDs block, exits immediately"

# Metrics
duration: 4min
completed: "2026-02-25"
---

# Phase 43 Plan 05: Exchange Price Feed Summary

**Live price feed comparison script (Coinbase + Kraken vs bar closes) with adaptive threshold alerts wired into run_daily_refresh.py as --exchange-prices**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-02-25T03:46:21Z
- **Completed:** 2026-02-25T03:50:17Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Created `refresh_exchange_price_feed.py` that fetches BTC/USD and ETH/USD from Coinbase and Kraken, compares against the most recent daily bar close, and writes snapshots to `exchange_price_feed`
- Implemented adaptive discrepancy threshold: `3 * std_ret_30 * 100` from `cmc_asset_stats`, with 5.0% fallback when no stats exist
- Updated `factory.get_exchange()` with optional `config: ExchangeConfig` parameter while keeping full backward compatibility
- Wired `--exchange-prices` flag into `run_daily_refresh.py` (standalone, NOT in `--all`)

## Task Commits

Each task was committed atomically:

1. **Task 1: Update factory + create refresh_exchange_price_feed.py** - `5bb20602` (feat)
2. **Task 2: Wire price feed into run_daily_refresh.py** - `12d20abe` (feat)

## Files Created/Modified

- `src/ta_lab2/scripts/exchange/__init__.py` - Package init for exchange scripts
- `src/ta_lab2/scripts/exchange/refresh_exchange_price_feed.py` - Main price feed comparison script with CLI
- `src/ta_lab2/connectivity/factory.py` - Added optional `config: ExchangeConfig` param to `get_exchange()`
- `src/ta_lab2/scripts/run_daily_refresh.py` - Added `TIMEOUT_EXCHANGE_PRICES`, `run_exchange_prices()`, `--exchange-prices` flag

## Decisions Made

- `discrepancy_pct = abs(last_price - bar_close) / bar_close * 100` using `last_price` (fallback to `mid`) — absolute value catches both over/under scenarios
- `factory.get_exchange()` injects `config` into `kwargs` dict alongside `**credentials` to avoid breaking existing callers that pass only keyword credentials
- `--exchange-prices` excluded from `--all` because live exchange fetches are rate-limited and on-demand; they should not run as part of the automated nightly pipeline unless explicitly requested
- `TIMEOUT_EXCHANGE_PRICES = 120s` — 2 exchanges × 2 pairs × ~10s per fetch with margin

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

Pre-commit hook ran `ruff format` and `mixed-line-ending` fixes on first commit attempt (Windows CRLF). Re-staged and committed successfully on second attempt. No logic changes.

## User Setup Required

None - no external service configuration required beyond existing exchange API keys.

## Next Phase Readiness

- Phase 43 complete: all 5 plans done (ExchangeConfig, Coinbase adapter, Kraken adapter, CanonicalOrder/PaperOrderLogger, price feed)
- `exchange_price_feed` table is populated on demand via `--exchange-prices`
- Future work: scheduled cron invocation, Telegram alerts on threshold breach, additional pairs/exchanges

---
*Phase: 43-exchange-integration*
*Completed: 2026-02-25*
