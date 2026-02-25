---
phase: 51-perps-readiness
plan: 01
subsystem: database
tags: [postgres, alembic, perps, perpetuals, funding-rates, margin, schema]

requires:
  - phase: 49-tail-risk
    provides: cmc_risk_events CHECK constraint base (tail_risk_escalated, tail_risk_cleared, tail_risk source)
  - phase: 44-paper-trading
    provides: cmc_positions spot table (justified separate cmc_perp_positions design)

provides:
  - cmc_funding_rates table: multi-venue perpetual funding rate history with (venue,symbol,ts,tf) PK
  - cmc_margin_config table: venue-specific tiered margin rates (seeded with Binance BTC/ETH + Hyperliquid BTC/ETH)
  - cmc_perp_positions table: perp position tracking with margin state columns (separate from spot)
  - Extended chk_risk_events_type: liquidation_warning, liquidation_critical, margin_alert added
  - Extended chk_risk_events_source: margin_monitor added
  - dim_risk_limits: margin_alert_threshold (1.5) and liquidation_kill_threshold (1.1) columns added

affects:
  - 51-02: funding rate ingestion scripts depend on cmc_funding_rates table
  - 51-03: margin model + position tracking depend on cmc_margin_config + cmc_perp_positions
  - 51-04: liquidation buffer + RiskEngine Gate 1.6 depend on all three new tables + extended constraints
  - future risk phases: margin_monitor source and liquidation event types now in CHECK constraints

tech-stack:
  added: []
  patterns:
    - "Venue CHECK pattern: 7-venue IN list (binance,hyperliquid,bybit,dydx,aevo,aster,lighter) reused across all 3 new tables"
    - "Separate perp table pattern: cmc_perp_positions instead of extending cmc_positions to avoid breaking spot exchange CHECK"
    - "Alembic DROP IF EXISTS + ADD CONSTRAINT pattern for extending CHECK constraints (established in drift_guard, continued here)"
    - "Seed data via op.execute() INSERT ... ON CONFLICT DO NOTHING for idempotent margin config initialization"

key-files:
  created:
    - sql/perps/095_cmc_funding_rates.sql
    - sql/perps/096_cmc_margin_config.sql
    - sql/perps/097_cmc_perp_positions.sql
    - alembic/versions/30eac3660488_perps_readiness.py
  modified: []

key-decisions:
  - "cmc_perp_positions is separate from cmc_positions (spot): cmc_positions has CHECK (exchange IN (coinbase,kraken,paper,aggregate)) which cannot include perp venue names without altering spot logic"
  - "8 margin config seed rows at creation: Binance BTC (3 tiers) + ETH (3 tiers) + Hyperliquid BTC (1) + ETH (1); idempotent via ON CONFLICT DO NOTHING"
  - "margin_alert_threshold=1.5 and liquidation_kill_threshold=1.1 match CONTEXT.md buffer zone spec; stored in dim_risk_limits for per-strategy configurability"
  - "Alembic revision ID 30eac3660488 generated dynamically; down_revision=a9ec3c00a54a (actual head from alembic heads)"

patterns-established:
  - "sql/perps/ directory: reference DDL for perp infrastructure tables"
  - "Venue allowlist pattern: 7 venues consistently enforced via CHECK across all perp tables"

duration: 4min
completed: 2026-02-25
---

# Phase 51 Plan 01: Perps Readiness Schema Summary

**Three PostgreSQL tables for perpetual futures infrastructure: cmc_funding_rates (7-venue funding history), cmc_margin_config (tiered margin rates seeded with 8 rows), and cmc_perp_positions (margin-tracked perp positions separate from spot), plus extended cmc_risk_events constraints and dim_risk_limits margin threshold columns**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-02-25T23:26:45Z
- **Completed:** 2026-02-25T23:30:15Z
- **Tasks:** 2/2
- **Files modified:** 4

## Accomplishments

- Created `sql/perps/` directory with 3 reference DDL files (ASCII-only, Windows cp1252 compatible)
- Created Alembic migration `30eac3660488_perps_readiness.py` creating all 3 tables, seeding 8 margin config rows, and extending 2 CHECK constraints plus adding 2 dim_risk_limits columns
- Upgrade and downgrade cycle both verified clean; 8 margin config rows confirmed; alembic current = `30eac3660488`
- chk_risk_events_source now includes `margin_monitor`; chk_risk_events_type includes `liquidation_warning`, `liquidation_critical`, `margin_alert`

## Task Commits

Each task was committed atomically:

1. **Task 1: Reference DDL files for all Phase 51 tables** - `7efd0477` (feat)
2. **Task 2: Alembic migration for all Phase 51 tables + risk event extension** - `cdc2710c` (feat)

**Plan metadata:** (included in this SUMMARY commit)

## Files Created/Modified

- `sql/perps/095_cmc_funding_rates.sql` - Reference DDL: (venue,symbol,ts,tf) PK, CHECK constraints for 7 venues and 4 tfs, 2 indexes, column comments
- `sql/perps/096_cmc_margin_config.sql` - Reference DDL: tiered margin config with seed data for Binance BTC/ETH (3 tiers each) and Hyperliquid BTC/ETH (1 tier each)
- `sql/perps/097_cmc_perp_positions.sql` - Reference DDL: perp position state with margin_utilization, liquidation_price, side/margin_mode CHECK constraints
- `alembic/versions/30eac3660488_perps_readiness.py` - Alembic migration: creates all 3 tables, seeds margin config, extends risk event constraints, adds dim_risk_limits threshold columns

## Decisions Made

- **Separate cmc_perp_positions from cmc_positions (spot):** The existing `cmc_positions` table has `CHECK (exchange IN ('coinbase','kraken','paper','aggregate'))`. Extending this constraint would touch live spot trading logic. A dedicated `cmc_perp_positions` table avoids the risk and cleanly separates perp vs spot position semantics.
- **Actual DB constraint state used as ground truth:** The plan doc listed "drift_signal/drift_attribution/drift_escalation" as existing event types, but the actual DB (from `a9ec3c00a54a`) has `tail_risk_escalated/tail_risk_cleared`. Used DB state from `pg_constraint` query, not plan doc.
- **Seed 8 margin config rows at migration time:** Binance BTC/ETH (3 tiers each at 50K/250K/1M notional brackets) + Hyperliquid BTC/ETH (single tier, IM=2%/MM=1% at 50x max leverage). ON CONFLICT DO NOTHING ensures idempotency on re-run.
- **margin_alert_threshold=1.5, liquidation_kill_threshold=1.1:** Stored in dim_risk_limits with server defaults matching CONTEXT.md buffer zone spec. Per-strategy configurability inherited from dim_risk_limits pattern.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Used actual DB constraint state instead of plan's listed event types**

- **Found during:** Task 2 (Alembic migration creation)
- **Issue:** Plan doc listed "drift_signal, drift_attribution, drift_escalation" as existing event types, but live DB shows "tail_risk_escalated, tail_risk_cleared" (from `a9ec3c00a54a` tail_risk_policy migration)
- **Fix:** Queried `pg_constraint` to get ground truth, used actual 12-type list in both upgrade() and downgrade() for the event_type constraint
- **Files modified:** `alembic/versions/30eac3660488_perps_readiness.py`
- **Verification:** Alembic upgrade completed without constraint errors; query confirmed liquidation_critical in chk_risk_events_type
- **Committed in:** `cdc2710c` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - factual correction on existing constraint state)
**Impact on plan:** Required for migration correctness. Plan doc had stale constraint list from before tail_risk_policy migration executed.

## Issues Encountered

- Pre-commit hooks fixed mixed line endings (CRLF to LF) on first commit attempt for both tasks; required re-staging and re-committing. Standard Windows/git behavior, no code impact.
- Pre-commit ruff-format reformatted the Alembic migration (long argument lists split across lines); required third commit attempt. No logic changes.

## User Setup Required

None - no external service configuration required. All changes are database schema via Alembic.

## Next Phase Readiness

- `cmc_funding_rates` table ready for Plan 02 ingestion scripts (6 venue fetchers)
- `cmc_margin_config` seeded with Binance and Hyperliquid BTC/ETH tiers; Plan 03 margin monitor can query immediately
- `cmc_perp_positions` ready for Plan 03 position tracking writes from paper executor
- `margin_monitor` trigger source and `liquidation_warning/critical/margin_alert` event types in CHECK constraints; Plan 04 RiskEngine Gate 1.6 can log these events immediately
- No blockers for subsequent plans

---
*Phase: 51-perps-readiness*
*Completed: 2026-02-25*
