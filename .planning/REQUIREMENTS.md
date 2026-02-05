# Requirements: v0.6.0 EMA & Bar Architecture Standardization

**Milestone:** v0.6.0
**Goal:** Lock down bars and EMAs foundation so adding new assets (crypto + equities) is mechanical and reliable
**Status:** Active

---

## Core Problem

EMAs using unvalidated data (price_histories7 with NULLs) creates data quality risk. 6 EMA variants with different patterns are hard to maintain. Incremental refresh behavior unclear. Need to understand and lock down the foundation before scaling to more assets and asset classes.

## Success Criteria

When v0.6.0 is complete:
- **I can add a new asset mechanically** - clear steps, no surprises
- **I trust data quality** - validated bars -> validated EMAs, NULLs can't slip through
- **Incremental refresh just works** - one command, visibility, efficient, gap handling
- **I understand the system** - clear docs (building on what exists), can explain how it works

---

## Phase 0: Historical Context

### Understand How We Got Here

- [ ] **HIST-01**: Review GSD phases 1-10 to understand prior bar/EMA work and decisions made
- [ ] **HIST-02**: Identify existing documentation to leverage (don't reinvent the wheel)
- [ ] **HIST-03**: Understand current state: what works, what's unclear, what's broken

---

## Phase 1: Comprehensive Review (Read-Only)

**Approach:** Complete ALL review/analysis BEFORE any code changes. Leverage existing docs.

### Understanding Questions to Answer

- [ ] **RVWQ-01**: What does each EMA variant do? (v1, v2, cal_us, cal_iso, cal_anchor_us, cal_anchor_iso) - purpose, use cases, why they exist
- [ ] **RVWQ-02**: How does incremental refresh work? (state table watermarking, picking up where left off, gap handling)
- [ ] **RVWQ-03**: What validation happens where? (where NULLs rejected, where OHLC invariants checked, quality flags)
- [ ] **RVWQ-04**: How do I add a new asset? (step-by-step guide: tables to update, scripts to run, verification)

### Review Deliverables

- [ ] **RVWD-01**: Script inventory table - every bar/EMA script with purpose, tables updated, state tables used, dependencies
- [ ] **RVWD-02**: Data flow diagram - visual showing price_histories7 -> bars -> EMAs with validation points marked
- [ ] **RVWD-03**: Variant comparison matrix - side-by-side comparison of 6 EMA variants (data source, state schema, calendar alignment, differences)
- [ ] **RVWD-04**: Gap analysis document - structured list with severity tiers (CRITICAL: data sources, HIGH: patterns, MEDIUM: schemas, LOW: cosmetic) and recommendations

---

## Phase 2: Critical Data Quality Fixes

**Priority:** CRITICAL - blocks scaling to new assets

### Data Source Migration

- [ ] **DATA-01**: All 6 EMA variants switched to use validated bar tables instead of price_histories7
- [ ] **DATA-02**: v1, cal_us, cal_iso, cal_anchor_us, cal_anchor_iso migrated to appropriate bar tables
- [ ] **DATA-03**: v2 verified to already use bars_1d (or migrated if not)
- [ ] **DATA-04**: No EMA script references price_histories7 (grep check enforced in CI)

### Database Validation

- [ ] **DVAL-01**: Bar tables have NOT NULL constraints on all OHLCV fields (already exist, verify complete)
- [ ] **DVAL-02**: Bar tables have check constraints for OHLC invariants (high >= low, high >= close, etc.) - verify or add
- [ ] **DVAL-03**: Quality flags standardized across bar tables (is_missing_days, repaired_timehigh, repaired_timelow, etc.)
- [ ] **DVAL-04**: Gap handling implemented - missing days flagged but don't break pipeline (manual fix option)

---

## Phase 3: Reliable Incremental Refresh

**Priority:** HIGH - enables operational confidence

### Orchestration

- [x] **ORCH-01**: Flexible orchestration script - can run: all tasks, bars only, EMAs only, specific variant
- [x] **ORCH-02**: Modular separation - bars and EMAs as separate pieces with clear interfaces
- [x] **ORCH-03**: One command for daily refresh - simple operational model
- [x] **ORCH-04**: Orchestration eventually covers all features (bars, EMAs, vol, returns) but allows selective execution

### State Management

- [x] **STAT-01**: Analyze current state management patterns across all scripts (don't assume - discover)
- [x] **STAT-02**: Unified state table schema if analysis shows inconsistency (id, tf, period PK or similar)
- [x] **STAT-03**: Consistent watermarking approach across bar builders and EMA calculators
- [x] **STAT-04**: State updates atomic with data updates (no partial states)

### Visibility & Efficiency

- [x] **VISI-01**: Logs show what was processed - X days, Y bars, Z EMAs, N gaps flagged
- [x] **VISI-02**: Efficient processing - only new data computed, not full recomputation
- [x] **VISI-03**: Gap handling visible - clear indication of missing data with manual fix option

---

## Phase 4: Pattern Consistency (Where Justified)

**Priority:** MEDIUM-LOW - only where review shows benefit

### Standardization (Guided by Review Findings)

- [x] **PATT-01**: Data loading standardization - consistent query patterns across variants (if analysis shows inconsistency)
- [x] **PATT-02**: State management code standardized - same read/write patterns (if analysis shows inconsistency)
- [x] **PATT-03**: Validation code shared - OHLC invariants, NULL handling, gap detection (if analysis shows duplication)
- [x] **PATT-04**: Shared utilities extracted - common code moved to reusable modules (if analysis shows duplication worth extracting)

### Boundaries

- [x] **PATT-05**: Keep all 6 EMA variants - they serve distinct purposes (calendar alignment, ISO vs US, anchoring)
- [x] **PATT-06**: Don't force standardization - only where analysis justifies (avoid premature abstraction)

---

## Phase 5: Validation

**Priority:** CRITICAL - must verify fixes worked correctly

### Testing Strategies

- [ ] **TEST-01**: Baseline capture - current EMA outputs from all 6 variants before any changes
- [ ] **TEST-02**: Side-by-side comparison - new outputs vs baseline within epsilon tolerance (floating point)
- [ ] **TEST-03**: New asset test - add test asset (e.g., LTC), verify full pipeline works end-to-end
- [ ] **TEST-04**: Incremental refresh test - run refresh script multiple times, verify only new data processed, state advances correctly
- [ ] **TEST-05**: Manual spot-checks - inspect key tables and outputs to confirm correctness

---

## Out of Scope (Explicit Exclusions)

- **Variant consolidation** - Keep all 6 variants; evaluate consolidation only AFTER standardization proves stable
- **Performance optimization** - Focus on correctness and reliability, not speed (separate milestone)
- **New features** - No new timeframes, periods, or calculation methods (standardize existing only)
- **Historical data repair** - Fix forward pipeline only, don't backfill historical inconsistencies
- **Major schema restructuring** - Add constraints/flags, but don't rename tables or major changes unless justified by review

---

## Constraints & Principles

- **Review first, then fix** - Complete ALL analysis before code changes
- **Leverage existing docs** - Don't reinvent, build on artifacts and documentation that already exist
- **Case-by-case scope decisions** - Small fixes do now, big changes defer or justify
- **Bars and EMAs separate** - Modular design, not tightly coupled
- **Move quickly on data sources** - Bar tables have better validation, switch over decisively
- **Whatever it takes timeline** - Do it right, even if it takes 6-8 weeks

---

## Traceability

Requirements mapped to roadmap phases:

| Requirement ID | Phase | Status |
|----------------|-------|--------|
| HIST-01 | Phase 20 | Pending |
| HIST-02 | Phase 20 | Pending |
| HIST-03 | Phase 20 | Pending |
| RVWQ-01 | Phase 21 | Pending |
| RVWQ-02 | Phase 21 | Pending |
| RVWQ-03 | Phase 21 | Pending |
| RVWQ-04 | Phase 21 | Pending |
| RVWD-01 | Phase 21 | Pending |
| RVWD-02 | Phase 21 | Pending |
| RVWD-03 | Phase 21 | Pending |
| RVWD-04 | Phase 21 | Pending |
| DATA-01 | Phase 22 | Pending |
| DATA-02 | Phase 22 | Pending |
| DATA-03 | Phase 22 | Pending |
| DATA-04 | Phase 22 | Pending |
| DVAL-01 | Phase 22 | Pending |
| DVAL-02 | Phase 22 | Pending |
| DVAL-03 | Phase 22 | Pending |
| DVAL-04 | Phase 22 | Pending |
| ORCH-01 | Phase 23 | Pending |
| ORCH-02 | Phase 23 | Pending |
| ORCH-03 | Phase 23 | Pending |
| ORCH-04 | Phase 23 | Pending |
| STAT-01 | Phase 23 | Pending |
| STAT-02 | Phase 23 | Pending |
| STAT-03 | Phase 23 | Pending |
| STAT-04 | Phase 23 | Pending |
| VISI-01 | Phase 23 | Pending |
| VISI-02 | Phase 23 | Pending |
| VISI-03 | Phase 23 | Pending |
| PATT-01 | Phase 24 | Pending |
| PATT-02 | Phase 24 | Pending |
| PATT-03 | Phase 24 | Pending |
| PATT-04 | Phase 24 | Pending |
| PATT-05 | Phase 24 | Pending |
| PATT-06 | Phase 24 | Pending |
| TEST-01 | Phase 25 | Pending |
| TEST-02 | Phase 26 | Pending |
| TEST-03 | Phase 26 | Pending |
| TEST-04 | Phase 26 | Pending |
| TEST-05 | Phase 26 | Pending |

---

**Total Requirements:** 40 across 6 requirement phases (mapped to 7 roadmap phases)
- Phase 0 (Historical Context): 3 requirements -> Roadmap Phase 20
- Phase 1 (Comprehensive Review): 8 requirements -> Roadmap Phase 21
- Phase 2 (Critical Fixes): 8 requirements -> Roadmap Phase 22
- Phase 3 (Incremental Refresh): 11 requirements -> Roadmap Phase 23
- Phase 4 (Pattern Consistency): 6 requirements -> Roadmap Phase 24
- Phase 5 (Validation): 5 requirements -> Roadmap Phases 25-26

**Coverage:** 40/40 requirements mapped (100%)

---

*Created: 2026-02-05*
*Last updated: 2026-02-05 (traceability section populated by roadmapper)*
