# Feature Research: EMA & Bar Architecture Standardization

**Domain:** Data validation pipeline standardization and comprehensive code review
**Researched:** 2026-02-05
**Confidence:** HIGH

## Feature Landscape

This research addresses a **subsequent milestone** focused on standardization of existing infrastructure. The features below are review/standardization capabilities needed to ensure consistency across 6 EMA variants and multiple bar builders.

**Context:** The project has:
- 6 working EMA calculation variants (22.4M rows across tables)
- Multiple bar builders with validation logic
- State management for incremental updates
- Mix of validated bar tables and unvalidated price histories as data sources

**Goal:** Comprehensive review + standardization, NOT building new data features.

---

## Table Stakes (Users Expect These)

Features that make this a "comprehensive" review rather than a surface-level pass.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Comprehensive Inventory** | Can't standardize what you don't know exists | LOW | File/function discovery across all 6 EMA variants, bar builders, state tables, helpers |
| **Current State Documentation** | Must document "as-is" before proposing changes | MEDIUM | What patterns exist today? What works? What's inconsistent? |
| **Gap Analysis** | Identify what's missing or inconsistent | MEDIUM | Data source mismatches, missing validation, schema inconsistencies |
| **Data Flow Mapping** | Understand dependencies before refactoring | MEDIUM | price_histories7 → bars → EMAs; state table relationships |
| **Schema Audit** | Table structures must be compared systematically | LOW | Column naming, constraint presence, quality flags, indexes |
| **Pattern Consistency Check** | Identify where same problem solved differently | MEDIUM | Data loading, state management, validation, error handling |
| **Code Annotation** | Inline documentation of complex logic | MEDIUM | Annotate existing code with comments explaining "why" not just "what" |
| **Recommendation Documentation** | Analysis must produce actionable next steps | LOW | What to fix, in what order, with what priority |

**Why table stakes:** A code review that doesn't inventory, document current state, identify gaps, map dependencies, audit schemas, check pattern consistency, annotate code, and provide recommendations is incomplete. Users (future maintainers) expect this baseline.

---

## Differentiators (Comprehensive vs Surface-Level)

Features that distinguish thorough standardization from a quick pass.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Constraint Verification** | Proves data quality claims are enforced | MEDIUM | Verify all bar tables have NOT NULL + OHLC invariants; identify unvalidated sources |
| **State Schema Standardization** | Unified state management across all EMAs | MEDIUM | Already started (see EMA_STATE_STANDARDIZATION.md); ensure all 6 variants follow same pattern |
| **Validation Pattern Library** | Reusable validation logic instead of copy-paste | HIGH | Extract common OHLC validation, gap detection, quality scoring into shared modules |
| **Incremental Refresh Analysis** | Understand watermark patterns and correctness | MEDIUM | High watermark tracking, partial update handling, state consistency |
| **Data Source Migration Plan** | Systematic conversion from price_histories7 to validated bars | HIGH | Not all EMAs use validated bar data yet; plan phased migration |
| **Quality Flag Standardization** | Consistent quality tracking across all tables | MEDIUM | Bar quality flags (reject reasons, repair strategies) vs EMA quality (coverage, gaps) |
| **Cross-Script Comparison Matrix** | Side-by-side comparison of 6 EMA variants | MEDIUM | Comparison table showing data loading, state management, validation differences |
| **Architecture Decision Records** | Document WHY certain patterns exist | LOW | Why 6 separate EMA tables? Why price_histories7 vs bars? Preserve institutional knowledge |
| **Dependency Graph** | Visual map of table/script dependencies | MEDIUM | Which scripts depend on which tables? What order must things run? |
| **Test Coverage Analysis** | Identify untested code paths | MEDIUM | Which validation logic has tests? Which state transitions lack coverage? |

**Why differentiators:** These features move from "we documented what exists" to "we understand the architecture deeply and can safely refactor it." The Cross-Script Comparison Matrix and Validation Pattern Library particularly enable systematic standardization.

---

## Anti-Features (Commonly Requested, Often Problematic)

Features to explicitly NOT do during standardization.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Immediate Refactoring** | "Fix it while reviewing" | Mixing analysis and implementation causes scope creep | Document issues, prioritize, refactor in separate phase |
| **Perfect Pattern Enforcement** | "Make everything identical" | Different EMA variants have legitimately different needs (calendar vs fixed-day) | Standardize non-differentiating features only; preserve intentional differences |
| **Complete Test Suite** | "100% coverage before standardizing" | Testing slows review; you don't know what to test until patterns identified | Write contract tests for interfaces; defer implementation tests |
| **Schema Migration During Review** | "Update schemas while auditing" | Schema changes are risky; require separate validation | Document schema changes needed; execute in controlled migration phase |
| **One Unified EMA Table** | "Merge all 6 EMA tables into one" | Already tried; different canonical boundary definitions require separate tables | Keep 6 tables; standardize patterns WITHIN each family |
| **Automated Fix-All Script** | "Script to auto-standardize everything" | Code generation without understanding causes subtle bugs | Manual fixes with careful review; automation for repetitive tasks only |
| **Gold-Plating Documentation** | "Document every line of code" | Over-documentation becomes outdated quickly | Annotate complex/non-obvious logic; let code be self-documenting where clear |
| **Premature Optimization** | "Refactor for performance while reviewing" | Performance fixes without profiling waste time | Note performance concerns; profile and optimize separately if needed |

**Critical anti-feature:** **Immediate Refactoring** is the biggest trap. This milestone is REVIEW + DOCUMENT + PLAN. Actual standardization comes after. Mixing them causes scope explosion and incomplete analysis.

---

## Feature Dependencies

```
Comprehensive Inventory
    └──requires──> Current State Documentation
                       └──requires──> Gap Analysis
                                         └──requires──> Recommendation Documentation

Data Flow Mapping ──enhances──> Gap Analysis
                 └──requires──> Comprehensive Inventory

Schema Audit ──enhances──> Gap Analysis
Pattern Consistency Check ──enhances──> Gap Analysis

Constraint Verification ──requires──> Schema Audit
State Schema Standardization ──requires──> Pattern Consistency Check

Validation Pattern Library ──requires──> Pattern Consistency Check
                           └──conflicts──> Immediate Refactoring (anti-feature)

Data Source Migration Plan ──requires──> Data Flow Mapping
                           └──requires──> Constraint Verification

Cross-Script Comparison Matrix ──requires──> Comprehensive Inventory
                                └──enhances──> Pattern Consistency Check

Architecture Decision Records ──requires──> Data Flow Mapping
Dependency Graph ──requires──> Data Flow Mapping

Test Coverage Analysis ──requires──> Comprehensive Inventory
```

### Dependency Notes

- **Comprehensive Inventory must come first:** Can't analyze what you haven't catalogued
- **Gap Analysis is the convergence point:** Inventory, data flows, schemas, patterns all feed into gap identification
- **Validation Pattern Library conflicts with Immediate Refactoring:** Can't extract patterns while simultaneously refactoring; must understand patterns first
- **Data Source Migration Plan requires constraint verification:** Must prove bar tables are properly constrained before migrating EMAs to use them
- **Cross-Script Comparison Matrix is a force multiplier:** Makes pattern inconsistencies obvious; drives standardization priorities

---

## MVP Definition

### Phase 1: Discovery & Documentation (v1 of this milestone)

This phase is about **understanding** the current state.

- [ ] **Comprehensive Inventory** - Complete file/function/table listing
  - Essential: Need to know scope before analyzing
- [ ] **Data Flow Mapping** - Diagram showing price_histories7 → bars → EMAs → state
  - Essential: Can't identify data source issues without flow map
- [ ] **Schema Audit** - Systematic comparison of all bar/EMA/state table schemas
  - Essential: Schema inconsistencies are a primary concern
- [ ] **Cross-Script Comparison Matrix** - Side-by-side comparison of 6 EMA variants
  - Essential: Reveals pattern inconsistencies
- [ ] **Current State Documentation** - Narrative document describing "as-is" architecture
  - Essential: Provides context for gap analysis

**Success criteria:** Team can answer "What do we have?" and "How does it work?"

### Phase 2: Analysis & Planning (add after v1)

This phase is about **identifying problems** and **planning fixes**.

- [ ] **Gap Analysis** - Systematic identification of inconsistencies and missing features
  - Trigger: After comprehensive inventory complete
- [ ] **Constraint Verification** - Prove which tables have proper constraints
  - Trigger: After schema audit reveals constraint status
- [ ] **Pattern Consistency Check** - Identify where same problem solved differently
  - Trigger: After cross-script comparison matrix built
- [ ] **Data Source Migration Plan** - Phased plan to move EMAs from price_histories7 to validated bars
  - Trigger: After data flow mapped and constraints verified
- [ ] **Recommendation Documentation** - Prioritized list of standardization tasks
  - Trigger: After gap analysis complete

**Success criteria:** Team can answer "What's wrong?" and "What should we fix?"

### Phase 3: Standardization Execution (defer to separate milestone)

This phase is about **implementing fixes**.

- [ ] **Code Annotation** - Annotate existing code with inline comments
- [ ] **State Schema Standardization** - Finish unified state table migration
- [ ] **Quality Flag Standardization** - Consistent quality tracking across tables
- [ ] **Validation Pattern Library** - Extract reusable validation modules
- [ ] Data source migration implementation
- [ ] Schema migrations

**Why defer:** Can't execute standardization until you know what to standardize. Phases 1-2 produce the roadmap; Phase 3 executes it.

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Comprehensive Inventory | HIGH | LOW | P1 (Phase 1) |
| Data Flow Mapping | HIGH | MEDIUM | P1 (Phase 1) |
| Schema Audit | HIGH | LOW | P1 (Phase 1) |
| Cross-Script Comparison Matrix | HIGH | MEDIUM | P1 (Phase 1) |
| Current State Documentation | HIGH | MEDIUM | P1 (Phase 1) |
| Gap Analysis | HIGH | MEDIUM | P1 (Phase 2) |
| Constraint Verification | HIGH | MEDIUM | P1 (Phase 2) |
| Pattern Consistency Check | HIGH | MEDIUM | P1 (Phase 2) |
| Data Source Migration Plan | HIGH | HIGH | P2 (Phase 2) |
| Recommendation Documentation | HIGH | LOW | P1 (Phase 2) |
| State Schema Standardization | MEDIUM | MEDIUM | P2 (Phase 3) |
| Validation Pattern Library | MEDIUM | HIGH | P2 (Phase 3) |
| Code Annotation | MEDIUM | MEDIUM | P2 (Phase 3) |
| Quality Flag Standardization | MEDIUM | MEDIUM | P2 (Phase 3) |
| Architecture Decision Records | MEDIUM | LOW | P2 (Phase 1-2) |
| Dependency Graph | MEDIUM | MEDIUM | P2 (Phase 1) |
| Test Coverage Analysis | LOW | MEDIUM | P3 (Phase 2) |
| Incremental Refresh Analysis | MEDIUM | MEDIUM | P2 (Phase 2) |

**Priority key:**
- P1: Must have for comprehensive review (Phases 1-2)
- P2: Should have for thorough standardization (Phases 2-3)
- P3: Nice to have, future consideration

**Critical path:** Inventory → Data Flow + Schema Audit + Comparison Matrix → Gap Analysis → Recommendations

---

## Domain-Specific Patterns

### Data Pipeline Standardization Best Practices

Based on industry research for 2026:

**1. DRY Principle for Pipeline Code**
All code organization patterns follow the DRY (don't-repeat-yourself) principle, where standard code must remain in a single place. Most company pipelines follow similar patterns which depend on available tools, and establishing a blueprint enables consistent standards.

**Source:** [Start Data Engineering](https://www.startdataengineering.com/post/de_best_practices/), [FasterCapital Pipeline Standardization](https://fastercapital.com/topics/best-practices-for-code-review-in-pipelines.html)

**2. State Management Patterns**
Organizations are developing data asset systems to track what exactly had been computed in the pipeline and when. High watermark pattern is the most common approach for timestamp or sequence-based incremental extraction, storing the last processed timestamp and updating only after successful load.

**Source:** [Incremental Pipelines at Scale](https://www.geteppo.com/blog/incremental-pipelines-managing-state-at-scale), [Data Engineering Incremental Loading](https://dataengineeracademy.com/blog/data-engineering-incremental-data-loading-strategies/)

**3. Constraint-First Data Quality**
Establishing standards for data types and constraints such as primary keys, foreign keys, unique constraints, and default values ensures data integrity and consistency. Advanced constraint frameworks leverage check constraints, triggers, and stored procedures to implement complex business rules at the database layer.

**Source:** [Schema Standardization](https://airbyte.com/data-engineering-resources/how-to-standardize-data), [MongoDB Schema Validation](https://www.queryleaf.com/blog/2025/08/21/mongodb-data-validation-and-schema-enforcement-sql-style-data-integrity-patterns/)

**4. Code Review Standards**
Clear, concise guidelines for the code review process should be established, including defining what constitutes a reviewable piece of code, the scope of the review, and the criteria for approval. Automated code review tools enforce consistency objectively.

**Source:** [Code Review Best Practices 2025](https://group107.com/blog/code-review-best-practices/), [Secoda Code Review](https://www.secoda.co/blog/how-to-introduce-code-review-to-your-data-engineering-team)

**5. Migration Strategy Framework**
Modernizing code often involves refactoring rather than complete rewrites, making it more efficient and cost-effective. Phased approaches are often better than attempting complete migrations in one go to avoid significant risks and complications.

**Source:** [Code Migration Strategy](https://www.redhat.com/en/blog/modernization-developing-your-code-migration-strategy), [vFunction Migration Strategies](https://vfunction.com/resources/guide-migration-strategies-basics-lift-and-shift-refactor-or-replace/)

### Application to This Project

**Current state:**
- ✅ State management exists (6 state tables, unified schema)
- ✅ Constraints exist on bar tables (NOT NULL, OHLC invariants)
- ❌ DRY violation: 6 EMA scripts with duplicated loading/validation logic
- ❌ Mixed data sources: Some EMAs use validated bars, some use price_histories7
- ⚠️ No centralized validation pattern library

**Standardization priorities based on patterns:**
1. Extract validation logic into shared modules (DRY principle)
2. Migrate all EMAs to validated bar tables (constraint-first quality)
3. Complete state schema unification (state management patterns)
4. Document architecture decisions (review standards)
5. Plan phased migration (migration strategy framework)

---

## Technical Debt Quantification

Based on findings from existing analysis documents:

### Current Technical Debt

| Category | Severity | Description | Impact |
|----------|----------|-------------|--------|
| **Data Source Inconsistency** | HIGH | Some EMAs use price_histories7 (unvalidated) instead of bar tables (validated) | Risk of OHLC invariant violations propagating to EMAs |
| **Pattern Duplication** | MEDIUM | 6 EMA scripts implement data loading/state management differently | Maintenance burden; bug fixes require 6 updates |
| **Schema Naming Inconsistency** | LOW | Column names vary (time_close vs timeclose, bar_seq presence) | Confusion; join complexity |
| **Quality Flag Gaps** | MEDIUM | Bar tables have quality tracking; EMA tables lack explicit quality columns | Can't identify problematic EMA calculations |
| **Validation Logic Duplication** | HIGH | OHLC validation repeated across bar builders | Inconsistent validation; DRY violation |
| **State Table Migration Incomplete** | MEDIUM | State schema unified but not all scripts updated | Inconsistent state management |

### Cost Estimation

Using [technical debt quantification methods](https://fullscale.io/blog/technical-debt-quantification-financial-analysis/) and [financial services debt patterns](https://www.wwt.com/wwt-research/addressing-technical-debt-in-financial-services):

**Maintenance overhead:**
- 6 EMA variants × inconsistent patterns = 6× maintenance cost for bug fixes
- Data source inconsistency = risk of data quality incidents (HIGH impact in trading systems)
- Pattern duplication = estimated 40% of development time spent on "find and fix in all 6 places"

**Standardization ROI:**
- Shared validation library → 1 place to fix bugs (6× reduction)
- Unified data sources → eliminate unvalidated data risk
- Consistent patterns → faster onboarding, reduced cognitive load

---

## Existing Architecture Insights

From project documentation:

### What Already Exists

**Strong foundations:**
- 6 working EMA calculation variants processing 22.4M rows
- State management with unified schema (see EMA_STATE_STANDARDIZATION.md)
- Bar builders with OHLC validation and NOT NULL constraints
- Comprehensive analysis documents already created:
  - `artifacts/ema_architecture_analysis.md` - Full EMA system mapping
  - `artifacts/bar_table_vs_histories_analysis.md` - Data source analysis
  - `docs/EMA_STATE_STANDARDIZATION.md` - State table unification

**Partial standardization already complete:**
- State table schema unified across all 6 EMA variants
- Shared state management functions (`state_management.py`)
- Common snapshot contract for bar builders

### What Needs Standardization

**Non-differentiating features to standardize:**
- Data loading patterns (how EMAs read bar data)
- Validation logic (OHLC checks, gap detection)
- State management usage (function calls, watermark updates)
- Schema naming (consistent column names across related tables)
- Quality tracking (consistent quality flags/scores)

**Intentional differences to PRESERVE:**
- Canonical boundary definitions (fixed-day vs calendar vs anchored)
- Bar-space vs time-space calculations
- TF-specific aggregation logic
- Different table structures for different EMA families

**Key architectural principle:**
> Price histories should only be used to create bars. All downstream consumers (EMAs, features) should use validated bar data.

This principle is documented in PROJECT.md but not fully implemented yet.

---

## Sources

### Data Pipeline Standards
- [Start Data Engineering - Data Flow & Code Best Practices](https://www.startdataengineering.com/post/de_best_practices/)
- [FasterCapital - Best Practices for Code Review in Pipelines](https://fastercapital.com/topics/best-practices-for-code-review-in-pipelines.html)
- [Secoda - How to Introduce Code Review to Data Engineering Teams](https://www.secoda.co/blog/how-to-introduce-code-review-to-your-data-engineering-team)
- [FasterCapital - Pipeline Standardization](https://fastercapital.com/content/Pipeline-standardization--How-to-standardize-your-pipeline-code-and-components-and-follow-the-best-practices-and-conventions.html)
- [Code Review Best Practices for 2025](https://group107.com/blog/code-review-best-practices/)

### State Management & Incremental Processing
- [Incremental Pipelines: Managing State at Scale](https://www.geteppo.com/blog/incremental-pipelines-managing-state-at-scale)
- [Data Engineering Incremental Loading Strategies](https://dataengineeracademy.com/blog/data-engineering-incremental-data-loading-strategies/)
- [OneUpTime - Incremental Extraction](https://oneuptime.com/blog/post/2026-01-30-data-pipeline-incremental-extraction/view)
- [Google SRE - Data Processing Pipelines](https://sre.google/sre-book/data-processing-pipelines/)
- [Coalesce - Incremental Processing Strategies](https://coalesce.io/product-technology/incremental-processing-strategies/)

### Schema Standardization & Validation
- [Adobe Experience Platform - Schema Composition](https://experienceleague.adobe.com/en/docs/experience-platform/xdm/schema/composition)
- [Airbyte - Database Standardization](https://airbyte.com/data-engineering-resources/how-to-standardize-data)
- [MongoDB Schema Validation Guide](https://www.datacamp.com/tutorial/mongodb-schema-validation)
- [QueryLeaf - MongoDB Data Validation](https://www.queryleaf.com/blog/2025/08/21/mongodb-data-validation-and-schema-enforcement-sql-style-data-integrity-patterns/)
- [Medium - Implementing Data Contracts: Schema Validation](https://medium.com/@brunouy/implementing-data-contracts-schema-validation-5aefa2b89332)

### Technical Debt & Gap Analysis
- [CodeAnt - Technical Debt Measurement Tools 2026](https://www.codeant.ai/blogs/tools-measure-technical-debt)
- [WWT - Addressing Technical Debt in Financial Services](https://www.wwt.com/wwt-research/addressing-technical-debt-in-financial-services)
- [Full Scale - Technical Debt Quantification](https://fullscale.io/blog/technical-debt-quantification-financial-analysis/)
- [Test Gap Analysis - Teamscale](https://teamscale.com/features/test-gap-analysis)
- [Gap Analysis in QA - testRigor](https://testrigor.com/blog/gap-analysis-in-qa/)

### Code Documentation & Annotation
- [Codacy - Code Documentation Best Practices](https://blog.codacy.com/code-documentation)
- [PEP 8 - Python Style Guide](https://peps.python.org/pep-0008/)
- [Swimm - Comments in Code Best Practices](https://swimm.io/learn/code-collaboration/comments-in-code-best-practices-and-mistakes-to-avoid)
- [Document360 - Code Documentation Best Practices](https://document360.com/blog/code-documentation/)

### Migration & Refactoring Strategy
- [Red Hat - Developing Your Code Migration Strategy](https://www.redhat.com/en/blog/modernization-developing-your-code-migration-strategy)
- [vFunction - Migration Strategies Guide](https://vfunction.com/resources/guide-migration-strategies-basics-lift-and-shift-refactor-or-replace/)
- [Microsoft Learn - Select Cloud Migration Strategies](https://learn.microsoft.com/en-us/azure/cloud-adoption-framework/plan/select-cloud-migration-strategy)
- [Netguru - Streamline Code Migration](https://www.netguru.com/blog/code-migration)

### Project-Specific Sources
- Project documentation: `.planning/PROJECT.md`, `.planning/ROADMAP.md`
- Existing analysis: `docs/EMA_STATE_STANDARDIZATION.md`, `artifacts/ema_architecture_analysis.md`, `artifacts/bar_table_vs_histories_analysis.md`
- Codebase inspection: Bar builder scripts, EMA refresh scripts, state management modules

---

*Feature research for: EMA & Bar Architecture Standardization (v0.6.0 milestone)*
*Researched: 2026-02-05*
*Confidence: HIGH (based on project codebase inspection + 2026 industry best practices)*
