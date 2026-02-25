---
phase: 44-order-fill-store
plan: "01"
subsystem: trading-oms
tags: [alembic, postgresql, trading, orders, fills, positions, ddl, migrations]

dependency_graph:
  requires: [43-exchange-adapters]
  provides: [order-fill-store-schema, position-store-schema]
  affects: [44-03-order-manager, 44-04-paper-trading-pipeline]

tech_stack:
  added: []
  patterns:
    - alembic-hand-written-migration
    - partial-index-postgresql
    - check-constraint-state-machine
    - composite-pk-positions
    - weighted-avg-view

key_files:
  created:
    - alembic/versions/9e692eb7b762_order_fill_store.py
    - sql/trading/082_cmc_orders.sql
    - sql/trading/083_cmc_fills.sql
    - sql/trading/084_cmc_positions.sql
    - sql/trading/085_cmc_order_events.sql
    - sql/trading/086_cmc_order_dead_letter.sql
    - sql/trading/087_v_cmc_positions_agg.sql
  modified: []

decisions:
  - "UUID PKs with gen_random_uuid() for all order/fill/event/DLQ rows"
  - "TEXT payload (not JSONB) in cmc_order_dead_letter for lossless error capture"
  - "7-state status machine: created/submitted/partial_fill/filled/cancelled/rejected/expired"
  - "cmc_positions composite PK (asset_id, exchange) enforces one-row-per-asset-per-exchange"
  - "v_cmc_positions_agg uses ABS(quantity) weighting for cost basis -- handles shorts correctly"
  - "Partial indexes on signal_id/paper_order_uuid/exchange_order_id -- sparse optional FKs"
  - "DLQ partial index on status='pending' -- retry worker query pattern"

metrics:
  duration: "4 min"
  completed: "2026-02-25"
  tasks_total: 2
  tasks_completed: 2
---

# Phase 44 Plan 01: Order Fill Store Schema Summary

**One-liner:** Alembic migration creating 5 OMS tables (cmc_orders, cmc_fills, cmc_positions, cmc_order_events, cmc_order_dead_letter) and v_cmc_positions_agg view with full CHECK constraints, partial indexes, and FK relationships.

## What Was Built

Single Alembic migration (`9e692eb7b762`) creates all Phase 44 database objects from scratch. This is the persistence layer that OrderManager (Plan 03) will write to.

### Tables Created

| Table | PK | Key Constraints |
|-------|----|-----------------|
| cmc_orders | order_id UUID | 7-state status CHECK, side/order_type/tif/environment CHECK, quantity>0 |
| cmc_fills | fill_id UUID | FK to cmc_orders, fill_qty>0, fill_price>0, fee_amount>=0 |
| cmc_positions | (asset_id, exchange) composite | exchange IN (coinbase/kraken/paper/aggregate) |
| cmc_order_events | event_id UUID | FK to cmc_orders, to_status 7-state CHECK |
| cmc_order_dead_letter | dlq_id UUID | operation_type and status CHECK constraints |

### View Created

`v_cmc_positions_agg` aggregates cmc_positions by asset_id with:
- Weighted average cost basis (weight = ABS(quantity))
- Summed realized_pnl and unrealized_pnl
- Excludes rows where exchange = 'aggregate' to prevent double-counting

### Index Strategy

- `idx_orders_asset_status`: Query open orders per asset (composite + DESC timestamp)
- `idx_orders_signal/paper_order/exchange_order`: Partial indexes on sparse optional FK columns
- `idx_fills_order_id`: All fills for an order in chronological order
- `idx_fills_filled_at`: Time-ordered recent fills
- `idx_dlq_status_retry`: Partial index WHERE status='pending' for retry worker

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create Alembic migration | a29f4af5 | alembic/versions/9e692eb7b762_order_fill_store.py |
| 2 | Create reference DDL files | 19f3010d | sql/trading/082-087_*.sql (6 files) |

## Verification Results

- `alembic upgrade head` completed without error
- `alembic downgrade -1` dropped all 5 tables and view cleanly (verified empty table list + ProgrammingError on view query)
- `alembic upgrade head` re-applied successfully (round-trip confirmed)
- All 5 tables exist in information_schema.tables
- `SELECT count(*) FROM v_cmc_positions_agg` returns 0 (empty table, view functional)
- FK `fk_fills_order_id` exists on cmc_fills
- Composite PK on cmc_positions verified: columns (asset_id, exchange)
- 7 named CHECK constraints on cmc_orders verified in information_schema

## Decisions Made

1. **UUID PKs via gen_random_uuid()**: All tables use UUID PKs with server-side generation. Avoids sequence contention in concurrent fill processing.

2. **TEXT payload in DLQ (not JSONB)**: Lossless error capture -- if the payload is invalid JSON (which caused the failure), JSONB INSERT would fail again. TEXT preserves the raw data.

3. **7-state status machine**: created -> submitted -> partial_fill/filled/cancelled/rejected/expired. Same 7 values enforced identically by both chk_orders_status (cmc_orders) and chk_events_to_status (cmc_order_events).

4. **Composite PK (asset_id, exchange) on positions**: Enforces one-row-per-asset-per-exchange invariant at DB level. No application-layer upsert workarounds needed.

5. **Partial indexes for optional FKs**: signal_id, paper_order_uuid, exchange_order_id are nullable. Partial indexes are smaller and faster than full indexes on sparse columns.

6. **DLQ retry_after partial index**: WHERE status='pending' matches exactly the query pattern used by the retry worker loop -- covers only actionable rows.

## Deviations from Plan

None -- plan executed exactly as written.

## Next Phase Readiness

Plan 44-03 (OrderManager) can now:
- INSERT to cmc_orders and cmc_fills
- UPSERT to cmc_positions (composite PK enables clean ON CONFLICT DO UPDATE)
- INSERT to cmc_order_events for state machine audit trail
- INSERT to cmc_order_dead_letter for failed operations

All FK constraints, CHECK constraints, and indexes are in place before any application code writes to these tables.
