# Architecture Research: Review & Standardization of Data Pipeline Scripts

**Domain:** Data Pipeline Standardization (ETL/ELT)
**Researched:** 2026-02-05
**Confidence:** HIGH

## Standard Architecture for Review & Standardization Work

### System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     REVIEW LAYER (Read-Only)                         │
├─────────────────────────────────────────────────────────────────────┤
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐   │
│  │  Inventory │  │  Schemas   │  │ Data Flow  │  │  Helpers/  │   │
│  │  Scripts   │  │  & Tables  │  │  Patterns  │  │  Contracts │   │
│  └──────┬─────┘  └──────┬─────┘  └──────┬─────┘  └──────┬─────┘   │
│         │                │                │                │         │
│         └────────────────┴────────────────┴────────────────┘         │
│                              ▼                                       │
├─────────────────────────────────────────────────────────────────────┤
│                    ANALYSIS LAYER (Document)                         │
├─────────────────────────────────────────────────────────────────────┤
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Findings Documents + Code Annotations                        │  │
│  │  - Gap analysis                                                │  │
│  │  - Inconsistency catalog                                       │  │
│  │  - Integration point map                                       │  │
│  │  - Dependency graph                                            │  │
│  └───────────────────────────┬──────────────────────────────────┘  │
│                               ▼                                      │
├─────────────────────────────────────────────────────────────────────┤
│                  STANDARDIZATION LAYER (Fix & Unify)                │
├─────────────────────────────────────────────────────────────────────┤
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐   │
│  │ Data Source│  │  Patterns  │  │  Schemas   │  │    Code    │   │
│  │   Fixes    │  │  Alignment │  │  Alignment │  │  Comments  │   │
│  └────────────┘  └────────────┘  └────────────┘  └────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| Inventory Scripts | Enumerate all scripts, tables, helpers, contracts, orchestrators | File system scan + manual grouping |
| Schemas & Tables | Document table schemas, constraints, naming conventions, quality flags | Database introspection + DDL review |
| Data Flow Patterns | Map source → intermediate → target flow, identify validation points | Code inspection + state table analysis |
| Helpers/Contracts | Identify shared utilities, document interfaces, find duplication | AST analysis + manual review |
| Analysis Documents | Structured findings (gaps, inconsistencies, dependencies) | Markdown documents with references |
| Data Source Fixes | Update scripts to use validated sources (bars not raw data) | Code modifications with tests |
| Pattern Alignment | Standardize data loading, validation, state management | Extract to shared modules |
| Schema Alignment | Consistent naming, constraints, quality flags across tables | DDL updates + migration scripts |
| Code Comments | Annotate complex logic, document assumptions, flag TODOs | Inline docstrings + comments |

## Recommended Project Structure for Review Work

```
.planning/
├── research/                  # This directory
│   ├── ARCHITECTURE.md        # This file
│   ├── SUMMARY.md             # Executive summary
│   ├── STACK.md               # Technology decisions
│   ├── FEATURES.md            # Feature landscape
│   └── PITFALLS.md            # Domain pitfalls
│
└── phases/
    └── [milestone-name]/
        ├── review/            # Phase 1: Review outputs
        │   ├── 01-inventory.md           # What exists
        │   ├── 02-schema-analysis.md     # Table structure
        │   ├── 03-data-flow.md           # How data moves
        │   ├── 04-helpers-contracts.md   # Shared code
        │   ├── 05-gap-analysis.md        # What's missing
        │   └── 06-integration-points.md  # Where consistency matters
        │
        └── standardization/   # Phase 2: Fix outputs
            ├── 01-data-sources.md        # Fix EMA → bars
            ├── 02-patterns.md            # Standardize loading/validation
            ├── 03-schemas.md             # Align table structure
            └── 04-annotations.md         # Code documentation
```

### Structure Rationale

- **`.planning/research/`:** Domain-level research (applies to all milestones)
- **`.planning/phases/[milestone]/review/`:** Read-only analysis outputs
- **`.planning/phases/[milestone]/standardization/`:** Implementation plans for fixes
- **Separation of concerns:** Review (understand) before standardization (change)
- **Traceability:** Each standardization document references review findings

## Architectural Patterns for Review & Standardization

### Pattern 1: Inventory-First Discovery

**What:** Enumerate all components before analyzing relationships

**When to use:** Starting a comprehensive review with unknown scope

**Trade-offs:**
- **Pro:** Complete picture prevents missed dependencies
- **Pro:** Enables batch analysis (vs iterative discovery)
- **Con:** Can be time-consuming upfront
- **Con:** May discover irrelevant code (old, unused)

**Example:**
```python
# Inventory structure
inventory = {
    "bar_builders": {
        "1d": "refresh_cmc_price_bars_1d.py",
        "multi_tf": "refresh_cmc_price_bars_multi_tf.py",
        # ... 5 total
    },
    "ema_calculators": {
        "v1": "refresh_cmc_ema_multi_tf_from_bars.py",
        "v2": "refresh_cmc_ema_multi_tf_v2.py",
        "cal_us": "refresh_cmc_ema_multi_tf_cal_from_bars.py",
        "cal_iso": "refresh_cmc_ema_multi_tf_cal_from_bars.py",
        "cal_anchor_us": "refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py",
        "cal_anchor_iso": "refresh_cmc_ema_multi_tf_cal_anchor_from_bars.py",
    },
    "state_tables": ["..._state", "..._state", ...],
    "helpers": ["common_snapshot_contract.py", "base_ema_refresher.py"],
    "orchestrators": ["multiprocessing_orchestrator.py"],
}
```

### Pattern 2: Integration Point Mapping

**What:** Identify where components interact and consistency is critical

**When to use:** After inventory, before deep analysis

**Trade-offs:**
- **Pro:** Focuses effort on high-value areas (interfaces)
- **Pro:** Reveals cascading dependencies early
- **Con:** May overlook internal inconsistencies
- **Con:** Requires understanding of data flow

**Example:**
```markdown
# Integration Point Map

## Critical Integration Points
1. **Raw data → Bar tables**
   - Source: price_histories7
   - Validation: NOT NULL constraints, OHLC invariants
   - Consumers: All 6 EMA calculators (MUST use bars, not raw)

2. **Bar tables → EMA tables**
   - Source: cmc_price_bars_1d, cmc_price_bars_multi_tf_*
   - State management: per (id, tf, period) watermarks
   - Consumers: Features, signals, backtests

3. **State tables → Incremental refresh**
   - Pattern: Load state → compute dirty window → update state
   - Consistency: Unified schema (id, tf, period, timestamps, bar_seq)
```

### Pattern 3: Gap Analysis with Severity Tiers

**What:** Categorize findings by impact and urgency

**When to use:** During analysis phase, before standardization planning

**Trade-offs:**
- **Pro:** Prioritizes work effectively
- **Pro:** Allows incremental delivery (critical first)
- **Con:** Subjective severity assessment
- **Con:** May defer architectural debt

**Example:**
```markdown
# Gap Analysis

## CRITICAL (Breaks correctness)
- [ ] EMA v2 uses price_histories7 directly (bypasses validation)
- [ ] Inconsistent state table schemas (cal variants missing bar_seq)

## HIGH (Creates maintenance burden)
- [ ] Duplicate data loading logic across 6 EMA scripts
- [ ] Inconsistent table naming (some _state, some _refresh_state)

## MEDIUM (Quality/DX issues)
- [ ] Missing code annotations in complex logic
- [ ] No shared CLI parsing for EMA scripts

## LOW (Nice-to-have)
- [ ] Old scripts in /old folders (cleanup)
```

### Pattern 4: Review-Then-Standardize Phases

**What:** Complete read-only review before making changes

**When to use:** Large-scale standardization with many unknowns

**Trade-offs:**
- **Pro:** Prevents rework from incomplete understanding
- **Pro:** Enables holistic standardization (not piecemeal)
- **Con:** Delays visible progress (feels slow)
- **Con:** Requires discipline to not fix during review

**Key principle:** Resist the urge to fix issues discovered during review. Document them instead.

### Pattern 5: Data Source Standardization First

**What:** Fix upstream dependencies before downstream patterns

**When to use:** When correctness depends on data quality

**Trade-offs:**
- **Pro:** Prevents building on broken foundation
- **Pro:** Downstream work can assume validated data
- **Con:** May require coordination with data teams
- **Con:** Can block other standardization work

**Ordering rationale:**
```
1. Data sources (bars → EMAs)      ← MUST fix first (correctness)
2. State management (schemas)      ← Enables incremental refresh
3. Loading patterns (shared utils) ← Reduces duplication
4. Schema naming (cosmetic)        ← Last (low risk)
```

## Data Flow for Review & Standardization

### Review Flow (Phase 1)

```
[Codebase]
    ↓
[File system scan] → [Inventory document]
    ↓
[DDL inspection] → [Schema analysis]
    ↓
[Code inspection] → [Data flow map]
    ↓
[AST analysis] → [Helper/contract catalog]
    ↓
[Cross-reference] → [Gap analysis]
    ↓
[Dependency graph] → [Integration point map]
    ↓
[Findings documents] (Read-only, no code changes)
```

### Standardization Flow (Phase 2)

```
[Gap analysis] + [Integration point map]
    ↓
[Prioritization] → [Severity tiers]
    ↓
[Data source fixes] → [Update EMA scripts to use bars]
    ↓
[Pattern extraction] → [Shared utilities for loading/validation]
    ↓
[Schema alignment] → [DDL updates + migrations]
    ↓
[Code annotations] → [Inline comments + docstrings]
    ↓
[Verification] → [Tests + manual checks]
    ↓
[Documentation] → [Analysis docs + code comments]
```

### Key Data Flows in This Domain

1. **Inventory → Analysis:** List of components feeds into relationship mapping
2. **Gap analysis → Prioritization:** Findings with severity drive work order
3. **Integration points → Verification:** Critical interfaces get extra testing
4. **Review docs → Standardization plans:** Findings directly inform fixes

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1-10 scripts | Manual review, single-file analysis documents |
| 10-50 scripts | Automated inventory (AST parsing), structured templates for analysis |
| 50-200 scripts | Automated dependency graphing, database-backed findings tracking |
| 200+ scripts | Full codebase analysis tools (SonarQube, CodeQL), dedicated refactoring team |

### Scaling Priorities

1. **First bottleneck:** Manual inventory becomes error-prone at 20+ scripts
   - **Fix:** Automate with file system scans + AST parsing
   - **Tool:** Python `ast` module, `grep`/`ripgrep` for patterns

2. **Second bottleneck:** Analysis documents become unwieldy at 50+ findings
   - **Fix:** Structure findings in database or issue tracker
   - **Tool:** GitHub Issues, Linear, or custom SQLite database

3. **Third bottleneck:** Coordination between reviewers at 100+ scripts
   - **Fix:** Split by domain (bars, EMAs, features) with integration reviews
   - **Tool:** CODEOWNERS file, dedicated integration review phase

## Anti-Patterns

### Anti-Pattern 1: Fix-As-You-Go Review

**What people do:** Start fixing issues during the review phase

**Why it's wrong:**
- Incomplete understanding leads to rework
- May miss systemic issues requiring holistic fixes
- Review findings become stale as code changes
- Difficult to track what was reviewed vs fixed

**Do this instead:**
- Complete read-only review phase
- Document all findings with references
- Plan standardization holistically
- Execute fixes in prioritized order

### Anti-Pattern 2: Schema Alignment Before Data Source Fixes

**What people do:** Focus on cosmetic consistency (naming, constraints) before correctness

**Why it's wrong:**
- Building on broken foundation (e.g., EMAs using raw data)
- Schema changes may need rework after data source fixes
- Delays fixes to critical correctness issues
- Wastes effort on low-value cosmetics

**Do this instead:**
- Data source fixes first (bars → EMAs)
- State management second (enables incremental)
- Loading patterns third (reduces duplication)
- Schema naming last (cosmetic)

### Anti-Pattern 3: Over-Documentation of Obvious Code

**What people do:** Add verbose comments to simple, self-explanatory logic

**Why it's wrong:**
- Creates maintenance burden (comments go stale)
- Obscures truly complex logic that needs explanation
- Wastes review time on trivia
- Gives false sense of completeness

**Do this instead:**
- Annotate only complex, non-obvious logic
- Document assumptions and business rules
- Flag known limitations and TODOs
- Use descriptive names to make code self-documenting

### Anti-Pattern 4: Siloed Review (Per-Script Analysis)

**What people do:** Review each script in isolation without cross-referencing

**Why it's wrong:**
- Misses shared patterns and duplication
- Cannot identify integration point inconsistencies
- Prevents extraction of shared utilities
- Results in piecemeal, inconsistent fixes

**Do this instead:**
- Start with inventory of all components
- Map integration points across components
- Identify patterns (data loading, state management)
- Plan shared utilities before script-by-script fixes

### Anti-Pattern 5: State Table Fragmentation

**What people do:** Each script creates its own state table schema

**Why it's wrong:**
- Cannot query state across all scripts (no unified view)
- Inconsistent watermarking strategies
- Duplication of state management logic
- Difficult to add new scripts (no template)

**Do this instead:**
- Unified state table schema for all incremental scripts
- Shared state management module
- Document state fields and population rules
- Enforce schema via shared utilities (not script-local logic)

## Integration Points for This Domain

### Critical Integration Points

| Integration Point | Consistency Requirement | Validation Strategy |
|-------------------|-------------------------|---------------------|
| **Raw data → Bars** | NOT NULL constraints, OHLC invariants | Contract validation in bar builders |
| **Bars → EMAs** | EMAs MUST use validated bars (not raw) | Code inspection + unit tests |
| **State schema** | Unified (id, tf, period) PRIMARY KEY | Shared state management module |
| **Incremental refresh** | Consistent watermark pattern | Shared base class or utility functions |
| **Table naming** | Consistent suffixes (_state, _bars, _ema) | Linting rules + documentation |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| Bar builders ↔ Common contract | Function calls | `common_snapshot_contract.py` |
| EMA calculators ↔ Base refresher | Inheritance | `BaseEMARefresher` template method pattern |
| All scripts ↔ Orchestrator | Task execution | `MultiprocessingOrchestrator` |
| Scripts ↔ State tables | SQL queries | Shared schema via `EMAStateManager` |
| Review docs ↔ Standardization plans | References | Gap findings linked to fix tasks |

### External Boundaries (Not in Scope)

- **Database ↔ External sources:** Handled by separate ingestion scripts
- **Features/Signals ↔ Backtests:** Downstream consumers of standardized data
- **CI/CD ↔ Scripts:** Testing and deployment infrastructure

## Build Order for Review & Standardization

### Phase 1: Review (Read-Only, No Code Changes)

**Order rationale:** Inventory → Relationships → Analysis

```
1. Inventory (3 tasks, parallel)
   - Task 1.1: Enumerate bar builders + schemas
   - Task 1.2: Enumerate EMA calculators + schemas
   - Task 1.3: Enumerate helpers, contracts, orchestrators

2. Schema Analysis (1 task, depends on 1.1 + 1.2)
   - Task 2.1: Document table schemas, constraints, naming

3. Data Flow Mapping (1 task, depends on 1.1 + 1.2)
   - Task 3.1: Map price_histories7 → bars → EMAs → features

4. Helpers/Contracts Analysis (1 task, depends on 1.3)
   - Task 4.1: Document shared utilities, find duplication

5. Gap Analysis (1 task, depends on 2 + 3 + 4)
   - Task 5.1: Catalog inconsistencies, missing patterns, data source issues

6. Integration Point Mapping (1 task, depends on 5)
   - Task 6.1: Identify critical interfaces, document dependencies
```

**Critical path:** 1 → 2 → 3 → 5 → 6 (4 can run in parallel with 2/3)

### Phase 2: Standardization (Code Changes + Verification)

**Order rationale:** Correctness → Consistency → Quality

```
1. Data Source Fixes (1 task, CRITICAL)
   - Task 1.1: Update EMAs to use validated bar tables (not raw)
   - Verification: Unit tests + manual data checks

2. State Management (1 task, HIGH)
   - Task 2.1: Standardize state table schema (id, tf, period)
   - Task 2.2: Shared state management utilities
   - Verification: Schema migration scripts + tests

3. Pattern Standardization (2 tasks, HIGH)
   - Task 3.1: Extract shared data loading utilities
   - Task 3.2: Extract shared validation logic
   - Verification: Integration tests

4. Schema Alignment (1 task, MEDIUM)
   - Task 4.1: Consistent naming (_state, _bars, _ema suffixes)
   - Task 4.2: Add missing constraints (NOT NULL, CHECK)
   - Verification: DDL review + constraint tests

5. Code Annotations (1 task, LOW)
   - Task 5.1: Annotate complex logic in bar builders
   - Task 5.2: Annotate complex logic in EMA calculators
   - Verification: Documentation review

6. Documentation (1 task, final)
   - Task 6.1: Update analysis documents with findings
   - Task 6.2: Update code READMEs with new patterns
   - Verification: Manual review
```

**Critical path:** 1 → 2 → 3 → 4 → 5 → 6 (all sequential due to dependencies)

### Dependency Graph

```
Review Phase:
  Inventory (1.1, 1.2, 1.3) [parallel]
      ↓
  Schema Analysis (2.1) + Data Flow (3.1) + Helpers (4.1) [parallel]
      ↓
  Gap Analysis (5.1)
      ↓
  Integration Points (6.1)

Standardization Phase:
  Data Source Fixes (1.1) [CRITICAL, blocks everything]
      ↓
  State Management (2.1, 2.2)
      ↓
  Pattern Standardization (3.1, 3.2) [can overlap with 4]
      ↓
  Schema Alignment (4.1, 4.2)
      ↓
  Code Annotations (5.1, 5.2)
      ↓
  Documentation (6.1, 6.2)
```

### Parallelization Opportunities

**Review phase:**
- Tasks 1.1, 1.2, 1.3 can run in parallel (independent)
- Tasks 2.1, 3.1, 4.1 can run in parallel (all depend on inventory)

**Standardization phase:**
- Tasks 3.1, 3.2, 4.1, 4.2 can partially overlap (different code areas)
- Tasks 5.1, 5.2 can run in parallel (independent scripts)

## Research Confidence Assessment

| Area | Confidence | Evidence |
|------|------------|----------|
| Review patterns | HIGH | Industry standards from 2026 code audit guides |
| Standardization ordering | HIGH | Data pipeline best practices, ETL frameworks |
| Integration points | HIGH | Existing codebase analysis (common_snapshot_contract.py, base_ema_refresher.py) |
| State management | HIGH | Documented standardization (EMA_STATE_STANDARDIZATION.md) |
| Build order | HIGH | Dependency analysis from codebase structure |

## Sources

### Code Review & Refactoring
- [Software Code Refactoring: A Comprehensive Review](https://www.researchgate.net/publication/368921892_Software_Code_Refactoring_A_Comprehensive_Review)
- [Code Review Practices for Refactoring Changes](https://arxiv.org/abs/2203.14404)
- [The Complete Guide to Professional Code Refactoring](https://dev.to/devcorner/the-complete-guide-to-professional-code-refactoring-transform-your-code-like-a-pro-2h8a)

### Codebase Audit
- [How to Conduct a Code Audit Successfully for 2026](https://www.cleveroad.com/blog/software-code-auditing/)
- [COD Model: 5-Phase Guide to Codebase Dependency Mapping](https://augmentcode.com/guides/cod-model-5-phase-guide-to-codebase-dependency-mapping)
- [Effective Code Audits: Processes, Benefits, And Best Practices](https://devcom.com/tech-blog/software-code-audit-what-is-it-and-why-you-need-it-for-your-project/)

### Data Pipeline Standardization
- [ETL Frameworks in 2026 for Future-Proof Data Pipelines](https://www.integrate.io/blog/etl-frameworks-in-2025-designing-robust-future-proof-data-pipelines/)
- [ETL Pipeline best practices for reliable data workflows](https://www.getdbt.com/blog/etl-pipeline-best-practices)
- [Data Load Patterns 101: Full Refresh and Incremental](https://www.tobikodata.com/blog/data-load-patterns-101)
- [Incremental loading | dlt Docs](https://dlthub.com/docs/general-usage/incremental-loading)

### Database Standardization
- [Database Naming Standards: SQL Conventions for Tables](https://blog.devart.com/sql-database-naming-standards.html)
- [Best Practices for Database Schema Name Conventions](https://vertabelo.com/blog/database-schema-naming-conventions/)
- [Seven essential database schema best practices](https://www.fivetran.com/blog/database-schema-best-practices)

### Existing Codebase
- `src/ta_lab2/scripts/bars/common_snapshot_contract.py` - Shared bar builder utilities
- `src/ta_lab2/scripts/emas/base_ema_refresher.py` - Template Method pattern for EMA scripts
- `docs/EMA_STATE_STANDARDIZATION.md` - State table unification documentation
- `.planning/phases/bar-builders-FINAL-SUMMARY.md` - Prior refactoring case study

---
*Architecture research for: EMA & Bar Architecture Standardization*
*Researched: 2026-02-05*
