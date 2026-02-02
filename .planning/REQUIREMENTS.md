# ta_lab2 v0.5.0 Requirements

**Version:** 0.5.0 Ecosystem Reorganization
**Created:** 2026-02-02
**Status:** Active

## Summary

- **Total Requirements:** 32
- **Complete:** 0
- **Pending:** 32
- **Coverage:** 32/32 mapped to phases (100%)

## Memory Integration Requirements (MEMO-10 to MEMO-18) - CRITICAL BLOCKER

**Must complete BEFORE any file reorganization begins**

- [ ] **MEMO-10**: Update existing memory with v0.4.0 completion context
  - Extract conversations from recent Claude Code sessions
  - Add memories about Phase 10 completion, v0.4.0 release validation
  - Ensure memory system knows current project state

- [ ] **MEMO-11**: Pre-reorganization memory capture for ta_lab2
  - Capture current state of ta_lab2 codebase (file structure, functions, dependencies)
  - Create baseline memory snapshot before any moves
  - Tag with `pre_reorg_v0.5.0` metadata

- [ ] **MEMO-12**: Pre-integration memory capture for external directories
  - Index Data_Tools scripts (functions, dependencies, usage)
  - Index ProjectTT documentation (content, relationships)
  - Index fredtools2/fedtools2 packages (APIs, functions, dependencies)
  - Tag with `pre_integration_v0.5.0` metadata

- [ ] **MEMO-13**: File-level memory updates during reorganization
  - Update memory when individual files move (old path -> new path)
  - Create `moved_to` relationship links
  - Mark old location memories with `deprecated_since` timestamp

- [ ] **MEMO-14**: Phase-level memory snapshots
  - Create memory snapshot at end of each reorganization phase
  - Tag with phase number and completion timestamp
  - Enables phase-level rollback if needed

- [ ] **MEMO-15**: Function-level memory granularity
  - Extract function definitions via AST analysis
  - Create memories for each significant function (name, purpose, parameters, usage)
  - Support queries like "What does function X do?" and "What uses function X?"

- [ ] **MEMO-16**: Memory linking with all relationship types
  - `contains`: file contains function
  - `calls`: function A calls function B
  - `imports`: file imports module
  - `similar_to`: function A is similar to function B (for duplicate detection)
  - `moved_to` / `replaced_by`: tracking reorganization history

- [ ] **MEMO-17**: Duplicate function detection with thresholds
  - 95%+ similarity = exact duplicates (auto-flag for consolidation)
  - 85-95% similarity = very similar (flag for review/refactoring)
  - 70-85% similarity = somewhat similar (informational only)
  - Enable queries to find duplicate/similar functions across files

- [ ] **MEMO-18**: Post-reorganization memory validation
  - Verify all files have memory entries
  - Verify all relationships are correctly linked
  - Validate memory graph completeness (no orphaned memories)
  - Test query capabilities (function lookup, cross-reference, edit impact)

## Archive Management Requirements (ARCH-01 to ARCH-04)

- [ ] **ARCH-01**: Create .archive/ directory structure
  - Timestamped subdirectories (.archive/YYYY-MM-DD/category/)
  - Categories: backup_artifacts, root_files, deprecated_scripts, documentation

- [ ] **ARCH-02**: Git history preservation
  - Use `git mv` for all file moves (preserves git blame/log)
  - Verify `git log --follow` works for moved files
  - Never use OS-level moves or deletions

- [ ] **ARCH-03**: File inventory manifest system
  - Create manifest.json for each archive operation
  - Track: original_path, new_path (or archive_path), action, timestamp, sha256_checksum
  - Enable queries: "Where did file X go?" and "What files were archived in phase Y?"

- [ ] **ARCH-04**: Zero data loss guarantee
  - Pre-reorganization file count and size
  - Post-reorganization file count and size (active + archive)
  - Validation: counts match, no files disappeared
  - SHA256 checksums for critical files

## Documentation Consolidation Requirements (DOC-01 to DOC-03)

- [ ] **DOC-01**: Convert ProjectTT documentation to Markdown
  - Use pypandoc/pandoc for .docx -> .md conversion
  - Handle Excel files: extract key tables/content, preserve originals
  - Maintain formatting where possible (tables, lists, code blocks)

- [ ] **DOC-02**: Integrate documentation into unified docs/ structure
  - Organize by category: docs/design/, docs/analysis/, docs/research/
  - Create docs/index.md as documentation home page
  - Update cross-references between docs

- [ ] **DOC-03**: Preserve originals in archive
  - Move original Excel/Word files to .archive/documentation/
  - Link from Markdown docs to archived originals
  - Manifest tracking for all documentation conversions

## Tools Integration Requirements (TOOL-01 to TOOL-03)

- [ ] **TOOL-01**: Migrate Data_Tools scripts to ta_lab2/tools/
  - Create ta_lab2/tools/data_tools/ subdirectory
  - Move scripts with `git mv` (preserve history)
  - Organize by function: etl/, analysis/, utilities/

- [ ] **TOOL-02**: Update import paths
  - Update imports within migrated scripts (if needed)
  - Use rope or manual updates for import path changes
  - Verify no hardcoded paths remain

- [ ] **TOOL-03**: Validate imports work post-migration
  - Pytest smoke tests for all migrated scripts
  - Verify scripts can import from ta_lab2 modules
  - Test script execution (if scripts have main entry points)

## Economic Data Strategy Requirements (ECON-01 to ECON-03)

- [ ] **ECON-01**: Evaluate fredtools2 and fedtools2 packages
  - Inventory functions and APIs in each package
  - Assess code overlap between the two packages
  - Determine value for ta_lab2 (FRED data integration strategy)

- [ ] **ECON-02**: Integration decision and implementation
  - Decision matrix: merge into ta_lab2, keep as optional deps, or archive
  - If integrating: move to ta_lab2/lib/ as optional dependencies
  - If archiving: move to .archive/economic_data/ with documentation

- [ ] **ECON-03**: Optional dependency setup (if integrating)
  - Add to pyproject.toml as optional dependency group: `[economic-data]`
  - Update installation docs: `pip install ta_lab2[economic-data]`
  - Graceful degradation if not installed

## Repository Cleanup Requirements (CLEAN-01 to CLEAN-04)

- [ ] **CLEAN-01**: Clean root directory clutter
  - Archive temp files, *_refactored.py, *.original files
  - Archive audit CSVs and migration docs
  - Archive old config files (openai_config_2.env, etc.)
  - Target: minimal root directory (README, pyproject.toml, core configs only)

- [ ] **CLEAN-02**: Organize scattered documentation
  - Move loose .md files to appropriate docs/ subdirectories
  - Consolidate duplicate docs (archive older versions)
  - Update README to link to docs/ structure

- [ ] **CLEAN-03**: Remove/archive duplicate files
  - Identify exact duplicates via SHA256 checksums
  - Archive duplicates (keep one active copy)
  - Document which copy was kept and why

- [ ] **CLEAN-04**: Investigate duplicate/similar functions for refactoring
  - Use MEMO-17 duplicate detection (85%+ similarity threshold)
  - Review flagged function pairs for consolidation opportunities
  - Create shared utility functions if beneficial
  - Document refactoring decisions (consolidate vs keep separate)

## Verification & Validation Requirements (VAL-01 to VAL-04)

- [ ] **VAL-01**: Import validation suite
  - Pytest tests that import all modules after reorganization
  - Verify no ImportError or ModuleNotFoundError
  - Test both absolute and relative imports

- [ ] **VAL-02**: Dependency graph validation
  - Use tools like pydeps or import-linter
  - Detect circular dependencies introduced during reorganization
  - Visualize dependency graph for review

- [ ] **VAL-03**: Automated verification tests in CI
  - Tests that validate organization rules (no .py in root, no clutter)
  - Tests that validate archive integrity (manifest matches files)
  - Tests that validate memory graph completeness (MEMO-18)
  - Fail CI if organization degrades

- [ ] **VAL-04**: Pre-commit hooks to prevent future disorganization
  - Hook: no .py files in root directory (except setup.py if needed)
  - Hook: no duplicate files (check SHA256 on commit)
  - Hook: enforce file naming conventions
  - Hook: validate imports on commit (ruff/mypy)

## Structure Documentation Requirements (STRUCT-01 to STRUCT-03)

- [ ] **STRUCT-01**: Create docs/REORGANIZATION.md guide
  - Document reorganization decisions (what moved where and why)
  - Explain new directory structure with examples
  - Provide migration guide for developers (how to find moved files)
  - Include before/after directory tree diagrams

- [ ] **STRUCT-02**: Update README with new ecosystem structure
  - Update project structure section
  - Add links to major components (tools/, lib/, docs/)
  - Explain relationship to external directories (archived references)

- [ ] **STRUCT-03**: Document migration decisions in manifest
  - Structured manifest format (YAML or JSON)
  - Track rationale for each major decision
  - Enable future audits: "Why was file X archived instead of migrated?"

## Out of Scope (Explicitly Deferred)

- **Deletion of any files** - Everything preserved via git history + .archive/
- **Squash/rebase of commit history** - Accept history as-is, use conventional commits going forward
- **Automated bulk renames beyond imports** - Only update import paths, keep original file/function names unless manually decided
- **Conversion of all docs to Markdown** - Only convert high-value ProjectTT content, keep originals for reference
- **Live trading impact** - Reorganization is development-time only, no impact on trading systems

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| MEMO-10 | Phase 11 (Memory Preparation) | Pending |
| MEMO-11 | Phase 11 (Memory Preparation) | Pending |
| MEMO-12 | Phase 11 (Memory Preparation) | Pending |
| ARCH-01 | Phase 12 (Archive Foundation) | Pending |
| ARCH-02 | Phase 12 (Archive Foundation) | Pending |
| ARCH-03 | Phase 12 (Archive Foundation) | Pending |
| ARCH-04 | Phase 12 (Archive Foundation) | Pending |
| DOC-01 | Phase 13 (Documentation Consolidation) | Pending |
| DOC-02 | Phase 13 (Documentation Consolidation) | Pending |
| DOC-03 | Phase 13 (Documentation Consolidation) | Pending |
| MEMO-13 | Phases 13-16 (During Reorganization) | Pending |
| MEMO-14 | Phases 13-16 (During Reorganization) | Pending |
| TOOL-01 | Phase 14 (Tools Integration) | Pending |
| TOOL-02 | Phase 14 (Tools Integration) | Pending |
| TOOL-03 | Phase 14 (Tools Integration) | Pending |
| ECON-01 | Phase 15 (Economic Data Strategy) | Pending |
| ECON-02 | Phase 15 (Economic Data Strategy) | Pending |
| ECON-03 | Phase 15 (Economic Data Strategy) | Pending |
| CLEAN-01 | Phase 16 (Repository Cleanup) | Pending |
| CLEAN-02 | Phase 16 (Repository Cleanup) | Pending |
| CLEAN-03 | Phase 16 (Repository Cleanup) | Pending |
| CLEAN-04 | Phase 16 (Repository Cleanup) | Pending |
| VAL-01 | Phase 17 (Verification & Validation) | Pending |
| VAL-02 | Phase 17 (Verification & Validation) | Pending |
| VAL-03 | Phase 17 (Verification & Validation) | Pending |
| VAL-04 | Phase 17 (Verification & Validation) | Pending |
| STRUCT-01 | Phase 18 (Structure Documentation) | Pending |
| STRUCT-02 | Phase 18 (Structure Documentation) | Pending |
| STRUCT-03 | Phase 18 (Structure Documentation) | Pending |
| MEMO-15 | Phase 19 (Memory Validation & Release) | Pending |
| MEMO-16 | Phase 19 (Memory Validation & Release) | Pending |
| MEMO-17 | Phase 19 (Memory Validation & Release) | Pending |
| MEMO-18 | Phase 19 (Memory Validation & Release) | Pending |

---
*Created: 2026-02-02*
*Last updated: 2026-02-02 (traceability section added)*
