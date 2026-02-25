---
phase: 43-exchange-integration
plan: "04"
subsystem: paper-trading
tags: [paper-trading, canonical-order, coinbase, kraken, order-translation, sqlalchemy, nullpool]

# Dependency graph
requires:
  - phase: 43-exchange-integration
    plan: "01"
    provides: paper_orders table (Alembic migration b180d8d07a85) with UUID PK, CHECK constraints on side/order_type/status

provides:
  - CanonicalOrder dataclass (src/ta_lab2/paper_trading/canonical_order.py) with to_exchange() translation to Coinbase Advanced Trade and Kraken AddOrder formats
  - PaperOrderLogger (src/ta_lab2/paper_trading/paper_order_logger.py) that persists paper orders to paper_orders table with JSON exchange_payload
  - Paper trading package init (src/ta_lab2/paper_trading/__init__.py) exporting both classes
affects:
  - 43-05 (price feed poller can use CanonicalOrder + PaperOrderLogger for paper trade execution)
  - Future phases using signal pipeline output to generate paper orders via from_signal()

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CanonicalOrder.to_exchange(exchange): dispatch by exchange name (case-insensitive), raises ValueError for unknown exchange"
    - "Coinbase order format: product_id='BTC-USD', side=BUY/SELL uppercase, order_configuration nested dict (market_market_ioc / limit_limit_gtc / stop_limit_stop_limit_gtc)"
    - "Kraken order format: pair='XBTUSD' (BTC->XBT rename, slash stripped), type=buy/sell lowercase, ordertype=market/limit/stop-loss-limit, price/price2/volume"
    - "from_signal(): normalizes direction Long/Short->buy/sell, accepts side or direction key, quantity or size key"
    - "PaperOrderLogger.log_order(): validate -> to_exchange -> json.dumps -> INSERT RETURNING order_uuid pattern"
    - "NullPool engine + resolve_db_url() per project convention for scripts/loggers"

key-files:
  created:
    - src/ta_lab2/paper_trading/__init__.py
    - src/ta_lab2/paper_trading/canonical_order.py
    - src/ta_lab2/paper_trading/paper_order_logger.py
  modified: []

key-decisions:
  - "CanonicalOrder is a mutable dataclass (not frozen) to allow signal_id assignment after construction"
  - "Coinbase side is uppercase (BUY/SELL) per Coinbase Advanced Trade API spec; Kraken type is lowercase (buy/sell) per Kraken AddOrder spec"
  - "stop order in Coinbase uses stop_limit_stop_limit_gtc with limit_price fallback to stop_price when limit_price is None"
  - "from_signal() accepts both 'side' (preferred) and 'direction' (signal pipeline output) with Long/Short normalization"
  - "PaperOrderLogger uses individual INSERT per order (not bulk) for simplicity and per-order error isolation"

patterns-established:
  - "Paper trading package pattern: CanonicalOrder -> validate() -> to_exchange() -> PaperOrderLogger.log_order() -> paper_orders table"
  - "Exchange format translation: single canonical format dispatches to exchange-specific builders via to_exchange(name)"

# Metrics
duration: 5min
completed: 2026-02-25
---

# Phase 43 Plan 04: CanonicalOrder + PaperOrderLogger Summary

**CanonicalOrder dataclass translating BTC/USD slash-format orders to Coinbase Advanced Trade (product_id, order_configuration) and Kraken AddOrder (XBTUSD pair, ordertype) wire formats; PaperOrderLogger persisting paper trades to paper_orders table with JSON exchange_payload via NullPool SQLAlchemy INSERT RETURNING**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-25T03:38:15Z
- **Completed:** 2026-02-25T03:43:31Z
- **Tasks:** 2/2
- **Files created:** 3

## Accomplishments

- Created `CanonicalOrder` dataclass with full exchange format translation for Coinbase Advanced Trade and Kraken AddOrder APIs
  - Coinbase: `product_id='BTC-USD'`, `side=BUY/SELL` uppercase, nested `order_configuration` with `market_market_ioc` / `limit_limit_gtc` / `stop_limit_stop_limit_gtc`
  - Kraken: `pair='XBTUSD'` (BTC->XBT rename, slash removed), `type=buy/sell` lowercase, `ordertype=market/limit/stop-loss-limit`
  - `validate()` enforces field consistency before translation (limit needs limit_price, stop needs stop_price, quantity > 0)
  - `from_signal()` normalizes signal pipeline output: direction Long/Short -> buy/sell, accepts side or direction key, quantity or size key
- Created `PaperOrderLogger` for paper_orders table persistence
  - `log_order(order, exchange, environment)`: validate -> to_exchange -> json.dumps payload -> INSERT INTO paper_orders RETURNING order_uuid
  - `log_orders_batch()` for bulk logging
  - `get_recent_orders(exchange, limit)` for order retrieval
  - NullPool engine with `resolve_db_url()` per project convention
- Paper trading package `__init__.py` exports both `CanonicalOrder` and `PaperOrderLogger`

## Task Commits

1. **Task 1: Create CanonicalOrder dataclass** - `841ec789` (feat) - Note: committed as part of prior phase 43-02 agent run; files were verified present and correct
2. **Task 2: Create PaperOrderLogger** - `b4c2adeb` (feat)

## Files Created/Modified

- `src/ta_lab2/paper_trading/__init__.py` - Package init exporting CanonicalOrder and PaperOrderLogger
- `src/ta_lab2/paper_trading/canonical_order.py` - CanonicalOrder dataclass with to_exchange() translation
- `src/ta_lab2/paper_trading/paper_order_logger.py` - PaperOrderLogger with log_order(), log_orders_batch(), get_recent_orders()

## Decisions Made

1. **Mutable dataclass (not frozen):** `CanonicalOrder` is not frozen to allow `signal_id` assignment post-construction when logging DB signals.

2. **Side case per exchange spec:** Coinbase Advanced Trade requires uppercase `BUY`/`SELL`; Kraken AddOrder requires lowercase `buy`/`sell`. Each `_to_exchange()` method encodes the correct case.

3. **stop_limit_stop_limit_gtc for Coinbase stop orders:** Coinbase Advanced Trade only supports stop-limit (not pure stop-market) orders via REST. The `limit_price` defaults to `stop_price` when not explicitly set, creating a stop-limit at the same price.

4. **Individual INSERT per order in log_orders_batch():** Simpler than bulk insert; each order's UUID is returned separately; failure is isolated to the failing order. Acceptable for paper trading volumes.

5. **Task 1 already committed:** The CanonicalOrder files were found pre-committed in `841ec789` (from previous plan 43-02 agent run). This agent verified the files match the plan spec exactly and proceeded directly to Task 2.

## Deviations from Plan

None - plan executed exactly as written. Task 1 artifacts were already present from prior agent run; verified correctness and proceeded to Task 2.

## Issues Encountered

- Pre-commit hook stash cycle: The `mixed-line-ending` hook converted CRLF to LF in `paper_order_logger.py` on first commit attempt, consuming the staged file from git's index. Required re-staging the LF-fixed version before the second commit attempt succeeded.

## User Setup Required

None - no external service configuration required. PaperOrderLogger uses existing `paper_orders` table from Plan 01 migration.

## Next Phase Readiness

- **EXCH-03 satisfied:** Paper order adapter translates signal output to exchange-compatible format without live execution
- **CanonicalOrder ready:** Plans 02/03 adapters (Coinbase, Kraken) can use CanonicalOrder as input type for paper order generation
- **PaperOrderLogger ready:** Any phase can log paper orders with `PaperOrderLogger().log_order(order, "coinbase")` after DB is available
- **from_signal() bridge:** Signal pipeline output can be directly converted via `CanonicalOrder.from_signal(row)` for batch paper trading simulation
- **No blockers for Plan 05:** Price feed poller implementation can proceed

---
*Phase: 43-exchange-integration*
*Completed: 2026-02-25*
