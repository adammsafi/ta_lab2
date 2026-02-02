# Project Research Summary

**Project:** ta_lab2 v0.5.0 Ecosystem Reorganization
**Domain:** Python Monorepo Consolidation (Trading Platform)
**Researched:** 2026-02-02
**Confidence:** HIGH

## Executive Summary

This research addresses consolidating four external directories (ProjectTT documentation, Data_Tools scripts, fredtools2/fedtools2 economic data packages) into the existing ta_lab2 v0.4.0 quantitative trading platform without deletion, while preserving git history and ensuring import validation. The research reveals that modern Python monorepo consolidation (2026) follows well-established patterns: git-filter-repo for history-preserving merges, src-layout with editable installs, phased migration with validation gates, and workspace-aware dependency management.

The recommended approach is incremental migration over 2 weeks with 7 distinct phases: (1) archive management for backup artifacts, (2) documentation consolidation using centralized knowledge base patterns, (3) tools integration as internal utilities, (4) economic data packages as optional dependencies, (5) root cleanup, (6) structure documentation, and (7) final verification. Each phase has explicit validation gates to ensure no data loss, no broken imports, and full git history preservation. The critical constraint is the NO DELETION requirement, which transforms the challenge from "clean up" to "organize with traceability."

The key risk is silent import breakage from namespace collisions and circular dependencies. Prevention requires pre-move collision audits, explicit namespace hierarchies (ta_lab2.tools.data_tools vs ta_lab2.tools.fred_tools), and comprehensive import validation tests after each migration phase. Secondary risks include git history corruption from mixed refactoring (prevented by three-commit pattern: move, fix imports, refactor) and archive corruption from incomplete manifests (prevented by ARCHIVE_MANIFEST.md with every archived file indexed). With phased validation gates and proper tooling (git-filter-repo, pytest, ruff), this reorganization can achieve zero data loss while establishing maintainable structure for future growth.

## Key Findings

### Recommended Stack

The research identifies git-filter-repo as the industry standard for monorepo consolidation, 10-50x faster than deprecated git filter-branch, with Python-based history rewriting that preserves all commits. For file operations, pathlib and shutil from Python 3.12 stdlib provide cross-platform safety with atomic moves via staging directories. For import validation, the existing ta_lab2 toolchain (ruff 0.14.3, pytest 8.4.2, mypy 1.18.2) already provides everything needed. Optional tools include rope for AST-based import refactoring and pypandoc for Excel/Word to Markdown conversion.

**Core technologies:**
- **git-filter-repo 2.38+**: History-preserving repository merging — recommended by Git project itself, handles path rewriting with --to-subdirectory-filter
- **pathlib/shutil (stdlib)**: Safe file operations — built-in, cross-platform, use staging directory pattern for transaction-like guarantees
- **ruff 0.14.3**: Import validation and linting — already in ta_lab2, 1000x faster than pylint, catches broken import paths
- **pytest 8.4.2**: Package structure validation — already in ta_lab2, use --import-mode=importlib to test package imports as users experience them
- **rope 1.13+**: AST-based refactoring (optional) — for automated import path updates when consolidating packages into ta_lab2 namespace
- **pypandoc 1.14+ + pandoc 3.1+**: Document conversion (optional) — convert ProjectTT .docx files to Markdown for docs/ integration

**Critical pattern:** Three-commit workflow for file moves to preserve git history: (1) move file with zero code changes, (2) update import paths, (3) refactor code structure. Never mix move + refactor in single commit.

### Expected Features

The research identifies eight table stakes features for safe reorganization and eight differentiators that make reorganization successful rather than merely complete. The MVP (v0.5.0 milestone completion) requires all table stakes plus active/archive heuristics and root cleanup. Path update scripts, documentation integration, and automated verification are deferred to v0.5.x after core reorganization validates.

**Must have (table stakes):**
- **Git History Preservation**: Use git mv for all moves, never OS move — users expect full commit history, blame info, and tracking preserved
- **Archive Structure (.archive/)**: Timestamped subdirectories with manifest.json — users expect backup artifacts preserved somewhere visible, not deleted
- **Import Validation**: Pytest-based smoke tests for all ta_lab2 imports — users expect all Python imports to still work after reorganization
- **Zero Data Loss Guarantee**: Pre/post file count comparison with SHA256 checksums — users expect every file accounted for (active or archive)
- **Rollback Strategy**: Git branch + tag before reorganization with documented revert steps — users expect ability to undo if something breaks
- **File Inventory/Manifest**: YAML/JSON tracking {original_path, new_path, action, timestamp} — users expect clear record of what moved where
- **Path Update Scripts**: Automated find/replace for hardcoded paths in configs/docs with dry-run mode — users expect existing scripts to keep working
- **Dependency Graph Validation**: Ensure no broken internal imports or circular dependencies — users expect clean dependency structure

**Should have (competitive):**
- **Active vs Archive Heuristics**: Automatically classify files as active/archive based on patterns (e.g., *_refactored.py → archive) — differentiates successful cleanup from basic file moves
- **Documentation Integration Strategy**: Excel/Word docs converted to Markdown and integrated into docs/ — creates single source of truth instead of scattered documentation
- **Monorepo Structure**: Consolidate related projects into single logical repository with shared pyproject.toml — enables workspace-level dependency management
- **Incremental Migration**: Reorganize in phases (archive first, then consolidate, then cleanup) with validation between phases — reduces risk, matches ta_lab2 milestone approach
- **Automated Verification Suite**: CI tests that validate organization rules (no root clutter, archive integrity) — prevents future disorganization
- **Pre-commit Hooks**: Prevent future root clutter (no .py in root, no duplicate files) — maintains organization after initial cleanup

**Defer (v2+):**
- **Import Path Aliases**: Temporary shims during migration to maintain backward compatibility — only needed if external dependencies exist
- **Monorepo Tooling**: Advanced tools like Pants/Bazel — only needed if multi-package complexity grows beyond current scope
- **Dependency Graph Visualization**: Auto-generate import graphs — nice-to-have for documentation, not essential for functionality

**Anti-features (deliberately avoid):**
- Deletion of "old" files (breaks git blame/history, loses context) — use .archive/ instead
- Squash/rebase history during reorg (destroys provenance, makes rollback impossible) — accept history as-is
- Automated bulk renames (high risk of breaking imports, hard to review) — incremental renames with tests instead
- Convert all docs to Markdown (loses Excel formatting, destroys PowerPoint diagrams) — keep originals in .archive/, extract key content

### Architecture Approach

The recommended architecture preserves ta_lab2's existing src-layout structure while adding .archive/ for deprecated artifacts, lib/ for separate economic data packages, and consolidated docs/ with unified taxonomy. The key insight is that monorepo doesn't mean one package — fredtools2 and fedtools2 should remain separate packages in lib/ with path dependencies, not merged into ta_lab2 namespace. This maintains clear boundaries and enables independent versioning.

**Major components:**
1. **.archive/**: Historical artifacts preservation (code/bars/, code/emas/, docs/ProjectTT/) with 00-README.md index — preserves git history via git mv, maintains discoverability with comprehensive manifests
2. **docs/**: Unified documentation hub (domain/, architecture/, migration/, external/) — consolidates ProjectTT content into docs/domain/ (strategies/, indicators/, markets/), archives originals in .archive/docs/ProjectTT/original/
3. **src/ta_lab2/tools/data_tools/**: Migrated Data_Tools scripts (validators/, transforms/, exporters/) — refactored to use ta_lab2 namespace, exposed via __init__.py public API
4. **lib/**: Separate economic data packages (fredtools2/, fedtools2/) — workspace members with own pyproject.toml, installed as optional dependencies via pip install -e ".[economic-data]"
5. **Root workspace**: Unified pyproject.toml with [tool.uv.workspace] members — enables workspace-level lock file, manages path dependencies between packages

**Integration points:**
- Archive → Documentation: ProjectTT .docx → pandoc conversion → docs/domain/strategies/*.md, originals git mv to .archive/docs/ProjectTT/original/
- Data_Tools → ta_lab2.tools: Refactor imports from `from data_utils import X` → `from ta_lab2.tools.data_tools import X`, validate with pytest
- Economic packages → Optional dependency: Try/except imports with helpful error messages ("Install with: pip install -e '.[economic-data]'")

**Critical pattern:** Graceful optional dependencies — import external packages with try/except, provide helpful errors, don't force all users to install economic data dependencies when not needed.

### Critical Pitfalls

The research identifies seven critical pitfalls that cause reorganizations to fail. The top three risks for ta_lab2 are silent import breakage from namespace collisions (prevented by pre-move collision audit), circular import hell from cross-directory dependencies (prevented by pycycle analysis before moving), and git history corruption from mixed refactoring (prevented by three-commit pattern).

1. **Silent Import Breakage from Namespace Collisions**: When merging projects with overlapping module names (e.g., both Data_Tools/utils.py and ta_lab2/utils/), Python picks whichever appears first in sys.path, hiding the collision until runtime. **Prevention:** Audit for name collisions BEFORE moving files (create inventory of all module names), rename conflicting modules with domain prefixes (data_utils.py vs ta_utils.py), use explicit namespace packages (ta_lab2.tools.data_tools vs ta_lab2.tools.fred_tools), verify with import tracing (python -v -c "import module").

2. **Circular Import Hell from Cross-Directory Dependencies**: Moving interdependent code from separate projects into a single package exposes hidden circular dependencies that worked when separated by project boundaries. **Prevention:** Run static circular dependency detection BEFORE moving (use pycycle or pylint --disable=all --enable=cyclic-import), refactor shared code into separate module (ta_lab2.common with no imports from other modules), use TYPE_CHECKING pattern for type-only imports, lazy imports inside functions for non-critical imports.

3. **Git History Corruption from Mixed Refactoring**: Combining file moves with code refactoring in the same commit destroys Git's ability to track history — git log --follow loses the trail, git blame points to reorganization commit instead of original changes. **Prevention:** Follow three-commit pattern for each file move (Commit 1: move file with zero changes, Commit 2: update import paths, Commit 3: refactor code), use git mv for all operations, verify history preservation with git log --follow <new_path> after each move.

4. **The "Import Works But Tests Don't" Syndrome**: After reorganization, manual imports work but pytest discovery fails with ModuleNotFoundError because test discovery changes sys.path behavior differently than direct imports. **Prevention:** Mandate src/ layout pattern (keep src/ta_lab2/, never mix with flat ta_lab2/ at root), install in editable mode after every file move (pip install -e .), add __init__.py to ALL test directories, use absolute imports in tests (from ta_lab2.X import Y, not relative imports).

5. **Archive Corruption from Incomplete Preservation**: Files moved to .archive/ but metadata lost — .original files lack timestamps, *_refactored.py files archived without context, and the mapping from archive to current code is ambiguous. **Prevention:** Create ARCHIVE_MANIFEST.md before any moves with table of {archive_path, replacement_path, date, reason, notes}, archive directory structure mirrors source (.archive/2026-02-02-reorganization/Data_Tools/), include git commit hash in archive, automate archive validation (script to verify every archived file has manifest entry).

## Implications for Roadmap

Based on research, the recommended structure is 7 phases over 2 weeks, with each phase having explicit validation gates. The ordering follows dependency logic: establish archive pattern first (needed by all later phases), consolidate documentation early (defines domain structure), integrate tools (establishes import patterns), add economic packages last (least disruptive, optional dependencies).

### Phase 1: Archive Management (Week 1, Days 1-2)
**Rationale:** Must establish archive structure and preservation patterns before any other work. All later phases depend on .archive/ as destination for deprecated artifacts. Addresses Pitfall 5 (archive corruption) and establishes zero data loss guarantee.

**Delivers:** .archive/ directory structure (code/, docs/, configs/), 00-README.md index, migration manifest template

**Addresses:**
- Archive Structure (.archive/) from table stakes
- Zero Data Loss Guarantee from table stakes
- Active vs Archive Heuristics from differentiators

**Avoids:** Archive corruption from incomplete preservation (Pitfall 5)

**Validation gate:**
- All *.original files moved to .archive/code/ with git mv
- .archive/00-README.md comprehensively documents contents
- git log --follow works for archived files (history preserved)

**Research flag:** NO RESEARCH NEEDED — standard archival pattern, well-documented

### Phase 2: Documentation Consolidation (Week 1, Days 3-4)
**Rationale:** Must establish unified documentation taxonomy before integrating tools (which reference docs) and economic packages (which need integration guides). Converts ProjectTT Excel/Word docs to Markdown, defining domain knowledge structure that later phases reference.

**Delivers:** docs/domain/ (strategies/, indicators/, markets/), docs/architecture/, docs/migration/, .archive/docs/ProjectTT/original/ with 00-INDEX.md

**Uses:**
- pypandoc for Excel/Word to Markdown conversion
- Archive structure from Phase 1

**Implements:** Unified documentation hub (Architecture component 2)

**Addresses:**
- Documentation Integration Strategy from differentiators
- File Inventory/Manifest from table stakes

**Avoids:** Stale documentation from orphaned references (Pitfall 7)

**Validation gate:**
- All ProjectTT content accessible via docs/index.md
- Archive index maps old content to new locations
- Markdown files render correctly in docs/

**Research flag:** NEEDS RESEARCH IF ProjectTT contains specialized trading strategy documentation (may need domain expertise to categorize correctly)

### Phase 3: Tools Integration (Week 2, Days 1-3)
**Rationale:** Tools integration establishes import patterns and namespace conventions that Phase 4 (economic packages) will follow. Must come after Phase 2 because tools may reference documentation. Addresses Pitfall 1 (namespace collisions) and Pitfall 2 (circular imports) through explicit audit and validation.

**Delivers:** src/ta_lab2/tools/data_tools/ (validators/, transforms/, exporters/), import validation tests, migration documentation

**Uses:**
- rope for AST-based import refactoring (if needed)
- ruff and pytest for import validation
- Archive structure from Phase 1

**Implements:** data_tools component (Architecture component 3)

**Addresses:**
- Import Validation from table stakes
- Dependency Graph Validation from table stakes
- Path Update Scripts from table stakes

**Avoids:**
- Silent import breakage from namespace collisions (Pitfall 1)
- Circular import hell (Pitfall 2)
- Import works but tests don't syndrome (Pitfall 4)

**Validation gate:**
- All Data_Tools scripts importable via ta_lab2.tools.data_tools
- Import tests pass (100% coverage of public API)
- No hardcoded paths remain
- pycycle returns zero circular imports

**Research flag:** NEEDS RESEARCH — Data_Tools content unknown, may have undocumented dependencies or specialized utilities requiring investigation

### Phase 4: Economic Data Packages (Week 2, Days 4-5)
**Rationale:** Economic packages are optional dependencies, least disruptive to core ta_lab2 functionality. Must come after Phase 3 because integration examples in ta_lab2/scripts/etl/ follow tools integration patterns. Uses workspace structure to maintain separate package boundaries.

**Delivers:** lib/fredtools2/, lib/fedtools2/, root pyproject.toml with workspace config, ta_lab2 optional-dependencies, integration examples with graceful degradation

**Uses:**
- git-filter-repo for history-preserving moves (if fredtools2/fedtools2 have separate repos)
- Workspace-aware dependency management

**Implements:** lib/ component (Architecture component 4), optional dependency pattern (Architecture critical pattern)

**Addresses:**
- Git History Preservation from table stakes
- Monorepo Structure from differentiators
- Incremental Migration from differentiators

**Avoids:** Implicit dependency breakage from environment isolation (Pitfall 6)

**Validation gate:**
- fredtools2/fedtools2 installable via pip install -e ./lib/*
- ta_lab2 imports work with and without economic-data extra
- Helpful error message when not installed
- No dependency version conflicts (pip check passes)

**Research flag:** NO RESEARCH NEEDED IF fredtools2/fedtools2 are standard FRED API wrappers; NEEDS RESEARCH IF they contain custom economic models or proprietary data sources

### Phase 5: Root Cleanup (Week 2, Day 5)
**Rationale:** Root cleanup depends on all previous phases — can't move root scripts until we know whether they belong in tools/, docs/, or .archive/. Final step of physical reorganization before documentation and verification.

**Delivers:** Clean root directory (only src/, lib/, docs/, tests/, .planning/, config files), remaining clutter archived with manifest updates

**Uses:**
- Archive structure from Phase 1
- Active vs Archive Heuristics from Phase 1

**Addresses:**
- Root Directory Cleanup from table stakes
- Active vs Archive Heuristics from differentiators

**Validation gate:**
- Root directory contains only essential files
- All clutter archived with git history (git log --follow works)
- .archive/00-README.md updated with new entries

**Research flag:** NO RESEARCH NEEDED — straightforward cleanup based on established patterns

### Phase 6: Structure Documentation (Week 2, Day 5)
**Rationale:** Must document final structure after all physical changes complete. Enables future developers to understand reorganization decisions. Creates migration guide for users affected by import path changes.

**Delivers:** .planning/codebase/STRUCTURE.md (updated), docs/migration/v0.5-reorganization.md, README.md with ecosystem structure

**Addresses:**
- Migration Documentation from differentiators
- Path Update Scripts completion (documentation of changes)

**Avoids:** Stale documentation from orphaned references (Pitfall 7 — final mitigation)

**Validation gate:**
- STRUCTURE.md reflects post-reorganization state
- Migration guide explains all changes with old→new path mappings
- README.md updated with new structure

**Research flag:** NO RESEARCH NEEDED — documentation of completed work

### Phase 7: Final Verification (Week 2, Day 5)
**Rationale:** End-to-end validation ensures nothing was missed in phased migration. Fresh clone test validates that all changes work for new users, not just on developer's machine with cached state.

**Delivers:** Validated v0.5.0 release, git tag, verified import smoke tests, operational pipeline verification

**Addresses:**
- Rollback Strategy completion (tag before release)
- Import Validation final check
- Zero Data Loss final confirmation

**Avoids:** All pitfalls (final verification)

**Validation gate:**
- Fresh install works (all imports resolve)
- All tests pass (no import errors)
- Daily refresh pipeline runs successfully
- Documentation builds without errors
- pycycle confirms zero circular imports
- Archive manifest complete (every archived file indexed)

**Research flag:** NO RESEARCH NEEDED — verification of completed work

### Phase Ordering Rationale

The seven-phase structure follows these dependency chains:

1. **Archive first (Phase 1)**: All other phases need .archive/ as destination for deprecated artifacts
2. **Docs early (Phase 2)**: Tools and packages need documentation structure for integration guides
3. **Tools before packages (Phase 3 → 4)**: Tools integration establishes namespace patterns that packages follow
4. **Cleanup after integration (Phase 5)**: Can't categorize root files until we know where they belong
5. **Document after completion (Phase 6)**: Structure documentation requires final state to document
6. **Verify last (Phase 7)**: End-to-end validation requires all changes complete

This ordering minimizes rework by establishing patterns early (archive, docs, namespace) and deferring decisions (root cleanup) until context is available. Each phase has clear validation gates enabling incremental progress with rollback points.

### Research Flags

**Phases likely needing deeper research during planning:**
- **Phase 2 (Documentation Consolidation)**: If ProjectTT contains specialized trading strategy documentation or proprietary domain knowledge, may need domain expertise to categorize correctly. Standard docs consolidation patterns apply, but content categorization requires understanding.
- **Phase 3 (Tools Integration)**: Data_Tools content unknown — may contain undocumented dependencies, specialized utilities, or hardcoded environment assumptions that require investigation before migration can proceed.
- **Phase 4 (Economic Data Packages)**: If fredtools2/fedtools2 contain custom economic models or proprietary data sources beyond standard FRED API wrapping, requires research into integration patterns.

**Phases with standard patterns (skip research-phase):**
- **Phase 1 (Archive Management)**: Standard archival pattern with git mv, well-documented in sources
- **Phase 5 (Root Cleanup)**: Straightforward cleanup based on established patterns from Phase 1
- **Phase 6 (Structure Documentation)**: Documentation of completed work, no new patterns
- **Phase 7 (Final Verification)**: Verification of completed work, standard testing patterns

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All recommended tools verified with official documentation, compatibility confirmed with existing ta_lab2 setup (Git 2.47.1, Python 3.12.7, pytest 8.4.2, ruff 0.14.3) |
| Features | HIGH | Feature patterns well-established in Python monorepo consolidation literature, verified with multiple sources (2026 Python packaging guide, Real Python, Hitchhiker's Guide) |
| Architecture | HIGH | Architecture patterns verified with production monorepo examples (Opendoor, Tweag, Earthly), src-layout confirmed as 2026 best practice |
| Pitfalls | HIGH | Pitfalls verified with official sources (pytest docs, Git documentation, Python Packaging User Guide) and observed in ta_lab2 codebase (*.original files demonstrate archive management challenges) |

**Overall confidence:** HIGH

The research is based on authoritative 2026 sources (official Python Packaging User Guide, pytest documentation, Git official docs), multiple production monorepo case studies (Opendoor, Tweag), and verification against the actual ta_lab2 codebase (Git 2.47.1, Python 3.12.7, existing tool versions confirmed). All recommended tools are actively maintained with 2026 compatibility verified.

### Gaps to Address

While overall confidence is high, three specific gaps need attention during planning and execution:

- **Data_Tools content unknown**: Cannot assess migration complexity without inventorying Data_Tools scripts. **Handle during Phase 3 planning:** Create comprehensive inventory of Data_Tools directory contents, map dependencies, identify overlaps with existing ta_lab2.scripts/ before beginning migration. May discover scripts that belong in .archive/ rather than tools/.

- **ProjectTT documentation format and sensitivity**: Unknown whether ProjectTT contains sensitive information (API keys, proprietary strategies) or relies on Excel as computation tool vs documentation artifact. **Handle during Phase 2 planning:** Audit ProjectTT content before conversion, identify any sensitive information for redaction, determine which Excel sheets are computational tools (keep as .xlsx in archive) vs documentation (convert to Markdown).

- **fredtools2/fedtools2 relationship unclear**: Research assumes fredtools2 and fedtools2 are separate packages, but actual code overlap unknown — may be candidates for merging if >30% shared code. **Handle during Phase 4 planning:** Assess code overlap using decision matrix (>30% overlap → merge into fredtools2.fedfunds submodule, <30% → keep separate), check if they share dependencies or have independent release cycles.

These gaps are intentionally deferred to phase planning rather than upfront research because they require direct code inspection (Data_Tools, fredtools2/fedtools2) or content audit (ProjectTT), which is more efficiently done during execution when context is fresh.

## Sources

### Primary (HIGH confidence)
- [Git Official Documentation - git-archive](https://git-scm.com/docs/git-archive) — Git archive limitations, bundle superiority for history preservation
- [Python Official Docs - pathlib](https://docs.python.org/3/library/pathlib.html) — pathlib.Path.resolve() for absolute paths
- [Python Official Docs - shutil](https://docs.python.org/3/library/shutil.html) — shutil.move() and staging directory pattern
- [pytest Official Docs - Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html) — src-layout and importlib mode
- [Python Packaging User Guide - src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) — src-layout rationale and best practices
- [GitHub - newren/git-filter-repo](https://github.com/newren/git-filter-repo) — Official git-filter-repo repository and documentation
- [Ruff Official Docs](https://docs.astral.sh/ruff/) — Import validation and linting patterns

### Secondary (MEDIUM confidence)
- [The State of Python Packaging in 2026](https://learn.repoforge.io/posts/the-state-of-python-packaging-in-2026/) — Authoritative guide on 2026 Python tooling consolidation
- [Git Move Files: History Preservation in 2026](https://thelinuxcode.com/git-move-files-practical-renames-refactors-and-history-preservation-in-2026/) — Three-commit pattern and similarity threshold tuning
- [Python Monorepo: an Example. Part 1: Structure and Tooling - Tweag](https://www.tweag.io/blog/2023-04-04-python-monorepo-1/) — Production monorepo structure and workspace patterns
- [Our Python Monorepo - Opendoor Labs](https://medium.com/opendoor-labs/our-python-monorepo-d34028f2b6fa) — Real-world monorepo experience and lessons learned
- [Building a Monorepo with Python - Earthly Blog](https://earthly.dev/blog/python-monorepo/) — Workspace-level dependency management
- [Structuring Your Project - Hitchhiker's Guide to Python](https://docs.python-guide.org/writing/structure/) — Community standard patterns for project organization
- [Best Practices in Structuring Python Projects - Dagster](https://dagster.io/blog/python-project-best-practices) — Modern Python project structure patterns
- [Pycycle: Find and fix circular imports](https://github.com/bndr/pycycle) — Static circular dependency detection tool
- [Python Circular Import: Causes, Fixes, Best Practices - DataCamp](https://www.datacamp.com/tutorial/python-circular-import) — TYPE_CHECKING pattern and lazy imports
- [Merging Multiple Git Repositories with Git-Filter-Repo](https://medium.com/@umerfarooq.dev/merging-multiple-git-repositories-into-a-mono-repository-with-git-filter-repo-e3a6722e824d) — Monorepo consolidation workflow

### Tertiary (LOW confidence - needs validation)
- [Complete Data Migration Checklist for 2026](https://rivery.io/data-learning-center/complete-data-migration-checklist/) — Validation and rollback patterns (general data migration, adapted to code)
- [7 Document Management Best Practices in 2026](https://thedigitalprojectmanager.com/project-management/document-management-best-practices/) — Consolidation strategies (adapted from general docs to code docs)

---
*Research completed: 2026-02-02*
*Ready for roadmap: yes*
