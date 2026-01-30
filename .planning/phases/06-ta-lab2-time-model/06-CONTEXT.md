---
phase: 06-ta-lab2-time-model
gathered: 2026-01-29
status: ready_for_planning
---

# Phase 6 Context: ta_lab2 Time Model

**Phase Goal:** Time handling unified across ta_lab2 with formal dimension tables

**Gathered:** 2026-01-29
**Discussed Areas:** 4 (dimension table design, EMA unification, validation, incremental refresh)

## Phase Overview

From ROADMAP.md success criteria:
1. dim_timeframe table contains all TF definitions (1D, 3D, 5D, 1W, 1M, 3M, etc.)
2. dim_sessions table handles trading hours, DST, session boundaries
3. Single unified EMA table (cmc_ema_multi_tf + cmc_ema_multi_tf_cal merged)
4. All EMA refresh scripts reference dim_timeframe instead of hardcoded values
5. Time alignment validation tests pass (TF windows, calendar rolls, session boundaries)
6. Incremental EMA refresh computes only new rows
7. Rowcount validation confirms actual counts match tf-defined expectations

## Existing Infrastructure Review

**What already exists:**

1. **dim_timeframe.py** — TFMeta dataclass with comprehensive fields:
   - Core: tf, label, base_unit, tf_qty, tf_days_nominal
   - Alignment: alignment_type, calendar_anchor, roll_policy, has_roll_flag
   - Metadata: is_intraday, sort_order, is_canonical, calendar_scheme
   - Partial periods: allow_partial_start, allow_partial_end, tf_days_min/max
   - DimTimeframe class provides in-memory view with from_db() classmethod
   - **Key finding:** Already architected for calendar schemes and partial periods

2. **dim_sessions.py** — SessionKey and SessionMeta dataclasses:
   - SessionKey: (asset_class, region, venue, asset_key_type, asset_key, session_type)
   - SessionMeta: (asset_id, timezone, session_open_local, session_close_local, is_24h)
   - DimSessions class with session_windows_utc_by_key() for DST-safe windows
   - **Key finding:** Already architected for multiple venues

3. **EMA refresh scripts** — User confirmed: "Already reading from dim_timeframe"
   - Scripts currently reference dim_timeframe (validation needed)

4. **sync_cmc_ema_multi_tf_u.py** — Already exists for EMA table unification
   - User: "I'm pretty sure this is already being done by sync_cmc_ema_multi_tf_u.py check"
   - **Open question:** "You have to tell me if what is built is good enough?"

5. **Multiple EMA variants found:**
   - ema_multi_tf_cal.py
   - ema_multi_tf_cal_anchor.py
   - ema_multi_tf_v2.py
   - ema_multi_timeframe.py
   - **Open question:** Why do multiple tables exist? Investigation needed.

## Decisions Made

### 1. Dimension Table Design

**Population Strategy:**
- Approach: SQL seed file OR Python migration script (choose one or hybrid)
- Session management: **Hybrid** — seed common sessions, discover asset-specific sessions
- Existing data migration: Merge carefully, validate thoroughly, determine safe approach before execution

**Required Timeframes:**
- Daily/weekly: 1D, 3D, 5D, 1W
- Monthly/quarterly: 1M, 3M, etc.
- Custom rolling windows: as needed
- Intraday: Defer for now BUT structure dim_timeframe to support it (future-proof)
  - User: "We will go intraday later, so it may make sense to take care of it now or wait, im not sure"
  - Decision: Design schema to support intraday, implement population later

**Required Sessions:**
- Crypto: 24-hour (UTC, no DST)
- US Equity: 9:30-16:00 ET (handle DST transitions)
- Futures: Varied by contract (CME, NYMEX, etc.)
- International: Region-specific (LSE, TSE, HKEX, etc.)

**Multi-Venue Support:**
- User confirmed: "It should" (need multiple venues)
- SessionKey already includes venue field

**DST Handling:**
- Decision: Claude's discretion on implementation approach
- Constraint: session_windows_utc_by_key() must handle DST transitions correctly

### 2. EMA Table Unification

**Investigation Required:**
- **Why multiple EMA tables exist?** User: "Not sure - you investigate"
- Compare: ema_multi_tf, ema_multi_tf_cal, ema_multi_tf_cal_anchor, ema_multi_tf_v2
- Determine: Are they variants (different calculations) or should be unified?

**Primary Key Structure:**
- User confirmed: **(id, tf, period, alignment_source)**
- Rationale: Supports multiple alignment strategies (calendar vs trading day)

**Migration Tool:**
- sync_cmc_ema_multi_tf_u.py already exists
- **Validation needed:** Is what's built good enough for Phase 6 requirements?
- User expects analysis: "You have to tell me if what is built is good enough?"

**Unification Goal:**
- Single unified table per ROADMAP success criterion #3
- All EMA refresh scripts reference dim_timeframe (success criterion #4)

### 3. Validation Strategy

**Error Types to Cover (all four):**
1. Off-by-one errors in time calculations
2. Calendar roll misalignment
3. Session boundary violations
4. DST transition bugs

**Test Structure (all approaches):**
- Property-based testing (hypothesis, property invariants)
- Reference data validation (known-good calculations)
- Test fixtures with edge cases
- Cross-table consistency checks

**Rowcount Validation:**
- Decision: Claude's discretion on granularity
- Requirement: Actual counts must match tf-defined expectations (success criterion #7)

**When to Run (all four triggers):**
1. Pre-commit hooks (fast subset)
2. CI pipeline (comprehensive suite)
3. Post-refresh validation (data quality checks)
4. On-demand (manual investigation)

**Error Reporting:**
- Logs (structured logging)
- Exceptions (raise on critical errors)
- Metrics (time-series for monitoring)
- **Telegram** (alerts and notifications)
- User correction: "Instead of email or slack we should use telegram"

**Remediation Strategy:**
- **Auto-fix with approval via Telegram**
- No silent auto-fixes without human confirmation
- Preserve failed state for debugging before remediation

**Historical Validation:**
- Full audit (check all historical data for consistency)
- Sampling (statistical validation on subset)
- Rolling window (validate recent N periods deeply)

**Performance Considerations:**
- Async execution (parallel validation tasks)
- Incremental validation (only new/changed data)
- Sampling: Claude's discretion

**Edge Cases to Cover (all four):**
1. Leap years (Feb 29, 366-day years)
2. Market holidays (non-trading days in TF calculations)
3. Data gaps (missing bars, exchange outages)
4. Lifecycle events (ticker changes, delistings, splits)

**Failure Thresholds:**
- Zero tolerance for critical errors (time misalignment, data corruption)
- Override capability for known issues (manual approval + documentation)

**Cross-Table Consistency (all checks):**
1. EMA calculations match source prices
2. Features reference correct price bars
3. Signals align with features/prices
4. Metadata consistency across tables

**Audit Trail:**
- Database table (validation_log with results, errors, timestamps)
- Time-series metrics (success rates, error counts over time)
- User confirmed: "one and three should be good enough, we dont need two" (no separate log files)

### 4. Incremental Refresh Design

**State Tracking:**
- Approach: **State table** (dedicated table for refresh state)
- User validated: "i like three is that a good choice?" → Confirmed good choice
- Track: last_refresh_time, rows_processed, status, errors per (table, tf, asset)

**Idempotency:**
- Requirement: **Always idempotent** (reruns produce same result)
- Design mechanism to ensure idempotency (handle duplicates, use upsert patterns)
- Critical for retry logic and failure recovery

**Lookback Windows:**
- Decision: Claude's discretion
- Balance: Data freshness vs computational cost
- Consider: TF-specific lookback (longer for monthly vs daily)

**Failure Recovery (combined strategy):**
- **Checkpoint-based recovery:** Save progress at intervals, resume from last checkpoint
- **Manual recovery option:** Allow operator intervention for stuck states
- **Design combined strategy:** Checkpoints for automation + manual escape hatch for edge cases
- User: "two, three, and four - some combination"

## Open Questions for Planner

1. **EMA variant analysis:** Why do 4 different EMA tables exist? Should they be:
   - Merged into one unified table?
   - Kept separate as different calculation methods?
   - Partially unified (some are historical, some are current)?

2. **sync_cmc_ema_multi_tf_u.py evaluation:** Is the existing unification script sufficient?
   - Does it handle all required alignment types?
   - Does it properly reference dim_timeframe?
   - Does it support the (id, tf, period, alignment_source) primary key?

3. **Existing data migration safety:** How to safely merge existing EMA data?
   - What validation is needed before migration?
   - Can we prove equivalence between old and new calculations?
   - What rollback strategy if migration fails?

4. **Intraday future-proofing:** What schema changes support intraday without implementing it?
   - Session granularity (multiple sessions per day)?
   - TF definitions for sub-daily (1H, 15M, etc.)?
   - Bar alignment for intraday (session open vs wall clock)?

## Planning Guidance

**Investigation Phase:**
- Read and analyze all 4 EMA variant files
- Read sync_cmc_ema_multi_tf_u.py to assess sufficiency
- Examine existing EMA refresh scripts to confirm dim_timeframe usage
- Check existing data schema (what tables exist, what gets migrated)

**Design Decisions Required:**
- Choose: SQL seed file vs Python migration script vs hybrid
- Define: Exact dim_timeframe rows to populate (which TFs)
- Define: Exact dim_sessions rows to populate (which sessions)
- Specify: Lookback window logic (TF-dependent or fixed)
- Specify: Checkpoint granularity (per-asset, per-TF, per-table)
- Specify: Validation test coverage (how many tests per error type)

**Risk Areas:**
- Data loss during EMA unification (migration safety critical)
- Breaking existing refresh scripts (backward compatibility)
- DST transition bugs (session_windows_utc_by_key correctness)
- Performance regression (validation overhead on large datasets)

## Success Criteria Mapping

| ROADMAP Criterion | Context Coverage |
|-------------------|------------------|
| 1. dim_timeframe populated | Decision: Required TFs defined, population strategy chosen |
| 2. dim_sessions with DST | Decision: Required sessions defined, DST handling scoped |
| 3. Unified EMA table | Open: Investigation needed, primary key confirmed |
| 4. Scripts reference dim_timeframe | Existing: User confirmed already done, validation needed |
| 5. Validation tests pass | Decision: Error types, test structure, triggers all defined |
| 6. Incremental refresh | Decision: State tracking, idempotency, recovery all designed |
| 7. Rowcount validation | Decision: Included in validation strategy |

---

**Next Step:** `/gsd:plan-phase 6` — Create executable plans based on this context

_Context gathered: 2026-01-29_
_Participants: User (product owner), Claude (requirements analyst)_
