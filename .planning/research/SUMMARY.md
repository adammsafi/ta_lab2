# Project Research Summary

**Project:** EMA & Bar Architecture Standardization (v0.6.0)
**Domain:** Data Pipeline Standardization & Code Review (Financial/Trading System)
**Researched:** 2026-02-05
**Confidence:** HIGH

## Executive Summary

This milestone focuses on comprehensive review and standardization of an existing production quantitative trading system with 6 EMA calculation variants processing 22.4M rows and multiple bar builders. The system is working but has accumulated technical debt through duplicated patterns, inconsistent data sources (some EMAs use validated bars, others use raw price histories), and schema variations across similar components. The recommended approach is a rigorous two-phase strategy: first, conduct read-only analysis to understand current architecture and document all dependencies (Phase 1: Review); second, implement standardization fixes prioritizing correctness over cosmetics (Phase 2: Standardization).

The key risk is breaking working calculations during standardization. In quantitative systems, even floating-point precision differences can invalidate historical backtests and flip trading signals. Mitigation requires capturing baseline outputs before any changes, running side-by-side comparisons to verify calculation drift is within epsilon, and enforcing all-or-nothing rules for data source migrations. The architectural principle from PROJECT.md - "price histories should only be used to create bars; all downstream consumers should use validated bar data" - must be fully implemented during standardization, not partially.

The critical success factor is resisting the urge to "fix as you go" during review. The 6 EMA variants exist for legitimate reasons (calendar alignment, anchored snapshots, different week conventions), and premature consolidation will break downstream consumers. Documentation analysis shows partial standardization already in progress (state table schema unified, shared base classes exist), providing a strong foundation. The standardization work should complete these patterns systematically rather than start from scratch.

## Key Findings

### Recommended Stack

The existing stack (PostgreSQL, Python, psycopg2, SQLAlchemy, pandas, pytest) remains the foundation. Stack additions target analysis and validation capabilities rather than new feature libraries. The focus is on programmatic analysis tools that enable systematic pattern detection across 6 similar EMA variants.

**Core technologies:**
- **ast (stdlib)**: Programmatic AST analysis — Built-in to Python 3.11+, enables custom pattern detection across similar scripts without external dependencies
- **radon 6.0.1**: Code complexity metrics — Industry standard for identifying refactoring candidates through cyclomatic complexity analysis
- **hypothesis 6.151.4+**: Property-based testing — Already in requirements.txt; ideal for validating OHLC invariants across different data sources

**Supporting libraries:**
- **pycode-similar 1.0.3**: AST-based code similarity detection to compare 6 EMA variants and identify structural inconsistencies
- **pytest-cov 6.0+**: Coverage reporting to verify validation test completeness across bar/EMA scripts
- **SQLAlchemy Inspector**: Schema reflection (already available in stack) for programmatic table structure comparison
- **ruff 0.15.0+**: Linting and formatting (already in stack, upgrade recommended) for consistency enforcement

**What NOT to use:**
- External schema migration tools (Liquibase, Alembic) — Not modifying schemas in review phase, only analyzing
- Black/Flake8/isort — Replaced by ruff (faster, already in stack)
- External diff tools (pgdiff, pgquarrel) — SQLAlchemy Inspector provides programmatic access already

**Rationale:** Analysis over generation. This milestone reviews existing code rather than building new features. Tools focus on understanding current architecture through automation (AST parsing, similarity detection, complexity metrics) rather than manual inspection.

### Expected Features

This is a code review and standardization project, not a feature development project. The "features" are review and standardization capabilities needed to ensure consistency.

**Must have (table stakes for comprehensive review):**
- **Comprehensive Inventory** — Can't standardize what you don't catalog; must enumerate all 6 EMA variants, bar builders, state tables, helpers
- **Data Flow Mapping** — Must understand price_histories7 → bars → EMAs flow before refactoring dependencies
- **Schema Audit** — Table structures must be compared systematically to identify inconsistencies
- **Cross-Script Comparison Matrix** — Side-by-side comparison of 6 EMA variants reveals pattern differences
- **Gap Analysis** — Systematic identification of inconsistencies, missing patterns, data source mismatches
- **Current State Documentation** — Must document "as-is" architecture before proposing changes

**Should have (differentiators for thorough standardization):**
- **Constraint Verification** — Proves which bar tables have proper validation (NOT NULL, OHLC invariants) vs unvalidated sources
- **State Schema Standardization** — Complete the unified state management pattern across all 6 EMA variants (already started in EMA_STATE_STANDARDIZATION.md)
- **Validation Pattern Library** — Extract common OHLC validation, gap detection, quality scoring into shared modules rather than copy-paste
- **Data Source Migration Plan** — Systematic conversion from price_histories7 (raw) to validated bars for all EMAs
- **Cross-Script Comparison Matrix** — Side-by-side comparison reveals pattern inconsistencies and drives priorities

**Defer (Phase 3+ after stability proven):**
- **Variant Consolidation** — Only consolidate after proving standardization works; variants exist for legitimate reasons
- **Complete Test Suite** — Write contract tests for interfaces during standardization; defer 100% coverage to later
- **Automated Fix-All Script** — Manual fixes with careful review; automation only for repetitive safe tasks

**Critical anti-features (explicitly NOT do):**
- **Immediate Refactoring** — Mixing analysis and implementation causes scope creep; must complete review before standardization
- **Perfect Pattern Enforcement** — Different EMA variants have legitimately different needs; standardize non-differentiating features only
- **Schema Migration During Review** — Schema changes are risky and require separate validation phase

**Key insight from research:** The technical debt is quantifiable: 6 EMA variants with inconsistent patterns = 6× maintenance cost for bug fixes. Data source inconsistency (some using validated bars, some using raw price_histories7) creates data quality risk. Standardization ROI is significant: shared validation library reduces bug fix locations from 6 to 1.

### Architecture Approach

The recommended architecture follows a **Review-Then-Standardize** pattern with strict phase separation. Complete read-only analysis before making any code changes to prevent rework from incomplete understanding.

**Major components:**

1. **Review Layer (Read-Only)** — Inventory scripts, schemas/tables, data flow patterns, helpers/contracts → feeds analysis layer with complete picture
2. **Analysis Layer (Document)** — Findings documents with gap analysis, inconsistency catalog, integration point map, dependency graph → drives prioritization
3. **Standardization Layer (Fix & Unify)** — Data source fixes (EMAs → validated bars), pattern alignment (shared modules), schema alignment (consistent naming/constraints), code comments (annotate complex logic)

**Key patterns:**

- **Inventory-First Discovery**: Enumerate all components before analyzing relationships to prevent missed dependencies
- **Integration Point Mapping**: Focus effort on critical interfaces where consistency matters most (raw data → bars, bars → EMAs, state management)
- **Gap Analysis with Severity Tiers**: Categorize findings (CRITICAL/HIGH/MEDIUM/LOW) to prioritize work effectively
- **Data Source Standardization First**: Fix upstream dependencies before downstream patterns (correctness before cosmetics)

**Project structure:**
```
.planning/
├── research/                  # Domain research (this directory)
│   ├── STACK.md
│   ├── FEATURES.md
│   ├── ARCHITECTURE.md
│   ├── PITFALLS.md
│   └── SUMMARY.md             # This file
└── phases/
    └── [milestone-name]/
        ├── review/            # Phase 1: Read-only analysis
        │   ├── 01-inventory.md
        │   ├── 02-schema-analysis.md
        │   ├── 03-data-flow.md
        │   ├── 04-helpers-contracts.md
        │   ├── 05-gap-analysis.md
        │   └── 06-integration-points.md
        └── standardization/   # Phase 2: Implementation
            ├── 01-data-sources.md
            ├── 02-patterns.md
            ├── 03-schemas.md
            └── 04-annotations.md
```

**Build order rationale:** Inventory → Relationships → Analysis for review phase. Correctness → Consistency → Quality for standardization phase. Data source fixes MUST come first (if EMAs use unvalidated data, standardizing patterns builds on broken foundation).

### Critical Pitfalls

1. **Breaking Working Scripts During Standardization (Silent Calculation Drift)** — Changing data sources or calculation order can introduce floating-point differences that break backtests and flip trading signals. Prevention: Capture baseline outputs before refactoring, run side-by-side comparisons, document intentional changes, create --validate-against-legacy flag. Warning signs: "Small differences don't matter" (they do in quant systems), no baseline snapshots exist.

2. **Incomplete Inventory Leading to Orphaned Dependencies** — Teams miss helper scripts, orchestrators, or utility functions that reference "variant X." After consolidation, production jobs fail. Prevention: Grep for table names across entire codebase, grep for module imports, find SQL queries, check orchestrators for hardcoded paths, document ALL consumers with dependency graph. Warning signs: Review lists "6 main scripts" but repo has 30+ files with "ema" in name.

3. **Premature Consolidation (Removing Variants Still In Use)** — Assuming "variants are redundant" without understanding why 6 exist. Reality: each serves specific use case (calendar alignment, anchor snapshots, ISO week conventions). Prevention: Phase 1 MUST answer "What consumer depends on each variant's unique behavior?" Create variant justification matrix. Defer consolidation to Phase 4-5 after stability proven.

4. **Schema Change Coordination Failure (State Table Primary Key Migration)** — EMA_STATE_STANDARDIZATION.md documents breaking PK change from (id, tf) to (id, tf, period). Teams update scripts but forget to migrate data, update all dependencies, coordinate deployment. Prevention: Create migration checklist (DDL + data + scripts + staging test + rollback + atomic deploy), use shared state_management.py module, add schema version check in scripts.

5. **Validation Logic Inconsistency (Some Scripts Validated, Some Raw)** — PROJECT.md principle: "Price histories should only create bars; downstream consumers use validated bars." During standardization, partial migration (3 of 6 EMAs use bars, 3 still use raw) creates data quality divergence. Prevention: ALL-OR-NOTHING rule for Phase 2, validation contract test, automated CI check for price_histories7 references in EMA scripts.

**Top prevention strategies:**
- Capture baselines before ANY changes (mandatory for quant systems)
- Run comprehensive grep/imports analysis (find ALL consumers)
- ALL-OR-NOTHING for data source migrations (no partial standardization)
- Atomic schema migrations (DDL + data + scripts deployed together)
- Extract edge cases from ALL variants (not just "best" variant)

## Implications for Roadmap

Based on research, suggested phase structure follows **Review → Standardization** with correctness prioritized over cosmetics:

### Phase 1: Comprehensive Discovery & Inventory
**Rationale:** Must catalog all components before analyzing relationships. Prevents missing dependencies that break production during standardization.

**Delivers:**
- Complete inventory of all 6 EMA variants, bar builders, state tables, helpers, orchestrators
- Cross-script comparison matrix showing structural differences
- Schema audit documenting constraints, naming, quality flags

**Addresses:**
- Comprehensive Inventory (table stakes from FEATURES.md)
- Schema Audit (table stakes)
- Cross-Script Comparison Matrix (differentiator)

**Avoids:**
- Incomplete inventory leading to orphaned dependencies (Pitfall #2)
- Siloed review that misses integration points (Anti-pattern #4)

**Research flag:** Standard patterns (skip research-phase). File system scanning and AST analysis well-documented.

---

### Phase 2: Data Flow & Integration Point Mapping
**Rationale:** Must understand data dependencies (price_histories7 → bars → EMAs) before refactoring. Integration points are where consistency is critical.

**Delivers:**
- Data flow map showing source tables, validation points, consumers
- Integration point map identifying critical interfaces
- Current state documentation with "as-is" architecture

**Addresses:**
- Data Flow Mapping (table stakes from FEATURES.md)
- Integration Point Mapping (architecture pattern)
- Current State Documentation (table stakes)

**Avoids:**
- Premature consolidation without understanding consumers (Pitfall #3)
- Data source changes without dependency analysis

**Uses:** SQLAlchemy Inspector (STACK.md) for schema reflection, AST analysis for code dependencies

**Research flag:** Standard patterns (skip research-phase). Data lineage mapping well-documented in data engineering best practices.

---

### Phase 3: Gap Analysis & Prioritization
**Rationale:** Must identify ALL inconsistencies before planning fixes. Severity tiers (CRITICAL/HIGH/MEDIUM/LOW) drive work order.

**Delivers:**
- Gap analysis with severity tiers
- Pattern consistency check identifying where same problem solved differently
- Recommendations document with prioritized standardization tasks

**Addresses:**
- Gap Analysis (table stakes from FEATURES.md)
- Pattern Consistency Check (table stakes)
- Recommendation Documentation (table stakes)

**Avoids:**
- Schema alignment before data source fixes (Anti-pattern #2)
- Fix-as-you-go during review (Anti-pattern #1)

**Implements:** Gap Analysis with Severity Tiers (ARCHITECTURE.md pattern)

**Research flag:** Standard patterns (skip research-phase). Code review best practices well-established.

---

### Phase 4: Data Source Standardization (CRITICAL)
**Rationale:** Correctness before cosmetics. EMAs MUST use validated bars (not raw price_histories7) per PROJECT.md principle. This is foundation for all other standardization.

**Delivers:**
- ALL 6 EMA variants migrated to validated bar tables
- Validation contract tests proving no price_histories7 usage
- Baseline output comparison verifying calculation drift < epsilon

**Addresses:**
- Data Source Migration Plan (differentiator from FEATURES.md)
- Constraint Verification (differentiator)

**Avoids:**
- Validation logic inconsistency (Pitfall #5) — ALL-OR-NOTHING migration
- Silent calculation drift (Pitfall #1) — baseline comparison mandatory
- Building on broken foundation (Anti-pattern #2)

**Uses:** hypothesis (STACK.md) for property-based OHLC validation tests

**Research flag:** NEEDS RESEARCH. Data migration patterns for financial data with calculation validation requirements. Investigate epsilon tolerance for floating-point comparisons in trading systems.

---

### Phase 5: State Schema Completion
**Rationale:** Complete the unified state management pattern started in EMA_STATE_STANDARDIZATION.md. Enables consistent incremental refresh across all variants.

**Delivers:**
- All 6 variants using unified state schema (id, tf, period) PRIMARY KEY
- Shared state_management.py module enforcing schema
- Migration complete with atomic deployment (DDL + data + scripts)

**Addresses:**
- State Schema Standardization (differentiator from FEATURES.md)

**Avoids:**
- Schema change coordination failure (Pitfall #4) — atomic migration checklist
- State table fragmentation (Anti-pattern #5)

**Implements:** Data Source Standardization First pattern (ARCHITECTURE.md)

**Research flag:** Standard patterns (skip research-phase). State table unification already documented in EMA_STATE_STANDARDIZATION.md.

---

### Phase 6: Pattern Standardization (Shared Modules)
**Rationale:** After data sources fixed and state unified, extract common patterns (data loading, validation, error handling) into shared modules. Reduces duplication from 6× to 1×.

**Delivers:**
- Shared data loading utilities
- Shared validation logic (OHLC checks, gap detection, quality scoring)
- Edge case handling merged from ALL variants (not just "best" one)

**Addresses:**
- Validation Pattern Library (differentiator from FEATURES.md)
- Pattern Consistency Check results from Phase 3

**Avoids:**
- Edge case coverage gaps (Pitfall #6) — extract edge cases from ALL variants
- DRY principle violations (FEATURES.md technical debt)

**Uses:** radon (STACK.md) to identify refactoring candidates through complexity metrics

**Research flag:** Standard patterns (skip research-phase). Shared module extraction well-documented in refactoring literature.

---

### Phase 7: Schema Alignment (Cosmetic)
**Rationale:** After correctness fixed (data sources, state management, patterns), standardize cosmetic consistency (naming, constraints, quality flags).

**Delivers:**
- Consistent table naming (_state, _bars, _ema suffixes)
- Missing constraints added (NOT NULL, CHECK where needed)
- Quality flag standardization across tables

**Addresses:**
- Schema Audit findings from Phase 1
- Quality Flag Standardization (differentiator from FEATURES.md)

**Avoids:**
- Cosmetic changes before correctness (Anti-pattern #2)

**Research flag:** Standard patterns (skip research-phase). Database naming conventions well-documented.

---

### Phase 8: Code Annotation & Documentation
**Rationale:** After code stabilized, annotate complex logic and update architecture documentation. Preserves institutional knowledge.

**Delivers:**
- Inline annotations for complex/non-obvious logic
- Architecture Decision Records documenting why 6 variants exist
- Updated PROJECT.md with standardization outcomes

**Addresses:**
- Code Annotation (table stakes from FEATURES.md)
- Architecture Decision Records (differentiator)

**Avoids:**
- Over-documentation of obvious code (Anti-pattern #3)

**Uses:** pdoc (STACK.md) for API documentation generation post-standardization

**Research flag:** Standard patterns (skip research-phase). Code documentation best practices established.

---

### Phase Ordering Rationale

1. **Phases 1-3 (Review)** must complete before any code changes. Prevents rework from incomplete understanding and ensures holistic standardization plan.

2. **Phase 4 (Data Source Fix)** is CRITICAL and blocks all downstream work. If EMAs use unvalidated data, standardizing patterns builds on broken foundation.

3. **Phase 5 (State Schema)** enables incremental refresh across all variants. Must complete before pattern standardization (shared modules need unified state interface).

4. **Phase 6 (Pattern Standardization)** extracts shared modules. Requires data sources fixed (Phase 4) and state unified (Phase 5) so shared modules work consistently.

5. **Phase 7 (Schema Alignment)** is cosmetic and safe to do after correctness proven. Low risk, improves maintainability.

6. **Phase 8 (Documentation)** happens last when code is stable. Documentation that describes unstable code becomes outdated quickly.

**Dependency chain:** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 (sequential; each phase builds on previous)

**Parallelization opportunities:**
- Within Phase 1: Inventory tasks can run in parallel (bars, EMAs, helpers)
- Within Phase 6: Pattern extraction for different modules can overlap
- Within Phase 8: Documentation tasks can run in parallel

**Critical path:** Phase 4 (Data Source Fix) is the bottleneck. All downstream standardization depends on EMAs using validated bars.

### Research Flags

**Needs research:**
- **Phase 4 (Data Source Standardization):** Financial data migration patterns with calculation validation. Investigate epsilon tolerance for floating-point comparisons in trading systems. Baseline capture strategies for large datasets (22.4M rows).

**Standard patterns (skip research-phase):**
- **Phase 1 (Inventory):** File system scanning, AST analysis for code structure
- **Phase 2 (Data Flow):** Data lineage mapping, dependency graphs
- **Phase 3 (Gap Analysis):** Code review methodologies, severity classification
- **Phase 5 (State Schema):** Already documented in EMA_STATE_STANDARDIZATION.md
- **Phase 6 (Pattern Standardization):** Refactoring literature, shared module extraction
- **Phase 7 (Schema Alignment):** Database naming conventions
- **Phase 8 (Documentation):** Code annotation best practices

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Official docs verified for all recommended tools; existing stack (PostgreSQL, pytest, SQLAlchemy) well-established; additions (radon, pycode-similar) are mature stable libraries with clear use cases |
| Features | HIGH | Feature landscape derived from codebase inspection + 2026 data engineering best practices; table stakes vs differentiators based on code review literature; anti-features validated against refactoring pitfalls |
| Architecture | HIGH | Patterns based on industry standards (Review-Then-Standardize, Data Source First); existing codebase shows partial implementation (state_management.py, base_ema_refresher.py) validating approach; build order derived from dependency analysis |
| Pitfalls | HIGH | Critical pitfalls identified from project-specific evidence (EMA_STATE_STANDARDIZATION.md, run_all_ema_refreshes.py) combined with 2026 ETL pipeline failure modes; recovery strategies based on existing codebase patterns |

**Overall confidence:** HIGH

All four research areas have high confidence due to:
1. **Existing codebase analysis**: Research grounded in actual project structure (6 EMA variants, state tables, bar builders) rather than theoretical patterns
2. **Official documentation**: Stack recommendations verified against official tool docs (ast, radon, hypothesis, SQLAlchemy)
3. **2026 industry research**: Feature patterns, architecture approaches, and pitfalls validated against current data engineering best practices
4. **Project-specific evidence**: Pitfalls derived from actual project docs (EMA_STATE_STANDARDIZATION.md documents breaking PK change; run_all_ema_refreshes.py shows connection pooling warnings)

### Gaps to Address

**Epsilon tolerance for calculation validation (Phase 4):**
- Research identifies need for baseline comparison to detect calculation drift
- Gap: What epsilon value is acceptable for floating-point differences in EMA calculations?
- Handling: During Phase 4 planning, research financial data validation standards and test with sample comparisons to determine appropriate tolerance (likely 1e-10 or tighter for trading systems)

**Variant consolidation criteria (deferred to Phase 9+):**
- Research recommends deferring consolidation until after standardization stability proven
- Gap: What criteria determine when consolidation is safe vs when variants should remain separate?
- Handling: Document during Phase 1 (inventory) which consumers depend on variant-specific behavior. Create "consolidation readiness checklist" for future phases (after v0.6.0 milestone).

**Test coverage baseline for validation:**
- Research recommends contract tests during standardization, defer 100% coverage to later
- Gap: What coverage threshold is sufficient to validate standardization correctness?
- Handling: During Phase 4 (data source fix), establish baseline coverage for OHLC validation logic and incremental refresh paths. Target 80% coverage for critical paths (data loading, state management, validation) rather than 100% overall.

**Performance impact of shared modules:**
- Pattern standardization (Phase 6) extracts shared utilities for data loading and validation
- Gap: Will shared modules introduce performance overhead vs inline implementations?
- Handling: Use pytest-benchmark (already in requirements.txt per STACK.md) to compare performance before/after standardization. Document acceptable performance tolerance (likely <10% overhead acceptable for maintainability gain).

## Sources

### Primary (HIGH confidence)

**Stack Research:**
- [Python ast module documentation](https://docs.python.org/3/library/ast.html) — Built-in AST analysis capabilities
- [Radon documentation](https://radon.readthedocs.io/en/latest/) — Code metrics computation
- [pytest 9.0 release notes](https://docs.pytest.org/en/stable/changelog.html) — Latest pytest features 2026
- [Ruff documentation](https://docs.astral.sh/ruff/) — Linter/formatter capabilities
- [SQLAlchemy reflection documentation](https://docs.sqlalchemy.org/en/20/core/reflection.html) — Schema introspection
- [Hypothesis documentation](https://hypothesis.readthedocs.io/) — Property-based testing

**Architecture Research:**
- [Software Code Refactoring: A Comprehensive Review](https://www.researchgate.net/publication/368921892_Software_Code_Refactoring_A_Comprehensive_Review)
- [ETL Pipeline best practices for reliable data workflows](https://www.getdbt.com/blog/etl-pipeline-best-practices)
- [Database Naming Standards: SQL Conventions for Tables](https://blog.devart.com/sql-database-naming-standards.html)

**Pitfalls Research:**
- [5 Critical ETL Pipeline Design Pitfalls to Avoid](https://airbyte.com/data-engineering-resources/etl-pipeline-pitfalls-to-avoid)
- [Code Refactoring: When to Refactor and How to Avoid Mistakes](https://www.tembo.io/blog/code-refactoring)
- [Data validation best practices and techniques for finance teams](https://www.cubesoftware.com/blog/data-validation-best-practices)

**Project-Specific Documentation:**
- `docs/EMA_STATE_STANDARDIZATION.md` — State table unification (breaking PK change documented)
- `src/ta_lab2/scripts/emas/base_ema_refresher.py` — Template Method pattern for EMA scripts
- `src/ta_lab2/scripts/bars/common_snapshot_contract.py` — Shared bar builder utilities
- `.planning/PROJECT.md` — Architectural principle (price_histories7 → bars → EMAs one-way flow)

### Secondary (MEDIUM confidence)

**Feature Research:**
- [Start Data Engineering - Data Flow & Code Best Practices](https://www.startdataengineering.com/post/de_best_practices/)
- [Incremental Pipelines: Managing State at Scale](https://www.geteppo.com/blog/incremental-pipelines-managing-state-at-scale)
- [Secoda - How to Introduce Code Review to Data Engineering Teams](https://www.secoda.co/blog/how-to-introduce-code-review-to-your-data-engineering-team)

**Architecture Research:**
- [COD Model: 5-Phase Guide to Codebase Dependency Mapping](https://augmentcode.com/guides/cod-model-5-phase-guide-to-codebase-dependency-mapping)
- [Data Load Patterns 101: Full Refresh and Incremental](https://www.tobikodata.com/blog/data-load-patterns-101)

### Tertiary (LOW confidence)

**Stack Research:**
- [Top Python Code Analysis Tools 2026](https://www.jit.io/resources/appsec-tools/top-python-code-analysis-tools-to-improve-code-quality) — AST tool landscape (needs validation in practice)
- [Property-based testing tutorial](https://semaphore.io/blog/property-based-testing-python-hypothesis-pytest) — Hypothesis integration patterns (tutorial quality variable)

**Feature Research:**
- Technical debt quantification methods (multiple approaches exist, chose conservative estimates)

---
*Research completed: 2026-02-05*
*Ready for roadmap: yes*
*Synthesis: Complete integration of STACK, FEATURES, ARCHITECTURE, PITFALLS research*
