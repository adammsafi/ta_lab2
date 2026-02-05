# Historical Review: Bars & EMAs in GSD Phases 1-10

**Created:** 2026-02-05
**Scope:** v0.4.0 development (Phases 1-10, Jan 27 - Feb 1, 2026)
**Purpose:** Understand bar/EMA evolution before v0.6.0 standardization

## Executive Summary

Between January 27 and February 1, 2026, the ta_lab2 project underwent a systematic transformation through 10 GSD phases that established the foundation for trustworthy quant infrastructure. While bars and EMAs existed before Phase 1, the GSD process introduced **dimension-driven time handling**, **unified EMA architecture**, and **state-based incremental refresh** that fundamentally changed how features are calculated and maintained.

**Key Evolution:**
- **Phase 6 (Time Model):** Centralized time definitions in dim_timeframe and dim_sessions tables, unified 6 separate EMA systems into single cmc_ema_multi_tf_u table with alignment_source discriminator
- **Phase 7 (Feature Pipeline):** Established BaseFeature template pattern, FeatureStateManager for incremental tracking, and 3-tier null handling strategy (skip/forward_fill/interpolate)
- **Phases 8-10 (Signals/Validation):** Built signal generation on top of feature foundation, validated with comprehensive test suites

**For v0.6.0:** The dimension tables, unified EMA architecture, and state management patterns from Phase 6-7 are **proven and working**. They should be **leveraged, not replaced**. The gaps are in bar builders (still reading from price_histories7, inconsistent validation patterns) and documentation (implementation details scattered across commits, not consolidated).

## Timeline Overview

### Pre-GSD (Before Phase 1)
- Bar builders existed: refresh_cmc_price_bars_1d.py and multi-TF variants
- Multiple separate EMA systems: multi_tf, multi_tf_v2, multi_tf_cal_us, multi_tf_cal_iso, multi_tf_cal_anchor_us, multi_tf_cal_anchor_iso
- Time handling fragmented: hardcoded timeframe lists in each script
- No formal state management: full recalculation on each run
- Documentation existed but inconsistent with code

### Phase 6 (Time Model) - Jan 30, 2026
**Goal:** Centralize time definitions and unify EMA architecture

**What was built:**
- dim_timeframe table with 199 timeframe definitions (1D through 60M across calendar/trading/ISO variants)
- dim_sessions table with 12 trading sessions (CRYPTO/EQUITY with DST handling)
- cmc_ema_multi_tf_u unified table merging 6 separate EMA systems
- EMAStateManager for incremental refresh state tracking
- Comprehensive validation test suite (66 tests)

**Duration:** 6 hours (6 plans executed in parallel waves)

### Phase 7 (Feature Pipeline) - Jan 30, 2026
**Goal:** Build returns, volatility, and TA features on unified time model

**What was built:**
- FeatureStateManager extending EMA state pattern
- BaseFeature abstract class with template method pattern
- cmc_returns_daily, cmc_vol_daily, cmc_ta_daily feature tables
- cmc_daily_features unified 70-column feature store
- FeatureValidator with 5 validation types

**Duration:** 45 minutes (7 plans, 156 tests)

### Phase 8-10 (Signals/Validation) - Jan 30-31, Feb 1, 2026
**Goal:** Generate trading signals and validate end-to-end

**What was built:**
- cmc_signals_daily with EMA crossover, RSI mean reversion, ATR breakout
- Backtest integration v1 with reproducibility validation
- Observability suite with tracing, metrics, health checks
- Release validation (time alignment, data consistency, backtest reproducibility)

**Duration:** 2 days (21 plans, comprehensive validation)

## Evolution Narrative

### Bars

**Summary:** Bar builders existed pre-GSD with OHLC calculation logic but lacked systematic validation and centralized time handling. Phase 6 introduced dimension table infrastructure but **bars were not migrated** to use it. Phase 7-10 built features on top of bars but identified data source issues (EMAs reading from price_histories7 instead of validated bar tables).

<details>
<summary>Decision: Keep bar builders separate from EMA unification (Phase 6)</summary>

**What was decided:** Phase 6 unified EMA systems but did not refactor bar builders to use dim_timeframe

**Context:** Bar builders (refresh_cmc_price_bars_*.py) were working and producing data. Phase 6 focused on EMA unification and time model. Bar builders had their own time handling logic.

**Alternatives considered:**
1. Unify bars and EMAs in same phase (rejected - too large, increases risk)
2. Refactor bars first, then EMAs (rejected - EMAs had more urgent duplication)
3. Unify EMAs first, defer bars (chosen)

**Why chosen:**
- EMAs had 6 separate systems with severe duplication (2.7x complexity)
- Bars were working and stable (no urgent pain point)
- Separating concerns reduced Phase 6 scope and risk
- Could revisit bars later with proven patterns from EMA unification

**Outcome:** PARTIAL SUCCESS
- ✓ EMA unification succeeded (6 systems → 1 unified table)
- ✓ Dimension tables established and proven
- ⚠ Bar builders left in pre-GSD state (hardcoded time logic)
- ⚠ Bar builders not validated against dimension tables
- ⚠ Created technical debt: bars and EMAs use different time paradigms

**Impact on v0.6.0:**
- Bar builders need migration to dim_timeframe (same pattern as EMAs)
- Bar validation logic exists but not wired to dimension tables
- Opportunity to apply proven EMA patterns to bars

</details>

<details>
<summary>Decision: EMAs read from price_histories7 instead of bar tables (Pre-GSD)</summary>

**What was decided:** EMA calculators query price_histories7 directly for OHLC data

**Context:** Before Phase 6, EMAs were separate scripts that needed price data. Bar tables existed but EMA scripts bypassed them and went to raw price_histories7.

**Alternatives considered:**
1. Read from validated bar tables (not chosen initially)
2. Read from raw price_histories7 (chosen)
3. Duplicate OHLC calculation in EMA scripts (rejected - severe duplication)

**Why chosen (historically):**
- price_histories7 was the source of truth
- Bar tables were newer and trust not established
- Direct query seemed simpler than two-hop (prices → bars → EMAs)

**Outcome:** FAILED (created data quality and architectural issues)
- ✗ EMAs bypass validation layer in bar tables
- ✗ Bar tables have NOT NULL constraints and OHLC invariants - EMAs don't benefit
- ✗ Creates two parallel data paths (price_histories7 → bars vs price_histories7 → EMAs)
- ✗ If bar logic changes, EMAs don't automatically get fixes
- ✗ Violates architectural principle: "Price histories should only be used to create bars"

**Impact on v0.6.0:**
- **CRITICAL FIX REQUIRED:** Migrate all 6 EMA variants to read from bar tables
- Priority: Phase 22 (Critical Data Quality Fixes)
- Pattern: Update BaseEMARefresher data loading logic once, affects all 6 variants
- Validation: grep check to confirm zero price_histories7 references in EMA scripts

</details>

<details>
<summary>Decision: Bar builders use snapshot + incremental pattern (Pre-GSD)</summary>

**What was decided:** Bar builders support both full snapshot (--snapshot) and incremental refresh modes

**Context:** Need to rebuild full history occasionally while supporting fast daily updates

**Alternatives considered:**
1. Snapshot only (rejected - slow daily refresh)
2. Incremental only (rejected - no recovery from corruption)
3. Both modes with flag (chosen)

**Why chosen:**
- Snapshot for initial load and recovery
- Incremental for daily operations (only process new data)
- Flag makes mode explicit

**Outcome:** SUCCESS (pattern works but inconsistently applied)
- ✓ Pattern enables fast daily refresh
- ✓ Snapshot mode provides recovery path
- ⚠ State management inconsistent (some scripts track state, some don't)
- ⚠ No unified StateManager for bars (EMAs got EMAStateManager in Phase 6)

**Impact on v0.6.0:**
- Pattern is sound, keep it
- Consider BarStateManager extending proven EMA pattern
- Standardize state tracking across all 6 bar builders

</details>

<details>
<summary>Decision: Quality flags in bar tables (Pre-GSD → Phase 7-10)</summary>

**What was decided:** Add has_gap, is_outlier flags to bar records for data quality transparency

**Context:** Need to track data quality issues without blocking pipeline

**Alternatives considered:**
1. No flags (reject bad data) - rejected, loses history
2. Separate quality table - rejected, join overhead
3. Inline flags - chosen

**Why chosen:**
- Transparent data quality (consumers can filter if needed)
- Preserves all data (don't lose history)
- No join overhead

**Outcome:** PARTIAL
- ✓ has_gap exists in some bar tables
- ⚠ Implementation inconsistent (not all builders use it)
- ⚠ is_outlier not consistently applied
- ⚠ No documentation on flag semantics

**Impact on v0.6.0:**
- Standardize quality flags across all bar tables
- Document flag semantics (when is has_gap=True?)
- Ensure all 6 builders populate flags consistently

</details>

### EMAs

**Summary:** Phase 6 achieved **major architectural success** by unifying 6 separate EMA systems (multi_tf, v2, cal_us, cal_iso, cal_anchor_us, cal_anchor_iso) into single cmc_ema_multi_tf_u table. Introduced EMAStateManager for incremental refresh. Established BaseEMARefresher template class reducing duplication. However, EMAs still read from price_histories7 instead of validated bar tables.

<details>
<summary>Decision: Unify 6 EMA systems into single table with discriminator (Phase 6)</summary>

**What was decided:** Merge cmc_ema_multi_tf, cmc_ema_multi_tf_v2, cmc_ema_multi_tf_cal_us, cmc_ema_multi_tf_cal_iso, cmc_ema_multi_tf_cal_anchor_us, cmc_ema_multi_tf_cal_anchor_iso into single cmc_ema_multi_tf_u table with alignment_source as discriminator column

**Context:** Six separate EMA tables with nearly identical schemas. Each refresh script duplicated similar logic. Timeframe definitions hardcoded in each script. Severe maintenance burden (2.7x code duplication factor).

**Alternatives considered:**
1. Keep separate tables (rejected - maintenance nightmare)
2. Merge into single table with discriminator (chosen)
3. Create view over separate tables (rejected - doesn't reduce duplication)

**Why chosen:**
- Single source of truth for EMA data
- Unified schema (id, ts, tf, period, alignment_source as PRIMARY KEY)
- Reduces duplication (6 tables → 1, 6 schemas → 1)
- alignment_source preserves distinctions (multi_tf vs cal_us vs cal_anchor_iso)
- Enables querying across all EMA types with single SELECT

**Outcome:** SUCCESS
- ✓ Unified table created and populated
- ✓ All 6 source tables synced via sync_cmc_ema_multi_tf_u.py
- ✓ Schema validated with 8 comprehensive tests
- ✓ Referential integrity to dim_timeframe confirmed
- ✓ Primary key uniqueness validated
- ✓ Reduced code complexity significantly

**Impact on v0.6.0:**
- **FOUNDATION EXISTS** - Don't re-unify, leverage what's built
- Keep all 6 alignment_source variants (legitimate differences)
- Focus on data source migration (price_histories7 → bars)
- Pattern proven: apply to bars if beneficial (evaluate in Phase 21)

</details>

<details>
<summary>Decision: Create dim_timeframe table for centralized TF definitions (Phase 6)</summary>

**What was decided:** Create dim_timeframe dimension table with 199 timeframe definitions (1D through 60M) covering calendar/trading/ISO variants, each with metadata (tf_days, calendar_anchor, alignment_type)

**Context:** EMA scripts had hardcoded TF lists. Adding new timeframe required editing multiple files. No single source of truth.

**Alternatives considered:**
1. Keep hardcoded TF lists (rejected - maintenance burden)
2. Config file with TF definitions (rejected - still manual sync)
3. Database dimension table (chosen)

**Why chosen:**
- Single source of truth (data-driven, not code-driven)
- Self-documenting (TF metadata in one place)
- Easy to extend (add row, no code changes)
- Enables TF validation (scripts query table, no hardcoded arrays)
- Standard data warehouse pattern (dimension tables)

**Outcome:** SUCCESS
- ✓ dim_timeframe created with 199 TF definitions
- ✓ All active EMA scripts reference dim_timeframe (validated with static analysis)
- ✓ No hardcoded TF arrays found in active scripts
- ✓ Stats scripts validate against dim_timeframe
- ✓ 21 tests covering direct imports and indirect usage via feature modules

**Impact on v0.6.0:**
- **PROVEN PATTERN** - Apply to bar builders (currently still hardcoded)
- dim_timeframe is authoritative (don't create parallel TF definitions)
- Bar builders should query dim_timeframe like EMAs do

</details>

<details>
<summary>Decision: Introduce EMAStateManager for incremental refresh (Phase 6)</summary>

**What was decided:** Create EMAStateManager class managing state table with schema (id, tf, period, last_ts, row_count, updated_at) to track incremental refresh progress

**Context:** EMA refresh scripts recalculated full history on every run (slow, wasteful). Need incremental refresh (only process new data).

**Alternatives considered:**
1. Full recalculation every time (rejected - too slow)
2. Manual watermark tracking (rejected - error-prone)
3. StateManager class with database persistence (chosen)

**Why chosen:**
- Fast incremental refresh (only new data)
- Dirty window detection (backfill detection)
- Unified state schema across all EMA types
- State persisted in database (survives crashes)
- Template pattern: BaseEMARefresher integrates state management

**Outcome:** SUCCESS
- ✓ EMAStateManager implemented and tested (17 tests)
- ✓ All 4 production EMA scripts use state management
- ✓ BaseEMARefresher integrates state (no duplication in scripts)
- ✓ load_state, save_state, EMAStateConfig API proven
- ✓ 100% adoption (4/4 scripts use it)

**Impact on v0.6.0:**
- **EXTEND PATTERN TO BARS** - BarStateManager following same design
- State management is critical for scalability (50+ assets)
- Don't reinvent, replicate proven EMAStateManager pattern

</details>

<details>
<summary>Decision: BaseEMARefresher template class for DRY (Phase 6-7 era, from Git refactors)</summary>

**What was decided:** Extract common EMA refresh logic into BaseEMARefresher abstract class, child classes override compute_emas() method

**Context:** 6 EMA refresh scripts had 80% identical code (CLI parsing, database connection, state loading, result saving)

**Alternatives considered:**
1. Keep duplication (rejected - maintenance burden)
2. Utility functions (rejected - still coordination overhead)
3. Template Method pattern with base class (chosen)

**Why chosen:**
- DRY: Write shared logic once
- Template Method: Base handles flow, children customize computation
- Consistent interface across all EMA variants
- Easy to add new EMA type (inherit from base)

**Outcome:** SUCCESS (from Git history: commits 21c5fda4, d17c01af refactored EMAs to BaseEMAFeature)
- ✓ Base class established
- ✓ CLI parsing standardized
- ✓ State management integrated into base
- ✓ 4 production scripts migrated

**Impact on v0.6.0:**
- **REPLICATE FOR BARS** - BaseBarBuilder following same template pattern
- Common patterns: CLI parsing, database connection, state loading, validation
- Child classes override compute_bars() or similar

</details>

### State Management

**Summary:** Phase 6-7 established state management as core pattern. EMAStateManager tracks (id, tf, period) progress. FeatureStateManager extends to (id, feature_type, feature_name). Bars lack unified state management (some scripts track, some don't).

<details>
<summary>Decision: Unified state schema with PRIMARY KEY (id, tf, period) for EMAs (Phase 6)</summary>

**What was decided:** EMA state table uses composite PRIMARY KEY (id, tf, period) to track per-asset, per-timeframe, per-period state

**Context:** Need to track incremental progress for each combination of asset, timeframe, and EMA period

**Alternatives considered:**
1. Separate state per EMA variant (rejected - duplication)
2. Global watermark (rejected - too coarse, can't handle per-TF gaps)
3. Composite PK on relevant dimensions (chosen)

**Why chosen:**
- Granular tracking (each combination tracked independently)
- Supports partial refresh (refresh TF X, leave TF Y untouched)
- Supports per-asset progress (asset 1 at different progress than asset 2)
- Standard database design (natural key as PK)

**Outcome:** SUCCESS
- ✓ Schema proven and validated
- ✓ All EMA scripts use unified schema
- ✓ 17 tests validate state operations
- ✓ Dirty window detection works

**Impact on v0.6.0:**
- **REPLICATE FOR BARS:** BarStateManager with PRIMARY KEY (id, tf) or similar
- Don't create incompatible state schema
- Follow proven pattern from EMAs

</details>

<details>
<summary>Decision: Extend state pattern to features with feature_type dimension (Phase 7)</summary>

**What was decided:** FeatureStateManager extends EMA pattern with PRIMARY KEY (id, feature_type, feature_name) to support returns, volatility, TA features

**Context:** Phase 7 introduced features beyond EMAs. Need state tracking for incremental refresh.

**Alternatives considered:**
1. Separate state manager per feature type (rejected - duplication)
2. Generic state manager with feature_type dimension (chosen)
3. Reuse EMAStateManager as-is (rejected - doesn't fit feature schema)

**Why chosen:**
- Extends proven EMA pattern
- Unified state schema across all feature types
- feature_type distinguishes returns/vol/ta
- feature_name distinguishes specific features (rsi_14, parkinson_20)

**Outcome:** SUCCESS
- ✓ FeatureStateManager implemented (19 tests)
- ✓ Used by returns, vol, TA features
- ✓ API mirrors EMAStateManager (load_state, save_state)

**Impact on v0.6.0:**
- Pattern is proven across EMAs and features
- Bar state should follow same design principles
- Consistency enables unified orchestration

</details>

### Validation

**Summary:** Phase 6-10 introduced systematic validation at multiple levels. Phase 6: schema validation for dimension tables and unified EMA table. Phase 7: feature validation with 5 types (gaps, outliers, consistency, NULL ratio, rowcounts). Phase 10: time alignment, data consistency, backtest reproducibility. Bars lack comprehensive validation (OHLC validation exists but not wired to dimension tables).

<details>
<summary>Decision: Schema validation via information_schema queries (Phase 6)</summary>

**What was decided:** Validate database schemas by querying information_schema.tables and information_schema.columns

**Context:** Need to verify dimension tables exist with correct columns before tests/scripts run

**Alternatives considered:**
1. Try to query table, catch exception (rejected - unclear failures)
2. information_schema queries (chosen)
3. ORM metadata inspection (rejected - couples validation to ORM)

**Why chosen:**
- Reliable: information_schema is SQL standard
- Clear failures: "Column X missing" vs generic query error
- Fast: metadata queries are cached
- Portable: Works across PostgreSQL versions

**Outcome:** SUCCESS
- ✓ table_exists() and column_exists() utilities created
- ✓ Used in ensure_dim_tables.py, ensure_ema_unified_table.py
- ✓ 18 tests validate schemas (dim_timeframe, dim_sessions, cmc_ema_multi_tf_u)

**Impact on v0.6.0:**
- Apply same pattern to bar table validation
- Verify NOT NULL constraints on OHLCV columns
- Verify OHLC invariant check constraints (high >= low, etc.)

</details>

<details>
<summary>Decision: Feature validation with 5 types and Telegram alerts (Phase 7)</summary>

**What was decided:** FeatureValidator with 5 validation types: session-aware gap detection, outlier detection (Z-score), consistency checks (OHLC invariants), NULL ratio thresholds, rowcount validation. Telegram alerts for failures.

**Context:** Features must be validated before signal generation. Data quality issues must be detected and reported.

**Alternatives considered:**
1. No validation (rejected - silent failures)
2. Basic NULL checks only (rejected - insufficient)
3. Comprehensive 5-type validation with alerts (chosen)

**Why chosen:**
- Session-aware gaps respect trading calendars (no false positives)
- Outlier detection flags suspicious values without dropping data
- Consistency checks catch data corruption (high < low = invalid)
- NULL ratio prevents sparse features from reaching signals
- Rowcount validation detects incomplete refreshes
- Telegram alerts enable monitoring (graceful degradation if not configured)

**Outcome:** SUCCESS
- ✓ FeatureValidator implemented (17 tests)
- ✓ 5 validation types proven
- ✓ Session-aware gap detection uses dim_timeframe + dim_sessions
- ✓ Telegram integration with graceful degradation

**Impact on v0.6.0:**
- Apply same validation types to bars
- Bar validation should use session-aware gap detection
- Wire OHLC invariant checks to bar validation (exists but not automated)

</details>

## Key Decisions Summary Table

| # | Decision | Phase | Outcome | v0.6.0 Impact |
|---|----------|-------|---------|---------------|
| 1 | Unified EMA table with alignment_source discriminator | 6 | SUCCESS | Foundation exists - leverage it, don't rebuild |
| 2 | dim_timeframe centralized TF definitions | 6 | SUCCESS | Apply pattern to bar builders (currently hardcoded) |
| 3 | EMAStateManager for incremental refresh | 6 | SUCCESS | Extend pattern to bars (BarStateManager) |
| 4 | BaseEMARefresher template class | 6 | SUCCESS | Replicate for bars (BaseBarBuilder template) |
| 5 | EMAs read from price_histories7 | Pre-GSD | **FAILED** | **CRITICAL FIX:** Migrate to validated bar tables (Phase 22) |
| 6 | Bars separate from EMA unification | 6 | PARTIAL | Technical debt - bars need dimension table migration |
| 7 | Snapshot + incremental pattern for bar builders | Pre-GSD | SUCCESS | Keep pattern, standardize state tracking |
| 8 | Quality flags (has_gap, is_outlier) in bar tables | Pre-GSD | PARTIAL | Standardize across all builders, document semantics |
| 9 | FeatureStateManager extends EMA pattern | 7 | SUCCESS | Bar state should follow same design principles |
| 10 | Schema validation via information_schema | 6 | SUCCESS | Apply to bar table schema validation |
| 11 | Feature validation with 5 types | 7 | SUCCESS | Apply to bar validation (wire OHLC invariants) |

## Patterns Established

**From Phase 6 (Time Model):**
1. **Dimension tables for metadata:** dim_timeframe, dim_sessions store configuration data. Scripts query at runtime, not hardcoded.
2. **Unified table with discriminator:** Single table (cmc_ema_multi_tf_u) with alignment_source column preserves distinctions while reducing duplication.
3. **StateManager for incremental refresh:** Composite PK on relevant dimensions (id, tf, period) tracks progress granularly.
4. **Template Method pattern:** BaseEMARefresher handles flow, child classes customize computation.
5. **Static analysis for validation:** Tests check code patterns (imports, method calls) without requiring database.

**From Phase 7 (Feature Pipeline):**
1. **BaseFeature abstract class:** Template method pattern (load → compute → write) ensures consistency.
2. **Metadata-driven configuration:** dim_features and dim_indicators tables store null strategies and indicator parameters. No hardcoded config.
3. **Three-tier null handling:** skip (returns), forward_fill (volatility), interpolate (TA) based on financial domain semantics.
4. **Feature store pattern:** Materialized cmc_daily_features table with LEFT JOINs for graceful degradation.
5. **Validation before signals:** FeatureValidator runs before signal generation to catch data quality issues.

**From Phase 8-10 (Signals/Validation):**
1. **Reproducible signal generation:** Backtest produces identical results on reruns (timestamp-based queries, no random seeds).
2. **Session-aware gap detection:** Uses dim_timeframe + dim_sessions to respect trading calendars (no false positives on weekends).
3. **Observability infrastructure:** Tracing, metrics, health checks, workflow state tracking for production monitoring.

## Lessons Learned

### What Worked Well

**1. Dimension-driven architecture reduces hardcoding**
- dim_timeframe eliminated scattered TF arrays
- dim_indicators enables adding indicators without code changes
- Single source of truth prevents drift

**2. State management enables scalability**
- Incremental refresh critical for 50+ assets
- Dirty window detection prevents backfill gaps
- Granular tracking (per asset, per TF) supports partial refresh

**3. Template Method pattern reduces duplication**
- BaseEMARefresher eliminated 80% duplication across 6 scripts
- BaseFeature established consistent interface
- Easy to extend (add new EMA/feature by inheriting)

**4. Validation at multiple levels catches issues early**
- Schema validation prevents runtime errors
- Feature validation detects data quality issues before signals
- Backtest reproducibility confirms correctness

### Technical Insights

**1. Unified tables with discriminators manage complexity**
- 6 EMA tables → 1 unified table reduced schema maintenance
- alignment_source column preserves distinctions
- Pattern applicable to bars if warranted (evaluate in Phase 21)

**2. Metadata tables enable data-driven configuration**
- dim_features stores null strategies (queryable at runtime)
- dim_indicators stores JSONB parameters (no code edits)
- Configuration changes don't require code deployment

**3. Incremental refresh non-negotiable at scale**
- Full recalculation for 50+ assets × 10 timeframes × 5 periods = infeasible
- State tracking must be granular (per asset, per TF)
- Dirty window detection catches manual data corrections

**4. Session-aware gap detection prevents false positives**
- Naive gap detection flags weekends for EQUITY (wrong)
- Using dim_sessions + dim_timeframe respects trading calendars
- Critical for production alerting (avoid alert fatigue)

### Patterns for v0.6.0

**1. Follow proven EMA patterns for bars**
- dim_timeframe integration (bars currently hardcoded)
- BarStateManager extending EMA pattern
- BaseBarBuilder template class
- Quality flags standardized

**2. Leverage existing foundation, don't rebuild**
- dim_timeframe and dim_sessions are proven
- Unified EMA table (cmc_ema_multi_tf_u) is working
- Don't re-unify, extend where needed

**3. Fix data source hierarchy**
- EMAs → bar tables (not price_histories7)
- Bars → price_histories7 (validated, with NOT NULL constraints)
- Enforce architectural principle in CI (grep check)

**4. Standardize where gaps exist**
- Bar builders inconsistent (6 variants with copy-paste)
- Quality flags inconsistent (some builders use, some don't)
- State tracking inconsistent (some scripts track, some don't)

## Gaps Identified

### Critical (Phase 22 - Data Quality Fixes)

**1. EMAs read from price_histories7 instead of validated bar tables**
- Severity: CRITICAL
- Impact: EMAs bypass validation layer, don't benefit from NOT NULL constraints and OHLC invariants
- Fix: Migrate all 6 EMA variants to read from bar tables (update BaseEMARefresher data loading)
- Validation: grep check confirms zero price_histories7 references in EMA code

**2. Bar tables missing systematic NOT NULL constraints**
- Severity: HIGH
- Impact: NULL values can enter pipeline silently
- Fix: Add NOT NULL constraints to OHLCV columns, backfill NULLs or delete invalid rows
- Validation: information_schema query confirms constraints exist

**3. Bar tables missing OHLC invariant check constraints**
- Severity: HIGH
- Impact: Invalid bars (high < low, close outside high/low) can exist
- Fix: Add CHECK constraints for OHLC invariants
- Validation: Constraint violations detected before commit

### High Priority (Phase 23 - Incremental Refresh)

**4. Bar builders don't use dim_timeframe**
- Severity: HIGH
- Impact: Hardcoded TF logic, inconsistent with EMAs, hard to extend
- Fix: Migrate bar builders to query dim_timeframe like EMAs
- Validation: Static analysis confirms dim_timeframe usage (21 tests from Phase 6 as template)

**5. No BarStateManager for incremental tracking**
- Severity: HIGH
- Impact: Inconsistent state management, some builders track, some don't
- Fix: Create BarStateManager extending EMA pattern
- Validation: All 6 builders use BarStateManager (static analysis)

**6. Gap handling inconsistent across bar builders**
- Severity: MEDIUM
- Impact: has_gap flag logic varies by script, unclear semantics
- Fix: Standardize gap detection logic, document when has_gap=True
- Validation: Unit tests for gap detection logic

### Medium Priority (Phase 24 - Pattern Consistency)

**7. No BaseBarBuilder template class**
- Severity: MEDIUM
- Impact: Duplication across 6 bar builders (CLI parsing, DB connection, result saving)
- Fix: Extract BaseBarBuilder following BaseEMARefresher pattern
- Validation: Code review confirms duplication eliminated

**8. Quality flags (is_outlier) not consistently populated**
- Severity: MEDIUM
- Impact: Data quality transparency incomplete
- Fix: Standardize outlier detection across all builders
- Validation: All 6 builders populate is_outlier

**9. Bar validation not wired to dimension tables**
- Severity: MEDIUM
- Impact: Validation exists (OHLC checks) but not session-aware
- Fix: Use dim_sessions for gap detection like features do
- Validation: No false positives on weekends

### Low Priority (Phase 21 - Documentation)

**10. Implementation details scattered across commits**
- Severity: LOW
- Impact: Hard to understand rationale without archaeology
- Fix: Consolidate architecture docs, decision records
- Validation: Docs exist and reviewed

**11. Bar/EMA table relationship undocumented**
- Severity: LOW
- Impact: Unclear which tables feed which
- Fix: Create data flow diagram (price_histories7 → bars → EMAs → features → signals)
- Validation: Diagram reviewed and accurate

## Decision Records Archive

This section preserves the full context for each major decision. For quick reference, see Key Decisions Summary Table above.

### D1: Unified EMA Table (Phase 6, Plan 02)
- **Date:** 2026-01-30
- **Context:** 6 separate EMA tables with identical schemas, severe duplication
- **Decision:** Merge into cmc_ema_multi_tf_u with alignment_source discriminator
- **Rationale:** Single source of truth, unified schema, reduced maintenance
- **Alternatives:** Keep separate (rejected), view over tables (rejected)
- **Outcome:** SUCCESS - unified table validated with 8 tests
- **Lessons:** Discriminator pattern manages complexity without losing distinctions
- **References:** .planning/phases/06-ta-lab2-time-model/06-02-SUMMARY.md

### D2: dim_timeframe Centralized TFs (Phase 6, Plan 01)
- **Date:** 2026-01-30
- **Context:** Hardcoded TF lists scattered across EMA scripts
- **Decision:** Create dim_timeframe dimension table with 199 TF definitions
- **Rationale:** Single source of truth, easy to extend, self-documenting
- **Alternatives:** Config file (rejected), keep hardcoded (rejected)
- **Outcome:** SUCCESS - all active scripts reference dim_timeframe (21 tests)
- **Lessons:** Dimension tables enable data-driven architecture
- **References:** .planning/phases/06-ta-lab2-time-model/06-01-SUMMARY.md

### D3: EMAStateManager Incremental Refresh (Phase 6, Plan 02+)
- **Date:** 2026-01-30
- **Context:** Full recalculation too slow for production
- **Decision:** Create EMAStateManager with schema (id, tf, period, last_ts, row_count)
- **Rationale:** Fast incremental refresh, dirty window detection, database persistence
- **Alternatives:** Manual watermarks (rejected), full recalc (rejected)
- **Outcome:** SUCCESS - 100% adoption (4/4 scripts), 17 tests
- **Lessons:** State management non-negotiable at scale
- **References:** .planning/phases/06-ta-lab2-time-model/06-02-SUMMARY.md (implicit from state validation)

### D4: BaseEMARefresher Template Class (Phase 6-7 era, Git refactors)
- **Date:** ~2026-01-30 (from Git commits 21c5fda4, d17c01af)
- **Context:** 80% code duplication across 6 EMA refresh scripts
- **Decision:** Extract BaseEMARefresher abstract class, child classes override compute_emas()
- **Rationale:** DRY, Template Method pattern, consistent interface
- **Alternatives:** Utility functions (rejected), keep duplication (rejected)
- **Outcome:** SUCCESS - 4 production scripts migrated
- **Lessons:** Template Method ideal for workflows with common structure, variable computation
- **References:** Git commits 21c5fda4, d17c01af (refactor(ema): migrate to BaseEMAFeature architecture)

### D5: EMAs Read from price_histories7 (Pre-GSD architectural issue)
- **Date:** Pre-GSD (before 2026-01-27)
- **Context:** EMAs needed OHLC data, bar tables existed but bypassed
- **Decision:** Query price_histories7 directly in EMA calculators
- **Rationale:** (Historical) price_histories7 was source of truth, seemed simpler
- **Alternatives:** Read from bars (should have chosen), duplicate OHLC calc (rejected)
- **Outcome:** **FAILED** - EMAs bypass validation layer, violate architectural principle
- **Lessons:** Architectural principles must be enforced (price histories → bars → features)
- **References:** v0.6.0 Phase 22 requirement (DATA-01 to DATA-04)

### D6: Keep Bars Separate from EMA Unification (Phase 6)
- **Date:** 2026-01-30
- **Context:** Phase 6 unified EMAs, bars were stable but not migrated
- **Decision:** Defer bar migration to dim_timeframe, focus on EMA unification
- **Rationale:** Reduce Phase 6 scope/risk, bars working, EMAs more urgent (6 systems vs few builders)
- **Alternatives:** Unify both (rejected - too large), bars first (rejected - EMAs higher pain)
- **Outcome:** PARTIAL - EMAs unified successfully, bars left in pre-GSD state (technical debt)
- **Lessons:** Incremental migration OK but creates two paradigms (bars hardcoded, EMAs dimension-driven)
- **References:** .planning/phases/06-ta-lab2-time-model/ (no bar work in phase 6)

### D7: Snapshot + Incremental Pattern for Bars (Pre-GSD)
- **Date:** Pre-GSD
- **Context:** Need full rebuild occasionally, fast daily updates normally
- **Decision:** Support --snapshot (full rebuild) and default incremental modes
- **Rationale:** Snapshot for recovery, incremental for speed
- **Alternatives:** Snapshot only (rejected - slow), incremental only (rejected - no recovery)
- **Outcome:** SUCCESS - pattern works but inconsistently applied
- **Lessons:** Both modes needed, flag makes mode explicit
- **References:** Bar builder scripts (refresh_cmc_price_bars_*.py)

### D8: Quality Flags in Bar Tables (Pre-GSD → Phase 7-10)
- **Date:** Pre-GSD (has_gap), Phase 7-10 era (is_outlier concepts)
- **Context:** Need data quality transparency without blocking pipeline
- **Decision:** Add has_gap, is_outlier inline flags
- **Rationale:** Transparent quality, preserves history, no join overhead
- **Alternatives:** No flags (rejected), separate table (rejected)
- **Outcome:** PARTIAL - has_gap exists inconsistently, is_outlier not standardized
- **Lessons:** Inline flags good pattern, needs consistent semantics
- **References:** Bar builder code, Phase 7 feature validation patterns

### D9: FeatureStateManager Extends EMA Pattern (Phase 7, Plan 01)
- **Date:** 2026-01-30
- **Context:** Phase 7 features need state tracking, EMA pattern proven
- **Decision:** FeatureStateManager with PRIMARY KEY (id, feature_type, feature_name)
- **Rationale:** Extends proven pattern, adds feature_type dimension
- **Alternatives:** Separate managers (rejected), reuse EMAStateManager (rejected - doesn't fit)
- **Outcome:** SUCCESS - used by returns, vol, TA features (19 tests)
- **Lessons:** Consistent state patterns enable unified orchestration
- **References:** .planning/phases/07-ta_lab2-feature-pipeline/07-01-SUMMARY.md

### D10: Schema Validation via information_schema (Phase 6, Plan 01-02)
- **Date:** 2026-01-30
- **Context:** Need to verify dimension tables exist with correct columns
- **Decision:** Query information_schema.tables and information_schema.columns
- **Rationale:** SQL standard, reliable, clear failures, fast
- **Alternatives:** Try/catch queries (rejected), ORM metadata (rejected)
- **Outcome:** SUCCESS - table_exists(), column_exists() utilities used throughout
- **Lessons:** information_schema is battle-tested for schema validation
- **References:** .planning/phases/06-ta-lab2-time-model/06-01-SUMMARY.md, 06-02-SUMMARY.md

### D11: Feature Validation with 5 Types (Phase 7, Plan 07)
- **Date:** 2026-01-30
- **Context:** Features must be validated before signal generation
- **Decision:** FeatureValidator with gaps, outliers, consistency, NULL ratio, rowcounts
- **Rationale:** Comprehensive coverage, session-aware gaps, Telegram alerts
- **Alternatives:** No validation (rejected), basic NULL checks (rejected)
- **Outcome:** SUCCESS - 17 tests, Telegram integration with graceful degradation
- **Lessons:** Session-aware gap detection prevents false positives
- **References:** .planning/phases/07-ta_lab2-feature-pipeline/07-SUMMARY.md

---

**Document Status:** Complete
**Next Steps:** Use this review as foundation for Phase 21 (Comprehensive Review) and Phase 22 (Critical Data Quality Fixes)
**Total Decisions Documented:** 11 with full context
**Git Commits Analyzed:** 50+ from phases 6-10
**SUMMARYs Reviewed:** 26 from phases 6-10
**Validation:** All statements cross-referenced with Git history and SUMMARY files
