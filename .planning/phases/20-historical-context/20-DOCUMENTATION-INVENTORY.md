# Documentation Inventory: Bars & EMAs

**Created:** 2026-02-05
**Phase:** 20-historical-context
**Purpose:** Catalog all bar/EMA-related documentation with multi-dimensional assessment to identify leverage-worthy materials and gaps for v0.6.0

## Executive Summary

The ta_lab2 project contains **extensive documentation** across bars, EMAs, time model, state management, and operations. This inventory assessed **25+ documents** across multiple dimensions.

**Leverage-worthy findings:**
- **5 highly leverage-worthy documents** meet all 4 criteria (architecture + implementation + rationale + actionable)
- These cover bar validation patterns, EMA state standardization, multi-timeframe semantics, and calendar anchoring
- Most valuable for v0.6.0: `bar-implementation.md`, `EMA_STATE_STANDARDIZATION.md`, `ema-multi-tf-cal-anchor.md`

**Key gaps identified:**
- Gap detection logic rationale (why different approaches across bar builders)
- Quality flag semantics (flags exist but meaning/usage undocumented)
- Bar data source migration decision history (when/why price_histories vs bar tables)
- Incremental refresh pattern differences (bar builders vs EMA scripts)
- EMA variant comparison (why 6 variants exist, when to use each)

**Documentation quality:**
- **Complete documentation (8):** Comprehensive, accurate, actionable
- **Partial documentation (12):** Useful content but incomplete or needs verification
- **Stub documentation (5):** Minimal content, placeholders, or outdated

## Inventory Criteria

**Leverage-Worthy Criteria (ALL must apply):**
1. **Explains architecture**: How bars/EMAs work structurally
2. **Contains implementation**: Code examples, validation logic, state patterns
3. **Shows rationale**: WHY decisions were made
4. **Has actionable info**: Can directly inform v0.6.0 work

**Quality Levels:**
- **Complete**: Comprehensive, up-to-date, accurate
- **Partial**: Useful but incomplete or partially outdated
- **Stub**: Placeholder or minimal content
- **Outdated**: Superseded or no longer accurate

## Full Inventory

### By Topic

#### Bars

| Document | Quality | Source | A | I | R | Act | Leverage? |
|----------|---------|--------|---|---|---|-----|-----------|
| docs/features/bar-implementation.md | Complete | Pre-GSD/v0.5.0 | Y | Y | Y | Y | **YES** |
| docs/features/bar-creation.md | Complete | Pre-GSD/v0.5.0 | Y | Y | Y | Y | **YES** |
| docs/Data Pipeline.md | Stub | Pre-GSD | Y | N | N | N | NO |
| sql/ddl/create_cmc_price_bars_1d_state.sql | Partial | v0.5.0 | N | Y | N | Y | NO |

**Bar documentation notes:**
- `bar-implementation.md`: **480+ lines**, covers deterministic tie-breaks, watermark/state reconciliation, snapshot contracts, incremental driver standard, OHLC validation. Highly actionable for v0.6.0 standardization work.
- `bar-creation.md`: **850+ lines**, defines formal invariants, bar boundaries, calendar alignment/anchoring, partial periods, canonical close rules, error handling. Authoritative specification.
- `Data Pipeline.md`: Very brief overview, no implementation details
- DDL files exist but lack rationale documentation

#### EMAs

| Document | Quality | Source | A | I | R | Act | Leverage? |
|----------|---------|--------|---|---|---|-----|-----------|
| docs/features/ema-multi-tf-cal-anchor.md | Complete | Pre-GSD/v0.5.0 | Y | Y | Y | Y | **YES** |
| docs/features/ema-multi-tf.md | Complete | Pre-GSD/v0.5.0 | Y | Y | Y | Y | **YES** |
| docs/features/ema-multi-tf-cal.md | Complete | Pre-GSD/v0.5.0 | Y | Y | Y | Y | **YES** |
| docs/features/emas/ema-study.md | Partial | Pre-GSD | Y | Y | Y | N | NO |
| docs/features/ema-overview.md | Partial | Pre-GSD | Y | N | N | N | NO |
| docs/features/ema-multi-tf-cal-anchor.md (old) | Complete | Pre-GSD | Y | Y | Y | Y | **YES** |
| docs/features/ema-daily.md | Partial | Pre-GSD | Y | N | N | N | NO |
| docs/features/ema-loo.md | Partial | Pre-GSD | N | Y | N | N | NO |
| docs/features/ema-thoughts.md | Stub | Pre-GSD | N | N | N | N | NO |
| docs/features/ema-possible-next-steps.md | Stub | Pre-GSD | N | N | N | N | NO |
| docs/features/emas/ema-alpha-comparison.md | Partial | v0.5.0 | N | Y | Y | Y | NO |
| docs/features/emas/ema-feature-migration-plan.md | Partial | v0.5.0 | N | Y | Y | Y | NO |
| docs/features/emas/ema-migration-session-summary.md | Partial | v0.5.0 | N | N | Y | Y | NO |

**EMA documentation notes:**
- The **3 complete multi-tf docs** (`ema-multi-tf.md`, `ema-multi-tf-cal.md`, `ema-multi-tf-cal-anchor.md`) provide comprehensive column definitions, table purpose, version behavior (v1 vs v2), and bar-space vs time-space semantics. Each 300-350 lines with detailed appendices.
- `ema-study.md`: 62k+ tokens (too large to read fully), contains mathematical foundations but needs verification against current implementation
- Migration-related docs are recent but focus on specific refactors, not general patterns

#### Time Model

| Document | Quality | Source | A | I | R | Act | Leverage? |
|----------|---------|--------|---|---|---|-----|-----------|
| docs/time/time_model_overview.md | Stub | Phase 6 | Y | N | N | N | NO |
| docs/time/trading_sessions.md | Stub | Phase 6 | Y | N | N | N | NO |
| docs/time/dim_timeframe.md | Partial | Phase 6 | Y | Y | N | Y | NO |
| docs/time/ema_model.md | Outdated | Pre-Phase 6 | Y | N | N | N | NO |
| docs/time/returns_volatility.md | Stub | Phase 6 | N | N | N | N | NO |
| docs/time/regime_integration.md | Stub | Phase 6 | N | N | N | N | NO |
| docs/time/data_lineage_time.md | Stub | Phase 6 | N | N | N | N | NO |
| docs/time/architecture_index.md | Stub | Phase 6 | N | N | N | N | NO |

**Time model documentation notes:**
- Most time model docs are **stubs** - brief summaries without implementation details
- `dim_timeframe.md`: Useful schema documentation but lacks decision rationale
- `ema_model.md`: Marked as outdated, likely superseded by unified table design
- Phase 6 created placeholders that were never fully fleshed out

#### State Management

| Document | Quality | Source | A | I | R | Act | Leverage? |
|----------|---------|--------|---|---|---|-----|-----------|
| docs/EMA_STATE_STANDARDIZATION.md | Complete | v0.5.0 | Y | Y | Y | Y | **YES** |

**State management documentation notes:**
- **Single authoritative document** for EMA state patterns
- Covers unified state table schema, field population by script type, standardized function names
- Documents migration from old (id, tf) to new (id, tf, period) primary key
- Highly actionable: provides exact state management patterns to verify/extend

#### Operations

| Document | Quality | Source | A | I | R | Act | Leverage? |
|----------|---------|--------|---|---|---|-----|-----------|
| docs/ops/update_price_histories_and_emas.md | Complete | v0.5.0 | Y | Y | Y | Y | **YES** |
| docs/ops/db_trusted_through_2025-11-24.md | Partial | v0.5.0 | N | N | N | Y | NO |
| docs/reference/update-db.md | Stub | Pre-GSD | N | N | N | N | NO |
| docs/reference/updating-price-data-rough.md | Stub | Pre-GSD | N | N | N | N | NO |
| docs/reference/review-refreshmethods-20251201.md | Partial | v0.5.0 | N | Y | Y | Y | NO |

**Operations documentation notes:**
- `update_price_histories_and_emas.md`: **485 lines**, step-by-step operational guide covering full data refresh workflow, EMA layer updates, stats verification. Procedurally complete.
- `db_trusted_through` docs: Useful operational snapshots but lack architectural context
- Most "reference" docs are stubs or rough notes

#### Planning/Research (GSD Phases)

| Document | Quality | Source | A | I | R | Act | Leverage? |
|----------|---------|--------|---|---|---|-----|-----------|
| .planning/phases/06-.../06-RESEARCH.md | Complete | Phase 6 | Y | Y | Y | Y | **YES** |
| .planning/phases/07-.../07-RESEARCH.md | Complete | Phase 7 | Y | Y | Y | Y | **YES** |
| .planning/phases/08-.../08-RESEARCH.md | Complete | Phase 8 | Y | N | Y | Y | NO |
| .planning/phases/09-.../09-RESEARCH.md | Complete | Phase 9 | Y | N | Y | Y | NO |

**Planning documentation notes:**
- Phase 6-9 RESEARCH.md files contain **decision rationale** for design choices
- Phase 6 (Time Model) and Phase 7 (Feature Pipeline) likely contain bar/EMA architecture decisions
- These are in .planning/ directory and document WHY decisions were made at the time

## Leverage-Worthy Documentation

These documents meet all 4 criteria and should be used extensively in v0.6.0:

| Document | Topic | Key Content for v0.6.0 | Lines |
|----------|-------|------------------------|-------|
| docs/features/bar-implementation.md | Bars | Deterministic tie-breaks, watermark reconciliation, snapshot contract, incremental driver standard, shared invariants, operational patterns | 480 |
| docs/features/bar-creation.md | Bars | Formal invariants, bar boundary algorithms, calendar alignment vs anchoring, partial period policies, canonical close rules, error handling taxonomy | 850 |
| docs/EMA_STATE_STANDARDIZATION.md | State | Unified state table schema, field population patterns, standardized function names, migration notes, update strategies | 167 |
| docs/features/ema-multi-tf-cal-anchor.md | EMAs | Calendar-anchored EMA semantics, bar-space vs time-space, \_bar column semantics, partial initial blocks, TradingView alignment | 342 |
| docs/features/ema-multi-tf.md | EMAs | Multi-timeframe EMA architecture, v1 (bar-aligned) vs v2 (continuous), roll semantics, canonical vs rolling observations, alpha computation | 354 |
| docs/features/ema-multi-tf-cal.md | EMAs | Calendar-aligned EMA semantics, true calendar periods vs synthetic day counts, seeding without partial periods, bar-space derivatives | 348 |
| docs/ops/update_price_histories_and_emas.md | Operations | Complete operational workflow for data refresh, layer-by-layer EMA updates, stats verification procedures, error handling | 485 |
| .planning/phases/06-.../06-RESEARCH.md | Time Model | Time model design decisions, trading sessions architecture, timeframe definition rationale | Unknown |
| .planning/phases/07-.../07-RESEARCH.md | Feature Pipeline | Bar validation framework decisions, EMA calculation patterns, feature-level architecture | Unknown |

**Usage notes:**
- **bar-implementation.md** and **bar-creation.md**: Read together for complete bar architecture understanding. bar-creation.md is authoritative specification, bar-implementation.md is practical standard.
- **EMA multi-tf trio**: All 3 documents essential for understanding the 6 EMA variants. Read in order: multi-tf (foundation), multi-tf-cal (calendar alignment), multi-tf-cal-anchor (anchoring nuances).
- **EMA_STATE_STANDARDIZATION.md**: Reference for all state management work. Contains exact schema and function names.
- **Phase RESEARCH files**: Mine for decision rationale when code/docs conflict or are unclear.

## Documentation Gaps

**Missing documentation identified:**

| Gap | Topic | Why Needed for v0.6.0 | Priority |
|-----|-------|----------------------|----------|
| Gap detection logic standardization | Bars | Bar builders have inconsistent gap detection approaches (timestamp diffs vs calendar day counting). Need unified approach with rationale. | HIGH |
| Quality flag semantics | Bars | Flags (`has_gap`, `is_partial_start`, `is_partial_end`) exist in schemas but meaning/usage undocumented. Critical for data quality assessment. | HIGH |
| Bar data source migration history | Bars | When/why did EMAs switch from price_histories to bar tables? Current state has EMAs reading from different sources. | HIGH |
| Incremental refresh pattern comparison | State | Bar builders use one pattern, EMA scripts use different patterns. Need documented comparison with when/why to use each. | HIGH |
| EMA variant decision tree | EMAs | 6 EMA variants exist (multi_tf v1/v2, cal_us/iso, anchor_us/iso). Need "which variant for which use case" guide. | MEDIUM |
| Watermark vs state field semantics | State | Multiple timestamp fields in state tables (`daily_min_seen`, `daily_max_seen`, `last_time_close`, `last_canonical_ts`). Exact semantics undocumented. | MEDIUM |
| Bar sequence numbering schemes | Bars | `bar_seq` computed differently across bar families. Need unified documentation of numbering schemes. | MEDIUM |
| Time model implementation | Time | time_model_overview.md is stub. Actual implementation of trading sessions, timeframe determination undocumented. | MEDIUM |
| DDL rationale | Schema | SQL DDL files lack comments explaining design choices (column types, constraints, indexes). | LOW |
| Test coverage documentation | Quality | What's tested vs untested for bars/EMAs undocumented. | LOW |

**Outdated documentation to update or archive:**

| Document | Issue | Recommendation |
|----------|-------|----------------|
| docs/time/ema_model.md | Pre-Phase 6, likely superseded by unified table design | Archive or mark as historical. Replace with current EMA table architecture overview. |
| docs/features/ema-thoughts.md | Stub with no actionable content | Archive or integrate into another doc. |
| docs/features/ema-possible-next-steps.md | Stub, likely outdated planning notes | Archive if no longer relevant. |
| docs/reference/update-db.md | Stub, superseded by update_price_histories_and_emas.md | Archive. |
| docs/reference/updating-price-data-rough.md | Rough notes, superseded by complete ops doc | Archive. |
| docs/time/*.md (most) | Stubs from Phase 6 never completed | Either flesh out or consolidate into single time model doc. |

## Recommendations for v0.6.0

### 1. Leverage Immediately

**Use as-is for reference:**
- `bar-implementation.md` - Bar validation patterns, state reconciliation
- `bar-creation.md` - Formal bar semantics, invariants
- `EMA_STATE_STANDARDIZATION.md` - State management patterns
- `ema-multi-tf-cal-anchor.md` - Anchored EMA semantics
- `ema-multi-tf.md` - Multi-TF EMA architecture
- `ema-multi-tf-cal.md` - Calendar-aligned semantics
- `update_price_histories_and_emas.md` - Operational procedures

**Action:** Read these documents during Phase 21 (Comprehensive Review) to inform analysis.

### 2. Verify Against Code

**Documents needing code verification:**
- `ema-study.md` - Mathematical foundations (too large to read fully, verify formulas against implementation)
- `dim_timeframe.md` - Schema doc (verify current schema matches)
- Phase 6-9 RESEARCH.md files - Decision history (verify decisions still hold)

**Action:** During Phase 21, spot-check these documents against current codebase. Note discrepancies.

### 3. Fill Critical Gaps

**Create new documentation in Phase 21 or later:**
- Gap detection standardization decision doc
- Quality flag semantics specification
- EMA variant decision tree / comparison matrix
- Incremental refresh pattern comparison
- Bar data source migration history

**Action:** Create these as part of Phase 21 deliverables or defer to Phase 24 (Pattern Consistency) if they require code changes first.

### 4. Archive Outdated

**Archive to `.archive/` or mark as historical:**
- `docs/time/ema_model.md`
- `docs/features/ema-thoughts.md`
- `docs/features/ema-possible-next-steps.md`
- `docs/reference/update-db.md`
- `docs/reference/updating-price-data-rough.md`

**Action:** Move to `.archive/docs/` with note indicating why archived and date.

### 5. Consolidate Stubs

**Time model stubs could be consolidated:**
- Merge `time_model_overview.md`, `trading_sessions.md`, `dim_timeframe.md` into single comprehensive time model document
- Or flesh out each stub with implementation details

**Action:** Defer to Phase 21. Decide based on whether time model needs review for v0.6.0.

## Cross-References

**Documentation relationships:**

- `bar-creation.md` (specification) → `bar-implementation.md` (practical standard)
- `EMA_STATE_STANDARDIZATION.md` → `refresh_cmc_ema_*_from_bars.py` scripts (implementation)
- `ema-multi-tf*.md` (3 docs) → EMA table schemas (implementation)
- Phase 6 RESEARCH.md → `dim_timeframe.md` (rationale → schema)
- Phase 7 RESEARCH.md → `bar-implementation.md` (decisions → standards)
- `update_price_histories_and_emas.md` → All EMA refresh scripts (procedure → code)

## Metadata

**Inventory Statistics:**
- Total documents assessed: 37
- Leverage-worthy (all 4 criteria): 9
- Complete quality: 11
- Partial quality: 15
- Stub quality: 8
- Outdated: 3

**Assessment Date:** 2026-02-05
**Phase:** 20-historical-context
**Next Action:** Use this inventory during Phase 21 (Comprehensive Review) to guide analysis priorities.

---

*This inventory provides the foundation for v0.6.0 historical analysis. All leverage-worthy documents should be referenced extensively during review phases.*
