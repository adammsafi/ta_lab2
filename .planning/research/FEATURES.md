# Feature Research: Ecosystem Reorganization

**Domain:** Python Project Consolidation and Repository Cleanup
**Researched:** 2026-02-02
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Must Have for Safe Reorganization)

Features that users (developers/maintainers) expect in any repository reorganization. Missing these = reorganization feels dangerous or incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Git History Preservation** | Reorganization must not lose commit history, blame info, or tracking | MEDIUM | Use `git mv` for moves (not OS move), preserve .git directory fully |
| **Archive Structure (.archive/)** | Backup artifacts must be preserved somewhere visible, not deleted | LOW | Standard pattern: .archive/YYYY-MM-DD/original-path/ with manifest |
| **Import Validation** | After reorganization, all Python imports must still work | MEDIUM | Pytest-based import smoke tests, validate circular dependencies |
| **Rollback Strategy** | Must be able to undo reorganization if something breaks | LOW | Git branch + tag before reorganization, documented revert steps |
| **File Inventory/Manifest** | Track what moved where, what was archived, nothing disappeared | LOW | YAML/JSON manifest: {original_path, new_path, action, timestamp} |
| **Zero Data Loss Guarantee** | Every file accounted for (active or archive), auditable | LOW | Pre/post file count comparison, SHA256 checksums for critical files |
| **Path Update Scripts** | Automated updates for hardcoded paths in configs/docs | MEDIUM | Regex-based find/replace with dry-run mode, manual review of changes |
| **Dependency Graph Validation** | Ensure no broken internal imports or circular dependencies | MEDIUM | Use tools like pydeps, import-linter, or custom AST analysis |

### Differentiators (What Makes Reorganization Successful)

Features that set a successful reorganization apart from a basic cleanup. Not strictly required, but provide significant value.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Active vs Archive Heuristics** | Automatically classify files as active/archive based on patterns | MEDIUM | Rules: *_refactored.py → archive, *.original → archive, unused test files → archive |
| **Documentation Integration Strategy** | Excel/Word docs converted to markdown and integrated into docs/ | HIGH | Requires manual conversion + validation, but creates single source of truth |
| **Monorepo Structure** | Consolidate multiple related projects into single logical repository | MEDIUM | Standard Python monorepo: projects/, lib/, tools/ with shared pyproject.toml |
| **Incremental Migration** | Reorganize in phases (archive first, then consolidate, then cleanup) | LOW | Reduces risk, allows validation between phases, matches ta_lab2 milestone approach |
| **Import Path Aliases** | Temporary shims during migration to maintain backward compatibility | MEDIUM | __init__.py imports or warnings for deprecated paths during transition |
| **Automated Verification Suite** | CI tests that validate organization rules (no root clutter, archive integrity) | MEDIUM | Pytest fixtures that fail if new clutter added, archive tampered with, etc. |
| **Pre-commit Hooks** | Prevent future disorganization (no .py in root, no duplicate files) | LOW | Pre-commit config with file placement rules, naming conventions |
| **Migration Documentation** | Clear record of what changed, why, and how to adapt | LOW | docs/REORGANIZATION.md with before/after structure, decision rationale |

### Anti-Features (Deliberately Avoid These)

Features that seem good but create problems during repository reorganization.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Deletion of "Old" Files** | "Clean slate" mentality, reduce repo size | Irreversible, breaks git blame/history, loses context for future debugging | Move to .archive/ with timestamp, keep in git history |
| **Squash/Rebase History** | "Clean up messy commit history" during reorg | Destroys provenance, makes rollback impossible, breaks existing clones | Accept history as-is, use conventional commits going forward |
| **Automated Bulk Renames** | "Fix all naming inconsistencies at once" | High risk of breaking imports, hard to review, creates massive diff | Incremental renames with tests, one subsystem at a time |
| **Force Push to Main** | "Need to clean up after reorg mistakes" | Breaks collaborators, loses tags/branches, violates git safety | Use revert commits, document mistakes, learn for next reorg |
| **Aggressive .gitignore Updates** | "Clean up tracked files that should be ignored" | Can accidentally hide files that should be tracked, breaks reproducibility | Audit .gitignore carefully, use git check-ignore for testing, commit removals explicitly |
| **Merge Unrelated Projects** | "Everything in one repo is easier" | Creates bloated repo, slow operations, unclear boundaries | Only consolidate truly related projects, use git submodules for loose coupling |
| **Convert All Docs to Markdown** | "Single format is cleaner" | Loses formatting/tables from Excel, destroys PowerPoint diagrams | Keep originals in .archive/, extract key content to markdown, link to originals |
| **Delete Test/Backup Directories** | "We have git, don't need backups" | Some backups have metadata (like audit results) not in main code | Archive test/backup dirs with clear naming, preserve audit trails |

## Feature Dependencies

```
[Git History Preservation]
    └──requires──> [File Inventory/Manifest]
                       └──requires──> [Zero Data Loss Guarantee]

[Import Validation]
    └──requires──> [Path Update Scripts]
    └──requires──> [Dependency Graph Validation]

[Archive Structure]
    └──enables──> [Active vs Archive Heuristics]
    └──enables──> [Zero Data Loss Guarantee]

[Documentation Integration]
    └──requires──> [Archive Structure] (keep originals)
    └──enhances──> [Migration Documentation]

[Automated Verification Suite]
    └──requires──> [Import Validation]
    └──requires──> [File Inventory/Manifest]

[Monorepo Structure] ──conflicts──> [Multiple Separate Repos]
[Incremental Migration] ──enables──> [Rollback Strategy]
```

### Dependency Notes

- **Git History Preservation requires File Inventory**: Can't prove history preservation without tracking what moved where
- **Import Validation requires Path Updates**: Can't validate imports until paths are updated in code
- **Archive Structure enables Active/Archive Heuristics**: Need destination for archived files before classifying
- **Documentation Integration requires Archive**: Original Excel/Word files must be preserved even after markdown conversion
- **Automated Verification requires both Import Validation and Manifest**: Tests need to validate both imports work and nothing was lost
- **Monorepo conflicts with Multiple Repos**: Architectural decision, ta_lab2 is staying monorepo
- **Incremental Migration enables Rollback**: Smaller changes = easier to revert if phase fails

## MVP Definition (v0.5.0 Ecosystem Reorganization)

### Launch With (Milestone Completion)

Minimum viable reorganization - what's needed to achieve "consolidation without data loss."

- [x] **Archive Structure** - .archive/ directory with timestamped subdirs, manifest.json
- [x] **File Inventory** - Complete manifest of all moves/archives with checksums
- [x] **Git History Preservation** - Use git mv for all moves, verify blame/log still work
- [x] **Zero Data Loss Guarantee** - Pre/post file counts match, all files accounted for
- [x] **Import Validation** - Pytest suite validates all ta_lab2 imports work
- [x] **Rollback Strategy** - Tag before reorg, document revert procedure
- [x] **Active vs Archive Heuristics** - Rules for *_refactored.py, *.original, temp files
- [x] **Root Directory Cleanup** - Move scattered files (*.csv, *.py, *.md clutter) to logical locations

### Add After Validation (v0.5.x)

Features to add once core reorganization is stable and tested.

- [ ] **Path Update Scripts** - Automate finding/fixing hardcoded paths in configs (trigger: if hardcoded paths found)
- [ ] **Documentation Integration** - Convert key ProjectTT Excel/Word docs to markdown (trigger: after phase validation)
- [ ] **Automated Verification Suite** - CI tests that enforce organization rules (trigger: after reorg complete)
- [ ] **Pre-commit Hooks** - Prevent future root clutter (trigger: after reorg validated)
- [ ] **Migration Documentation** - Comprehensive docs/REORGANIZATION.md (trigger: before milestone close)

### Future Consideration (v0.6+)

Features to defer until reorganization patterns are proven.

- [ ] **Import Path Aliases** - Temporary backward compatibility shims (defer: only if external dependencies)
- [ ] **Monorepo Tooling** - Advanced tools like Pants/Bazel (defer: only if multi-package complexity grows)
- [ ] **Dependency Graph Visualization** - Auto-generate import graphs (defer: nice-to-have for docs)

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Archive Structure | HIGH | LOW | P1 |
| File Inventory | HIGH | LOW | P1 |
| Git History Preservation | HIGH | MEDIUM | P1 |
| Zero Data Loss Guarantee | HIGH | LOW | P1 |
| Import Validation | HIGH | MEDIUM | P1 |
| Rollback Strategy | HIGH | LOW | P1 |
| Active vs Archive Heuristics | HIGH | MEDIUM | P1 |
| Root Directory Cleanup | HIGH | LOW | P1 |
| Path Update Scripts | MEDIUM | MEDIUM | P2 |
| Documentation Integration | MEDIUM | HIGH | P2 |
| Automated Verification Suite | MEDIUM | MEDIUM | P2 |
| Pre-commit Hooks | MEDIUM | LOW | P2 |
| Migration Documentation | MEDIUM | LOW | P2 |
| Import Path Aliases | LOW | MEDIUM | P3 |
| Monorepo Tooling | LOW | HIGH | P3 |
| Dependency Graph Visualization | LOW | MEDIUM | P3 |

**Priority key:**
- P1: Must have for milestone completion (table stakes)
- P2: Should have, add during or immediately after milestone (differentiators)
- P3: Nice to have, future consideration

## Reorganization Pattern Analysis

### Current ta_lab2 State

**Root Directory Clutter Identified:**
- Temporary files: `C:UsersasafiAppDataLocalTempclaudeC--Users-asafi-Downloads-ta-lab2c83d074d-ffff-4260-96b8-93d1abaa9042scratchpadplan-04-*.txt`
- Archive candidates: `test_*_refactored.py` files (6 files in root and src/ta_lab2/features/m_tf/)
- Archive candidates: `*.original` files (8 files in src/ta_lab2/scripts/emas/ and src/ta_lab2/features/m_tf/)
- Audit artifacts: `ema_audit.csv`, `ema_expected_coverage.csv`, `ema_samples.csv` (112 MB!)
- Migration docs in root: `EMA_FEATURE_MIGRATION_PLAN.md`, `EMA_MIGRATION_SESSION_SUMMARY.md`
- Miscellaneous scripts: `convert_docx_to_txt.py`, `count_chromadb_memories.py`, `fix_qdrant_persistence.py`, `generate_structure_docs.py`
- Old configs: `config.py` (Nov 13), `openai_config.env`, `openai_config_2.env`
- Old artifacts: `diff.txt`, `full_diff.patch`, `full_git_log.txt`
- Mysterious empty/broken entries: `-k`, `-p`, `nul`

**Archive Strategy for ta_lab2:**

1. **Refactored Code** (.archive/2026-02-02/code-refactoring/)
   - `test_*_refactored.py` (6 files)
   - `*_refactored.py` (3 files in src/ta_lab2/features/m_tf/)
   - `*.original` (8 files in scripts/features/)

2. **Migration Artifacts** (.archive/2026-02-02/ema-migration/)
   - `EMA_FEATURE_MIGRATION_PLAN.md`
   - `EMA_MIGRATION_SESSION_SUMMARY.md`
   - `ema_audit.csv`, `ema_expected_coverage.csv`, `ema_samples.csv`

3. **Temporary/Broken Files** (.archive/2026-02-02/temp-files/)
   - `C:UsersasafiAppDataLocalTemp...` files
   - `-k`, `-p`, `nul` files

4. **Old Tooling Scripts** (.archive/2026-02-02/utility-scripts/)
   - `convert_docx_to_txt.py`
   - `count_chromadb_memories.py`
   - `fix_qdrant_persistence.py`
   - `generate_structure_docs.py`

5. **Old Git Artifacts** (.archive/2026-02-02/git-history/)
   - `diff.txt`, `full_diff.patch`, `full_git_log.txt`

6. **Obsolete Configs** (.archive/2026-02-02/old-configs/)
   - `config.py` (replaced by src/ta_lab2/config.py)
   - `openai_config.env`, `openai_config_2.env`

**Keep Active (Organized):**
- `API_MAP.md`, `ARCHITECTURE.md`, `CHANGELOG.md`, `CONTRIBUTING.md` → already in correct location
- `CI_DEPENDENCY_FIXES.md` → docs/development/
- `lab2_analysis_gemini.md` → docs/analysis/
- `memory_enrich_run_manifest.json` → .memory/ (already organized)
- `mkdocs.yml` → keep in root (standard location)

### Industry Standard Patterns (2026)

**Monorepo Structure (Python 2026 Consensus):**
```
project_root/
├── src/                    # Source code (importable packages)
│   └── project_name/
├── tests/                  # Test suite mirroring src/
├── docs/                   # Documentation (markdown preferred)
├── tools/                  # Development utilities, scripts
├── .archive/               # Preserved backup artifacts (timestamped)
├── .planning/              # Project management (GSD, milestones)
├── pyproject.toml          # Single source of truth for package metadata
├── README.md               # Entry point documentation
└── (minimal root files)    # Only essential: LICENSE, .gitignore, CI configs
```

**Archive Directory Standard:**
```
.archive/
├── MANIFEST.md                           # Index of all archived content
├── 2026-02-02-ecosystem-reorg/
│   ├── manifest.json                     # Machine-readable inventory
│   ├── code-refactoring/
│   │   ├── test_multi_tf_refactored.py
│   │   └── ema_multi_timeframe_refactored.py
│   ├── migration-artifacts/
│   │   └── ema_audit.csv
│   └── utility-scripts/
│       └── convert_docx_to_txt.py
└── 2025-12-15-old-experiments/
    └── ...
```

**Import Validation Pattern:**
```python
# tests/test_imports.py (smoke test suite)
def test_core_imports():
    """Validate all public API imports work after reorganization."""
    import ta_lab2
    from ta_lab2 import features, signals, orchestrator
    from ta_lab2.features import ema, returns, volatility
    # ... all expected imports

def test_no_circular_dependencies():
    """Ensure reorganization didn't introduce circular imports."""
    # Use import-linter or custom AST traversal
```

**File Inventory Pattern:**
```json
{
  "reorganization_date": "2026-02-02",
  "actions": [
    {
      "action": "archive",
      "original_path": "test_multi_tf_refactored.py",
      "archive_path": ".archive/2026-02-02-ecosystem-reorg/code-refactoring/test_multi_tf_refactored.py",
      "sha256": "a1b2c3d4...",
      "reason": "Refactored code superseded by src/ta_lab2/features/m_tf/ema_multi_timeframe.py"
    },
    {
      "action": "move",
      "original_path": "CI_DEPENDENCY_FIXES.md",
      "new_path": "docs/development/CI_DEPENDENCY_FIXES.md",
      "git_commit": "abc123",
      "reason": "Documentation consolidation"
    }
  ],
  "statistics": {
    "files_archived": 45,
    "files_moved": 12,
    "files_deleted": 0,
    "total_size_archived_mb": 115.3
  }
}
```

## ta_lab2-Specific Considerations

### Constraint: NO DELETION

**Implication:** Archive everything, even obviously broken/temp files. Git history shows why they existed.

**Implementation:**
- .archive/ serves as "graveyard with GPS"
- manifest.json provides forensics
- Future cleanup can reference manifest to prove files are truly unused

### Integration with Existing Structure

**Already Good:**
- src/ta_lab2/ package structure (standard src-layout)
- tests/ directory separate from src/
- docs/ for markdown documentation
- .planning/ for GSD workflow

**Needs Work:**
- Root directory has 20+ files that should be elsewhere
- *_refactored.py and *.original files pollute active code directories
- Large CSV audit files (112 MB!) in root

### External Projects (Future Phases)

**ProjectTT**: Excel/Word documentation scattered elsewhere
- Strategy: Convert key docs to markdown in docs/, archive originals
- Complexity: HIGH (manual conversion + validation)

**Data_Tools**: Python scripts in separate directory
- Strategy: Evaluate each script, migrate useful ones to ta_lab2/tools/
- Complexity: MEDIUM (import updates, dependency checks)

**fredtools2/fedtools2**: Economic data packages
- Strategy: Decide integrate vs reference (likely reference for now)
- Complexity: LOW (just update docs if staying separate)

## Sources

### Primary Sources (HIGH Confidence)

- [The State of Python Packaging in 2026](https://learn.repoforge.io/posts/the-state-of-python-packaging-in-2026/) - Authoritative guide on 2026 Python tooling consolidation
- [Git Move Files: History Preservation in 2026](https://thelinuxcode.com/git-move-files-practical-renames-refactors-and-history-preservation-in-2026/) - Git mv patterns and file reorganization
- [Best Practices in Structuring Python Projects](https://dagster.io/blog/python-project-best-practices) - Modern Python project structure patterns
- [Python Application Layouts Reference](https://realpython.com/python-application-layouts/) - Real Python's layout guide (updated Jan 2026)
- [Structuring Your Project - Hitchhiker's Guide to Python](https://docs.python-guide.org/writing/structure/) - Community standard patterns

### Monorepo & Migration (MEDIUM Confidence)

- [Our Python Monorepo at Opendoor](https://medium.com/opendoor-labs/our-python-monorepo-d34028f2b6fa) - Real-world monorepo experience
- [Python Monorepo: Centralizing Multiple Projects](https://medium.com/@mtakanobu2/python-monorepo-centralizing-multiple-projects-and-sharing-code-3c1ab496340a) - Code sharing patterns
- [Top 5 Monorepo Tools for 2025](https://www.aviator.co/blog/monorepo-tools/) - Tooling comparison (Bazel, Pants, Nx)
- [Python Monorepo Example - Tweag](https://www.tweag.io/blog/2023-04-04-python-monorepo-1/) - Structure and tooling deep dive

### Documentation & Validation (MEDIUM Confidence)

- [7 Document Management Best Practices in 2026](https://thedigitalprojectmanager.com/project-management/document-management-best-practices/) - Consolidation strategies
- [Complete Data Migration Checklist for 2026](https://rivery.io/data-learning-center/complete-data-migration-checklist/) - Validation and rollback patterns
- [Repository Migration Checklist - GitHub Well-Architected](https://wellarchitected.github.com/library/scenarios/migrations/repository-checklist/) - GitHub's official migration guidance
- [Mastering Python Migration Guide](https://www.weblineindia.com/blog/python-migration-guide/) - Testing and validation strategies

### Git & Archiving (MEDIUM Confidence)

- [Git Housekeeping: Repository Cleanup](https://idemax.medium.com/git-housekeeping-keep-your-repository-clean-and-efficient-bc1602ea220a) - Git cleanup patterns
- [How to Archive Git Branches](https://www.tutorialpedia.org/blog/how-can-i-archive-git-branches/) - archive/ prefix pattern for branches
- [Python GitHub Backup Tool](https://github.com/josegonzalez/python-github-backup) - Preservation tooling examples

---
*Feature research for: ta_lab2 v0.5.0 Ecosystem Reorganization*
*Researched: 2026-02-02*
*Confidence: HIGH (patterns well-established, applied to ta_lab2 context)*
