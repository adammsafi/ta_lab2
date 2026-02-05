# Gap Analysis: Bars & EMAs Infrastructure

**Deliverable:** RVWD-04
**Created:** 2026-02-05
**Phase:** 21 - Comprehensive Review
**Purpose:** Severity-tiered gap analysis sourced from Wave 1 outputs, prioritized for Phase 22-24

---

## Executive Summary

**Total Gaps Identified:** 15 (4 CRITICAL, 5 HIGH, 4 MEDIUM, 2 LOW)

**Key Themes:**
1. **Data Quality:** Multi-TF builders lack reject tables (silent repairs), no EMA output validation
2. **Documentation:** Manual asset onboarding, state management patterns undocumented
3. **Operational:** No summary logging, error recovery manual, backfill detection absent in 1D builder
4. **Code Quality:** No BaseBarBuilder template (80% duplication across 6 builders)
5. **Testing:** All validation is manual (no automated test suite)

**Priority Distribution:**
- **Phase 22 (Critical Data Quality):** 4 CRITICAL + 3 HIGH gaps → Fix silent data corruption, validation blind spots
- **Phase 23 (Reliable Operations):** 2 HIGH + 3 MEDIUM gaps → Operational automation, error handling
- **Phase 24 (Pattern Consistency):** 1 MEDIUM + 2 LOW gaps → Code quality, nice-to-haves

---

## CRITICAL Gaps (Blocks Data Quality)

### GAP-C01: Multi-TF builders have no rejects table

**Source:** validation-points.md lines 76-77
> "Multi-TF builder does not reject rows to a rejects table. Instead, it raises exceptions that halt processing for that ID. NULL validation is less strict than 1D builder."

**Impact:**
- OHLC invariant violations are silently repaired via enforce_ohlc_sanity (validation-points.md lines 189-237)
- No visibility into data quality issues (how many bars repaired? which invariants violated?)
- Cannot audit historical data quality problems (rejects table provides audit trail)
- Comparison: 1D builder logs ALL rejects with categorized reasons (validation-points.md lines 50-58)

**Recommendation:** Create reject tables for all 5 multi-TF builders
- Mirror 1D reject table schema: `(id, timestamp, tf, bar_seq, reason, time_open, time_close, ...)`
- Log rows BEFORE enforce_ohlc_sanity repair (capture original invalid values)
- Categorize reasons: `high_lt_low_before_repair`, `high_lt_oc_max_before_repair`, etc.
- Keep enforce_ohlc_sanity repair (don't change behavior), but log what was repaired

**Priority:** Phase 22 (Critical Data Quality Fixes)

**Effort:** 12-16 hours
- Replicate 1D rejects table pattern (5 builders × ~2 hours each)
- Shared reject schema in common_snapshot_contract.py (~4 hours)
- Testing: Inject broken OHLC, verify reject logging (~2 hours)

---

### GAP-C02: No EMA output validation

**Source:** validation-points.md lines 463-464
> "**EMA output validation:** None - No validation that computed EMA values are reasonable (e.g., not NaN, within expected range)"

**Impact:**
- Broken EMAs (NaN, infinity, negative values) persist to EMA tables
- Downstream features/signals use corrupt EMAs without warning
- Silent calculation drift: If compute_ema has bugs, no detection mechanism
- Real example: If alpha calculation breaks, EMAs could be constant or explode

**Recommendation:** Add EMA sanity checks before database write
- NOT NULL check: `WHERE ema IS NOT NULL`
- Range check: `ema BETWEEN (0.5 * min_price) AND (2.0 * max_price)` for given asset/TF window
- NaN/infinity check: `WHERE ema IS NOT NULL AND ema > 0 AND ema < 'infinity'::float`
- Reject invalid EMAs to audit table (similar to bar rejects)

**Priority:** Phase 22 (Critical Data Quality Fixes)

**Effort:** 8-12 hours
- Add validation layer to BaseEMARefresher (~4 hours)
- Define reasonable bounds (price-based, not hardcoded) (~2 hours)
- Create ema_rejects table schema (~1 hour)
- Test with intentionally broken compute_ema (~3 hours)

---

### GAP-C03: 1D bars: No backfill detection

**Source:** incremental-refresh.md lines 173-177
> "**1D Bars:** No backfill detection
> - State tracks `last_src_ts` only (not min)
> - Always processes from `last_src_ts - lookback_days` forward
> - No detection of historical data appearing before first processed row"

**Impact:**
- If price_histories7 backfills historical data (before first processed date), 1D bars never rebuild
- bar_seq numbering becomes incorrect (bar_seq assigned via dense_rank from first row)
- Comparison: Multi-TF builders detect backfill via daily_min_seen (incremental-refresh.md lines 179-202)
- Data corruption risk: Backfilled historical data invisible to 1D builder

**Recommendation:** Add backfill detection to 1D builder
- Track `daily_min_seen` in cmc_price_bars_1d_state (add column, default to last_src_ts for existing rows)
- Query: `SELECT MIN(timestamp) as daily_min_ts FROM price_histories7 WHERE id = ?`
- Compare: `if daily_min_ts < daily_min_seen → rebuild required`
- Rebuild: DELETE bars for id, reprocess all history, update state

**Priority:** Phase 22 (Critical Data Quality Fixes)

**Effort:** 6-8 hours
- Alter state table schema (add daily_min_seen column) (~1 hour)
- Add backfill detection logic to refresh_cmc_price_bars_1d.py (~3 hours)
- Backfill existing state rows with daily_min_seen = last_src_ts (~1 hour)
- Test: Insert historical data before first bar, verify rebuild triggered (~2 hours)

---

### GAP-C04: No automated validation test suite

**Source:** validation-points.md lines 523-597 (Testing Strategy section describes manual tests only)
> "### How to Verify Validation Works
> **1D Bar Builder:**
> ```bash
> python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py --ids 1 --keep-rejects --fail-on-rejects
> psql -c \"SELECT reason, COUNT(*) FROM public.cmc_price_bars_1d_rejects GROUP BY reason ORDER BY 2 DESC;\"
> ```"

**Impact:**
- Validation regressions undetected (no CI tests to catch broken OHLC checks)
- Manual testing required after every builder change (time-consuming, error-prone)
- No coverage visibility: Can't measure which validation paths are exercised
- Comparison: Tests directory has connectivity tests (tests/test_connectivity.py) but NO bar/EMA validation tests

**Recommendation:** Create automated validation test suite
- Test OHLC invariant enforcement: Inject broken OHLC, assert rejection/repair
- Test NULL rejection: Inject NULL values, assert rejection to rejects table
- Test quality flags: Verify is_partial_end, is_missing_days set correctly
- Test EMA filtering: Verify is_partial_end=TRUE bars excluded from EMA computation
- Test backfill detection: Inject historical data, verify rebuild triggered
- CI integration: Run tests on every PR, block merge if validation fails

**Priority:** Phase 22 (Critical Data Quality Fixes)

**Effort:** 16-24 hours
- Test infrastructure setup (fixtures, mock data) (~6 hours)
- Bar validation tests (NULL, OHLC, quality flags) (~8 hours)
- EMA validation tests (filtering, output sanity) (~4 hours)
- State management tests (backfill, incremental) (~4 hours)
- CI integration (GitHub Actions workflow) (~2 hours)

---

## HIGH Gaps (Makes Onboarding Error-Prone)

### GAP-H01: Manual dim_assets insertion (no validation)

**Source:** new-asset-guide.md lines 27-68 (Step 1: Add to dim_assets shows manual SQL INSERT)
> "### Action
> ```sql
> INSERT INTO public.dim_assets (id, cmc_id, symbol, name)
> VALUES (<internal_id>, <cmc_id>, '<symbol>', '<name>')
> ON CONFLICT (id) DO NOTHING;
> ```"

**Impact:**
- Error-prone: Typos in symbol/name, duplicate cmc_id, wrong id assignment
- No CMC API validation: Can insert invalid cmc_id that doesn't exist
- No duplicate detection: Manual check required (`GROUP BY cmc_id HAVING COUNT(*) > 1`)
- Manual workflow: Slows down asset onboarding, increases cognitive load

**Recommendation:** Create add_asset.py script with validation
- CLI: `python add_asset.py --cmc-id 1027 --symbol ETH --name Ethereum --validate`
- CMC API validation: Check cmc_id exists, is active, retrieve metadata
- Duplicate detection: Query dim_assets, warn if cmc_id already exists
- Auto-assign id: Use `MAX(id) + 1` from dim_assets (or user-provided)
- Confirmation prompt: Show metadata, ask "Proceed? [y/N]"

**Priority:** Phase 23 (Reliable Operations)

**Effort:** 6-8 hours
- CLI argument parsing (argparse) (~1 hour)
- CMC API integration (requests + caching) (~3 hours)
- dim_assets query/insert logic (~2 hours)
- Duplicate detection + confirmation flow (~2 hours)

---

### GAP-H02: No orchestration script for full asset onboarding

**Source:** new-asset-guide.md lines 787-801 (Quick Reference shows 6 separate commands)
> "```bash
> # Step 2: Build 1D bars
> python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py --ids <id> --keep-rejects
> # Step 3: Build multi-TF bars
> python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_multi_tf.py --ids <id>
> # Step 4: Compute EMAs
> python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py --ids <id>
> ```"

**Impact:**
- Manual step-by-step execution (15-40 minutes per asset, new-asset-guide.md line 816)
- No error propagation: If Step 2 fails, user might run Step 3 anyway (wastes time)
- No progress visibility: User doesn't know when safe to interrupt
- No rollback on failure: Partial asset state (bars exist, EMAs missing)

**Recommendation:** Create onboard_asset.py orchestrator script
- CLI: `python onboard_asset.py --id 1 --validate --build-bars --compute-emas`
- Sequential execution: Step 2 → Step 3 → Step 4 (fail-fast on errors)
- Progress logging: "Step 2/4: Building 1D bars... [DONE in 3.2s]"
- Validation queries: Automatic checks after each step (bar counts, state verification)
- Rollback option: `--rollback-on-failure` flag to DELETE partial data

**Priority:** Phase 23 (Reliable Operations)

**Effort:** 8-12 hours
- Orchestration framework (step sequencing, error handling) (~4 hours)
- Progress logging + validation queries (~3 hours)
- Rollback logic (DELETE bars/state for id) (~2 hours)
- Integration tests (end-to-end onboarding) (~3 hours)

---

### GAP-H03: State schema variation undocumented (looks like inconsistency)

**Source:** incremental-refresh.md lines 653-660 (Comparison table shows intentional variation)
> "| **State granularity** | 1D: (id)<br>Multi-TF: (id, tf) | (id, tf, period) |"

**Impact:**
- Appears inconsistent: 1D uses (id), multi-TF uses (id, tf), EMAs use (id, tf, period)
- Developers may "fix" variation, breaking state management
- Not obvious WHY schemas differ: 1D needs simple watermark, multi-TF needs backfill detection
- Phase 20 CURRENT-STATE.md clarified variation is JUSTIFIED (line 274), but not in code comments

**Recommendation:** Add schema justification comments to state DDL
- Add comment block above each CREATE TABLE statement
- Document WHY schema differs from other builders
- Example for 1D: "Schema uses (id) PRIMARY KEY because 1D bars have no TF dimension. Multi-TF builders use (id, tf) for per-timeframe watermarks."
- Example for multi-TF: "Schema uses daily_min_seen for backfill detection. 1D builder doesn't need backfill detection (bar_seq independent of historical data)."

**Priority:** Phase 23 (Reliable Operations)

**Effort:** 2-3 hours
- Write justification comments for all state table schemas (~1 hour)
- Update STATE.md to cross-reference code comments (~1 hour)

---

### GAP-H04: No error recovery documentation (manual DB surgery)

**Source:** new-asset-guide.md troubleshooting sections (lines 568-674) describe manual fixes, no recovery scripts

**Impact:**
- When onboarding fails mid-process (e.g., Step 3 crashes), no clear recovery path
- Manual DB surgery: Users must write DELETE statements to clean up partial state
- Risk of incorrect cleanup: Deleting too much (other assets) or too little (orphaned rows)
- No rollback: Can't easily undo failed onboarding attempt

**Recommendation:** Create recovery.py utility script
- CLI: `python recovery.py --id 1 --reset-bars --reset-emas --reset-state`
- Operations:
  - `--reset-bars`: DELETE FROM bars tables WHERE id = ?
  - `--reset-emas`: DELETE FROM EMA tables WHERE id = ?
  - `--reset-state`: DELETE FROM state tables WHERE id = ?
  - `--reset-all`: All of the above
- Safety: `--dry-run` flag to preview DELETE queries without executing
- Confirmation: Require `--confirm` flag for destructive operations

**Priority:** Phase 23 (Reliable Operations)

**Effort:** 4-6 hours
- CLI argument parsing (~1 hour)
- DELETE query generation (parameterized, safe) (~2 hours)
- Dry-run + confirmation flow (~1 hour)
- Testing: Verify doesn't delete other assets (~1 hour)

---

### GAP-H05: No observability for incremental refresh (silent success/failure)

**Source:** incremental-refresh.md lines 468-479 (Performance section mentions no summary logging)
> "**Incremental append fails**
> - **Multi-TF:** (lines 956-970) Catch exception, log error, update state to preserve last known good watermark"

Also: script-inventory.md line 525-528
> "**Logging:**
> - Worker-level logging via `get_worker_logger()` at lines 56-61
> - Logs start/complete/errors per ID"

**Impact:**
- No summary of work done: "Refreshed 3 assets, inserted 150 bars, updated 4500 EMAs"
- Silent failures: If incremental append fails for 1 asset out of 50, no aggregate visibility
- No performance metrics: Can't measure refresh time per asset, bottleneck identification
- Manual checking: Must query state tables to see if refresh completed

**Recommendation:** Add summary logging to all refresh scripts
- Print at script completion:
  ```
  === REFRESH SUMMARY ===
  Assets processed: 3
  1D bars: 150 rows inserted, 0 rejected
  Multi-TF bars: 1050 snapshots inserted (7 TFs)
  EMAs: 4500 rows inserted (7 TFs × 17 periods × 3 assets)
  Duration: 42.3s
  Errors: 0
  ```
- Per-asset timing: Log slowest asset (helps identify bottlenecks)
- Error aggregation: "Errors: 2 (asset 52: CMC API timeout, asset 1027: OHLC validation failed)"

**Priority:** Phase 23 (Reliable Operations)

**Effort:** 4-6 hours
- Add summary collection to BaseEMARefresher (~2 hours)
- Add summary logging to bar builders (~2 hours)
- Format output (table or JSON) (~1 hour)

---

## MEDIUM Gaps (Requires Workarounds)

### GAP-M01: BaseBarBuilder template class missing (80% duplication)

**Source:** script-inventory.md lines 695-702
> "**Bar Builders:**
> - Total scripts: 6
> - Shared dependencies: `common_snapshot_contract` (6/6 scripts), `dim_timeframe` (5/6 scripts), `polars` (5/6 scripts)
> - LOC range: ~850 (refresh_cmc_price_bars_1d.py) to ~1450+ (cal_us, cal_iso, anchor variants)"

Also: ema-variants.md lines 369-389 shows EMA scripts reduced from ~500 LOC to ~150 LOC via BaseEMARefresher

**Impact:**
- Code duplication: DB connection, CLI parsing, state loading duplicated 6 times
- Inconsistent patterns: Each builder implements similar logic slightly differently
- Harder to maintain: Bug fixes must be applied to 6 scripts
- Comparison: EMA scripts achieved 70% LOC reduction via BaseEMARefresher pattern

**Recommendation:** Extract BaseBarBuilder template class
- Pattern: Follow BaseEMARefresher design (template method pattern)
- Shared logic: DB connection, CLI parsing, state loading/updating, ID resolution
- Abstract methods: `build_bars_for_id(df_daily) -> df_bars` (builder-specific OHLC logic)
- Inheritance: All 6 builders inherit from BaseBarBuilder
- Benefit: 80% code reduction (~850 LOC → ~200 LOC per builder)

**Priority:** Phase 24 (Pattern Consistency)

**Effort:** 20-30 hours
- Design BaseBarBuilder interface (~4 hours)
- Implement shared template logic (~8 hours)
- Refactor 1D builder to use template (~4 hours)
- Refactor 5 multi-TF builders (~10 hours, ~2 hours each)
- Testing: Verify no behavior change (~4 hours)

---

### GAP-M02: No dim_assets population script (manual SQL)

**Source:** new-asset-guide.md lines 27-37 (Prerequisites assume dim_assets pre-populated)

**Impact:**
- Initial setup unclear: New users don't know how to populate dim_assets
- No bulk import: Adding 20 assets requires 20 manual INSERT statements
- No CMC sync: dim_assets can drift from CMC asset universe (delisted coins, new listings)

**Recommendation:** Create populate_dim_assets.py script
- CLI: `python populate_dim_assets.py --from-cmc --top-n 100 --dry-run`
- CMC API integration: Fetch top N assets by market cap
- Bulk insert: INSERT multiple assets in single transaction
- Sync mode: Update existing assets (symbol/name changes), insert new
- Dry-run: Preview inserts without committing

**Priority:** Phase 24 (Pattern Consistency)

**Effort:** 6-8 hours
- CMC API integration (fetch asset list) (~3 hours)
- Bulk INSERT logic (~2 hours)
- Sync detection (compare existing vs CMC) (~2 hours)
- Testing: Mock CMC API responses (~1 hour)

---

### GAP-M03: Calendar builders: tz column NOT in PRIMARY KEY (looks like design bug)

**Source:** incremental-refresh.md lines 56-62
> "#### Calendar Multi-TF State (with timezone)
> Same schema as multi-TF bars, plus:
> | Column | Type | Purpose |
> |--------|------|---------|
> | tz | text | Timezone for calendar alignment (NOT in primary key) |
> **Primary key:** (id, tf) — **NOT** (id, tf, tz)"

**Impact:**
- Ambiguous: State table has tz column but it's not in PRIMARY KEY
- Appears as design bug: If tz differs per (id, tf), should be in PK to prevent conflicts
- Actually correct: Calendar builders process one tz at a time (--tz flag), so no conflicts
- But not obvious: Requires understanding builder execution model to see why PK is correct

**Recommendation:** Add clarifying comment to state DDL
- Comment: "tz column is metadata only, NOT part of PRIMARY KEY because calendar builders process single timezone per run (via --tz flag). Multiple timezones for same (id, tf) not supported in same state table."
- Alternative design (deferred): If multi-tz support needed, change PK to (id, tf, tz)

**Priority:** Phase 24 (Pattern Consistency)

**Effort:** 1 hour
- Add comment to state DDL in calendar builder scripts
- Update incremental-refresh.md to clarify design rationale

---

### GAP-M04: No gap-fill strategy documented (is_missing_days flags exist, but then what?)

**Source:** validation-points.md lines 396-403
> "#### Gap Detection (Missing Days in Sequence)
> **Already covered:** See is_missing_days section above
> **Location:** Multi-TF bar builder during snapshot computation (lines 367-376)
> **Action:** Flag set, no rejection"

Also: new-asset-guide.md line 421
> "**Issue:** is_missing_days=TRUE for many bars
> **Cause:** Gaps in price_histories7 data (weekends, holidays, data outages)
> **Solution:** This is informational, not an error. Downstream systems can filter bars with gaps if needed."

**Impact:**
- Quality flags set but unused: is_missing_days=TRUE means bar has gaps, but no downstream action
- No EMA gap-fill: EMAs computed on gapped bars without special handling (potential accuracy issues)
- No documentation: Should EMAs be reseeded after gaps? Marked as low-quality?
- Manual decision: Each consumer (features, signals) must decide how to handle is_missing_days

**Recommendation:** Document gap-fill strategy in ARCHITECTURE.md
- Policy: "Bars with is_missing_days=TRUE are included in EMA computation by default. EMAs propagate through gaps using last available value."
- Alternative strategies:
  - "Strict: Filter WHERE is_missing_days=FALSE (only gap-free bars)"
  - "Gap-reseed: Reset EMA computation after N-day gap (requires new EMAStateManager logic)"
  - "Flag propagation: Set ema_quality='gap-affected' if source bar has is_missing_days=TRUE"
- Phase 22 decision: Document current behavior (gaps included), defer gap-reseed to Phase 25

**Priority:** Phase 24 (Pattern Consistency)

**Effort:** 2-3 hours
- Document current gap behavior in ARCHITECTURE.md (~1 hour)
- Add gap-fill policy to EMA feature module docstrings (~1 hour)

---

## LOW Gaps (Nice-to-Have)

### GAP-L01: Six separate EMA state tables (could unify with alignment_source)

**Source:** ema-variants.md lines 458-465 (Open Question 4)
> "**Question 4: Six state tables - Could be one unified?**
> **Similarity:** All 6 variants use identical state schema defined in `ema_state_manager.py` lines 78-99:
> ```sql
> PRIMARY KEY (id, tf, period)
> Columns: daily_min_seen, daily_max_seen, last_time_close, last_canonical_ts, last_bar_seq, updated_at
> ```
> **Current design:** Each variant has separate state table"

Also: variant-comparison.md lines 346-371 (Question 4 section)

**Impact:**
- Table proliferation: 6 state tables with identical schema
- Operational complexity: Must manage 6 separate tables (backfill, cleanup, monitoring)
- Minor: No schema conflicts (all identical), but more tables to maintain

**Recommendation:** Evaluate unified EMA state table with alignment_source discriminator
- Alternative schema:
  ```sql
  PRIMARY KEY (id, tf, period, alignment_source)
  alignment_source IN ('multi_tf', 'multi_tf_v2', 'cal_us', 'cal_iso', 'cal_anchor_us', 'cal_anchor_iso')
  ```
- Pros: Single table, easier to query across variants
- Cons: Higher complexity (discriminator column), harder to backfill single variant
- Decision: Defer to Phase 24 (not critical, existing design works)

**Priority:** Phase 24 (Pattern Consistency) - LOW PRIORITY

**Effort:** 16-24 hours
- Schema design (unified vs separate tables) (~4 hours)
- Migration script (consolidate existing state tables) (~8 hours)
- Update EMAStateManager to support discriminator (~6 hours)
- Testing: Verify all 6 variants work with unified table (~6 hours)

**Note:** Operational isolation (backfill one variant without affecting others) may justify separate tables. Document trade-offs but don't consolidate unless clear benefit.

---

### GAP-L02: No bar metadata table (must query bars to get date ranges)

**Source:** new-asset-guide.md line 334-348 (Validation queries must scan full bars table to get MIN/MAX dates)

**Impact:**
- Slow queries: `SELECT MIN(timestamp), MAX(timestamp) FROM cmc_price_bars_1d WHERE id = ?` scans full table
- No caching: Date ranges recomputed every query
- Minor performance: Only affects validation queries, not production pipeline

**Recommendation:** Create bar_metadata table (optional optimization)
- Schema:
  ```sql
  CREATE TABLE bar_metadata (
    id INTEGER,
    table_name TEXT,  -- 'cmc_price_bars_1d', 'cmc_price_bars_multi_tf', etc.
    first_date TIMESTAMPTZ,
    last_date TIMESTAMPTZ,
    row_count INTEGER,
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id, table_name)
  );
  ```
- Updated by bar builders after upsert (add metadata update step)
- Benefits: Fast date range queries (index scan instead of table scan)
- Cons: Extra table to maintain, potential for stale metadata if update fails

**Priority:** Deferred (optimization, not correctness issue)

**Effort:** 4-6 hours
- Create bar_metadata table and indexes (~1 hour)
- Add metadata update to bar builders (~2 hours)
- Update validation queries to use metadata (~1 hour)
- Testing: Verify metadata accuracy (~1 hour)

---

## Summary by Category

| Category | CRITICAL | HIGH | MEDIUM | LOW | Total |
|----------|----------|------|--------|-----|-------|
| **Data Quality** | 4 | 0 | 0 | 0 | 4 |
| **Documentation** | 0 | 1 | 2 | 0 | 3 |
| **Operational** | 0 | 4 | 0 | 0 | 4 |
| **Code Quality** | 0 | 0 | 1 | 1 | 2 |
| **Testing** | 0 | 0 | 1 | 0 | 1 |
| **Performance** | 0 | 0 | 0 | 1 | 1 |
| **TOTAL** | 4 | 5 | 4 | 2 | 15 |

---

## Recommended Prioritization

### Phase 22: Critical Data Quality Fixes (Q1 2026)

**Focus:** Fix silent data corruption, validation blind spots

**Gaps to address:**
- GAP-C01: Multi-TF reject tables (CRITICAL, 12-16h)
- GAP-C02: EMA output validation (CRITICAL, 8-12h)
- GAP-C03: 1D backfill detection (CRITICAL, 6-8h)
- GAP-C04: Automated validation tests (CRITICAL, 16-24h)
- GAP-H03: State schema documentation (HIGH, 2-3h)

**Total effort:** 44-63 hours (1-1.5 weeks full-time)

**Success criteria:**
- All multi-TF builders log rejects (audit trail exists)
- EMA sanity checks catch NaN/infinity/out-of-range values
- 1D builder detects and handles backfilled historical data
- Validation test suite runs in CI, blocks merge on failures
- State schema variation documented in code comments

---

### Phase 23: Reliable Operations (Q1-Q2 2026)

**Focus:** Operational automation, error handling, observability

**Gaps to address:**
- GAP-H01: add_asset.py script (HIGH, 6-8h)
- GAP-H02: onboard_asset.py orchestrator (HIGH, 8-12h)
- GAP-H04: recovery.py utility (HIGH, 4-6h)
- GAP-H05: Summary logging (HIGH, 4-6h)
- GAP-M02: populate_dim_assets.py script (MEDIUM, 6-8h)
- GAP-M04: Gap-fill strategy documentation (MEDIUM, 2-3h)

**Total effort:** 30-43 hours (1 week full-time)

**Success criteria:**
- Asset onboarding is single command (add_asset.py + onboard_asset.py)
- Failed onboarding recoverable (recovery.py --reset-all)
- Incremental refresh summary shows work done, errors, timing
- Bulk dim_assets population from CMC API
- Gap-fill policy documented (current behavior + alternatives)

---

### Phase 24: Pattern Consistency (Q2 2026)

**Focus:** Code quality, maintainability, nice-to-haves

**Gaps to address:**
- GAP-M01: BaseBarBuilder template class (MEDIUM, 20-30h)
- GAP-M03: Calendar tz column documentation (MEDIUM, 1h)
- GAP-L01: Unified EMA state table evaluation (LOW, 16-24h if pursued)
- GAP-L02: bar_metadata table (LOW, 4-6h if pursued)

**Total effort:** 21-31 hours (0.5-1 week full-time) for MEDIUM gaps only

**Success criteria:**
- Bar builders reduced from ~850 LOC to ~200 LOC via BaseBarBuilder
- Calendar tz column rationale documented
- Decision documented for L01/L02: unify or keep separate (with trade-off analysis)

---

### Deferred (Phase 25+ or Never)

**Gaps without clear ROI:**
- GAP-L01: Unified EMA state table (operational isolation may justify separation)
- GAP-L02: bar_metadata table (optimization, not correctness issue)

**Rationale:** These gaps have workarounds (current design works), and benefits don't outweigh migration costs. Document trade-offs but defer implementation unless usage patterns change.

---

## Gap Analysis Completeness

**Wave 1 outputs analyzed:**
1. ✓ script-inventory.md: 6 bar builders, 4 EMA refreshers, supporting modules cataloged
2. ✓ data-flow-diagram.md: L0/L1/L2 flows documented, validation points identified
3. ✓ ema-variants.md: 6 variants compared, open questions flagged (basis for GAP-L01)
4. ✓ variant-comparison.md: Dimension-by-dimension analysis, similarities/differences documented
5. ✓ incremental-refresh.md: State management patterns documented, backfill mechanics (basis for GAP-C03)
6. ✓ validation-points.md: Validation coverage analysis, gaps section (basis for GAP-C01, GAP-C02, GAP-C04)

**Evidence standard:** Every gap cites source document + line numbers or section references.

**Validation:** All CRITICAL gaps trace to validation-points.md or incremental-refresh.md (data quality/reliability focus). All HIGH gaps trace to new-asset-guide.md or operational patterns. MEDIUM/LOW gaps trace to code duplication observations or nice-to-have optimizations.

---

## Conclusion

**Key findings:**
1. **Data quality is strong at bar level** (1D builder has comprehensive validation)
2. **Multi-TF builders have silent repair** (no reject visibility)
3. **EMA validation is absent** (assumes bars are correct, no output checks)
4. **Operational tooling is manual** (asset onboarding requires 6 separate commands)
5. **Code duplication is high in bar builders** (80% shared logic not extracted)

**Recommended approach:**
- **Phase 22 (4-6 weeks):** Fix CRITICAL data quality gaps → Reject tables, EMA validation, 1D backfill, test suite
- **Phase 23 (1-2 weeks):** Build operational tools → add_asset, onboard_asset, recovery, summary logging
- **Phase 24 (1-2 weeks):** Extract BaseBarBuilder → Reduce duplication, improve maintainability
- **Deferred:** LOW priority gaps (unified state table, bar_metadata) → Document trade-offs, implement only if usage justifies

**Total effort:** 95-137 hours (3-4 weeks full-time) for Phases 22-24.

**Success metric:** Zero silent data corruption (reject visibility), automated asset onboarding (<5 minutes, single command), 80% code reduction in bar builders (BaseBarBuilder template).
