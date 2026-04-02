---
phase: 113-vm-execution-deployment
plan: 02
subsystem: executor
tags: [websocket, price-feed, hyperliquid, kraken, coinbase, threading, asyncio, decimal]

# Dependency graph
requires:
  - phase: 113-01
    provides: VM table DDL and deployment script for executor tables
provides:
  - Thread-safe PriceCache for real-time price storage keyed by symbol
  - Hyperliquid allMids WebSocket feed via hyperliquid-python-sdk WebsocketManager
  - Kraken WS v2 ticker feed with auto-reconnect via websockets 16.0
  - Coinbase Advanced Trade ticker feed with 5s subscribe enforcement
  - start_all_feeds() convenience starter returning daemon thread list
affects:
  - 113-03 (stop monitor consumes PriceCache)
  - 113-04 (executor service wires all feeds together)
  - position_sizer (VM price resolution extension in 113-05)

# Tech tracking
tech-stack:
  added:
    - hyperliquid-python-sdk (pip) — WebsocketManager for allMids subscription
    - websockets>=16.0 (pip) — async WS client with infinite-iterator auto-reconnect
  patterns:
    - Daemon thread per feed — threads die with process, no explicit cleanup needed
    - asyncio event loop isolated per thread — no interference with caller loops
    - Graceful ImportError degradation — missing SDK logs warning and returns no-op thread
    - try/except in all callbacks — WS parse errors never kill the feed thread

key-files:
  created:
    - src/ta_lab2/executor/price_cache.py
    - src/ta_lab2/executor/ws_feeds.py
  modified: []

key-decisions:
  - "Use hyperliquid-python-sdk WebsocketManager (not raw websockets) for HL: SDK handles ping/keepalive and subscription routing, threading-based so it fits the sync executor model"
  - "Each async feed gets its own asyncio.new_event_loop() in its thread: prevents cross-contamination with any caller event loop"
  - "Graceful ImportError for both hyperliquid SDK and websockets: VM deploy can stagger dependency installs without crashing on import"
  - "All WS message callbacks wrapped in try/except: parse errors in one message must not kill the feed thread"
  - "Coinbase subscribe sent immediately after connect (before any reads): enforces the 5s subscribe requirement documented in Coinbase API"

patterns-established:
  - "PriceCache: central shared price store; all feeds write, all consumers read — single source of truth for live tick prices"
  - "start_all_feeds() returns list of threading.Thread for caller monitoring (can check t.is_alive())"
  - "stale_symbols() + is_stale() for external staleness monitoring — caller should alert if symbols go stale > 120s"

# Metrics
duration: 3min
completed: 2026-04-02
---

# Phase 113 Plan 02: WebSocket Price Feed Infrastructure Summary

**Thread-safe PriceCache + three exchange WebSocket feeds (HL allMids, Kraken v2 ticker, Coinbase Advanced Trade) running in daemon threads with Decimal precision and staleness detection**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-04-02T04:11:21Z
- **Completed:** 2026-04-02T04:14:16Z
- **Tasks:** 2
- **Files modified:** 2 created

## Accomplishments

- PriceCache delivers thread-safe get/update using RLock, Decimal(str(price)) precision, per-symbol UTC timestamps, is_stale/stale_symbols/get_with_age helpers, and all_symbols introspection
- Hyperliquid allMids feed uses official SDK WebsocketManager (threading-based, 50s ping) — no asyncio complexity for the primary exchange
- Kraken and Coinbase feeds use websockets 16.0 `async for websocket in connect(...)` infinite-iterator pattern for automatic exponential-backoff reconnection; each runs in a freshly created asyncio event loop in its own daemon thread
- Coinbase critical requirement met: subscribe message sent immediately after connect before entering the message receive loop (Coinbase disconnects within 5s otherwise)
- All feeds degrade gracefully on missing dependencies (ImportError → log warning, return no-op thread)

## Task Commits

1. **Task 1: Create PriceCache thread-safe price dictionary** - `1b3dd188` (feat)
2. **Task 2: Create WebSocket feed managers for HL, Kraken, Coinbase** - `69251b1e` (feat)

## Files Created/Modified

- `src/ta_lab2/executor/price_cache.py` — Thread-safe price dict with Decimal precision, staleness detection (is_stale, stale_symbols, get_with_age), all_symbols introspection
- `src/ta_lab2/executor/ws_feeds.py` — start_hl_feed, start_kraken_feed, start_coinbase_feed, start_all_feeds; all write to shared PriceCache; daemon threads; graceful ImportError degradation

## Decisions Made

- Used `hyperliquid-python-sdk` `WebsocketManager` rather than raw `websockets` for HL: SDK is threading-based (matches sync executor model), handles 50s ping/keepalive, and has proven subscription routing. Raw websockets would require asyncio bridge for HL.
- Each async feed (Kraken, Coinbase) gets `asyncio.new_event_loop()` in its thread: prevents cross-contamination with any outer event loop (e.g., if caller uses asyncio themselves).
- Both dependencies (hyperliquid SDK and websockets) use `try/except ImportError` with graceful no-op: VM deploy can install dependencies incrementally without import-time crashes.
- Coin base subscribe sent before entering message receive loop per RESEARCH.md Pitfall 6 (5s disconnect requirement).

## Deviations from Plan

None - plan executed exactly as written. Ruff reformatted one line in ws_feeds.py during pre-commit hook (minor style, not a deviation).

## Issues Encountered

- Pre-commit ruff-format hook reformatted a long line in `start_coinbase_feed`; re-staged and committed cleanly on second attempt.

## User Setup Required

None - no external service configuration required for this plan. WebSocket connections require network access but are not tested at import time.

## Next Phase Readiness

- `PriceCache` is ready for consumption by the stop monitor (Plan 113-03) and executor service (Plan 113-04)
- `start_all_feeds()` is the single call to wire all price feeds in the executor service entry point
- **Note for Plan 113-03 (stop monitor):** PriceCache.is_stale(symbol, max_age_seconds=120) is the hook for staleness alerting — stop monitor should check this before trusting prices for stop/TP decisions
- **Note for Plan 113-05 (position sizer VM extension):** PriceCache.get(symbol) should be injected as the first tier in get_current_price() fallback chain, ahead of hl_assets.mark_px and hl_candles

---
*Phase: 113-vm-execution-deployment*
*Completed: 2026-04-02*
