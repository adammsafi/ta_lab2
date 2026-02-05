# Current State Assessment: Bars & EMAs

**Assessment Date:** 2026-02-05
**Phase:** 20 - Historical Context
**Scope:** Bar builders and EMA calculators health analysis

## Executive Summary

**Overall Health Status:** WORKS with minor quality improvements needed

The bar builders and EMA infrastructure is fundamentally sound with strong validation frameworks and modern performance optimizations. All 6 bar builder variants and 6 EMA variants are functional and operational. Critical finding: EMAs are **ALREADY USING VALIDATED BAR TABLES**, contradicting initial v0.6.0 assumptions. The primary issues are inconsistencies in documentation, state management patterns, and quality flag semantics rather than broken functionality.

**Key Findings:**
- Bar builders: OHLC calculation and validation WORKS across all 6 variants
- EMAs: All 6 variants use validated bar tables (cmc_price_bars_*), not price_histories7
- Data source migration (assumed v0.6.0 priority) is ALREADY COMPLETE
- State management patterns exist but vary in implementation across scripts
- Quality flags (is_partial_start, is_partial_end, is_missing_days) are present but semantics undocumented

**v0.6.0 Priorities Should Shift To:**
1. Document quality flag semantics (UNCLEAR → documented)
2. Standardize state management patterns (inconsistent → uniform)
3. Add gap detection validation (works but inconsistent)
4. Improve incremental refresh observability (state exists but visibility low)

## Health Criteria

**Three-Tier Assessment:**
- **Functional**: Scripts run successfully, data updates correctly, calculations are accurate
- **Maintainable**: Code is clear, consistent, documented, and safe to modify
- **Scalable**: Ready for 50+ assets without major architectural changes

**Status Definitions:**
- **WORKS**: All three criteria met (functional + maintainable + scalable) - low risk to modify
- **UNCLEAR**: Functional but maintenance/scale uncertain (inconsistent, undocumented, untested) - medium risk
- **BROKEN**: Functional failure (crashes, wrong results, doesn't run) - high risk, requires fixing

## Bar Builders Health Matrix

| Script | OHLC Calc | Gap Detection | Quality Flags | Incr Refresh | Validation | Overall |
|--------|-----------|---------------|---------------|--------------|------------|---------|
| refresh_cmc_price_bars_1d.py | WORKS | WORKS | UNCLEAR | WORKS | WORKS | WORKS |
| refresh_cmc_price_bars_multi_tf.py | WORKS | WORKS | UNCLEAR | WORKS | WORKS | WORKS |
| refresh_cmc_price_bars_multi_tf_cal_us.py | WORKS | WORKS | UNCLEAR | WORKS | WORKS | WORKS |
| refresh_cmc_price_bars_multi_tf_cal_iso.py | WORKS | WORKS | UNCLEAR | WORKS | WORKS | WORKS |
| refresh_cmc_price_bars_multi_tf_cal_anchor_us.py | WORKS | WORKS | UNCLEAR | WORKS | WORKS | WORKS |
| refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py | WORKS | WORKS | UNCLEAR | WORKS | WORKS | WORKS |

### Bar Builder Detailed Findings

<details>
<summary>refresh_cmc_price_bars_1d.py</summary>

**OHLC Calculation: WORKS**
- Evidence: Lines 267-489 - comprehensive OHLC calculation with repair logic
- Implementation: Deterministic bar_seq from dense_rank, OHLC invariants enforced
- Validation: High >= low, time_high/time_low within [time_open, time_close]
- Notes: Includes repair logic for invalid time_high/time_low (lines 334-365)

**Gap Detection: WORKS**
- Evidence: Lines 141-143 - is_missing_days flag exists
- Implementation: Boolean flag set during bar creation
- Notes: Logic is hardcoded to FALSE for 1D bars (line 408) - 1D bars are canonical, never partial
- Scalability: Simple boolean check, no performance concerns

**Quality Flags: UNCLEAR**
- Evidence: Lines 141-143 - is_partial_start, is_partial_end, is_missing_days columns exist
- Issue: Flag semantics not documented - what triggers each flag? When are they set?
- Impact: Other scripts/features may interpret flags inconsistently
- Current behavior: All set to FALSE for 1D canonical bars (lines 408-410)

**Incremental Refresh: WORKS**
- Evidence: Lines 670-778 - state-based incremental with lookback
- Implementation: Uses cmc_price_bars_1d_state table with last_src_ts tracking
- State pattern: Per-id watermark with configurable lookback_days (default 3)
- Scalability: Processes ids individually, no O(n²) issues

**Data Validation: WORKS**
- Evidence: Lines 440-459 - comprehensive OHLC invariant checks before insert
- Checks: NOT NULL constraints, time ordering, OHLC bounds (high >= max(open,close,low))
- Rejects handling: Lines 492-662 - categorized reject reasons logged to rejects table
- Quality: 15 distinct reject reasons for debugging (lines 590-604)

</details>

<details>
<summary>refresh_cmc_price_bars_multi_tf.py</summary>

**OHLC Calculation: WORKS**
- Evidence: Lines 175-313 (Polars vectorization) - full build using cumulative operations
- Implementation: cum_max/cum_min for high/low, cumsum for volume, per-bar aggregations
- Performance: Polars path is 20-30% faster than pandas (documented line 23)
- Fallback: Lines 316-441 - pandas reference implementation maintained

**Gap Detection: WORKS**
- Evidence: Lines 367-377 (pandas) and missing_days logic in Polars pipeline
- Implementation: Computes missing days from expected vs observed days per bar
- Contract: Uses common_snapshot_contract.compute_missing_days_diagnostics
- Notes: Gap detection integrated into bar building, not post-hoc

**Quality Flags: UNCLEAR**
- Evidence: Lines 261-268 (Polars), lines 400-402 (pandas) - flags set during bar creation
- Flags: is_partial_start (always FALSE), is_partial_end (pos_in_bar < tf_days), is_missing_days
- Issue: Semantics clear in code but not documented for downstream consumers
- Impact: Features reading bars may misinterpret flag meaning

**Incremental Refresh: WORKS**
- Evidence: Lines 746-981 - serial incremental, lines 1219-1304 - parallel incremental
- State management: cmc_price_bars_multi_tf_state with daily_min_seen/daily_max_seen tracking
- Backfill detection: Lines 863-895 - rebuilds if daily_min moves earlier
- Scalability: Multiprocessing support (--num-processes flag), orchestrator-based (line 1274)

**Data Validation: WORKS**
- Evidence: Lines 195-196 - assert_one_row_per_local_day contract enforcement
- Validation: Enforces 1 row per local day invariant before processing
- OHLC sanity: Lines 311-312 - enforce_ohlc_sanity applied to output
- Quality: Contract module ensures consistency across all bar builders

</details>

<details>
<summary>refresh_cmc_price_bars_multi_tf_cal_us.py</summary>

**OHLC Calculation: WORKS**
- Evidence: Lines 444-663 (Polars) - calendar-aligned bar building with cumulative aggregations
- Implementation: US calendar semantics (Sunday-start weeks), full-period only
- Contract: Uses common_snapshot_contract for schema normalization
- Performance: Polars vectorization 5-6x faster than pandas (documented line 28)

**Gap Detection: WORKS**
- Evidence: Lines 576-586 (Polars) - missing days diagnostics computed per snapshot
- Implementation: Tracks count_missing_days, count_missing_days_start/end/interior
- Calendar-aware: Gap detection respects calendar boundaries (weeks/months/years)
- Notes: More sophisticated than multi_tf - tracks gap location within bars

**Quality Flags: UNCLEAR**
- Evidence: Lines 596-598 - is_partial_end based on day_date < bar_end comparison
- Flags: is_partial_start (always FALSE - full-period only), is_partial_end, is_missing_days
- Issue: Calendar semantics for flags not documented (when is a month bar "partial"?)
- Impact: Users may not understand when calendar bars are considered complete

**Incremental Refresh: WORKS**
- Evidence: Lines 1182-1288 - incremental with multiprocessing orchestrator
- State management: cmc_price_bars_multi_tf_cal_us_state with per-(id,tf,tz) tracking
- Fast path: Lines 1094-1167 - uses Polars rebuild + filter instead of iterrows
- Scalability: Batch loads last snapshot info for all TFs (line 962), parallel by ID

**Data Validation: WORKS**
- Evidence: Line 460 - assert_one_row_per_local_day enforced
- Contract: Shared contract module ensures consistency with other builders
- Calendar validation: Lines 373-426 - calendar boundary computation functions
- Quality: Deterministic tie-breaks for time_high/time_low (earliest among ties)

</details>

<details>
<summary>refresh_cmc_price_bars_multi_tf_cal_iso.py</summary>

**OHLC Calculation: WORKS**
- Evidence: Structure mirrors cal_us.py with ISO calendar semantics
- Implementation: ISO week start is Monday (vs Sunday for US)
- Contract: Uses common_snapshot_contract (line 30)
- Notes: ISO calendar variant, same quality as cal_us

**Gap Detection: WORKS**
- Evidence: Uses same missing_days diagnostics as cal_us
- Implementation: Calendar-aware gap tracking
- Notes: ISO calendar boundaries respected

**Quality Flags: UNCLEAR**
- Evidence: Same flag structure as cal_us
- Issue: ISO-specific calendar semantics not documented
- Impact: Users may confuse ISO vs US calendar flag behavior

**Incremental Refresh: WORKS**
- Evidence: Multiprocessing orchestrator-based refresh
- State management: cmc_price_bars_multi_tf_cal_iso_state
- Scalability: Same performance optimizations as cal_us

**Data Validation: WORKS**
- Evidence: assert_one_row_per_local_day enforced
- Contract: Shared contract module
- Quality: ISO calendar boundary validation

</details>

<details>
<summary>refresh_cmc_price_bars_multi_tf_cal_anchor_us.py</summary>

**OHLC Calculation: WORKS**
- Evidence: Anchor variant extends cal_us logic
- Implementation: Year-anchored calendar bars (resets at year boundary)
- Notes: Anchor semantics add complexity but OHLC calculation sound

**Gap Detection: WORKS**
- Evidence: Same diagnostics as cal_us
- Implementation: Anchor-aware gap tracking
- Notes: Gap detection respects year-anchor boundaries

**Quality Flags: UNCLEAR**
- Evidence: Same flag structure as cal_us
- Issue: Anchor semantics not documented (when does anchoring affect flags?)
- Impact: Year-boundary anchor behavior may surprise users

**Incremental Refresh: WORKS**
- Evidence: Multiprocessing orchestrator-based
- State management: cmc_price_bars_multi_tf_cal_anchor_us_state
- Scalability: Same optimizations as cal_us/cal_iso

**Data Validation: WORKS**
- Evidence: Contract module enforced
- Quality: Anchor boundary validation

</details>

<details>
<summary>refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py</summary>

**OHLC Calculation: WORKS**
- Evidence: ISO + anchor variant
- Implementation: Year-anchored ISO calendar bars
- Notes: Combines ISO calendar + year anchor

**Gap Detection: WORKS**
- Evidence: Same diagnostics as other calendar builders
- Implementation: ISO + anchor-aware gap tracking

**Quality Flags: UNCLEAR**
- Evidence: Same flag structure
- Issue: ISO + anchor semantics interaction not documented

**Incremental Refresh: WORKS**
- Evidence: Multiprocessing orchestrator-based
- State management: cmc_price_bars_multi_tf_cal_anchor_iso_state
- Scalability: Same optimizations

**Data Validation: WORKS**
- Evidence: Contract module enforced
- Quality: ISO + anchor validation

</details>

## EMA Calculators Health Matrix

| Variant | EMA Calc | Data Loading | Multi-TF | State Mgmt | Cal/Anchor | Overall |
|---------|----------|--------------|----------|------------|------------|---------|
| ema_multi_timeframe (v1) | WORKS | WORKS* | WORKS | WORKS | N/A | WORKS |
| ema_multi_tf_v2 | WORKS | WORKS* | WORKS | WORKS | N/A | WORKS |
| ema_multi_tf_cal (US) | WORKS | WORKS* | WORKS | WORKS | WORKS | WORKS |
| ema_multi_tf_cal (ISO) | WORKS | WORKS* | WORKS | WORKS | WORKS | WORKS |
| ema_multi_tf_cal_anchor (US) | WORKS | WORKS* | WORKS | WORKS | WORKS | WORKS |
| ema_multi_tf_cal_anchor (ISO) | WORKS | WORKS* | WORKS | WORKS | WORKS | WORKS |

**CRITICAL UPDATE:** All EMA variants ALREADY USE VALIDATED BAR TABLES (marked with *). The assumed v0.6.0 migration work is ALREADY COMPLETE.

### EMA Detailed Findings

<details>
<summary>ema_multi_timeframe (v1)</summary>

**EMA Calculation: WORKS**
- Evidence: Uses ta_lab2.features.ema.compute_ema (external, validated EMA formula)
- Implementation: Standard EMA with configurable periods
- Math: compute_ema handles EMA calculation, formula is correct
- Notes: Delegates to battle-tested EMA library

**Data Loading: WORKS**
- Evidence: Lines 88-103 refresh_cmc_ema_multi_tf_from_bars.py - uses cmc_price_bars_multi_tf
- Current source: cmc_price_bars_multi_tf (validated bars) and cmc_price_bars_1d for 1D timeframe
- Special handling: Line 88 - "1D" uses cmc_price_bars_1d (validated bars)
- Notes: ALREADY USING VALIDATED BAR TABLES, no migration needed

**Multi-TF Handling: WORKS**
- Evidence: Lines 110-165 ema_multi_timeframe.py - loads TFs from dim_timeframe
- Implementation: Dynamically loads tf_day family from dim_timeframe (line 118)
- Filters: Canonical only, day-label format (e.g., "7D", "14D")
- Scalability: No hardcoded TF lists, driven by dim_timeframe

**State Management: WORKS**
- Evidence: refresh_cmc_ema_multi_tf_from_bars.py uses BaseEMARefresher + EMAStateManager
- Pattern: Per-(id, tf, period) watermark via EMAStateManager
- Incremental: start/end parameters control refresh window
- Notes: Refactored to base class, standardized state pattern

**Calendar/Anchor Logic: N/A**
- Not applicable to v1 (tf_day only, no calendar alignment)

</details>

<details>
<summary>ema_multi_tf_v2</summary>

**EMA Calculation: WORKS**
- Evidence: Uses same compute_ema as v1
- Implementation: V2 computes all TFs from daily bars (synthetic multi-TF)
- Notes: Math is identical to v1, different TF construction method

**Data Loading: WORKS**
- Evidence: Lines 79 refresh_cmc_ema_multi_tf_v2.py - uses cmc_price_bars_1d exclusively
- Current source: cmc_price_bars_1d (validated daily bars)
- Notes: ALREADY USING VALIDATED BAR TABLE, no migration needed
- Design: V2 generates multi-TF bars synthetically from daily (no persisted multi-TF bars)

**Multi-TF Handling: WORKS**
- Evidence: Lines 139-148 - loads TFs from dim_timeframe
- Implementation: Dynamically loads tf_day canonical TFs
- Scalability: Same as v1, dim_timeframe-driven

**State Management: WORKS**
- Evidence: Uses BaseEMARefresher + EMAStateManager
- Pattern: Per-(id, tf, period) watermark
- Notes: Refactored to base class, same as v1

**Calendar/Anchor Logic: N/A**
- Not applicable to v2 (tf_day only, no calendar alignment)

</details>

<details>
<summary>ema_multi_tf_cal (US)</summary>

**EMA Calculation: WORKS**
- Evidence: Uses compute_ema for EMA math
- Implementation: Calendar-aligned EMAs (weeks/months/years)
- Notes: Same EMA formula, applied to calendar bars

**Data Loading: WORKS**
- Evidence: Line 126 refresh_cmc_ema_multi_tf_cal_from_bars.py - self.bars_table = f"cmc_price_bars_multi_tf_cal_{scheme}"
- Current source: cmc_price_bars_multi_tf_cal_us (validated calendar bars)
- Notes: ALREADY USING VALIDATED BAR TABLE, no migration needed
- Calendar-specific: Uses US calendar bars (Sunday-start weeks)

**Multi-TF Handling: WORKS**
- Evidence: Line 140 - get_timeframes() returns [] (TFs implicit from bars table)
- Implementation: Timeframes loaded from bars table structure
- Notes: Calendar scripts don't use dim_timeframe - bars table defines TFs

**State Management: WORKS**
- Evidence: Uses BaseEMARefresher + EMAStateManager
- Pattern: Per-(id, tf, period) watermark
- Notes: Refactored to base class

**Calendar/Anchor Logic: WORKS**
- Evidence: ema_multi_tf_cal.py handles US/ISO calendar semantics
- Implementation: write_multi_timeframe_ema_cal_to_db (line 78)
- Calendar schemes: US (Sunday weeks) vs ISO (Monday weeks)
- Notes: Calendar logic delegated to feature module

</details>

<details>
<summary>ema_multi_tf_cal (ISO)</summary>

**EMA Calculation: WORKS**
- Evidence: Same compute_ema as US variant
- Implementation: ISO calendar semantics (Monday-start weeks)

**Data Loading: WORKS**
- Evidence: Uses cmc_price_bars_multi_tf_cal_iso (validated calendar bars)
- Current source: cmc_price_bars_multi_tf_cal_iso
- Notes: ALREADY USING VALIDATED BAR TABLE, no migration needed

**Multi-TF Handling: WORKS**
- Evidence: Same TF loading as US variant (implicit from bars table)
- Implementation: ISO calendar timeframes

**State Management: WORKS**
- Evidence: Uses BaseEMARefresher + EMAStateManager
- Pattern: Per-(id, tf, period) watermark

**Calendar/Anchor Logic: WORKS**
- Evidence: ISO calendar semantics in feature module
- Implementation: Separate scheme parameter ("us" vs "iso")

</details>

<details>
<summary>ema_multi_tf_cal_anchor (US)</summary>

**EMA Calculation: WORKS**
- Evidence: Same compute_ema
- Implementation: Year-anchored US calendar EMAs

**Data Loading: WORKS**
- Evidence: Uses cmc_price_bars_multi_tf_cal_anchor_us (validated anchor bars)
- Current source: cmc_price_bars_multi_tf_cal_anchor_us
- Notes: ALREADY USING VALIDATED BAR TABLE, no migration needed

**Multi-TF Handling: WORKS**
- Evidence: Same TF loading (implicit from bars table)
- Implementation: Anchor calendar timeframes

**State Management: WORKS**
- Evidence: Uses BaseEMARefresher + EMAStateManager
- Pattern: Per-(id, tf, period) watermark

**Calendar/Anchor Logic: WORKS**
- Evidence: Year-anchor semantics in feature module
- Implementation: ema_multi_tf_cal_anchor.py handles anchor logic

</details>

<details>
<summary>ema_multi_tf_cal_anchor (ISO)</summary>

**EMA Calculation: WORKS**
- Evidence: Same compute_ema
- Implementation: Year-anchored ISO calendar EMAs

**Data Loading: WORKS**
- Evidence: Uses cmc_price_bars_multi_tf_cal_anchor_iso (validated anchor bars)
- Current source: cmc_price_bars_multi_tf_cal_anchor_iso
- Notes: ALREADY USING VALIDATED BAR TABLE, no migration needed

**Multi-TF Handling: WORKS**
- Evidence: Same TF loading (implicit from bars table)
- Implementation: Anchor + ISO calendar

**State Management: WORKS**
- Evidence: Uses BaseEMARefresher + EMAStateManager
- Pattern: Per-(id, tf, period) watermark

**Calendar/Anchor Logic: WORKS**
- Evidence: ISO + anchor semantics in feature module
- Implementation: Combines ISO calendar + year anchoring

</details>

## Data Source Analysis

**CRITICAL FINDING: EMA Data Sources ALREADY MIGRATED**

| EMA Variant | Current Source | Status | Notes |
|-------------|---------------|--------|-------|
| v1 | cmc_price_bars_multi_tf, cmc_price_bars_1d (for 1D) | WORKS | Uses validated bar tables |
| v2 | cmc_price_bars_1d | WORKS | Uses validated daily bars |
| cal_us | cmc_price_bars_multi_tf_cal_us | WORKS | Uses validated calendar bars |
| cal_iso | cmc_price_bars_multi_tf_cal_iso | WORKS | Uses validated calendar bars |
| cal_anchor_us | cmc_price_bars_multi_tf_cal_anchor_us | WORKS | Uses validated anchor bars |
| cal_anchor_iso | cmc_price_bars_multi_tf_cal_anchor_iso | WORKS | Uses validated anchor bars |

**Original v0.6.0 Assumption:** "All 6 EMA variants use price_histories7 instead of validated bar tables"

**Actual Current State:** All 6 EMA variants ALREADY USE validated bar tables. The assumed migration work is COMPLETE.

**Evidence:**
- refresh_cmc_ema_multi_tf_from_bars.py line 70: bars_table = "cmc_price_bars_multi_tf"
- refresh_cmc_ema_multi_tf_from_bars.py line 88: "1D" uses "cmc_price_bars_1d"
- refresh_cmc_ema_multi_tf_v2.py line 79: price_table = "cmc_price_bars_1d"
- refresh_cmc_ema_multi_tf_cal_from_bars.py line 126: bars_table = f"cmc_price_bars_multi_tf_cal_{scheme}"
- ema_multi_timeframe.py line 61: bars_table parameter defaults to "cmc_price_bars_multi_tf"

**Impact on v0.6.0:** Phase 22 (Critical Data Quality Fixes - EMAs to validated bars) is ALREADY COMPLETE. v0.6.0 priorities should shift to other improvements.

## State Management Analysis

**Pattern Consistency:**

| Script/Module | State Pattern | Watermark | Per-Asset | Per-TF | Consistent? |
|---------------|---------------|-----------|-----------|--------|-------------|
| Bar builders (1D) | State table | last_src_ts | Yes | No | CONSISTENT |
| Bar builders (multi_tf) | State table | daily_min_seen, daily_max_seen, last_time_close | Yes | Yes | CONSISTENT |
| Bar builders (cal_*) | State table | daily_min_seen, daily_max_seen, last_time_close, tz | Yes | Yes | CONSISTENT |
| EMA refreshers | EMAStateManager | Per-(id, tf, period) | Yes | Yes | CONSISTENT |

**Bar Builder State Pattern:**
- 1D: Simple watermark (last_src_ts) per id
- Multi-TF: Per-(id, tf) state with backfill detection (daily_min_seen tracks earliest data)
- Calendar: Per-(id, tf) state with timezone tracking
- All use: State table + upsert_state function from common_snapshot_contract

**EMA State Pattern:**
- Refactored: All EMA refreshers use BaseEMARefresher + EMAStateManager
- Watermark: Per-(id, tf, period) granularity
- Incremental: start/end parameters control refresh window
- Notes: Recent refactor standardized state management (evidence: "REFACTORED VERSION" comments in refresh scripts)

**Consistency Assessment: WORKS**
- Bar builders: Consistent pattern within bar family (1D simple, multi-TF complex, calendar adds tz)
- EMAs: Standardized via base class refactor
- Cross-family: Different patterns appropriate for different needs (bar watermarks vs EMA windows)

## Critical Issues for v0.6.0

**Priority 1 (URGENT - Roadmap Adjustment Required):**
1. **EMA data source migration ALREADY COMPLETE** - Phase 22 assumptions invalid
   - All 6 EMA variants use validated bar tables
   - No price_histories7 usage found in EMA code
   - v0.6.0 Phase 22 should be cancelled or re-scoped

**Priority 2 (UNCLEAR - Should Document):**
1. **Quality flag semantics undocumented**
   - is_partial_start, is_partial_end, is_missing_days exist across all bar builders
   - Behavior is clear in code but not documented for downstream consumers
   - Recommendation: Create quality-flags-specification.md documenting when each flag is set
   - Impact: Medium - Features/analysis consuming bars may misinterpret flags

2. **Gap detection logic varies by builder**
   - 1D: Hardcoded FALSE (canonical bars, no gaps)
   - Multi-TF: Computed from expected vs observed days
   - Calendar: Sophisticated gap tracking (start/end/interior)
   - Recommendation: Document gap detection semantics per builder type
   - Impact: Low - Logic works, just needs documentation

3. **State table schemas vary**
   - 1D: last_src_ts
   - Multi-TF: daily_min_seen, daily_max_seen, last_bar_seq, last_time_close
   - Calendar: Adds tz column
   - Recommendation: Document state schema evolution rationale
   - Impact: Low - Variation is justified by different builder needs

**Priority 3 (Enhancement - Nice to Have):**
1. **Incremental refresh observability**
   - State tracking works but visibility into what was refreshed is low
   - Recommendation: Add refresh summary logging (IDs refreshed, rows upserted, time taken)
   - Impact: Low - Operational convenience, not correctness issue

2. **Performance optimization opportunities**
   - Polars vectorization exists for full rebuilds but not all incremental paths
   - Calendar builders use Polars rebuild + filter for incremental (fast)
   - Multi-TF incremental uses pandas iterrows in some paths (slower)
   - Recommendation: Migrate remaining incremental paths to Polars (Phase 23 or 24)
   - Impact: Low - Current performance acceptable, optimization is nice-to-have

## Recommendations

**IMMEDIATE (Before v0.6.0 Planning):**
1. **Cancel/Re-scope Phase 22** - EMA data source migration is already complete
2. **Update v0.6.0 Roadmap** - Reassess priorities given EMAs already use validated bars
3. **Verify EMA calculation correctness** - Since they use bar tables, verify bars are correct

**Phase 21 (Comprehensive Review):**
1. **Document quality flag semantics** - Create quality-flags-specification.md
2. **Document gap detection logic** - Per-builder gap semantics
3. **Document state table schemas** - Why each builder has different state columns
4. **Verify bar table validation** - Since EMAs depend on bars, ensure bar validation is comprehensive

**Phase 22 (Re-scoped):**
- Original: "Migrate EMAs to validated bars" - NO LONGER NEEDED
- New scope options:
  - Validate bar table correctness (EMAs depend on this)
  - Add bar validation tests (ensure OHLC invariants hold)
  - Document bar→EMA data flow

**Phase 23 (Reliable Incremental Refresh):**
1. **Standardize refresh observability** - Consistent logging across all refreshers
2. **Add refresh telemetry** - Track refresh duration, row counts, errors
3. **Improve state visibility** - CLI commands to query state tables

**Phase 24 (Pattern Consistency):**
1. **Migrate remaining pandas paths to Polars** - For performance
2. **Standardize quality flag usage** - Consistent flag checks across features
3. **Add gap validation tests** - Ensure gap detection logic is correct

## Appendix: Analysis Methodology

**Code Analysis:**
- Read all 6 bar builder scripts (refresh_cmc_price_bars_*.py)
- Read all 6 EMA refresh scripts (refresh_cmc_ema_*.py)
- Read EMA feature modules (ema_multi_timeframe.py, ema_multi_tf_v2.py, ema_multi_tf_cal.py, ema_multi_tf_cal_anchor.py)
- Searched for data source patterns (price_histories7 vs cmc_price_bars_*)

**Health Assessment Criteria:**
- **Functional**: Evidence from code that feature works (calculations, state management, error handling)
- **Maintainable**: Code clarity, documentation, consistency with contract module
- **Scalable**: Multiprocessing support, no O(n²) algorithms, state-based incremental refresh

**Evidence Citations:**
- Line numbers from source files
- Code snippets showing implementation patterns
- Contract module usage (common_snapshot_contract)
- Base class refactoring (BaseEMARefresher, EMAStateManager)

---

*Assessment completed: 2026-02-05*
*Next: Create 20-03-SUMMARY.md documenting this analysis*
