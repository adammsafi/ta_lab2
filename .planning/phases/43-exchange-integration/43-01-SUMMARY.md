---
phase: 43-exchange-integration
plan: "01"
subsystem: connectivity
tags: [exchange, credentials, alembic, ddl, exchange-config, paper-orders, price-feed, coinbase, kraken]

# Dependency graph
requires:
  - phase: 42-strategy-bake-off
    provides: strategy bakeoff results; Phase 43 foundation plan has no data dependency on Phase 42
  - phase: 41-asset-descriptive-stats-correlation
    provides: cmc_asset_stats.std_ret_30 -- used by exchange_price_feed adaptive threshold logic (Plans 02-03)
provides:
  - ExchangeConfig dataclass (src/ta_lab2/connectivity/exchange_config.py) for Coinbase/Kraken credential management
  - Alembic migration b180d8d07a85 creating exchange_price_feed and paper_orders tables
  - Reference DDL files (sql/exchange/080_exchange_price_feed.sql, sql/exchange/081_paper_orders.sql)
affects:
  - 43-02 (Coinbase authenticated adapter uses ExchangeConfig for credential injection)
  - 43-03 (Kraken authenticated adapter uses ExchangeConfig for HMAC signing)
  - 43-04 (price feed poller writes to exchange_price_feed table)
  - 43-05 (paper order adapter writes to paper_orders table)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ExchangeConfig from_env_file: manual dotenv parser (no python-dotenv dependency) strips quotes, skips comments, allows ENVIRONMENT key override"
    - "Alembic partial index: postgresql_where=sa.text('exceeds_threshold = TRUE') -- only indexes flagged rows for alert queries"
    - "Alembic UUID PK: sa.UUID() for both exchange tables -- app generates UUIDs, not DB sequences"
    - "Reference DDL pattern: sql/exchange/ mirrors alembic migration for human readability; alembic is authoritative"

key-files:
  created:
    - src/ta_lab2/connectivity/exchange_config.py
    - alembic/versions/b180d8d07a85_exchange_tables.py
    - sql/exchange/080_exchange_price_feed.sql
    - sql/exchange/081_paper_orders.sql
  modified: []

key-decisions:
  - "down_revision = e74f5622e710 (strategy_bakeoff_results from Phase 42-02), NOT 8d5bc7ee1732 as the plan spec suggested -- plan note said to double-check actual head first"
  - "ExchangeConfig is NOT frozen dataclass -- allows mutation for testing/runtime environment switching"
  - "No python-dotenv dependency -- manual line-by-line dotenv parser keeps the module dependency-free"
  - "paper_orders.status CHECK includes future states (pending, filled, cancelled, rejected) for Phase 44 compatibility; current Phase 43 only uses 'paper'"
  - "exchange_price_feed uses partial index on exceeds_threshold=TRUE -- threshold alerts are minority of rows, partial index is more efficient than full index"

patterns-established:
  - "ExchangeConfig pattern: load from .env file -> validate() before adapter init -> pass to factory"
  - "Exchange table UUID PKs: app-generated UUIDs as PKs instead of DB sequences for distributed-safe inserts"

# Metrics
duration: 9min
completed: 2026-02-25
---

# Phase 43 Plan 01: ExchangeConfig + Exchange Table DDL Summary

**ExchangeConfig dataclass with dotenv-style credential loading, validate(), is_sandbox; Alembic migration b180d8d07a85 creating exchange_price_feed (spot price snapshots with discrepancy metrics) and paper_orders (paper trade log) tables with CHECK constraints and indexes**

## Performance

- **Duration:** 9 min
- **Started:** 2026-02-25T03:29:42Z
- **Completed:** 2026-02-25T03:38:00Z
- **Tasks:** 2/2
- **Files created:** 4 (exchange_config.py, migration, 2x reference DDL)

## Accomplishments

- Created `ExchangeConfig` dataclass at `src/ta_lab2/connectivity/exchange_config.py`
  - `from_env_file(venue, env_file, environment)` classmethod: manual dotenv parser, no python-dotenv dependency
  - `validate()`: raises `ValueError` when `api_key` or `api_secret` is empty/whitespace
  - `is_sandbox` property: returns `True` when `environment == 'sandbox'`
  - Masked `__repr__` showing first 4 chars of key + `***` to avoid credential leaks in logs
- Generated Alembic revision `b180d8d07a85` chained off `e74f5622e710` (actual current head)
- `exchange_price_feed` table: UUID PK, fetched_at, exchange/pair/environment, bid/ask/mid/last prices, bar_close/bar_ts for comparison, discrepancy_pct, threshold_pct, exceeds_threshold BOOLEAN; CHECK on exchange IN (coinbase, kraken, binance, bitfinex, bitstamp); composite index on (exchange, pair, fetched_at DESC); partial index on exceeds_threshold=TRUE
- `paper_orders` table: UUID PK, created_at, signal_id/asset_id, exchange/pair, side/order_type/quantity/limit_price/stop_price, exchange_payload TEXT, status, environment, client_order_id; CHECK constraints on side (buy/sell), order_type (market/limit/stop/stop_limit), status (paper/pending/filled/cancelled/rejected)
- Round-trip migration tested: `alembic upgrade head` -> `alembic downgrade -1` (both tables dropped cleanly) -> `alembic upgrade head` (both tables restored)
- Reference DDL files created at `sql/exchange/080_exchange_price_feed.sql` and `sql/exchange/081_paper_orders.sql`

## Task Commits

1. **Task 1: ExchangeConfig dataclass** - `ae0495f4` (feat)
2. **Task 2: Alembic migration + reference DDL** - `4860f205` (feat)

## Files Created/Modified

- `src/ta_lab2/connectivity/exchange_config.py` - ExchangeConfig dataclass for credential management
- `alembic/versions/b180d8d07a85_exchange_tables.py` - Migration creating exchange_price_feed and paper_orders
- `sql/exchange/080_exchange_price_feed.sql` - Reference DDL for exchange_price_feed
- `sql/exchange/081_paper_orders.sql` - Reference DDL for paper_orders

## Decisions Made

1. **down_revision is e74f5622e710, not 8d5bc7ee1732:** The plan spec listed `8d5bc7ee1732` as the expected `down_revision`, but the plan's own "Project state" note said to run `alembic history` first. The actual head was `e74f5622e710` (strategy_bakeoff_results from Phase 42-02). `alembic revision -m "exchange_tables"` auto-detected and set this correctly.

2. **No python-dotenv dependency:** The `from_env_file()` classmethod implements a minimal dotenv parser directly (key=value, skip `#` comments, strip surrounding quotes). This keeps `exchange_config.py` import-free of third-party packages and avoids adding a dependency for what is essentially 15 lines of parsing logic.

3. **ExchangeConfig NOT frozen:** Mutable dataclass allows environment switching at runtime (e.g., `config.environment = 'production'` in tests after initial sandbox setup) without recreating the object.

4. **paper_orders.status CHECK includes future lifecycle states:** Added `pending`, `filled`, `cancelled`, `rejected` to the CHECK constraint now (Phase 43 only uses `'paper'`). This avoids needing an ALTER TABLE in Phase 44 when live order tracking is added.

5. **Partial index on exceeds_threshold:** Alert queries typically scan only 2-5% of rows (those where discrepancy exceeds threshold). A partial index on `exceeds_threshold = TRUE` is more efficient than a full index and avoids bloat from the majority of non-flagged rows.

## Deviations from Plan

None - plan executed exactly as written.

## Next Phase Readiness

- **ExchangeConfig ready:** Plans 02 and 03 can import and use ExchangeConfig immediately for Coinbase/Kraken adapter credential injection
- **Tables created:** Plans 04-05 (price feed poller, paper order adapter) have their target tables ready in the DB
- **Chain intact:** Alembic revision chain unbroken; `alembic upgrade head` runs cleanly from any revision
- **No blockers for Plan 02:** Coinbase authenticated adapter implementation can proceed

---
*Phase: 43-exchange-integration*
*Completed: 2026-02-25*
