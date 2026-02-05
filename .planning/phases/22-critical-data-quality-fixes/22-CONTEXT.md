# Phase 22: Critical Data Quality Fixes - Context

**Gathered:** 2026-02-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix 4 CRITICAL data quality gaps identified in Phase 21 comprehensive review, PLUS architectural refactor to derive multi-TF bars from 1D bars.

**Scope includes:**
- GAP-C01: Multi-TF reject tables for OHLC repair audit trail (12-16 hours)
- GAP-C02: EMA output validation with bounds checking (8-12 hours)
- GAP-C03: 1D backfill detection + derive multi-TF from 1D bars (46-68 hours combined)
- GAP-C04: Expand automated validation test suite (16-24 hours)

**Total effort:** 82-120 hours (Option B - comprehensive fix with architectural refactor)

**Key insight from Phase 21:** EMAs already use validated bar tables (Phase 20 discovery), so Phase 22 focuses on bar table data quality and architectural unification, NOT EMA migration.

</domain>

<decisions>
## Implementation Decisions

### Reject Table Strategy (GAP-C01)

**Approach:** Create multi-TF reject tables, keep them post-derivation for aggregation validation
- Multi-TF reject tables serve dual purpose: log OHLC repairs pre-derivation, validate aggregation logic post-derivation
- Even after deriving from 1D, aggregation-level validation catches: volume mismatches, missing daily bars within weeks, aggregation bugs

**Repair behavior:** Keep current behavior - log to rejects THEN repair and write
- `enforce_ohlc_sanity()` continues repairing OHLC violations
- Log original invalid values to reject table BEFORE repair
- Repaired bar still gets written to main table
- No breaking changes - maintains backward compatibility

**Reason categorization:** Both violation type AND repair action (complete audit trail)
- Two columns in reject schema:
  - `violation_type`: What was wrong (e.g., 'high_lt_low', 'high_lt_oc_max')
  - `repair_action`: What was done to fix it (e.g., 'high_low_swapped', 'high_adjusted_to_oc_max')
- Provides complete audit trail for data quality analysis

**Shared schema:** Extract reject table schema to common_snapshot_contract.py (DRY principle)
- Single source of truth for reject table DDL
- All 6 builders import and use same schema
- Easier to evolve schema over time
- Matches existing pattern (5 of 6 builders already use common_snapshot_contract)

### EMA Validation Bounds (GAP-C02)

**Bounds strategy:** Hybrid - price bounds (wide) + statistical bounds (narrow)
- **Price bounds:** 0.5x to 2x recent min/max price from source bars
  - Catches extreme outliers, infinity, corruption
  - Asset-aware, simple to compute
- **Statistical bounds:** Z-score (mean ± 3 std dev) from historical EMA distribution
  - Catches calculation drift, subtle errors
  - Adapts to asset volatility
- Two-tier validation: price bounds (safety net) + statistical (precision)

**Validation strictness:** Warn and continue - log violations but write all EMAs
- **WITH prominent alerting in logs**
- Write all EMAs (even invalid ones) to maintain data continuity
- Log violations to both ema_rejects table AND application logs (WARNING level)
- No data loss, maximum visibility
- Downstream consumers can filter if needed

**Violation logging:** Both ema_rejects table + application logs
- **ema_rejects table:** Queryable audit trail with full context (id, tf, period, ema_value, violation_type, bounds_info)
- **Application logs:** WARNING level for monitoring/alerting
- Maximum visibility: easy to query (table) and monitor (logs/alerts)

**Validation layer:** Central - add to BaseEMARefresher.save_output()
- Single validation layer in base class
- All 6 EMA variants inherit automatically
- DRY principle, consistent behavior
- Performance impact: ~1-2% slowdown (5-8 seconds overhead on 6-7 minute refresh)
- Optimizations: batch bound queries, cache statistical bounds, vectorized validation

### Backfill Rebuild Behavior (GAP-C03)

**Two-part approach:** Simple fix (6-8 hours) followed immediately by complex fix (40-60 hours)

**Simple fix: Add backfill detection to 1D builder**
- Add `daily_min_seen` column to `cmc_price_bars_1d_state`
- Check for backfills before each run: if `MIN(day_date) < daily_min_seen` → rebuild required
- Full rebuild: DELETE bars for id, reprocess all history, update state
- Closes the 1D blind spot (multi-TF builders already have this)

**Complex fix: Derive multi-TF from 1D bars (architectural refactor)**
- Multi-TF builders read from `cmc_price_bars_1d` instead of `price_histories7`
- Daily bars copied directly, weekly/monthly bars aggregated from daily
- Aggregation logic unchanged (same OHLCV math, just different input source)
- Calendar variants still apply different week boundaries (canonical vs US vs ISO vs anchor)

**Rationale for both:**
- Simple fix closes data corruption risk immediately
- Complex fix creates single source of truth (1D validation rules propagate to all multi-TF)
- Trade-off accepted: 2x slower refresh (12 min vs 6 min) for data consistency guarantees
- Unified backfill handling: fix 1D, all downstream rebuilds automatically

**No issues with derivation:**
- 1D table is pure daily bars (no week concept)
- Multi-TF aggregation logic is universal (doesn't change between sources)
- Weekly/monthly bars aggregate from daily using same OHLCV math
- Calendar boundaries only affect grouping, not aggregation logic

### Test Coverage Priorities (GAP-C04)

**Test data strategy:** Hybrid - mocks for unit tests, real snapshots for integration tests
- Unit tests: Small generated fixtures with targeted scenarios (specific OHLC violations, NULL cases)
- Integration tests: Real price_histories7 snapshots for authentic edge cases
- Best of both worlds: targeted coverage + real-world validation

**Critical path coverage:** All validation paths need 100% coverage
- OHLC invariant enforcement (high >= low, etc.)
- NULL rejection (OHLCV columns)
- Quality flags (is_partial_end, is_missing_days)
- Backfill detection (new in GAP-C03)
- EMA output validation (new in GAP-C02)
- Aggregation validation (new in multi-TF rejects, GAP-C01)

**Existing tests (Phases 1-10):**
- ✓ test_bar_ohlc_correctness.py - OHLC values match source
- ✓ test_bar_contract.py - Schema/constraints
- ✓ test_bar_contract_gap_tests.py - Gap detection
- ✓ test_polars_bar_operations.py - Aggregation logic
- ✓ test_features_ema.py - EMA calculations
- Need to expand for Phase 22 additions (rejects tables, bounds validation, backfill detection)

### Claude's Discretion

**CI integration strategy:**
- Decide threshold: block on all failures vs CRITICAL only vs warning-only
- Balance quality bar with velocity
- Consider test flakiness and DB dependency

**Test scope boundaries:**
- Mix of unit tests (validation logic) and E2E tests (full pipeline)
- Follow existing test patterns in codebase
- Ensure reasonable runtime (<5 min for fast feedback)

</decisions>

<specifics>
## Specific Ideas

**Performance optimization:**
- Batch bound queries (get all EMA bounds in 2 queries, not 1,250)
- Cache statistical bounds (recompute weekly, not every run)
- Vectorized validation with pandas/numpy (already standard in codebase)

**Reject table dual purpose:**
- Pre-derivation: Log OHLC repairs from enforce_ohlc_sanity()
- Post-derivation: Validate aggregation (week volume = sum of day volumes)

**Architectural insight:**
- Deriving from 1D is straightforward (daily bars are daily bars)
- Aggregation logic doesn't change (same OHLCV math, different input)
- No issues expected - effort estimate might be conservative

</specifics>

<deferred>
## Deferred Ideas

None - discussion stayed within phase scope. All 4 CRITICAL gaps plus architectural refactor fit cleanly within Phase 22 boundaries.

</deferred>

---

*Phase: 22-critical-data-quality-fixes*
*Context gathered: 2026-02-05*
