---
phase: 44-order-fill-store
plan: "03"
subsystem: trading-oms
tags: [order-manager, fill-processing, position-management, atomic-transactions, dead-letter, state-machine, unit-tests]

dependency_graph:
  requires:
    - "44-01"  # cmc_orders, cmc_fills, cmc_positions, cmc_order_events, cmc_order_dead_letter tables
    - "44-02"  # compute_position_update() pure function
  provides:
    - "OrderManager class: process_fill, promote_paper_order, update_order_status"
    - "FillData dataclass: structured fill event value object"
    - "VALID_TRANSITIONS dict: enforces 7-state order lifecycle"
    - "Comprehensive unit tests (55 tests, no live DB required)"
  affects:
    - "45-paper-trade-executor"  # Primary consumer of OrderManager.process_fill
    - "46-risk-controls"         # Will call update_order_status on circuit breaker trips

tech_stack:
  added: []
  patterns:
    - "stateless static methods pattern (all OrderManager methods are static)"
    - "engine.begin() for atomic multi-table writes"
    - "separate engine.begin() for dead-letter (isolation from failed transaction)"
    - "FOR SHARE + FOR UPDATE locking pattern for concurrent fill safety"
    - "ON CONFLICT DO UPDATE for position upsert"
    - "str() Decimal conversion at SQL boundary (psycopg2 compatibility)"
    - "try/except with dead-letter + re-raise wrapper on all public methods"

key_files:
  created:
    - src/ta_lab2/trading/order_manager.py
    - tests/trading/test_order_manager.py
  modified:
    - src/ta_lab2/trading/__init__.py

decisions:
  - id: "44-03-01"
    decision: "FOR SHARE on order read, FOR UPDATE on position -- not both FOR UPDATE"
    rationale: "Multiple concurrent fills for different orders can read the order row simultaneously; only position needs exclusive lock since two fills for the same asset+exchange race on the position row"
  - id: "44-03-02"
    decision: "FillData.fill_qty is always positive; direction inferred from order.side"
    rationale: "Positive fill_qty matches exchange API semantics (fill_qty > 0 CHECK constraint in cmc_fills); signed_fill computed inside _do_process_fill as fill_qty * -1 for sells"
  - id: "44-03-03"
    decision: "Dead-letter uses its own engine.begin() (separate connection from failed transaction)"
    rationale: "The original transaction is in a rolled-back state; using the same connection would fail. Separate connection guarantees DLQ write always commits regardless of original failure."
  - id: "44-03-04"
    decision: "All OrderManager methods are static (stateless class)"
    rationale: "Callers pass the engine explicitly; no instance state needed. Stateless design makes testing trivial (no constructor setup) and prevents accidental engine reuse across workers."
  - id: "44-03-05"
    decision: "Unit tests mock the engine, not a real DB -- no live DB dependency"
    rationale: "Tests validate SQL call ordering, parameter values, and error propagation. Real DB tests would require Phase 44 migration applied, creating fragile CI dependency."

metrics:
  duration: "6 min"
  completed: "2026-02-25"
  tasks_completed: 2
  tasks_total: 2
  tests_added: 55
  tests_passing: 55
  lines_created: 1511  # 609 order_manager.py + 902 test file
  commits: 2
---

# Phase 44 Plan 03: OrderManager Class and Unit Tests Summary

**One-liner:** Atomic 4-table fill processing (fills/orders/positions/events) via OrderManager with dead-letter capture and 55 mock-based unit tests.

## What Was Built

### `src/ta_lab2/trading/order_manager.py` (609 lines)

**VALID_TRANSITIONS dict** -- 7-state machine:
- `created` -> `submitted`
- `submitted` -> `partial_fill | filled | cancelled | rejected | expired`
- `partial_fill` -> `partial_fill | filled | cancelled`
- `filled | cancelled | rejected | expired` -> [] (terminal)

**FillData dataclass** -- fill event value object:
- Required: `order_id`, `fill_qty` (Decimal, always positive), `fill_price` (Decimal)
- Optional: `fee_amount`, `fee_currency`, `exchange_fill_id`, `filled_at`
- Uses `field(default_factory=...)` for Decimal defaults (not shared mutable default)

**OrderManager class** -- all static methods, callers supply engine:

`process_fill(engine, fill_data) -> fill_id`:
- Wraps `_do_process_fill` in try/except; on failure calls `_write_dead_letter` then re-raises
- `_do_process_fill` uses single `engine.begin()` for all 6 SQL operations:
  1. SELECT cmc_orders WHERE order_id = ? **FOR SHARE**
  2. SELECT cmc_positions WHERE asset_id+exchange = ? **FOR UPDATE** (or use Decimal("0") defaults if no row)
  3. INSERT INTO cmc_fills
  4. UPDATE cmc_orders (filled_qty, remaining_qty, avg_fill_price, status)
  5. INSERT INTO cmc_positions ... ON CONFLICT (asset_id, exchange) DO UPDATE
  6. INSERT INTO cmc_order_events

`promote_paper_order(engine, paper_order_uuid, environment) -> order_id`:
- Reads paper_orders row, inserts cmc_orders with status='created', inserts 'created' event

`update_order_status(engine, order_id, new_status, reason)`:
- Validates VALID_TRANSITIONS; raises ValueError on invalid transition
- SELECT FOR UPDATE -> UPDATE cmc_orders -> INSERT cmc_order_events

`_write_dead_letter(engine, operation_type, order_id, payload_dict, exc)`:
- SEPARATE engine.begin() -- guaranteed to commit even if original transaction failed
- If DLQ write itself fails, logs at CRITICAL level but does NOT raise

### `tests/trading/test_order_manager.py` (902 lines, 55 tests)

7 test classes, all mock-based (no live DB):

| Class | Tests | What it verifies |
|-------|-------|-----------------|
| TestValidTransitions | 7 | All 7 states, terminal sets, no self-loops, partial_fill loop |
| TestFillData | 5 | Construction, defaults, Decimal types, factory independence |
| TestValidateFillTransition | 8 | Terminal status raises, overfill raises, valid fills pass |
| TestProcessFill | 17 | SQL call order (exactly 6), FOR SHARE/FOR UPDATE, partial/final status, avg price math, sell direction |
| TestDeadLetter | 6 | DLQ called on failure, separate connection, JSON payload, DLQ failure silent |
| TestUpdateOrderStatus | 8 | Invalid transition raises, terminal block, UPDATE + INSERT event, reason prop |
| TestPromotePaperOrder | 5 | DLQ on failure, not-found raises, UUID return, inserts to both tables |

### `src/ta_lab2/trading/__init__.py` (updated)

Exports: `FillData`, `OrderManager`, `VALID_TRANSITIONS`, `compute_position_update`

## Key Implementation Details

**Atomicity pattern:**
```python
with engine.begin() as conn:  # All 6 SQL ops in one transaction
    order_row = conn.execute(text("... FOR SHARE"), ...).fetchone()
    pos_row = conn.execute(text("... FOR UPDATE"), ...).fetchone()
    conn.execute(text("INSERT INTO cmc_fills ..."), ...)
    conn.execute(text("UPDATE cmc_orders ..."), ...)
    conn.execute(text("INSERT INTO cmc_positions ... ON CONFLICT DO UPDATE"), ...)
    conn.execute(text("INSERT INTO cmc_order_events ..."), ...)
```

**Dead-letter isolation:**
```python
def _write_dead_letter(engine, ...):
    with engine.begin() as conn:  # OWN connection, not the failed one
        conn.execute(text("INSERT INTO cmc_order_dead_letter ..."), ...)
```

**Decimal -> SQL conversion:**
All Decimal values passed via `str()`:
```python
"fill_qty": str(fill_data.fill_qty),
"quantity": str(pos_update["quantity"]),
```

**Partial vs final fill detection:**
```python
new_remaining = Decimal(str(order.quantity)) - new_filled_qty
to_status = "filled" if new_remaining <= Decimal("0") else "partial_fill"
```

## Verification Results

```
python -c "from ta_lab2.trading import OrderManager, FillData, VALID_TRANSITIONS, compute_position_update; print('imports OK')"
imports OK

python -m pytest tests/trading/ -v
71 passed in 2.27s
```

## Deviations from Plan

None -- plan executed exactly as written.

## Next Phase Readiness

**Phase 45 (Paper-Trade Executor)** can import:
```python
from ta_lab2.trading import OrderManager, FillData
# Process each simulated fill:
fill_id = OrderManager.process_fill(engine, FillData(
    order_id=order_id,
    fill_qty=Decimal("1.0"),
    fill_price=Decimal("50000.00"),
))
```

The OrderManager is the primary building block Phase 45 needs. All 4-table atomic writes are encapsulated and tested.
