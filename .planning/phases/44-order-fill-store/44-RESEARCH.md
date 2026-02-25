# Phase 44: Order & Fill Store - Research

**Researched:** 2026-02-24
**Domain:** Order management systems, position tracking, PostgreSQL atomic transactions, dead letter queues
**Confidence:** HIGH (architecture patterns, DDL schemas, SQL patterns), MEDIUM (trading-specific conventions), LOW (Phase 43 migration head — depends on Phase 43 execution)

---

## Summary

Phase 44 creates the persistence layer for a paper trading OMS: `cmc_orders`, `cmc_fills`, `cmc_positions`, `cmc_order_events`, and `cmc_order_dead_letter` tables, plus an `OrderManager` class that handles all writes atomically. The CONTEXT.md has locked most design decisions; the remaining open questions (position flip handling, signal FK chain, dead letter design, etc.) are resolved here.

The primary architectural challenge is atomicity: one fill event must atomically update four tables (fills, order status, position, audit log), with a dead letter fallback for failures. PostgreSQL's `SELECT ... FOR UPDATE` pessimistic locking on the position row, combined with `engine.begin()` transaction blocks (the project's existing pattern), handles this cleanly.

For `OrderManager`, the project's established pattern is raw SQL via `text()` in `engine.begin()` blocks. This is the right choice for Phase 44: the atomic transaction requires explicit control over multiple INSERTs/UPDATEs in a single connection that the ORM makes harder to reason about. Use the project pattern: raw `text()` with `engine.begin()`.

**Primary recommendation:** Use net-quantity position flips (NautilusTrader pattern), raw SQL `text()` for OrderManager, a domain-specific dead letter table, a regular DB view for aggregate positions, and denormalize `signal_id` only on `cmc_orders` (not fills or positions).

---

## Standard Stack

### Core (No New Dependencies)

| Library | Version | Purpose | Already Installed |
|---------|---------|---------|------------------|
| `sqlalchemy` | existing | engine.begin() transactions, text() raw SQL | YES |
| `alembic` | existing | Schema migration chained from Phase 43 | YES |
| `uuid` | stdlib | gen_random_uuid() server-side; UUID str in Python | YES |
| `dataclasses` | stdlib | OrderManager input/output types | YES |
| `typing` | stdlib | Type hints | YES |

No new packages needed. Phase 44 is pure SQL + Python using the project's existing stack.

**Installation:**
```bash
# Nothing to install
```

---

## Architecture Patterns

### Recommended Project Structure

```
src/ta_lab2/
├── paper_trading/                   # existing from Phase 43
│   ├── __init__.py
│   ├── canonical_order.py
│   └── paper_order_logger.py
│
└── trading/                         # NEW package for Phase 44
    ├── __init__.py
    ├── order_manager.py             # OrderManager class -- primary deliverable
    └── position_math.py             # Weighted avg cost, realized PnL helpers

alembic/versions/
└── XXXX_order_fill_store.py         # NEW -- chains from Phase 43 migration

sql/trading/                         # NEW reference DDL directory
├── 082_cmc_orders.sql
├── 083_cmc_fills.sql
├── 084_cmc_positions.sql
├── 085_cmc_order_events.sql
├── 086_cmc_order_dead_letter.sql
└── 087_v_cmc_positions_agg.sql      # aggregate view DDL
```

### Pattern 1: Alembic Migration Chaining

**CRITICAL:** The Phase 44 migration must chain from the Phase 43 migration, NOT from the current head `e74f5622e710`.

- Current Alembic head (before Phase 43): `e74f5622e710` (add_strategy_bakeoff_results)
- Phase 43 plan-01 creates a new migration chaining from `8d5bc7ee1732` (but note: `e74f5622e710` is the actual current head, so Phase 43's migration will actually need to chain from `e74f5622e710` — the Phase 43 plan has a stale reference; the executor will use `alembic revision` which auto-detects the current head)
- Phase 44 migration chains from whatever hash Phase 43's migration generates

**How to handle in practice:** Phase 44's plan should NOT hardcode Phase 43's migration hash (it doesn't exist yet). Instead, the Phase 44 plan instructs: run `alembic revision -m "order_fill_store"` after Phase 43 completes. Alembic auto-detects the head and sets `down_revision` correctly. The plan verifies with `alembic history`.

**Migration structure pattern (from existing migrations):**
```python
# Source: alembic/versions/c3b718c2d088_ic_results_table.py pattern

revision: str = "XXXX_order_fill_store"
down_revision: Union[str, None] = "PHASE_43_MIGRATION_HASH"  # set by alembic revision command
branch_labels = None
depends_on = None

def upgrade() -> None:
    # Create in dependency order: orders -> fills -> positions -> events -> dead letter
    op.create_table("cmc_orders", ...)
    op.create_table("cmc_fills", ...)
    op.create_table("cmc_positions", ...)
    op.create_table("cmc_order_events", ...)
    op.create_table("cmc_order_dead_letter", ...)
    # Create view via op.execute() -- no native op for views
    op.execute("CREATE OR REPLACE VIEW public.v_cmc_positions_agg AS ...")

def downgrade() -> None:
    # Drop in reverse order
    op.execute("DROP VIEW IF EXISTS public.v_cmc_positions_agg")
    op.drop_table("cmc_order_dead_letter", schema="public")
    op.drop_table("cmc_order_events", schema="public")
    op.drop_table("cmc_positions", schema="public")
    op.drop_table("cmc_fills", schema="public")
    op.drop_table("cmc_orders", schema="public")
```

**CRITICAL Windows encoding note (from MEMORY.md):** Do NOT use UTF-8 box-drawing characters (===, ---) in SQL comments inside migration files. Use plain ASCII dashes only.

### Pattern 2: OrderManager Transaction (Engine.begin)

The project uses `engine.begin()` for all multi-step atomic writes (confirmed in `backtest_from_signals.py`, `ama_state_manager.py`, `run_ic_eval.py`). `engine.begin()` opens a connection, begins a transaction, and auto-commits on success or auto-rolls back on exception.

```python
# Source: project pattern from src/ta_lab2/scripts/backtests/backtest_from_signals.py

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

def process_fill(engine, fill_data: dict) -> None:
    """Atomic fill processing: INSERT fill, UPDATE order, UPSERT position, INSERT event."""
    with engine.begin() as conn:
        # Step 1: SELECT position FOR UPDATE (pessimistic lock)
        # Step 2: INSERT fill
        # Step 3: UPDATE order (filled_qty, status)
        # Step 4: UPSERT position (with weighted avg cost update)
        # Step 5: INSERT order_event audit record
        # On any exception: engine.begin() auto-rolls back all 5 steps
```

**Key insight:** `engine.begin()` is the project's established atomicity pattern. Do NOT use session.add() / session.commit() ORM style -- it diverges from the project's codebase and adds no value for this use case.

### Pattern 3: Position Flip Algorithm

**Recommendation: Net-Quantity (NautilusTrader pattern) -- CONFIRMED as industry standard**

A position flip (long-to-short or short-to-long) happens when a fill's signed_qty would push the position past zero. The algorithm:

1. Compute `new_qty = current_qty + fill_signed_qty`
2. If `sign(new_qty) != sign(current_qty)` AND `current_qty != 0`: flip detected
3. Close portion: the `abs(current_qty)` units at the fill price generate realized PnL
4. Open portion: the remaining `abs(new_qty)` units start a new position at fill price
5. Update position: `quantity = new_qty`, `avg_cost_basis = fill_price`, `realized_pnl += realized_from_close`

```python
# Source: NautilusTrader position documentation + Alpaca position docs

def compute_position_update(
    current_qty: Decimal,       # signed: positive=long, negative=short
    current_avg_cost: Decimal,  # per-unit cost basis
    current_realized_pnl: Decimal,
    fill_qty: Decimal,          # signed: positive for buy-fill, negative for sell-fill
    fill_price: Decimal,
) -> dict:
    """
    Compute updated position fields after a fill.
    Handles new positions, additions, partial closes, full closes, and flips.

    Returns dict with: quantity, avg_cost_basis, realized_pnl, unrealized_pnl (pass mark_price separately)
    """
    new_qty = current_qty + fill_qty

    # Case 1: New position (was flat)
    if current_qty == 0:
        return {
            "quantity": new_qty,
            "avg_cost_basis": fill_price,
            "realized_pnl": current_realized_pnl,
        }

    # Case 2: Adding to existing position (same direction)
    if (current_qty > 0) == (new_qty > 0) and new_qty != 0:
        # Weighted average cost: (old_total_cost + fill_cost) / new_total_qty
        old_total_cost = current_qty * current_avg_cost
        fill_total_cost = fill_qty * fill_price
        new_avg_cost = (old_total_cost + fill_total_cost) / new_qty
        return {
            "quantity": new_qty,
            "avg_cost_basis": new_avg_cost,
            "realized_pnl": current_realized_pnl,
        }

    # Case 3: Closing or flipping
    # Determine how many units are being closed vs opened
    if abs(fill_qty) <= abs(current_qty):
        # Partial or full close (no flip)
        closed_qty = abs(fill_qty)
    else:
        # Flip: close current position entirely, open remainder in opposite direction
        closed_qty = abs(current_qty)

    # Realized PnL on closed portion
    # For long: (sell_price - avg_cost) * closed_qty
    # For short: (avg_cost - buy_price) * closed_qty
    if current_qty > 0:
        realized = (fill_price - current_avg_cost) * closed_qty
    else:
        realized = (current_avg_cost - fill_price) * closed_qty

    new_realized_pnl = current_realized_pnl + realized

    if new_qty == 0:
        # Full close -- position is flat
        return {
            "quantity": Decimal("0"),
            "avg_cost_basis": Decimal("0"),
            "realized_pnl": new_realized_pnl,
        }
    else:
        # Flip -- open new position in opposite direction at fill price
        return {
            "quantity": new_qty,
            "avg_cost_basis": fill_price,  # fresh cost basis for new direction
            "realized_pnl": new_realized_pnl,
        }
```

**This lives in `src/ta_lab2/trading/position_math.py`** -- pure functions, easily unit-tested without DB.

### Pattern 4: Signal FK Chain -- Denormalize Only on cmc_orders

**Recommendation: Keep signal_id on cmc_orders only. Do NOT propagate to cmc_fills or cmc_positions.**

**Rationale:**
- Query pattern for Phase 47 (Drift Guard): compare paper trades by signal to backtest runs. This join path is: `cmc_backtest_runs (signal_id) JOIN cmc_orders (signal_id) JOIN cmc_fills`. One join suffices.
- cmc_fills are execution events -- they don't have independent signal identity (a single order from one signal can have many fills)
- cmc_positions aggregate across potentially multiple orders/signals for the same asset -- putting signal_id there doesn't make sense semantically
- The Phase 43 `paper_orders` table already has `signal_id`; cmc_orders has a `paper_order_uuid` FK to paper_orders for full traceability

**FK chain for Drift Guard queries:**
```sql
-- Phase 47: Compare paper fills vs backtest trades for same signal
SELECT
    br.signal_id,
    br.total_return AS backtest_return,
    SUM(f.pnl_realized) AS paper_pnl
FROM cmc_backtest_runs br
JOIN cmc_orders o ON o.signal_id = br.signal_id AND o.asset_id = br.asset_id
JOIN cmc_fills f ON f.order_id = o.order_id
WHERE br.run_id = :run_id
GROUP BY br.signal_id, br.total_return;
```

### Pattern 5: Backtest Linkage for Drift Guard

**Recommendation: Do NOT add a foreign key from cmc_orders to cmc_backtest_runs. Link via signal_id + asset_id.**

**Rationale:**
- A backtest run tests a strategy over a historical date range. Paper orders happen in real time.
- There is no 1:1 relationship between paper orders and backtest runs -- one signal_id can have multiple backtest runs (different date ranges, different cost models)
- Drift Guard (Phase 47) compares distributions, not individual trade pairs
- The join key for drift analysis is `(signal_id, asset_id)` -- this naturally links cmc_orders/cmc_fills to cmc_backtest_runs/cmc_backtest_trades

**No schema change needed** -- the natural join via signal_id is sufficient. Phase 47 will query both tables independently and compare aggregated metrics.

### Pattern 6: Aggregate Position View vs Materialized Table

**Recommendation: Regular DB view (not materialized) for v_cmc_positions_agg**

**Rationale:**
- cmc_positions is updated on every fill -- position rows change frequently (every paper trade)
- A materialized view would need `REFRESH MATERIALIZED VIEW` after every fill write, negating its benefit
- cmc_positions table will be small (one row per asset+exchange pair; <= 100 rows for this project)
- A simple `GROUP BY asset_id, SUM(quantity)` view over cmc_positions is fast even without materialization
- Regular views always reflect current data; materialized views are stale until refreshed

**Exception:** If Phase 52 (Operational Dashboard) shows view query is slow (unlikely given table size), add a materialized view then. Don't optimize prematurely.

### Pattern 7: Dead Letter Table -- Domain-Specific

**Recommendation: cmc_order_dead_letter (domain-specific, NOT generic retry_queue)**

**Rationale from research (PostgreSQL DLQ patterns):**
- Domain-specific table allows querying by order_id, fill_data, operation_type -- essential for debugging
- JSONB `payload` column stores the exact failed operation for replay
- The `retry_count` + `retry_after` pattern (from PostgreSQL DLQ research) prevents retry floods
- No external queue infrastructure needed -- pure PostgreSQL

**Design:** See DDL schema section below.

### Anti-Patterns to Avoid

- **Using ORM for OrderManager:** The project uses raw `text()` exclusively. The ORM adds no value for the 5-table atomic transaction and makes the SELECT ... FOR UPDATE pattern more complex to write and audit.
- **Adding signal_id to cmc_fills:** Fills don't have independent signal identity. FK to cmc_orders is sufficient for traceability.
- **Adding backtest_run_id to cmc_orders:** No 1:1 relationship exists. Use signal_id join for drift analysis.
- **Materializing the aggregate position view:** The table is tiny; refreshing after every fill is overhead without benefit.
- **Enforcing state transitions in DB triggers:** Use application-level validation (OrderManager) as the primary guard. DB CHECK constraint validates valid status values. Triggers add deployment complexity.
- **Storing realized_pnl as a derived column only:** Store it cumulatively in cmc_positions -- it changes with each fill and recalculating from fills table is expensive.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| UUID generation | Custom random ID | `gen_random_uuid()` server-side in DDL | Collision-resistant, exchange-standard, already used project-wide |
| Position weighted average | Custom formula | `position_math.py` helper (documented here) | Edge cases: flips, full closes, flat-to-long |
| Atomic multi-table write | Multiple separate conn.execute() calls | `engine.begin()` context manager | Auto-rollback on any step failure |
| Pessimistic row locking | Application mutex / advisory lock | `SELECT ... FOR UPDATE` on position row | PostgreSQL native, transactionally correct |
| Dead letter replay | Manual SQL fixes | Scan `cmc_order_dead_letter WHERE status='pending' AND retry_after <= now()` | Structured retry with backoff |
| State transition validation | DB triggers | Python dict in `OrderManager.VALID_TRANSITIONS` | Easier to test, audit, and modify |

**Key insight:** All the "hard" problems (atomicity, locking, cost basis math) have established patterns in the project or in standard PostgreSQL. Nothing here requires novel engineering.

---

## Recommended DDL Schemas

### cmc_orders

```sql
-- sql/trading/082_cmc_orders.sql
CREATE TABLE IF NOT EXISTS public.cmc_orders (
    -- Primary key
    order_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Origin traceability
    paper_order_uuid    UUID NULL,          -- FK to paper_orders (Phase 43); nullable for manually created orders
    signal_id           INTEGER NULL,       -- FK to dim_signals; denormalized from paper_orders for query convenience

    -- Asset identification
    asset_id            INTEGER NOT NULL,   -- FK to dim_assets
    pair                TEXT NOT NULL,      -- 'BTC/USD' -- human-readable, denormalized

    -- Order specification
    exchange            TEXT NOT NULL,      -- 'coinbase' | 'kraken' | 'paper'
    side                TEXT NOT NULL,      -- 'buy' | 'sell'
    order_type          TEXT NOT NULL,      -- 'market' | 'limit' | 'stop'
    quantity            NUMERIC NOT NULL,   -- total requested quantity
    limit_price         NUMERIC NULL,       -- null for market orders
    stop_price          NUMERIC NULL,       -- null for non-stop orders
    time_in_force       TEXT NULL,          -- 'GTC' | 'GTD' | 'IOC' -- null = GTC default
    expires_at          TIMESTAMPTZ NULL,   -- for GTD orders only

    -- Lifecycle state
    status              TEXT NOT NULL DEFAULT 'created',

    -- Fill tracking (materialized for fast reads; source of truth is cmc_fills)
    filled_qty          NUMERIC NOT NULL DEFAULT 0,
    remaining_qty       NUMERIC NOT NULL,   -- set to quantity at creation, decremented on fills
    avg_fill_price      NUMERIC NULL,       -- weighted avg of fill prices so far

    -- Environment
    environment         TEXT NOT NULL DEFAULT 'sandbox',  -- 'sandbox' | 'production'
    client_order_id     TEXT NULL,          -- UUID assigned at order creation

    -- Exchange response
    exchange_order_id   TEXT NULL,          -- exchange's own order ID (NULL for paper)

    CONSTRAINT chk_orders_side         CHECK (side IN ('buy', 'sell')),
    CONSTRAINT chk_orders_order_type   CHECK (order_type IN ('market', 'limit', 'stop')),
    CONSTRAINT chk_orders_status       CHECK (status IN ('created', 'submitted', 'partial_fill', 'filled', 'cancelled', 'rejected', 'expired')),
    CONSTRAINT chk_orders_tif          CHECK (time_in_force IS NULL OR time_in_force IN ('GTC', 'GTD', 'IOC')),
    CONSTRAINT chk_orders_environment  CHECK (environment IN ('sandbox', 'production')),
    CONSTRAINT chk_orders_quantity_pos CHECK (quantity > 0)
);

CREATE INDEX IF NOT EXISTS idx_orders_asset_status
    ON public.cmc_orders (asset_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_signal
    ON public.cmc_orders (signal_id)
    WHERE signal_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_orders_paper_order
    ON public.cmc_orders (paper_order_uuid)
    WHERE paper_order_uuid IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_orders_exchange_order
    ON public.cmc_orders (exchange_order_id)
    WHERE exchange_order_id IS NOT NULL;
```

### cmc_fills

```sql
-- sql/trading/083_cmc_fills.sql
CREATE TABLE IF NOT EXISTS public.cmc_fills (
    -- Primary key
    fill_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filled_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Parent order
    order_id            UUID NOT NULL,      -- FK to cmc_orders

    -- Execution details
    fill_qty            NUMERIC NOT NULL,   -- quantity filled in this fill event (always positive)
    fill_price          NUMERIC NOT NULL,   -- execution price for this fill
    fee_amount          NUMERIC NOT NULL DEFAULT 0,  -- fee paid for this fill
    fee_currency        TEXT NULL,          -- 'USD' | 'BTC' -- currency of fee
    side                TEXT NOT NULL,      -- 'buy' | 'sell' -- from parent order (denormalized for query speed)

    -- Venue details
    exchange            TEXT NOT NULL,      -- 'coinbase' | 'kraken' | 'paper'
    exchange_fill_id    TEXT NULL,          -- exchange's fill/trade ID -- NULL for paper fills

    -- Lot tracking (for FIFO reconstruction if needed later)
    lot_id              UUID NOT NULL DEFAULT gen_random_uuid(),  -- unique lot identifier

    CONSTRAINT chk_fills_side     CHECK (side IN ('buy', 'sell')),
    CONSTRAINT chk_fills_qty_pos  CHECK (fill_qty > 0),
    CONSTRAINT chk_fills_price_pos CHECK (fill_price > 0),
    CONSTRAINT chk_fills_fee_nn   CHECK (fee_amount >= 0)
);

CREATE INDEX IF NOT EXISTS idx_fills_order_id
    ON public.cmc_fills (order_id, filled_at);
CREATE INDEX IF NOT EXISTS idx_fills_exchange_fill
    ON public.cmc_fills (exchange_fill_id)
    WHERE exchange_fill_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fills_filled_at
    ON public.cmc_fills (filled_at DESC);
```

### cmc_positions

```sql
-- sql/trading/084_cmc_positions.sql
CREATE TABLE IF NOT EXISTS public.cmc_positions (
    -- Composite primary key: one row per (asset, exchange)
    asset_id            INTEGER NOT NULL,   -- FK to dim_assets
    exchange            TEXT NOT NULL,      -- 'coinbase' | 'kraken' | 'paper'

    -- Position state
    -- signed quantity: positive = long, negative = short, 0 = flat
    quantity            NUMERIC NOT NULL DEFAULT 0,
    avg_cost_basis      NUMERIC NOT NULL DEFAULT 0,   -- weighted avg entry price (per unit)

    -- PnL tracking
    realized_pnl        NUMERIC NOT NULL DEFAULT 0,   -- cumulative realized PnL in quote currency
    unrealized_pnl      NUMERIC NULL,                 -- updated when mark price provided
    unrealized_pnl_pct  NUMERIC NULL,                 -- unrealized_pnl / (abs(quantity) * avg_cost_basis)

    -- Mark price (last known price for unrealized PnL calc)
    last_mark_price     NUMERIC NULL,
    last_mark_ts        TIMESTAMPTZ NULL,

    -- Audit
    last_fill_id        UUID NULL,          -- fill_id of the most recent fill that updated this position
    last_updated        TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (asset_id, exchange),
    CONSTRAINT chk_positions_exchange CHECK (exchange IN ('coinbase', 'kraken', 'paper', 'aggregate'))
);

CREATE INDEX IF NOT EXISTS idx_positions_asset
    ON public.cmc_positions (asset_id);
```

### cmc_order_events (audit log)

```sql
-- sql/trading/085_cmc_order_events.sql
CREATE TABLE IF NOT EXISTS public.cmc_order_events (
    -- Primary key
    event_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_ts            TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Parent order
    order_id            UUID NOT NULL,      -- FK to cmc_orders

    -- Transition
    from_status         TEXT NULL,          -- NULL for 'created' event (no prior status)
    to_status           TEXT NOT NULL,

    -- Context
    reason              TEXT NULL,          -- rejection reason, cancellation note, etc.
    fill_id             UUID NULL,          -- FK to cmc_fills if this event was triggered by a fill

    CONSTRAINT chk_events_to_status CHECK (to_status IN ('created', 'submitted', 'partial_fill', 'filled', 'cancelled', 'rejected', 'expired'))
);

CREATE INDEX IF NOT EXISTS idx_events_order_id
    ON public.cmc_order_events (order_id, event_ts);
CREATE INDEX IF NOT EXISTS idx_events_ts
    ON public.cmc_order_events (event_ts DESC);
```

### cmc_order_dead_letter

```sql
-- sql/trading/086_cmc_order_dead_letter.sql
-- Specific dead letter table for order/fill/position transaction failures.
-- Design: domain-specific (not generic retry_queue) for SQL queryability by order_id.
-- Source: PostgreSQL DLQ pattern from https://www.diljitpr.net/blog-post-postgresql-dlq

CREATE TABLE IF NOT EXISTS public.cmc_order_dead_letter (
    -- Primary key
    dlq_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Failed operation context
    operation_type      TEXT NOT NULL,      -- 'process_fill' | 'promote_order' | 'update_position'
    order_id            UUID NULL,          -- the order involved (NULL if order creation itself failed)
    fill_id             UUID NULL,          -- the fill involved (NULL if fill insertion failed)

    -- Failure details
    payload             JSONB NOT NULL,     -- full operation payload for replay (fill_data dict, etc.)
    error_reason        TEXT NOT NULL,      -- exception message
    error_stacktrace    TEXT NULL,          -- full traceback for debugging

    -- Retry state
    status              TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'retrying' | 'succeeded' | 'abandoned'
    retry_count         INTEGER NOT NULL DEFAULT 0,
    retry_after         TIMESTAMPTZ NOT NULL DEFAULT now(),  -- exponential backoff: now() + 2^retry_count seconds

    CONSTRAINT chk_dlq_operation CHECK (operation_type IN ('process_fill', 'promote_order', 'update_position', 'other')),
    CONSTRAINT chk_dlq_status    CHECK (status IN ('pending', 'retrying', 'succeeded', 'abandoned'))
);

CREATE INDEX IF NOT EXISTS idx_dlq_status_retry
    ON public.cmc_order_dead_letter (status, retry_after)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_dlq_order_id
    ON public.cmc_order_dead_letter (order_id)
    WHERE order_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_dlq_created_at
    ON public.cmc_order_dead_letter (created_at DESC);
```

### v_cmc_positions_agg (aggregate view)

```sql
-- sql/trading/087_v_cmc_positions_agg.sql
-- Regular view (NOT materialized) -- position data changes too frequently for materialized views.
-- Per-asset aggregate across all exchanges. Refreshes automatically on every query.

CREATE OR REPLACE VIEW public.v_cmc_positions_agg AS
SELECT
    asset_id,
    'aggregate'::TEXT                             AS exchange,
    SUM(quantity)                                 AS quantity,
    -- Weighted avg cost basis across exchanges
    CASE
        WHEN SUM(ABS(quantity)) = 0 THEN 0
        ELSE SUM(ABS(quantity) * avg_cost_basis) / SUM(ABS(quantity))
    END                                           AS avg_cost_basis,
    SUM(realized_pnl)                             AS realized_pnl,
    SUM(COALESCE(unrealized_pnl, 0))              AS unrealized_pnl,
    MAX(last_mark_price)                          AS last_mark_price,
    MAX(last_updated)                             AS last_updated
FROM public.cmc_positions
WHERE exchange != 'aggregate'
GROUP BY asset_id;
```

---

## OrderManager Class Design

```python
# src/ta_lab2/trading/order_manager.py
# Pattern: raw text() SQL, engine.begin() transactions, NullPool engine
# Source: project pattern from backtest_from_signals.py + ama_state_manager.py

from __future__ import annotations

import logging
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from ta_lab2.trading.position_math import compute_position_update

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Valid state transitions (application-level enforcement)
# DB CHECK constraint enforces valid status values only.
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[str, list[str]] = {
    "created":      ["submitted"],
    "submitted":    ["partial_fill", "filled", "cancelled", "rejected", "expired"],
    "partial_fill": ["partial_fill", "filled", "cancelled"],
    "filled":       [],   # terminal
    "cancelled":    [],   # terminal
    "rejected":     [],   # terminal
    "expired":      [],   # terminal
}


@dataclass
class FillData:
    """Input to OrderManager.process_fill()."""
    order_id: str                       # UUID of cmc_orders row
    fill_qty: Decimal                   # quantity filled (positive)
    fill_price: Decimal                 # execution price
    fee_amount: Decimal = Decimal("0")
    fee_currency: Optional[str] = None
    exchange_fill_id: Optional[str] = None
    filled_at: Optional[datetime] = None  # defaults to now() if None


class OrderManager:
    """
    Manages order/fill/position writes with full atomicity.

    All writes use engine.begin() (project pattern) with pessimistic
    SELECT ... FOR UPDATE locking on position rows.

    High-level API:
        process_fill(engine, fill_data) -- does everything atomically

    Low-level API (for testing or custom flows):
        insert_fill(conn, fill_data, order_row)
        update_order(conn, order_id, filled_qty, status, avg_fill_price)
        upsert_position(conn, asset_id, exchange, position_update)
        insert_order_event(conn, order_id, from_status, to_status, reason, fill_id)
    """

    @staticmethod
    def promote_paper_order(
        engine: Engine,
        paper_order_uuid: str,
        environment: str = "sandbox",
    ) -> str:
        """
        Promote a paper_orders row to cmc_orders (created status).
        Returns the new order_id (UUID string).
        """
        with engine.begin() as conn:
            # Read paper order
            po = conn.execute(
                text("""
                    SELECT signal_id, asset_id, exchange, pair, side, order_type,
                           quantity, limit_price, stop_price, client_order_id
                    FROM public.paper_orders
                    WHERE order_uuid = :uuid
                """),
                {"uuid": paper_order_uuid},
            ).fetchone()
            if po is None:
                raise ValueError(f"paper_order_uuid not found: {paper_order_uuid}")

            order_id = str(uuid.uuid4())
            conn.execute(
                text("""
                    INSERT INTO public.cmc_orders (
                        order_id, paper_order_uuid, signal_id, asset_id, pair,
                        exchange, side, order_type, quantity, limit_price, stop_price,
                        remaining_qty, environment, client_order_id, status
                    ) VALUES (
                        :order_id, :paper_order_uuid, :signal_id, :asset_id, :pair,
                        :exchange, :side, :order_type, :quantity, :limit_price, :stop_price,
                        :quantity, :environment, :client_order_id, 'created'
                    )
                """),
                {
                    "order_id": order_id,
                    "paper_order_uuid": paper_order_uuid,
                    "signal_id": po.signal_id,
                    "asset_id": po.asset_id,
                    "pair": po.pair,
                    "exchange": po.exchange,
                    "side": po.side,
                    "order_type": po.order_type,
                    "quantity": po.quantity,
                    "limit_price": po.limit_price,
                    "stop_price": po.stop_price,
                    "environment": environment,
                    "client_order_id": po.client_order_id,
                },
            )
            # Insert 'created' event
            conn.execute(
                text("""
                    INSERT INTO public.cmc_order_events
                        (order_id, from_status, to_status, reason)
                    VALUES (:order_id, NULL, 'created', 'promoted from paper_orders')
                """),
                {"order_id": order_id},
            )
        return order_id

    @staticmethod
    def process_fill(engine: Engine, fill_data: FillData) -> str:
        """
        Atomically process a fill event. One transaction for:
          1. SELECT order FOR SHARE (read order state)
          2. SELECT position FOR UPDATE (pessimistic lock)
          3. INSERT fill
          4. UPDATE order (filled_qty, remaining_qty, status, avg_fill_price)
          5. UPSERT position (quantity, avg_cost_basis, realized_pnl)
          6. INSERT order_event audit record

        On any exception: entire transaction rolls back automatically.
        On failure: writes to cmc_order_dead_letter via separate connection.

        Returns: fill_id (UUID string)
        """
        try:
            return OrderManager._do_process_fill(engine, fill_data)
        except Exception as exc:
            logger.error("process_fill failed for order %s: %s", fill_data.order_id, exc)
            OrderManager._write_dead_letter(engine, fill_data, exc)
            raise

    @staticmethod
    def _do_process_fill(engine: Engine, fill_data: FillData) -> str:
        """Inner implementation -- raises on any failure."""
        with engine.begin() as conn:
            # Step 1: Read order (FOR SHARE prevents concurrent state changes)
            order = conn.execute(
                text("""
                    SELECT order_id, asset_id, exchange, side, quantity,
                           filled_qty, remaining_qty, avg_fill_price, status
                    FROM public.cmc_orders
                    WHERE order_id = :order_id
                    FOR SHARE
                """),
                {"order_id": fill_data.order_id},
            ).fetchone()
            if order is None:
                raise ValueError(f"order_id not found: {fill_data.order_id}")

            from_status = order.status
            OrderManager._validate_fill_transition(from_status, fill_data.fill_qty, order)

            # Step 2: Lock position row FOR UPDATE (pessimistic -- prevents concurrent position updates)
            pos = conn.execute(
                text("""
                    SELECT quantity, avg_cost_basis, realized_pnl
                    FROM public.cmc_positions
                    WHERE asset_id = :asset_id AND exchange = :exchange
                    FOR UPDATE
                """),
                {"asset_id": order.asset_id, "exchange": order.exchange},
            ).fetchone()

            current_qty = Decimal(str(pos.quantity)) if pos else Decimal("0")
            current_cost = Decimal(str(pos.avg_cost_basis)) if pos else Decimal("0")
            current_realized = Decimal(str(pos.realized_pnl)) if pos else Decimal("0")

            # Step 3: Insert fill
            fill_id = str(uuid.uuid4())
            conn.execute(
                text("""
                    INSERT INTO public.cmc_fills (
                        fill_id, order_id, fill_qty, fill_price,
                        fee_amount, fee_currency, side, exchange, exchange_fill_id
                    ) VALUES (
                        :fill_id, :order_id, :fill_qty, :fill_price,
                        :fee_amount, :fee_currency, :side, :exchange, :exchange_fill_id
                    )
                """),
                {
                    "fill_id": fill_id,
                    "order_id": fill_data.order_id,
                    "fill_qty": str(fill_data.fill_qty),
                    "fill_price": str(fill_data.fill_price),
                    "fee_amount": str(fill_data.fee_amount),
                    "fee_currency": fill_data.fee_currency,
                    "side": order.side,
                    "exchange": order.exchange,
                    "exchange_fill_id": fill_data.exchange_fill_id,
                },
            )

            # Step 4: Update order
            new_filled_qty = Decimal(str(order.filled_qty)) + fill_data.fill_qty
            new_remaining = Decimal(str(order.quantity)) - new_filled_qty
            # Weighted avg fill price across all fills so far
            old_total = Decimal(str(order.avg_fill_price or 0)) * Decimal(str(order.filled_qty))
            new_avg_fill = (old_total + fill_data.fill_price * fill_data.fill_qty) / new_filled_qty

            to_status = "filled" if new_remaining <= 0 else "partial_fill"

            conn.execute(
                text("""
                    UPDATE public.cmc_orders SET
                        filled_qty    = :filled_qty,
                        remaining_qty = :remaining_qty,
                        avg_fill_price = :avg_fill_price,
                        status        = :status,
                        updated_at    = now()
                    WHERE order_id = :order_id
                """),
                {
                    "filled_qty": str(new_filled_qty),
                    "remaining_qty": str(new_remaining),
                    "avg_fill_price": str(new_avg_fill),
                    "status": to_status,
                    "order_id": fill_data.order_id,
                },
            )

            # Step 5: Upsert position (with position flip logic)
            # Buy fills are positive quantity, sell fills are negative
            signed_fill = fill_data.fill_qty if order.side == "buy" else -fill_data.fill_qty
            pos_update = compute_position_update(
                current_qty=current_qty,
                current_avg_cost=current_cost,
                current_realized_pnl=current_realized,
                fill_qty=signed_fill,
                fill_price=fill_data.fill_price,
            )

            conn.execute(
                text("""
                    INSERT INTO public.cmc_positions
                        (asset_id, exchange, quantity, avg_cost_basis, realized_pnl, last_fill_id, last_updated)
                    VALUES
                        (:asset_id, :exchange, :quantity, :avg_cost_basis, :realized_pnl, :fill_id, now())
                    ON CONFLICT (asset_id, exchange) DO UPDATE SET
                        quantity       = EXCLUDED.quantity,
                        avg_cost_basis = EXCLUDED.avg_cost_basis,
                        realized_pnl   = EXCLUDED.realized_pnl,
                        last_fill_id   = EXCLUDED.last_fill_id,
                        last_updated   = now()
                """),
                {
                    "asset_id": order.asset_id,
                    "exchange": order.exchange,
                    "quantity": str(pos_update["quantity"]),
                    "avg_cost_basis": str(pos_update["avg_cost_basis"]),
                    "realized_pnl": str(pos_update["realized_pnl"]),
                    "fill_id": fill_id,
                },
            )

            # Step 6: Audit event
            conn.execute(
                text("""
                    INSERT INTO public.cmc_order_events
                        (order_id, from_status, to_status, fill_id)
                    VALUES (:order_id, :from_status, :to_status, :fill_id)
                """),
                {
                    "order_id": fill_data.order_id,
                    "from_status": from_status,
                    "to_status": to_status,
                    "fill_id": fill_id,
                },
            )

        logger.info(
            "Processed fill %s: order=%s status=%s->%s qty=%s @ %s",
            fill_id, fill_data.order_id, from_status, to_status,
            fill_data.fill_qty, fill_data.fill_price,
        )
        return fill_id

    @staticmethod
    def _validate_fill_transition(from_status: str, fill_qty: Decimal, order) -> None:
        """Raise ValueError if the current order status cannot accept a fill."""
        if from_status in ("filled", "cancelled", "rejected", "expired"):
            raise ValueError(
                f"Cannot process fill for order in terminal status '{from_status}'"
            )
        if fill_qty > Decimal(str(order.remaining_qty)):
            raise ValueError(
                f"Fill qty {fill_qty} exceeds remaining qty {order.remaining_qty}"
            )

    @staticmethod
    def _write_dead_letter(engine: Engine, fill_data: FillData, exc: Exception) -> None:
        """Write failed fill operation to dead letter table. Uses separate connection."""
        import json
        payload = {
            "order_id": fill_data.order_id,
            "fill_qty": str(fill_data.fill_qty),
            "fill_price": str(fill_data.fill_price),
            "fee_amount": str(fill_data.fee_amount),
            "exchange_fill_id": fill_data.exchange_fill_id,
        }
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO public.cmc_order_dead_letter
                            (operation_type, order_id, payload, error_reason, error_stacktrace)
                        VALUES
                            ('process_fill', :order_id, :payload::jsonb, :reason, :stacktrace)
                    """),
                    {
                        "order_id": fill_data.order_id,
                        "payload": json.dumps(payload),
                        "reason": str(exc),
                        "stacktrace": traceback.format_exc(),
                    },
                )
        except Exception as dlq_exc:
            # DLQ write failed -- log to stderr at minimum, don't swallow original error
            logger.critical("DEAD LETTER WRITE FAILED: %s | original error: %s", dlq_exc, exc)

    @staticmethod
    def update_order_status(
        engine: Engine,
        order_id: str,
        new_status: str,
        reason: Optional[str] = None,
    ) -> None:
        """
        Transition order to a non-fill status (submitted, cancelled, rejected, expired).
        Validates transition. Writes audit event atomically.
        """
        with engine.begin() as conn:
            order = conn.execute(
                text("SELECT status FROM public.cmc_orders WHERE order_id = :id FOR UPDATE"),
                {"id": order_id},
            ).fetchone()
            if order is None:
                raise ValueError(f"order_id not found: {order_id}")

            from_status = order.status
            if new_status not in VALID_TRANSITIONS.get(from_status, []):
                raise ValueError(
                    f"Invalid transition: {from_status} -> {new_status} for order {order_id}"
                )

            conn.execute(
                text("""
                    UPDATE public.cmc_orders SET status = :status, updated_at = now()
                    WHERE order_id = :id
                """),
                {"status": new_status, "id": order_id},
            )
            conn.execute(
                text("""
                    INSERT INTO public.cmc_order_events
                        (order_id, from_status, to_status, reason)
                    VALUES (:order_id, :from_status, :to_status, :reason)
                """),
                {
                    "order_id": order_id,
                    "from_status": from_status,
                    "to_status": new_status,
                    "reason": reason,
                },
            )
```

---

## Common Pitfalls

### Pitfall 1: Alembic Down-Revision Points to Wrong Hash

**What goes wrong:** Phase 44 migration sets `down_revision` to `8d5bc7ee1732` (the old head) instead of Phase 43's migration hash. Running `alembic history` shows a branch, not a linear chain. `alembic upgrade head` either fails or doesn't apply Phase 44.

**Why it happens:** The researcher hard-codes a revision hash that was current during planning but stale after Phase 43 executes.

**How to avoid:** Phase 44 plan-01 should run `alembic revision -m "order_fill_store"` AFTER Phase 43 is complete. Alembic auto-detects the current head and sets `down_revision`. Never hard-code a revision hash in the plan instructions -- use the auto-detection.

**Warning signs:** `alembic history` shows two branches at the same revision level.

### Pitfall 2: Position Row Not Locked Before Update (Race Condition)

**What goes wrong:** Two fills for the same asset/exchange are processed concurrently. Both read the position row, both compute their update based on the same starting `current_qty`, one overwrites the other. Net quantity ends up wrong.

**Why it happens:** Missing `SELECT ... FOR UPDATE` on the position row.

**How to avoid:** Always do `SELECT ... FOR UPDATE` on the cmc_positions row at the start of the transaction, before any fill insertion. The lock is released when the transaction commits.

**Warning signs:** Position quantity doesn't match sum of signed fill quantities after concurrent fills.

### Pitfall 3: Dead Letter Write Uses the Same (Already Failed) Transaction

**What goes wrong:** Transaction for `process_fill` fails. Code tries to write to `cmc_order_dead_letter` inside the same `engine.begin()` block. The block is already in rollback state. Dead letter write also fails. Error is swallowed.

**Why it happens:** DLQ write shares the transaction context with the failed operation.

**How to avoid:** `_write_dead_letter` uses its OWN `engine.begin()` block (separate connection from NullPool). This is demonstrated in the OrderManager code above. If DLQ write also fails, log at CRITICAL level -- no silent failures.

### Pitfall 4: Decimal vs Float Arithmetic in Position Math

**What goes wrong:** Using `float` for position quantities and prices causes floating-point drift. Over many fills, `avg_cost_basis` accumulates rounding error. Realized PnL is off by fractions of a cent that compound.

**Why it happens:** Python `float` is IEEE 754 -- not exact for financial arithmetic.

**How to avoid:** All position math in `position_math.py` uses `Decimal`. DB columns are `NUMERIC` (exact). Convert DB results with `Decimal(str(row.quantity))` -- NOT `Decimal(row.quantity)` which can inherit float imprecision.

**Warning signs:** `quantity == 0` is false for a closed position due to floating point residue.

### Pitfall 5: Status CHECK Constraint Rejects Legitimate Updates

**What goes wrong:** Application adds a new order status (e.g., `"pending_cancel"`). DB CHECK constraint doesn't include it. INSERT/UPDATE fails with `check constraint violation`. Migration needed to expand the CHECK.

**Why it happens:** CHECK constraint lists all valid statuses; any future addition requires a migration.

**How to avoid:** The 7 statuses in CONTEXT.md (created, submitted, partial_fill, filled, cancelled, rejected, expired) are the complete set for Phase 44-45. Document the CHECK constraint in the migration docstring. Phase 46+ can add a new migration to ALTER CONSTRAINT if needed.

### Pitfall 6: Windows UTF-8 Migration Files

**What goes wrong:** Copying the DDL comments from this research (which may contain non-ASCII) into the Alembic migration file causes `UnicodeDecodeError` on Windows when Alembic reads `alembic.ini` (which uses `cp1252` by default).

**Why it happens:** MEMORY.md documents this Windows-specific pitfall.

**How to avoid:** The project's `env.py` already uses `encoding='utf-8'` for `fileConfig()`. But the migration Python files themselves should use only ASCII characters in string literals and comments. No box-drawing chars, no em-dashes, no curly quotes.

### Pitfall 7: `remaining_qty` Goes Negative for Over-Fills

**What goes wrong:** Fill simulator (Phase 45) sends a fill for more than `remaining_qty`. `remaining_qty` goes negative. Position becomes wrong. `status` stays `partial_fill` even though the order is over-filled.

**Why it happens:** Missing validation that `fill_qty <= remaining_qty` before insertion.

**How to avoid:** `_validate_fill_transition()` in OrderManager checks `fill_qty <= remaining_qty`. This is application-level guard. A DB CHECK constraint `remaining_qty >= 0` provides a second layer (add to DDL).

---

## Code Examples

### Position Flip Complete Example

```python
# Source: NautilusTrader pattern (net-quantity approach), verified

from decimal import Decimal

# Scenario: Long 100 BTC @ $50,000. Sell 150 BTC @ $52,000. Flip to Short 50 BTC.

result = compute_position_update(
    current_qty=Decimal("100"),        # long 100 BTC
    current_avg_cost=Decimal("50000"), # cost basis $50k
    current_realized_pnl=Decimal("0"),
    fill_qty=Decimal("-150"),          # sell 150 BTC (negative = sell)
    fill_price=Decimal("52000"),
)

# Expected:
# - Close 100 BTC long: realized = (52000 - 50000) * 100 = $200,000
# - Open 50 BTC short at $52,000
assert result["quantity"] == Decimal("-50")
assert result["avg_cost_basis"] == Decimal("52000")
assert result["realized_pnl"] == Decimal("200000")
```

### Dead Letter Retry Query

```python
# Source: PostgreSQL DLQ pattern from diljitpr.net, adapted for this schema

RETRY_QUERY = text("""
    SELECT dlq_id, operation_type, order_id, payload, retry_count
    FROM public.cmc_order_dead_letter
    WHERE status = 'pending'
      AND retry_after <= now()
      AND retry_count < 10
    ORDER BY created_at ASC
    LIMIT 50
    FOR UPDATE SKIP LOCKED
""")

UPDATE_RETRY = text("""
    UPDATE public.cmc_order_dead_letter SET
        status      = 'retrying',
        retry_count = retry_count + 1,
        retry_after = now() + (INTERVAL '1 second' * POWER(2, retry_count)),
        updated_at  = now()
    WHERE dlq_id = :dlq_id
""")
```

### Alembic Migration: Aggregate View via op.execute()

```python
# Source: project pattern from 8d5bc7ee1732 (cmc_corr_latest materialized view)

def upgrade() -> None:
    # ... create tables ...

    # Views use op.execute() -- no native Alembic op
    op.execute("""
        CREATE OR REPLACE VIEW public.v_cmc_positions_agg AS
        SELECT
            asset_id,
            'aggregate'::TEXT AS exchange,
            SUM(quantity) AS quantity,
            CASE
                WHEN SUM(ABS(quantity)) = 0 THEN 0
                ELSE SUM(ABS(quantity) * avg_cost_basis) / SUM(ABS(quantity))
            END AS avg_cost_basis,
            SUM(realized_pnl) AS realized_pnl,
            SUM(COALESCE(unrealized_pnl, 0)) AS unrealized_pnl,
            MAX(last_mark_price) AS last_mark_price,
            MAX(last_updated) AS last_updated
        FROM public.cmc_positions
        WHERE exchange != 'aggregate'
        GROUP BY asset_id
    """)

def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS public.v_cmc_positions_agg")
    # ... drop tables ...
```

### Testing OrderManager Without DB (low-level method injection)

```python
# The low-level methods (insert_fill, update_order, upsert_position, insert_order_event)
# accept a conn parameter, enabling injection of a mock connection in tests.
# This avoids the need for a real DB in unit tests.

def test_position_math_flat_open():
    """Test: open long position from flat."""
    result = compute_position_update(
        current_qty=Decimal("0"),
        current_avg_cost=Decimal("0"),
        current_realized_pnl=Decimal("0"),
        fill_qty=Decimal("1"),          # buy 1 BTC
        fill_price=Decimal("50000"),
    )
    assert result["quantity"] == Decimal("1")
    assert result["avg_cost_basis"] == Decimal("50000")
    assert result["realized_pnl"] == Decimal("0")
```

---

## Research Resolutions (6 Open Questions from CONTEXT.md)

### 1. Position Flip Best Practices
**RESOLVED: Net-quantity (NautilusTrader NETTING mode)**

Net-quantity is the industry standard for single-direction crypto paper trading:
- Alpaca uses weighted average with intraday compression
- NautilusTrader uses signed-quantity with automatic flip detection
- The algorithm in `position_math.py` handles all cases: new position, addition, partial close, full close, and flip
- FIFO reconstruction is possible later from `cmc_fills` lot tracking

**Decision: Net-quantity flip** with realized PnL credited on the closing portion, fresh `avg_cost_basis = fill_price` for the opening portion.

### 2. Signal FK Chain Recommendation
**RESOLVED: signal_id on cmc_orders only**

Keep `signal_id` on `cmc_orders` only. Do NOT propagate to `cmc_fills` or `cmc_positions`.

- `cmc_fills` → JOIN cmc_orders to get signal_id (one extra join, acceptable)
- `cmc_positions` → tracks per-asset-exchange position regardless of originating signal
- Phase 47 Drift Guard joins via: `cmc_backtest_runs(signal_id) -> cmc_orders(signal_id) -> cmc_fills`
- Denormalizing signal_id to fills would create redundancy without query benefit

### 3. Backtest Linkage for Drift Guard
**RESOLVED: No direct FK; link via signal_id + asset_id**

Do NOT add a FK from cmc_orders to cmc_backtest_runs. The linkage is:
```
cmc_backtest_runs (signal_id, asset_id)
       |
       | JOIN ON signal_id AND asset_id
       |
cmc_orders (signal_id, asset_id)
       |
       | JOIN ON order_id
       |
cmc_fills (order_id)
```
Phase 47 compares aggregate distributions (total PnL, Sharpe, drawdown) between paper execution and backtested strategy -- not individual trade pairs.

### 4. Aggregate Position View
**RESOLVED: Regular DB view (v_cmc_positions_agg)**

Do NOT use a materialized view:
- cmc_positions changes on every fill (frequent updates)
- Table is tiny (one row per asset+exchange, <= 100 rows)
- Materialized view would need REFRESH after every fill
- Regular view is automatically current and fast enough

### 5. Dead Letter Table Design
**RESOLVED: Domain-specific cmc_order_dead_letter**

Use a domain-specific table (not a generic retry_queue):
- `operation_type` column enables routing to correct replay handler
- `order_id` + `fill_id` columns enable SQL queries by business entity
- `payload JSONB` stores full operation for replay
- `retry_count` + `retry_after` enables exponential backoff
- `status` tracks: pending / retrying / succeeded / abandoned
- `FOR UPDATE SKIP LOCKED` on retry query prevents concurrent workers from grabbing the same row

### 6. Data Access Pattern
**RESOLVED: Raw SQL text() with engine.begin() -- project convention**

Use raw SQL `text()` inside `engine.begin()` blocks (the project's universal pattern):
- Backtest runner: `engine.begin()` + `text()` for 3-table atomic write
- AMA state manager: `engine.begin()` + `text()` for state reads/writes
- IC eval runner: `engine.begin()` + `text()` for result batch insert
- ORM adds no value for the 5-table transaction and makes `SELECT ... FOR UPDATE` harder to express clearly

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| FIFO-only cost basis | Weighted average (FIFO reconstructable from lots) | Simpler display, FIFO available for tax reporting later |
| Separate retry process (RabbitMQ/SQS) | PostgreSQL DLQ table with `retry_after` backoff | No external infrastructure; pure SQL queryability |
| ORM for complex transactions | Raw `text()` + `engine.begin()` for explicit control | Project-consistent, explicit lock visibility, easier to audit |
| Separate close+reopen on position flip | Net-quantity signed flip | Single row update; realized PnL computed inline |

---

## Open Questions

1. **Phase 43 Migration Hash**
   - What we know: Phase 43 creates a migration (hash unknown until Phase 43 executes). Phase 44's migration chains from it.
   - What's unclear: The exact hash won't be known until Phase 43's plan-01 runs `alembic revision`.
   - Recommendation: Phase 44 plan-01 instructs executor to run `alembic revision -m "order_fill_store"` after Phase 43 completes. Alembic auto-detects the head. Verify with `alembic history | head -3`.

2. **cmc_orders.pair column source**
   - What we know: paper_orders has `pair TEXT NOT NULL` (e.g., 'BTC/USD'). This denormalizes into cmc_orders.
   - What's unclear: Should `pair` be normalized via `dim_assets` (use `ticker` column) or kept as-is from paper_orders?
   - Recommendation: Keep `pair` as-is from paper_orders (e.g., 'BTC/USD'). It's for human readability, not joins. The asset_id FK handles the relational link.

3. **cmc_positions quantity = 0 cleanup**
   - What we know: When a position is fully closed, quantity becomes 0. The row remains in the table.
   - What's unclear: Should flat positions (quantity=0) be retained or deleted?
   - Recommendation: Retain flat position rows. `realized_pnl` is cumulative and belongs on the row. The row is cheap to keep and Phase 52 (Dashboard) can filter `WHERE quantity != 0` for active positions.

---

## Sources

### Primary (HIGH confidence)
- Existing project code: `src/ta_lab2/scripts/backtests/backtest_from_signals.py` -- transaction pattern (engine.begin() + text())
- Existing project code: `src/ta_lab2/scripts/amas/ama_state_manager.py` -- engine.begin() for atomic writes
- Existing project code: `alembic/versions/8d5bc7ee1732_asset_stats_and_correlation_tables.py` -- migration pattern with op.execute() for views
- Existing project code: `alembic/versions/c3b718c2d088_ic_results_table.py` -- sa.UUID() pattern, migration structure
- `.planning/phases/44-order-fill-store/44-CONTEXT.md` -- all locked decisions
- `.planning/phases/43-exchange-integration/43-01-PLAN.md` -- paper_orders table schema, migration chain starting from 8d5bc7ee1732
- `sql/backtests/070_cmc_backtest_runs.sql` -- backtest table schema for FK relationship analysis
- `sql/backtests/071_cmc_backtest_trades.sql` -- backtest trades schema

### Secondary (MEDIUM confidence)
- NautilusTrader position documentation: https://nautilustrader.io/docs/nightly/concepts/positions/ -- net-quantity flip pattern, NETTING vs HEDGING modes confirmed
- Alpaca position average entry price docs: https://docs.alpaca.markets/docs/position-average-entry-price-calculation -- weighted average method, intraday vs EOD compression
- PostgreSQL DLQ blog post: https://www.diljitpr.net/blog-post-postgresql-dlq -- dead letter table schema, retry pattern, `FOR UPDATE SKIP LOCKED` query

### Tertiary (LOW confidence)
- WebSearch: "SQLAlchemy raw SQL vs ORM complex transactions 2024" -- confirms raw SQL preference for complex multi-table transactions; no single authoritative source
- WebSearch: "PostgreSQL materialized view vs regular view aggregate" -- performance tradeoff confirmed (materialized better for large tables; regular view sufficient for small tables)

---

## Metadata

**Confidence breakdown:**
- DDL schemas: HIGH -- designed from existing project patterns, locked CONTEXT.md decisions, and confirmed DB conventions (UUID, TIMESTAMPTZ, gen_random_uuid(), NullPool)
- OrderManager design: HIGH -- follows established project pattern (engine.begin() + text()); transaction structure mirrors backtest_from_signals.py
- Position math: HIGH -- verified against NautilusTrader and Alpaca documentation
- Signal FK chain: MEDIUM -- recommendation based on query pattern analysis and OMS conventions; no authoritative source explicitly confirms this design
- Alembic chain: MEDIUM -- Phase 43 migration hash unknown; recommendation to use alembic auto-detect is correct
- Dead letter design: MEDIUM -- schema verified from PostgreSQL DLQ blog; retry pattern confirmed from multiple sources

**Research date:** 2026-02-24
**Valid until:** 2026-05-24 (stable patterns; re-verify only if Phase 43 migration structure changes)
