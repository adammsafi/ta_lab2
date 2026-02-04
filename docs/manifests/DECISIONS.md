# v0.5.0 Reorganization Decisions

**Version:** 1.0.0
**Created:** 2026-02-04
**Phases covered:** 11-17

This document provides human-readable rationale for decisions tracked in `decisions.json`.

## Overview

The v0.5.0 reorganization involved 22 major decisions across 7 phases, affecting 155+ files from external directories (ProjectTT, Data_Tools, fredtools2, fedtools2) and internal refactoring. Every decision was made with the constraint: **NO DELETION** - everything preserved in git history + .archive/.

## Decision Categories

| Category | Count | Description |
|----------|-------|-------------|
| archive | 4 | Files moved to .archive/ for preservation |
| migrate | 5 | Files moved to new location in ta_lab2 |
| convert | 1 | Files converted to different format (DOCX→Markdown) |
| create | 10 | New infrastructure created |
| refactor | 2 | Files moved for architectural correctness |

## Quick Reference

| Decision | Phase | Type | Summary |
|----------|-------|------|---------|
| DEC-001 | 13 | archive | Archive 62 DOCX files after Markdown conversion |
| DEC-002 | 13 | convert | Convert ProjectTT docs to Markdown |
| DEC-003 | 12 | create | Category-first archive structure |
| DEC-004 | 12 | create | Manifest per category with $schema |
| DEC-005 | 12 | create | SHA256 checksum validation |
| DEC-006 | 14 | migrate | Data_Tools export tools → ta_lab2 |
| DEC-007 | 14 | migrate | Data_Tools analysis tools → ta_lab2 |
| DEC-008 | 14 | migrate | Data_Tools memory tools → ta_lab2 |
| DEC-009 | 14 | migrate | Data_Tools processing tools → ta_lab2 |
| DEC-010 | 14 | migrate | Data_Tools context/generators → ta_lab2 |
| DEC-011 | 14 | archive | Archive 13 Data_Tools prototypes |
| DEC-012 | 15 | archive | Archive fredtools2 (13 files) |
| DEC-013 | 15 | archive | Archive fedtools2 (29 files) |
| DEC-014 | 15 | create | Economic data provider pattern |
| DEC-015 | 15 | create | ALTERNATIVES.md for archived packages |
| DEC-016 | 11 | create | Memory-first reorganization tracking |
| DEC-017 | 11 | create | Project state snapshot in Mem0 |
| DEC-018 | 11 | create | 80% queryability threshold |
| DEC-019 | 17 | refactor | Move ema_runners tools→scripts |
| DEC-020 | 17 | refactor | Move run_btc_pipeline regimes→scripts |
| DEC-021 | 17 | create | Pre-commit hooks with .archive exclusion |
| DEC-022 | 17 | create | CI workflows for import validation |

## Rationale Index

### RAT-001: Documentation Preservation Strategy
**Used by:** DEC-001, DEC-002
**Summary:** Preserve originals while enabling Markdown-based documentation

**Detail:**
DOCX files were archived after conversion to Markdown to enable:
- Full-text search in IDE and GitHub
- Version control with meaningful diffs
- Integration with docs/index.md navigation

The two-step conversion process (pypandoc for DOCX→HTML, then markdownify for HTML→Markdown) provides the best quality output. YAML front matter includes metadata: title, author, created, modified, original_path, original_size_bytes.

**Alternatives Considered:**
1. **Delete originals** - Rejected: Violates NO DELETION constraint. Git history is insufficient for binary files.
2. **Keep both in docs/** - Rejected: Clutters working directory with 62 DOCX files alongside Markdown versions.
3. **Convert in-place** - Rejected: No audit trail showing original→converted relationship.

**Impact:** 62 files affected (35 DOCX, 27 XLSX). Archiving freed docs/ for clean Markdown-only structure while preserving all originals.

---

### RAT-002: Category-First Archive Structure
**Used by:** DEC-003
**Summary:** Organize archives by content type, not date

**Detail:**
Archive structure follows `.archive/{category}/YYYY-MM-DD/` pattern rather than date-first. This enables browsing by content type (documentation, data_tools, external-packages) which is how developers think about archived content.

When searching for "what happened to that Data_Tools script?", developers browse by category. Dates within categories provide chronological organization for understanding evolution.

**Alternatives Considered:**
1. **Date-first structure** (.archive/2026-02-02/{category}/) - Rejected: Requires knowing exact archive date to find content type.
2. **Flat structure** - Rejected: Doesn't scale beyond ~50 files. Would become unmanageable.
3. **Source-path preservation** - Rejected: Loses semantic categorization. ProjectTT mixed foundational, feature, and planning docs.

**Pattern adopted by:** Phase 13 (documentation), Phase 14 (data_tools), Phase 15 (external-packages).

---

### RAT-003: Manifest Per Category with $schema Versioning
**Used by:** DEC-004
**Summary:** Single manifest per category enables simpler querying

**Detail:**
Each archive category maintains ONE manifest.json file tracking all files across dates. This is superior to manifest-per-date because:
- Querying "what Data_Tools scripts were archived?" reads one file, not N date-stamped manifests
- Category manifests grow linearly with actual archiving activity
- JSON structure naturally supports array of entries with timestamps

Following Phase 12 pattern, manifests include `$schema` field with versioned URL (https://ta-lab2.example.com/schemas/archive-manifest-1.0.0.json) for forward compatibility and validation tooling.

**Alternatives Considered:**
1. **Manifest per date** - Rejected: Forces iteration across multiple manifests for category-level queries.
2. **Single global manifest** - Rejected: Scales poorly, mixing unrelated categories.
3. **No schema versioning** - Rejected: Loses validation capability, forward compatibility unclear.

**Validation pattern:** JSON Schema Draft 2020-12 with required fields, checksum patterns, enum constraints.

---

### RAT-004: Checksum-Based Validation Not Path-Based
**Used by:** DEC-005
**Summary:** SHA256 checksums track files through moves

**Detail:**
Validation hierarchy:
1. **PRIMARY:** Checksum matching - file found anywhere with same SHA256 → PRESERVED
2. **SECONDARY:** Count matching - same number of files → likely reorganized not lost
3. **MEMORY:** Mem0 tracking - migration relationships document intentional moves

Using Python 3.11+ `hashlib.file_digest()` provides 2-10x faster computation by bypassing buffers (direct file descriptor → hash).

This enables files to move during reorganization while remaining verifiable. Example: ema_runners.py moved tools→scripts, checksum confirms same content.

**Alternatives Considered:**
1. **Path-based validation** - Rejected: Breaks on every file move. Reorganization is explicitly about moving files.
2. **MD5 checksums** - Rejected: Cryptographically weak, Python recommends SHA256.
3. **No checksums** - Rejected: Can't verify data integrity, no proof files unchanged during archiving.

**Real-world validation:** Phase 17-05 verified 9,620 Python files with zero data loss using checksum-primary hierarchy.

---

### RAT-005: Functional Package Organization for Data_Tools
**Used by:** DEC-006, DEC-007, DEC-008, DEC-009, DEC-010
**Summary:** Organize by purpose, not alphabetically

**Detail:**
Data_Tools scripts organized into 6 functional categories:
1. **analysis** - AST/tree analysis tools (8 scripts)
2. **processing** - DataFrame utilities (8 scripts)
3. **memory** - Embeddings/OpenAI integration (10 scripts)
4. **export** - ChatGPT/Claude export processing (6 scripts)
5. **context** - RAG/reasoning engines (4 scripts)
6. **generators** - Report/finetuning data generation (4 scripts)

Each category has descriptive `__init__.py` documenting available scripts. This makes tools discoverable by purpose: "I need to process ChatGPT exports" → look in export/.

**Alternatives Considered:**
1. **Flat tools/ directory** - Rejected: 40+ scripts too many to browse effectively.
2. **By data source** (chatgpt/, openai/, etc.) - Rejected: Doesn't match usage patterns. Scripts use multiple sources.
3. **By technology** (pandas/, ast/, langchain/) - Rejected: Too granular, creates 10+ categories.

**Migration result:** 40 scripts migrated, 11 archived (prototypes/one-offs). External dependencies added to pyproject.toml: openai, chromadb, mem0, google.auth, requests, pandas.

---

### RAT-006: Archive vs Migrate Criteria for Data_Tools
**Used by:** DEC-011
**Summary:** Migrate by default; archive only clear non-production code

**Detail:**
Criteria for archiving:
1. **Duplicates** - One-off runners that duplicate existing ta_lab2 functionality
2. **Prototypes** - Numbered iterations (chatgpt_script_keep_look1.py, chatgpt_script_keep_look2.py) indicating experimentation
3. **Test scripts** - run_instantiate_final_memories_tests.py, test_code_search.py

Everything else migrated by default. When in doubt, migrate - archiving is permanent.

**Archives (13 files):**
- 5 one-offs: Simple wrappers for ta_lab2 functionality
- 8 prototypes: Experimental/test files

Each archived file documented in manifest with `action` and `reason` fields following Phase 12 patterns.

**Alternatives Considered:**
1. **Migrate everything** - Rejected: Includes obsolete prototypes that confuse codebase.
2. **Archive everything** - Rejected: Loses 40 useful tools that ARE used by ta_lab2.
3. **Delete non-migrated** - Rejected: Violates NO DELETION constraint.

**Mem0 tracking:** Created `moved_to` relationships for all 40 migrated scripts + archive relationships for 13 archived scripts.

---

### RAT-007: Archive fredtools2/fedtools2 with Ecosystem Alternatives
**Used by:** DEC-012, DEC-013
**Summary:** Zero usage → archive with replacement guidance

**Detail:**
Both packages have **zero usage** in ta_lab2 codebase (verified via grep across all Python files). Ecosystem alternatives provide superior functionality:

**fredapi (replaces fredtools2):**
- 1M+ downloads/month vs fredtools2's ~0
- Active maintenance (last update: 2024)
- Comprehensive FRED API coverage
- Better documentation

**fedfred (replaces fredtools2):**
- Specialized Federal Reserve data tooling
- Active PyPI package

Archived with complete ALTERNATIVES.md documenting:
1. Feature mapping (what each archived function does → replacement)
2. API comparison (code examples)
3. Migration effort estimation
4. Ecosystem maturity (PyPI versions, GitHub stars, last update)

**Alternatives Considered:**
1. **Integrate into ta_lab2** - Rejected: Zero usage means no demand. Would add maintenance burden.
2. **Keep as is** - Rejected: External directories clutter workspace. No benefit without usage.
3. **Delete without archiving** - Rejected: Violates NO DELETION constraint. Lost work unrecoverable.

**Impact:** 42 files archived (13 fredtools2, 29 fedtools2). Package provenance documented: origin, author, purpose, entry_point.

---

### RAT-008: Provider Pattern for Economic Data Integration
**Used by:** DEC-014
**Summary:** Abstract protocol enables multiple data sources

**Detail:**
`EconomicDataProvider` protocol defines interface:
```python
class EconomicDataProvider(Protocol):
    def fetch_series(self, series_id: str, start_date: str, end_date: str) -> pd.DataFrame:
        ...
```

Working fredapi passthrough implementation demonstrates pattern functionality:
- Singleton rate limiter and cache (global across all instances)
- Per-provider circuit breaker (isolates failures per API key)
- Opt-out quality validation (validate=True default, can skip for performance)
- Soft import pattern (FREDAPI_AVAILABLE flag, graceful degradation)

This enables future providers (FRED, Fed, Bloomberg, etc.) without changing consumer code.

**Alternatives Considered:**
1. **Direct fredapi integration** - Rejected: Tight coupling makes adding Fed/Bloomberg sources require refactoring all consumers.
2. **No abstraction** - Rejected: Hard to extend, duplicates rate limiting/caching logic per source.
3. **Stub implementation** - Rejected: Not demonstrably working. Must prove pattern viability.

**Series covered:** 17 series across 4 categories (Fed policy rates, Treasury yields, Inflation indicators, Employment data).

---

### RAT-009: Four-Dimensional ALTERNATIVES.md Pattern
**Used by:** DEC-015
**Summary:** Comprehensive guidance for adopting alternatives

**Detail:**
ALTERNATIVES.md documents four dimensions:

1. **Feature Mapping**
   - What each archived function does
   - Exact replacement function in alternative package
   - Example: fredtools2.fred_api.get_series() → fredapi.Fred.get_series()

2. **API Comparison**
   - Code examples showing before/after
   - Parameter mapping
   - Return type differences

3. **Migration Effort**
   - Estimated time (minutes for simple, hours for complex)
   - Breaking changes to handle
   - Testing requirements

4. **Ecosystem Maturity**
   - PyPI versions and download stats
   - GitHub stars and last update
   - Maintenance status

This enables informed decisions: "Should I use archived package or alternative?" becomes data-driven comparison.

**Alternatives Considered:**
1. **Simple list of alternatives** - Rejected: Insufficient context for decision-making.
2. **No alternatives documentation** - Rejected: Leaves users stranded when they need archived functionality.
3. **In-code comments only** - Rejected: Not discoverable. Users won't find guidance.

**Result:** Clear upgrade path for anyone needing FRED/Fed data integration.

---

### RAT-010: Memory-First Reorganization for Auditability
**Used by:** DEC-016
**Summary:** Snapshot BEFORE moves enables "where did X go?" queries

**Detail:**
Phase 11 Memory Preparation completed BEFORE any file moves. This ensures Mem0 has complete snapshot of pre-reorganization state for semantic queries:
- "Where did Y.py go?" → Query returns migration path
- "What replaced X functionality?" → Query returns new location + related files
- "Why was Z archived?" → Query returns rationale from decision manifest

Memory enables AI agents to understand reorganization context during and after execution. Without memory, would need to manually maintain migration mappings or rely solely on git history (which AI finds difficult to navigate).

**Alternatives Considered:**
1. **Document-only tracking** - Rejected: Static docs not semantically queryable. Requires exact keyword matching.
2. **Git history only** - Rejected: Git commands hard for AI to construct and interpret. Doesn't capture rationale.
3. **Memory after moves** - Rejected: Can't capture before-state once files moved. Loses "was at" information.

**Phases affected:** All Phases 12-17 benefited from Phase 11 memory baseline.

---

### RAT-011: Dual Tagging Strategy for Snapshot Memories
**Used by:** DEC-017
**Summary:** Tags + metadata enables flexible querying

**Detail:**
Snapshot memories use:
1. **Simple tags:** phase, project, snapshot, memory, ta_lab2, file_list, directory_structure, conversation_context, commit_link
2. **Structured metadata:** {phase: "11-memory-preparation", snapshot_type: "directory_structure", path: "src/ta_lab2/features/"}

This enables both:
- Tag-based queries: "snapshot AND directory_structure" → all directory snapshots
- Post-search metadata filtering: Filter results by phase or path

Used `infer=False` in `batch_add_memories()` for performance (Phase 11 pattern). Disable LLM conflict detection when adding bulk snapshots - conflicts impossible when adding new memories.

**24-hour commit linkage window:** Link conversations to commits 0-24 hours after conversation timestamp (handles overnight work sessions).

**Alternatives Considered:**
1. **Tags only** - Rejected: Insufficient filtering precision. Can't filter by phase after initial query.
2. **Metadata only** - Rejected: Harder to query. Metadata queries less efficient than tag queries.
3. **Complex tag hierarchy** - Rejected: Maintenance burden. Tags should be simple enums, not hierarchical.

**Result:** 4/5 directories achieved 80% queryability threshold with weighted coverage calculation.

---

### RAT-012: 80% Directory Queryability Threshold with Weighted Coverage
**Used by:** DEC-018
**Summary:** Balance directory understanding with function detail

**Detail:**
Baseline established that **4/5 directories must be semantically queryable** (80% threshold). Weighted coverage calculation:
- **Inventory queries: 80% weight** - Directory structure understanding (critical for reorganization)
- **Function lookup: 20% weight** - Function-level detail (useful but not essential)

This prioritizes "What's in src/ta_lab2/features/?" over "What does calculate_ema() do?". Reorganization primarily about directories and modules, not individual functions.

**Alternatives Considered:**
1. **100% queryability** - Rejected: Unachievable with complex codebases. Data_Tools gaps acceptable per Claude discretion clause.
2. **Unweighted coverage** - Rejected: Over-values function lookup. Finding individual functions not reorganization blocker.
3. **No threshold** - Rejected: No quality target. Could declare success with 10% coverage.

**Result:** Phase 11-05 achieved weighted coverage above threshold, enabled Phase 12-17 reorganization with semantic memory support.

---

### RAT-013: Layer-Appropriate Module Placement
**Used by:** DEC-019, DEC-020
**Summary:** Enforce architectural layering with import-linter

**Detail:**
Import-linter enforces 4-tier layering hierarchy:
```
scripts (CLI, orchestration)
  ↓ can import
features (domain logic)
  ↓ can import
regimes (core infrastructure)
  ↓ can import
tools (pure utilities)
```

**Violations found:**
1. **tools→features:** ema_runners.py in tools/ imported from features/ → MOVED to scripts/emas/
2. **regimes<→pipelines:** Circular dependency with run_btc_pipeline.py → MOVED to scripts/pipelines/

**Resolution strategy:**
- Move violating modules to appropriate layer (not relax rules)
- Deprecation notices rather than re-exports (re-exports create new violations)
- CLI wrappers belong in scripts layer (orchestration, not core logic)

**Alternatives Considered:**
1. **Relax layering rules** - Rejected: Defeats purpose of architectural boundaries. Tech debt accumulates.
2. **Re-export with violations** - Rejected: Creates new import violations. Masks problem.
3. **Leave in wrong layer** - Rejected: Architectural violations propagate over time.

**Result:** Phase 17-08 achieved 0 violations across all 5 import-linter contracts.

---

### RAT-014: Pre-Commit Hooks with Archive Exclusion
**Used by:** DEC-021
**Summary:** Enforce quality without modifying historical artifacts

**Detail:**
Pre-commit hooks enforce quality standards:
- ruff lint (code quality)
- ruff-format (formatting)
- debug-statements (no pdb/breakpoint in commits)
- JSON validation for manifests

**Critical exclusion:** `.archive/` directory excluded from all hooks. Archived code is intentionally preserved as-is for historical reference, not subject to current quality standards.

Manifest JSON validation ensures archive metadata integrity without touching archived code content.

**Alternatives Considered:**
1. **Apply hooks to archives** - Rejected: Modifies historical artifacts. Checksums would change, breaking validation.
2. **No hooks** - Rejected: Loses quality enforcement on active codebase.
3. **Separate hook config for archives** - Rejected: Maintenance complexity. Simpler to exclude.

**Result:** Phase 17-04 documented 497 pre-existing Ruff errors for gap closure (not blocking current work).

---

### RAT-015: CI Workflow Separation: Critical vs Advisory Checks
**Used by:** DEC-022
**Summary:** Block on must-pass, warn on nice-to-have

**Detail:**
CI workflow structure:
1. **Critical jobs (no continue-on-error):**
   - import-validation-core: Core package imports must work
   - circular-dependencies: No circular imports allowed

2. **Advisory jobs (continue-on-error: true):**
   - organization-rules: Architectural suggestions
   - import-validation-optional: Optional dependency tests (can fail if dependency missing)

This distinguishes must-pass from nice-to-have validations. Core imports tested without orchestrator dependency, optional imports can fail non-blocking.

**Alternatives Considered:**
1. **All checks blocking** - Rejected: Optional dependencies (orchestrator) would fail CI when not installed.
2. **All checks advisory** - Rejected: Loses enforcement. Circular dependencies would slip through.
3. **No separation** - Rejected: Unclear which failures actually block merge.

**Result:** Clear CI signal - red = blocking issue, yellow = advisory warning.

---

## Decision Timeline

| Phase | Date | Decisions | Files Affected | Key Outcomes |
|-------|------|-----------|----------------|--------------|
| 11 | 2026-02-02 | DEC-016 to DEC-018 | Memory infrastructure | Mem0 baseline: 80% queryability, 24hr commit linkage |
| 12 | 2026-02-02 | DEC-003 to DEC-005 | Archive foundation | Category-first structure, $schema manifests, SHA256 checksums |
| 13 | 2026-02-02 | DEC-001 to DEC-002 | 62 documentation files | DOCX→Markdown conversion, originals archived |
| 14 | 2026-02-03 | DEC-006 to DEC-011 | 51 Data_Tools scripts | 40 migrated (6 categories), 11 archived (prototypes) |
| 15 | 2026-02-03 | DEC-012 to DEC-015 | 42 economic package files | fredtools2 + fedtools2 archived, ALTERNATIVES.md created |
| 16 | 2026-02-03 | (Not documented) | Repository cleanup | File deduplication, naming standardization |
| 17 | 2026-02-03 | DEC-019 to DEC-022 | Quality infrastructure | Layering fixes, pre-commit hooks, CI workflows |

## Decision Details

### DEC-001: Archive ProjectTT Documentation
**Phase:** 13 | **Type:** archive | **Rationale:** RAT-001
**Source:** ProjectTT/*.docx, ProjectTT/**/*.xlsx
**Destination:** .archive/documentation/2026-02-02/

62 files archived including:
- **Foundational documents:** CoreComponents.docx, KeyTerms.docx, ta_lab2_GenesisFiles_Summary.docx, Hysteresis.docx, RegimesInDepth.docx, TimeFrames.docx, feddata_inDepthSummary_20251110.docx
- **Feature documentation:** EMA (ema_multi_tf.docx, ema_multi_tf_cal.docx, ema_multi_tf_cal_anchor.docx, ema_overview.docx, ema_daily.docx), Bars (bar_creation.docx, bar_implementation.docx), Memory Model.docx
- **Planning documents:** 12wk_plan variations, status updates, next steps
- **Analysis spreadsheets:** EMA analysis, bar analysis, schema definitions, time tracking

All originals preserved with SHA256 checksums. Markdown conversions created in docs/ with YAML front matter.

**Related files:** See .archive/documentation/manifest.json for complete listing with checksums.

---

### DEC-002: Convert ProjectTT to Markdown
**Phase:** 13 | **Type:** convert | **Rationale:** RAT-001
**Source:** ProjectTT/*.docx
**Destination:** docs/*/*.md

Two-step conversion process:
1. **pypandoc:** DOCX → HTML (preserves document structure)
2. **markdownify:** HTML → Markdown (clean output)

Each converted file includes YAML front matter:
```yaml
---
title: Core Components
author: Adam Safi
created: 2024-11-08
modified: 2024-11-10
original_path: ProjectTT/Foundational/CoreComponents.docx
original_size_bytes: 18383
---
```

Media extraction: Images extracted to `docs/assets/{stem}/` for organized management.

**Content-based categorization:** Organized by type (Architecture/Features/Planning/Reference), not source location.

---

### DEC-003: Category-First Archive Structure
**Phase:** 12 | **Type:** create | **Rationale:** RAT-002
**Source:** N/A
**Destination:** .archive/{category}/YYYY-MM-DD/

Created archive structure:
- `.archive/documentation/` - Converted documents
- `.archive/data_tools/` - Data_Tools non-migrated scripts
- `.archive/external-packages/` - fredtools2, fedtools2
- `.archive/scripts/` - Old ta_lab2 scripts (Phase 16)

Each category supports multiple dates (YYYY-MM-DD format) for chronological tracking.

**Pattern adoption:** Used by Phases 13, 14, 15, 16 for consistent archiving.

---

### DEC-004: Manifest Per Category
**Phase:** 12 | **Type:** create | **Rationale:** RAT-003
**Source:** N/A
**Destination:** .archive/{category}/manifest.json

Manifest structure:
```json
{
  "$schema": "https://ta-lab2.example.com/schemas/archive-manifest-1.0.0.json",
  "version": "1.0.0",
  "created": "2026-02-02T21:41:22.129853+00:00",
  "category": "documentation",
  "files": [
    {
      "original_path": "ProjectTT/Foundational/CoreComponents.docx",
      "archive_path": ".archive/documentation/2026-02-02/CoreComponents.docx",
      "sha256_checksum": "481be902b1596053a3355ab8ccb533c5ba460e63bc821a75eb782fb209daf84b",
      "size_bytes": 18383,
      "action": "migrated",
      "timestamp": "2026-02-02T21:41:21.184647+00:00"
    }
  ]
}
```

**Validation:** JSON Schema Draft 2020-12 with required fields, checksum patterns, enum constraints.

---

### DEC-005: SHA256 Checksum Validation
**Phase:** 12 | **Type:** create | **Rationale:** RAT-004
**Source:** N/A
**Destination:** Manifest checksums

Validation hierarchy implemented:
1. **PRIMARY:** Checksum matching (file preserved anywhere with same SHA256)
2. **SECONDARY:** Count matching (same number of files)
3. **MEMORY:** Mem0 tracking (migration relationships)

Performance optimization: Python 3.11+ `hashlib.file_digest()` provides 2-10x faster SHA256 computation.

**Real-world result:** Phase 17-05 validated 9,620 Python files with zero data loss.

---

### DEC-006 to DEC-010: Data_Tools Migration
**Phase:** 14 | **Type:** migrate | **Rationale:** RAT-005

40 Data_Tools scripts migrated to ta_lab2 across 6 functional categories:

1. **export/ (6 scripts)** - ChatGPT/Claude export processing
   - chatgpt_pipeline.py, claude_pipeline.py, etc.

2. **analysis/ (8 scripts)** - AST and tree analysis
   - Tree_Outline.py, AST_Analyzer.py, generate_function_map.py, etc.

3. **memory/ (10 scripts)** - Embeddings and OpenAI integration
   - OpenAI_embedding.py, Mem0_Integration.py, Memory_Utilities.py, etc.

4. **processing/ (8 scripts)** - DataFrame utilities
   - DataFrame_Consolidation.py, Column_Mapper.py, etc.

5. **context/ (4 scripts)** - RAG and reasoning engines
   - create_reasoning_engine.py, Memory_Augmented_RAG.py, etc.

6. **generators/ (4 scripts)** - Report and finetuning data
   - Comprehensive_Report_Generator.py, Finetuning_Data_Generator.py, etc.

Each category has descriptive `__init__.py` documenting available scripts.

**Dependencies added:** openai, chromadb, mem0, google.auth, requests, pandas to pyproject.toml [tools] extra.

**Mem0 tracking:** Created `moved_to` relationships for all 40 migrated scripts with source/target paths and categories.

---

### DEC-011: Archive Data_Tools Prototypes
**Phase:** 14 | **Type:** archive | **Rationale:** RAT-006
**Source:** Data_Tools/*.py (prototypes/one-offs)
**Destination:** .archive/data_tools/2026-02-03/

13 files archived:
- **5 one-offs:** write_daily_emas.py, write_multi_tf_emas.py, write_ema_multi_tf_cal.py, upsert_new_emas_canUpdate.py, github instruction.py
- **8 prototypes:** chatgpt_script_look.py, chatgpt_script_keep_look*.py (numbered variations), chatgpt_pipeline.py, main.py, run_instantiate_final_memories_tests.py, test_code_search.py

Manifest documents each file with `action: "archived"` and `reason` explaining why (prototype/simple wrapper/test script).

**Archive relationships:** Created in Mem0 with archiving rationale for auditability.

---

### DEC-012 & DEC-013: Archive Economic Packages
**Phase:** 15 | **Type:** archive | **Rationale:** RAT-007
**Source:** fredtools2/**/* and fedtools2/**/*
**Destination:** .archive/external-packages/2026-02-03/

**fredtools2 (13 files archived):**
- PostgreSQL-backed FRED data ingestion with CLI
- 167 total lines
- Zero usage in ta_lab2

**fedtools2 (29 files archived):**
- ETL consolidation of Federal Reserve policy target datasets
- 659 total lines
- Zero usage in ta_lab2

Both packages documented with provenance:
- origin: Custom development
- author: Adam Safi
- purpose: FRED API wrapper / Fed data consolidation
- entry_point: CLI commands

**Ecosystem alternatives documented:**
- fredapi (replaces fredtools2): 1M+ downloads/month, active maintenance
- fedfred (replaces fredtools2): Specialized Fed data tooling

See .archive/external-packages/ALTERNATIVES.md for complete feature mapping and migration guidance.

---

### DEC-014: Economic Data Provider Pattern
**Phase:** 15 | **Type:** create | **Rationale:** RAT-008
**Source:** N/A
**Destination:** src/ta_lab2/integrations/economic/

Created `EconomicDataProvider` protocol with working fredapi implementation:

**Features:**
- Singleton rate limiter and cache (global across all instances)
- Per-provider circuit breaker (isolates failures per API key)
- Opt-out quality validation (validate=True default)
- Soft import pattern (graceful degradation when fredapi missing)

**Series coverage:** 17 series across 4 categories:
1. Fed policy rates (FEDFUNDS, DFF)
2. Treasury yields (DGS10, DGS2, DGS30, etc.)
3. Inflation indicators (CPIAUCSL, CPILFESL, T10YIE)
4. Employment data (UNRATE, PAYEMS)

**Configuration:** economic_data.env.example follows .env pattern for consistency.

---

### DEC-015: ALTERNATIVES.md for Archived Packages
**Phase:** 15 | **Type:** create | **Rationale:** RAT-009
**Source:** N/A
**Destination:** .archive/external-packages/ALTERNATIVES.md

Four-dimensional documentation:

1. **Feature Mapping**
   ```
   fredtools2.fred_api.get_series() → fredapi.Fred.get_series()
   fredtools2.cli.releases → fredapi.Fred.releases()
   ```

2. **API Comparison**
   Before:
   ```python
   from fredtools2.fred_api import get_series
   data = get_series('FEDFUNDS', start='2020-01-01')
   ```
   After:
   ```python
   from fredapi import Fred
   fred = Fred(api_key='...')
   data = fred.get_series('FEDFUNDS', start='2020-01-01')
   ```

3. **Migration Effort**
   - Simple series fetch: 5-10 minutes
   - CLI replacement: 30-60 minutes
   - PostgreSQL storage: Custom implementation needed (1-2 days)

4. **Ecosystem Maturity**
   - fredapi: 1M+ downloads/month, last update 2024
   - fredtools2: ~0 downloads, last update 2025

**Result:** Clear guidance for anyone needing FRED/Fed data integration.

---

### DEC-016: Memory-First Reorganization Tracking
**Phase:** 11 | **Type:** create | **Rationale:** RAT-010
**Source:** N/A
**Destination:** .planning/phases/{NN-name}/

Established memory-first reorganization pattern:
1. Phase 11: Memory Preparation (snapshot before moves)
2. Phases 12-17: Reorganization execution (with memory support)
3. Phase 18: Documentation (this phase)

Memory enables semantic queries during reorganization:
- "Where did Y.py go?" → Query memory for migration path
- "What replaced X?" → Query for related files + new location
- "Why archived?" → Query for rationale

Without memory, would need manual migration mappings or complex git history parsing (hard for AI).

---

### DEC-017: Project State Snapshot in Mem0
**Phase:** 11 | **Type:** create | **Rationale:** RAT-011
**Source:** N/A
**Destination:** Mem0 memories

Snapshot types created:
- File lists (all Python files per directory)
- Directory structures (tree output)
- Conversation context (linked to git commits)
- Commit links (24-hour window for overnight sessions)

Dual tagging strategy:
- Simple tags: phase, project, snapshot, memory, ta_lab2, file_list, directory_structure
- Structured metadata: {phase, snapshot_type, path}

Used `infer=False` in batch operations for performance (disables LLM conflict detection).

**Result:** 4/5 directories achieved 80% queryability threshold.

---

### DEC-018: 80% Queryability Threshold
**Phase:** 11 | **Type:** create | **Rationale:** RAT-012
**Source:** N/A
**Destination:** Coverage calculation

Weighted coverage formula:
```
Coverage = (0.80 × inventory_query_score) + (0.20 × function_lookup_score)
```

**Inventory queries (80% weight):**
- "What files in src/ta_lab2/features/?"
- "What subdirectories in tools/?"
- "List scripts in scripts/emas/"

**Function lookup (20% weight):**
- "Where is calculate_ema()?"
- "What does build_bar() do?"

Threshold: 4/5 directories must achieve 80%+ coverage.

**Result:** Phase 11-05 achieved threshold, enabled Phases 12-17 reorganization with memory support.

---

### DEC-019: Move ema_runners to Scripts Layer
**Phase:** 17 | **Type:** refactor | **Rationale:** RAT-013
**Source:** src/ta_lab2/tools/ema_runners.py
**Destination:** src/ta_lab2/scripts/emas/ema_runners.py

**Violation:** tools→features import (tools layer cannot import from features layer).

**Fix:** Move to scripts layer. Scripts CAN import features (scripts are orchestration, not pure utilities).

**Pattern:** Deprecation notice left in tools/ pointing to new location, no re-export (would violate layering).

---

### DEC-020: Move run_btc_pipeline to Scripts Layer
**Phase:** 17 | **Type:** refactor | **Rationale:** RAT-013
**Source:** src/ta_lab2/regimes/run_btc_pipeline.py
**Destination:** src/ta_lab2/scripts/pipelines/run_btc_pipeline.py

**Violation:** regimes<→pipelines circular dependency.

**Fix:** Move CLI orchestration to scripts layer (where orchestration belongs). Regimes contains core logic, not CLI wrappers.

**Result:** Phase 17-08 achieved 0 violations across all 5 import-linter contracts.

---

### DEC-021: Pre-Commit Hooks with Archive Exclusion
**Phase:** 17 | **Type:** create | **Rationale:** RAT-014
**Source:** N/A
**Destination:** .pre-commit-config.yaml

Hooks configured:
- ruff lint (code quality)
- ruff-format (formatting)
- trim trailing whitespace
- fix end of files
- check json/yaml/toml
- check for merge conflicts
- mixed line ending
- debug-statements (no pdb/breakpoint)
- validate manifest JSON

**Critical exclusion:** `.archive/` excluded from all hooks. Archived code preserved as-is.

**Result:** Phase 17-04 documented 497 pre-existing Ruff errors for gap closure (not blocking).

---

### DEC-022: CI Workflows for Import Validation
**Phase:** 17 | **Type:** create | **Rationale:** RAT-015
**Source:** N/A
**Destination:** .github/workflows/import-validation.yml

Workflow structure:
1. **Critical (blocking):**
   - import-validation-core: Core imports must work
   - circular-dependencies: No circular imports

2. **Advisory (non-blocking):**
   - organization-rules: Architectural suggestions
   - import-validation-optional: Optional dependencies (can fail)

**Test structure:**
- Core imports: 368 tests (without orchestrator)
- Optional imports: With full dependencies, continue-on-error: true

**Result:** Clear CI signal distinguishing blocking from advisory checks.

---

## Cross-References

### By Phase
- **Phase 11:** DEC-016 (memory tracking), DEC-017 (snapshots), DEC-018 (queryability)
- **Phase 12:** DEC-003 (archive structure), DEC-004 (manifests), DEC-005 (checksums)
- **Phase 13:** DEC-001 (archive docs), DEC-002 (convert DOCX)
- **Phase 14:** DEC-006 to DEC-011 (Data_Tools migration + archive)
- **Phase 15:** DEC-012 to DEC-015 (economic packages + alternatives)
- **Phase 17:** DEC-019 to DEC-022 (layering + quality infrastructure)

### By Category
- **Documentation:** DEC-001, DEC-002
- **Data_Tools:** DEC-006 to DEC-011
- **External Packages:** DEC-012, DEC-013, DEC-015
- **Infrastructure:** DEC-003, DEC-004, DEC-005, DEC-016, DEC-017, DEC-018, DEC-021, DEC-022
- **Economic Data:** DEC-014
- **Layering:** DEC-019, DEC-020

### By File Count Impact
1. DEC-001: 62 files (ProjectTT documentation archived)
2. DEC-006 to DEC-010: 40 files (Data_Tools migrated)
3. DEC-013: 29 files (fedtools2 archived)
4. DEC-012: 13 files (fredtools2 archived)
5. DEC-011: 13 files (Data_Tools prototypes archived)

**Total impact:** 155+ files reorganized across v0.5.0.

---

## Usage Examples

### Query by Decision ID
```bash
# Find all decisions about Data_Tools
jq '.decisions[] | select(.category == "data-tools")' docs/manifests/decisions.json

# Find rationale for decision
jq '.decisions[] | select(.id == "DEC-001") | .rationale_id' docs/manifests/decisions.json
jq '.rationales[] | select(.id == "RAT-001")' docs/manifests/decisions.json
```

### Query by Phase
```bash
# All Phase 14 decisions
jq '.decisions[] | select(.phase == 14)' docs/manifests/decisions.json

# Count decisions per phase
jq '[.decisions[] | .phase] | group_by(.) | map({phase: .[0], count: length})' docs/manifests/decisions.json
```

### Query by Type
```bash
# All archive decisions
jq '.decisions[] | select(.type == "archive")' docs/manifests/decisions.json

# All migrations
jq '.decisions[] | select(.type == "migrate")' docs/manifests/decisions.json
```

### Find Related Decisions
```bash
# Given decision ID, find related
DEC_ID="DEC-001"
jq --arg id "$DEC_ID" '.decisions[] | select(.id == $id) | .related_decisions[]' docs/manifests/decisions.json
```

---

*Generated: 2026-02-04*
*Schema version: 1.0.0*
*Decision count: 22*
*Rationale count: 15*
