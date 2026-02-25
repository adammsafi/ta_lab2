# Phase 44: Order & Fill Store — Context

## Area 1: Order Lifecycle & State Machine

### Table Architecture
- **paper_orders (Phase 43) stays separate** from cmc_orders. paper_orders is a lightweight log for signal-to-order translation. cmc_orders is the full lifecycle table for orders entering the executor.
- Paper orders get **promoted** to cmc_orders when the executor picks them up. cmc_orders has an optional `paper_order_uuid` FK back to paper_orders for traceability.

### State Machine
- **7 states**: `created`, `submitted`, `partial_fill`, `filled`, `cancelled`, `rejected`, `expired`
- Valid transitions:
  - created -> submitted (sent to exchange/simulator)
  - submitted -> partial_fill (first partial fill received)
  - submitted -> filled (single complete fill)
  - submitted -> cancelled (user/system cancel)
  - submitted -> rejected (exchange rejects)
  - submitted -> expired (TTL hit for GTD orders)
  - partial_fill -> partial_fill (additional fill received)
  - partial_fill -> filled (final fill completes order)
  - partial_fill -> cancelled (cancel remaining)
- **Enforcement**: Both DB CHECK constraint (valid status values) AND application-level Python validation (valid transitions). Defense in depth.

### Paper Trading Flow
- **Two-phase simulation**: Paper orders go `created -> submitted` (logged), then a separate fill simulator step processes them into fills. Allows configurable latency and rejection simulation.
- This enables Phase 47 (Drift Guard) to compare execution timing.

### Time-in-Force
- **Optional GTC/GTD field**: `time_in_force` column (GTC, GTD, IOC) and `expires_at` TIMESTAMPTZ. Orders with GTD auto-expire. Infrastructure ready for Phase 46 risk controls.

### Fill Tracking
- **Materialized + derived**: cmc_orders has `filled_qty` and `remaining_qty` columns updated on each fill for fast reads. cmc_fills table is source of truth. A consistency check can verify they match.

### Audit Trail
- **Both status column + audit log table**: cmc_orders has `status` and `updated_at` columns. Separate `cmc_order_events` table captures every state transition: `(event_id, order_id, from_status, to_status, event_ts, reason)`.

## Area 2: Position Tracking & Cost Basis

### Cost Basis Method
- **Average cost with lot tracking**: Primary display uses weighted average cost basis. Individual fill lots stored so FIFO could be reconstructed later for tax reporting.

### Position Granularity
- **Per-exchange + aggregate view**: cmc_positions tracks (asset_id, exchange) pairs. Aggregate view across exchanges provided (DB view vs materialized — **researcher decides**).

### Position Flips
- **Research best practices**: How to handle long-to-short flips (close + open vs net quantity vs prevent). **Researcher should investigate** standard approaches in trading systems.

### PnL Fields
- **Both unrealized + realized**: Position stores `avg_cost_basis`, `quantity`, `last_mark_price`, `unrealized_pnl`, `unrealized_pnl_pct`, AND cumulative `realized_pnl` for closed fills. Full P&L picture in one row.

## Area 3: Relationship to Existing Tables

### Signal FK Chain
- **Research best practices**: Whether to denormalize signal_id across order/fill/position tables or keep it only on paper_orders. **Researcher should recommend** based on query patterns and standard trading system design.

### Backtest Linkage
- **Research this**: How cmc_orders/cmc_fills should relate to cmc_backtest_runs/cmc_backtest_trades. Relevant for Phase 47 (Drift Guard) paper-vs-backtest comparison. **Researcher should determine** right linkage.

### Exchange Fill IDs
- **Store exchange fill ID**: cmc_fills has `exchange_fill_id` column (nullable TEXT). NULL for paper fills, stores venue's trade ID for live fills for reconciliation.

### Asset Reference
- **Both asset_id FK + pair string**: cmc_orders has asset_id FK to dim_assets for joins AND pair column ('BTC/USD') for human readability. Denormalized but practical.

## Area 4: Atomicity & Failure Handling

### Transaction Scope
- **Maximum atomicity**: One transaction for: INSERT fill, UPDATE order (filled_qty, status), UPDATE/INSERT position (quantity, cost basis, PnL), INSERT order_event audit log. All succeed or all roll back.

### Failure Mode
- **Fail fast + dead letter**: On transaction failure, write the failed operation to a dead letter table. A separate process replays failed operations. No inline retry. Dead letter table design (specific vs generic) — **researcher decides**.

### Data Access Pattern
- **Research best practices**: Whether to use raw SQL (text()) matching project convention, SQLAlchemy ORM, or hybrid approach for OrderManager. **Researcher should recommend** based on transaction complexity and project patterns.

### Concurrency Control
- **Pessimistic locking**: `SELECT ... FOR UPDATE` on position row before updating. Guarantees no concurrent modification. Heavier but bulletproof for position integrity.

### API Shape
- **Both high-level + composable**: `OrderManager.process_fill()` for normal use (does everything in one transaction). Low-level methods (`insert_fill`, `update_order`, `update_position`) available for testing or custom flows. `process_fill()` calls them internally.

## Research Items for Phase Researcher

1. **Position flips best practices** — close+open vs net quantity vs prevent. Standard trading system approaches.
2. **Signal FK chain recommendation** — denormalize signal_id everywhere vs join through paper_orders.
3. **Backtest linkage** — how orders/fills should relate to cmc_backtest_runs/cmc_backtest_trades for drift detection.
4. **Aggregate position view** — DB view vs materialized table for cross-exchange position aggregation.
5. **Dead letter table design** — specific cmc_order_failures vs generic retry_queue.
6. **Data access pattern** — raw SQL vs ORM vs hybrid for OrderManager given transaction complexity.

## Deferred Ideas
- Live order submission (Phase 45+)
- Order routing logic / smart order routing (future)
- Multi-leg orders / bracket orders (future)
- Tax lot reporting (future — lot tracking infrastructure ready)
