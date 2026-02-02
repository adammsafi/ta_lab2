# Pitfalls Research

**Domain:** Python Project Reorganization (Consolidating 4 directories into ta_lab2 v0.4.0)
**Researched:** 2026-02-02
**Confidence:** HIGH

## Critical Pitfalls

### Pitfall 1: Silent Import Breakage from Namespace Collisions

**What goes wrong:**
When consolidating multiple Python projects into a single namespace, identical module names from different source directories create collisions where Python imports the wrong module. The import succeeds but returns unexpected code, causing runtime failures that appear unrelated to the reorganization. Tests may pass in the original structure but fail silently in the new one.

**Why it happens:**
Python's import system resolves the first matching module in sys.path. When merging projects with overlapping module names (e.g., both `Data_Tools/utils.py` and `ta_lab2/utils/`), Python picks whichever appears first in the path, hiding the collision until runtime. Developers assume that because imports don't raise ImportError, the code is correct.

**How to avoid:**
1. **Audit for name collisions BEFORE moving files:** Create inventory of all module names across all 4 directories to consolidate
2. **Rename conflicting modules with domain prefixes:** If both have `utils.py`, rename to `data_utils.py` and `ta_utils.py`
3. **Use explicit namespace packages:** Organize under clear hierarchies like `ta_lab2.tools.data_tools` vs `ta_lab2.tools.fred_tools`
4. **Verify with import tracing:** Use `python -v -c "import module"` to see which file Python actually loads

**Warning signs:**
- Import statements succeed but code behaves unexpectedly
- Tests pass individually but fail when run together
- Functions have wrong signatures or missing methods
- Error messages reference unexpected file paths

**Phase to address:**
Phase 1 (Pre-Move Analysis) - Complete collision audit before any files move

---

### Pitfall 2: Circular Import Hell from Cross-Directory Dependencies

**What goes wrong:**
Moving interdependent code from separate projects into a single package exposes hidden circular dependencies. Code that worked when separated by project boundaries fails with `ImportError: cannot import name 'X' from partially initialized module` errors. The circular dependency graph becomes undetectable until runtime, and fixing one circle creates new ones elsewhere.

**Why it happens:**
Separate projects can have bidirectional dependencies without Python noticing because they're imported as separate top-level packages. When consolidated into subpackages of ta_lab2, Python enforces stricter dependency ordering. For example, `Data_Tools.loader` importing `ProjectTT.schema` and vice versa works separately but fails when both become `ta_lab2.tools.loader` and `ta_lab2.tools.schema`.

Additionally, moving files changes import timing - `__init__.py` files may import modules that aren't yet initialized, triggering circular imports that didn't exist before.

**How to avoid:**
1. **Run static circular dependency detection BEFORE moving:** Use `pycycle` or `pylint --disable=all --enable=cyclic-import` on consolidated structure
2. **Refactor shared code into separate module:** Extract commonly imported utilities into `ta_lab2.common` that has no imports from other ta_lab2 modules
3. **Use TYPE_CHECKING pattern for type-only imports:**
   ```python
   from typing import TYPE_CHECKING
   if TYPE_CHECKING:
       from ta_lab2.features import Feature  # Only for type hints
   ```
4. **Lazy imports inside functions:** For non-critical imports, move them inside function bodies to defer loading
5. **Dependency injection pattern:** Pass dependencies as arguments rather than importing directly

**Warning signs:**
- ImportError mentioning "partially initialized module"
- Tests fail with import errors only when running full suite
- Import order matters (works in one test file, fails in another)
- Adding seemingly unrelated imports breaks previously working code

**Phase to address:**
Phase 2 (Dependency Analysis) - Map all cross-directory imports, identify circles, refactor before moving

**Tools referenced:**
- [Pycycle](https://github.com/bndr/pycycle): Find and fix circular imports
- Instagram's LibCST approach for large codebases (26 seconds for millions of lines)

---

### Pitfall 3: Git History Corruption from Mixed Refactoring

**What goes wrong:**
Combining file moves with code refactoring in the same commit destroys Git's ability to track file history. `git log --follow` loses the trail, `git blame` points to the reorganization commit instead of original changes, and merging becomes impossible because Git can't detect that files moved. The entire codebase history appears to have been "created" on reorganization day.

**Why it happens:**
Git uses heuristics to detect file moves by comparing content similarity. When you move AND modify files simultaneously (rename variables, change imports, restructure code), similarity drops below Git's threshold (default 50%). Git treats it as delete + create, severing the historical link. This is especially harmful under the NO DELETION constraint because `.archive/` preservation depends on maintaining history links.

**How to avoid:**
1. **Follow three-commit pattern for each file move:**
   - Commit 1: Move file with zero code changes (imports may break, that's OK)
   - Commit 2: Update import paths throughout codebase to fix breakage
   - Commit 3: Refactor code structure if needed
2. **Use `git mv` for all file operations:** Guarantees Git recognizes moves
3. **Set Git similarity threshold higher:** `git config diff.renameLimit 5000` and `git config merge.renameLimit 5000`
4. **Verify history preservation:** After each move, run `git log --follow <new_path>` to confirm history intact
5. **Test mergeability:** Create test branch, make change to old path, merge to reorganized branch

**Warning signs:**
- `git log --follow` shows only reorganization commit
- `git blame` attributes all lines to recent reorganization
- Merge conflicts on every file despite no logical conflicts
- GitHub PR shows thousands of line deletions + additions for moved files

**Phase to address:**
Phase 3 (Structured Migration) - Enforce three-commit pattern via validation script

**Source:**
- [Git Move Files: Practical Renames, Refactors, and History Preservation in 2026](https://thelinuxcode.com/git-move-files-practical-renames-refactors-and-history-preservation-in-2026/)

---

### Pitfall 4: The "Import Works But Tests Don't" Syndrome

**What goes wrong:**
After reorganization, manual imports work (`python -c "import ta_lab2.tools.data_tools"` succeeds), but pytest discovery fails with "ModuleNotFoundError" or imports the wrong modules. Tests that passed pre-reorganization fail with cryptic import errors. Running individual test files works but `pytest tests/` fails. The codebase appears functional but is untestable.

**Why it happens:**
Test discovery in pytest changes sys.path behavior differently than direct imports. Before reorganization, tests may have relied on relative imports or `sys.path.append('..')` hacks that break when test directory structure changes relative to code. Additionally, mixing regular packages (with `__init__.py`) and namespace packages during migration creates import ambiguity that pytest resolves differently than Python's standard import.

The ta_lab2 structure uses `src/` layout, which requires proper installation (`pip install -e .`) for tests to work, but developers often test without reinstalling after reorganization.

**How to avoid:**
1. **Mandate src/ layout pattern:** Keep `src/ta_lab2/` structure, never mix with flat `ta_lab2/` at root
2. **Install in editable mode after every file move:** Run `pip install -e .` before testing
3. **Add `__init__.py` to ALL test directories:** Even though Python 3.3+ allows namespace packages, pytest still expects test packages to have `__init__.py`
4. **Use absolute imports in tests:**
   ```python
   # WRONG: from ..features import ema
   # RIGHT: from ta_lab2.features import ema
   ```
5. **Add conftest.py at test root:** Configure sys.path explicitly if needed
6. **Validate test discovery:** Run `pytest --collect-only` after each move to verify discovery works

**Warning signs:**
- `python -c "import X"` works but `pytest` fails with ModuleNotFoundError
- Tests work individually (`pytest tests/test_x.py`) but fail in suite
- Import errors mentioning "attempted relative import beyond top-level package"
- Test coverage shows 0% despite passing tests

**Phase to address:**
Phase 4 (Test Migration) - Migrate and validate test structure immediately after moving source files

**Sources:**
- [pytest: Good Integration Practices](https://docs.pytest.org/en/7.1.x/explanation/goodpractices.html)
- [Structuring Your Project — The Hitchhiker's Guide to Python](https://docs.python-guide.org/writing/structure/)

---

### Pitfall 5: Archive Corruption from Incomplete Preservation

**What goes wrong:**
Files are moved to `.archive/` but metadata is lost: `.original` files lack timestamps, `*_refactored.py` files are archived without the final working version, and the mapping from archive to current code is ambiguous. Six months later, when investigating a bug, developers can't determine which archive file corresponds to which current module, or whether the archived version is pre- or post-refactoring.

**Why it happens:**
The NO DELETION constraint requires preserving everything in `.archive/`, but without a preservation manifest, the archive becomes a junk drawer. Developers archive files reactively during reorganization without documenting:
- What the archived file contained
- Why it was replaced (refactored? consolidated? deprecated?)
- Which current file(s) replaced it (one-to-many mapping)
- When the archival happened

The ta_lab2 codebase already has `.original` and `*_refactored.py` files scattered throughout (found in `src/ta_lab2/features/m_tf/`), demonstrating this pattern already occurring.

**How to avoid:**
1. **Create ARCHIVE_MANIFEST.md before any moves:**
   ```markdown
   | Archive Path | Replacement Path | Date | Reason | Notes |
   |--------------|------------------|------|--------|-------|
   | .archive/Data_Tools/loader.py | ta_lab2/tools/data_tools/loader.py | 2026-02-02 | Consolidated | Original had hardcoded paths |
   ```
2. **Archive directory structure mirrors source:**
   ```
   .archive/
     2026-02-02-reorganization/
       Data_Tools/
         loader.py
       ProjectTT/
         schema.py
   ```
3. **Include git commit hash in archive:** Store SHA of last commit before archival
4. **Automate archive validation:** Script to verify every archived file has manifest entry
5. **No bare `.original` or `_refactored` suffixes:** Always use full `.original.2026-02-02` datestamp

**Warning signs:**
- Multiple `.original` files with unclear relationships
- Cannot determine if archived code is before or after a refactoring
- No mapping from archive path to current code location
- Archive directories without README explaining contents

**Phase to address:**
Phase 5 (Archive Management) - Create manifest and archive structure before any archival operations

---

### Pitfall 6: Implicit Dependency Breakage from Environment Isolation

**What goes wrong:**
After consolidation, code fails with "ModuleNotFoundError" for packages that were previously installed in separate virtual environments. For example, `Data_Tools` depended on pandas 1.5.x but `ta_lab2` uses pandas 2.0.x. After moving Data_Tools into ta_lab2, either the old Data_Tools code breaks with pandas 2.x, or upgrading ta_lab2 to pandas 1.5.x breaks existing ta_lab2 code.

More insidiously, code that worked in isolation fails when combined due to global state pollution. Two different logging configurations, conflicting matplotlib backends, or incompatible SQLAlchemy engine configurations clash when modules are imported into the same process.

**Why it happens:**
Separate projects maintained separate `requirements.txt` or `pyproject.toml` with conflicting version pins. Dependencies were specified for each project in isolation without considering compatibility. When consolidated, Python's single environment must satisfy all constraints simultaneously, which may be impossible.

Additionally, projects may have initialized global state (logging configs, matplotlib settings, environment variables) assuming they control the entire process. When combined, last-import-wins causes unpredictable behavior.

**How to avoid:**
1. **Audit dependency conflicts BEFORE consolidation:**
   ```bash
   pip-compile requirements-ta_lab2.txt requirements-Data_Tools.txt --output-file=- 2>&1 | grep conflict
   ```
2. **Create unified pyproject.toml with all dependencies:** Test resolution with `pip install -e .[all]` before moving code
3. **Use version ranges, not pins:** Change `pandas==1.5.3` to `pandas>=1.5.3,<3.0` to allow compatibility
4. **Isolate global state in module scope:**
   ```python
   # WRONG: module-level logging.basicConfig()
   # RIGHT: def setup_logging() called explicitly by user
   ```
5. **Document incompatibilities in migration plan:** Some projects may need to stay separate if dependency conflicts are unsolvable

**Warning signs:**
- ImportError or AttributeError on previously working code after consolidation
- Tests fail with version mismatch errors
- Different behavior when modules imported in different order
- Warnings about matplotlib backend or logging configuration conflicts

**Phase to address:**
Phase 1 (Pre-Move Analysis) - Resolve dependency conflicts before any code moves

**Source:**
- [8 Common Python Package Management Mistakes to Avoid](https://envelope.dev/blog/8-common-python-package-management-mistakes-to-avoid)

---

### Pitfall 7: Stale Documentation from Orphaned References

**What goes wrong:**
Documentation references old paths, import examples break, architecture diagrams show obsolete structure, and tutorials fail to run. README files in ProjectTT describe `from ProjectTT.schema import Table` but the path is now `from ta_lab2.tools.project_tt import Table`. New users following documentation get immediate import errors, eroding trust. Worse, internal documentation (architecture docs, memory bank entries, AI context files) contains outdated mental models that mislead future development.

**Why it happens:**
Documentation is scattered across multiple locations (README.md, docs/, .planning/, docstrings, code comments, external wikis) and doesn't fail loudly like code. Reorganization focuses on making code work, treating documentation as "fix it later". But documentation debt compounds: six months post-reorganization, 40% of examples are broken, nobody knows which docs are current, and onboarding takes 3x longer.

For ta_lab2 specifically, the AI orchestrator memory system likely contains thousands of memories referencing old paths and structure. Those memories will provide outdated context to future AI sessions, causing confusion.

**How to avoid:**
1. **Grep for path references in all text files:**
   ```bash
   rg "from (Data_Tools|ProjectTT|fredtools)" --type md --type py --type txt
   ```
2. **Update docstrings when moving files:** Treat docstring import examples as code, update in same commit
3. **Regenerate architecture diagrams:** Don't manually edit, use code generation to stay in sync
4. **Add import verification to CI:** Test that all code examples in documentation actually run
5. **Update AI memory bank:** Regenerate memories for moved modules or tag old memories as deprecated
6. **Create MIGRATION.md guide:** Document old path → new path mapping for users and AI

**Warning signs:**
- README examples fail to run
- Architecture docs don't match actual code structure
- API documentation references non-existent modules
- AI assistants suggest imports that don't exist

**Phase to address:**
Phase 6 (Documentation Update) - Update all documentation immediately after code stabilizes, before declaring migration complete

**Source:**
- [Structuring Your Project — The Hitchhiker's Guide to Python](https://docs.python-guide.org/writing/structure/)

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Moving files without updating tests | Faster migration, "fix tests later" | Test suite becomes permanently broken, regressions undetected | Never (tests define correctness) |
| Archiving files without manifest | Quick cleanup, less documentation work | Archive becomes unmaintainable junk drawer, history lost | Never (violates NO DELETION constraint purpose) |
| Using `sys.path.append()` to fix imports | Imports work immediately, no refactoring needed | Fragile, breaks in different environments, hides structural problems | Only temporarily during migration, must be removed before completion |
| Copying code instead of moving | Zero risk of breaking original | Duplicate code diverges, bugs fixed in one place but not other | Acceptable for MVP if flagged with TODO and timeline |
| Mixing move + refactor in one commit | Fewer commits, feels more efficient | Git history destroyed, impossible to debug later | Never (Git is core infrastructure) |
| Skipping editable install after moves | Saves 10 seconds per move | Tests import wrong code, creates false confidence | Never in CI, acceptable during rapid local iteration if aware |
| Pinning dependencies to avoid conflicts | Immediate resolution | Blocks security updates, creates technical debt debt | Only as temporary bridge with explicit unpin timeline |
| Updating imports via find-replace | Fast, automatable | Misses dynamic imports, breaks string references, changes comments | Acceptable with manual verification of each change |

---

## Integration Gotchas

Common mistakes when merging code from separate projects.

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Database connections | Each project initializes own engine with different settings | Create `ta_lab2.db.get_engine()` singleton, all code uses it |
| Configuration loading | Each project loads from different env file locations | Unified `ta_lab2.config` that loads from single source of truth |
| Logging setup | Multiple `logging.basicConfig()` calls, last one wins | Single logging config in ta_lab2.__init__, optional per-module loggers |
| CLI entrypoints | Multiple `if __name__ == "__main__"` scripts with same command names | Unified `ta_lab2.cli` with subcommands: `ta-lab2 data-tools load` |
| Test fixtures | Each project defines own database fixtures with different schemas | Consolidated conftest.py with shared fixtures, optional project-specific fixtures |
| Import path references in data | Pickled objects, database metadata, config files containing old paths | Add compatibility layer or migration script, cannot be fixed by find-replace |
| Relative imports in scripts | Scripts at different nesting levels use `..` imports | Convert all to absolute `from ta_lab2.X import Y` imports |

---

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Import all at top level | Slow startup time, imports unused code | Lazy imports, defer expensive imports to usage point | >50 modules, esp. with heavy deps like pandas |
| Circular __init__.py imports | Intermittent ImportError, ordering sensitivity | Avoid importing submodules in __init__, use lazy loading | When module count >20 with cross-deps |
| Monolithic archive directory | Git operations slow down, archive unusable | Date-partitioned archives: `.archive/2026-02-02/` | >1000 files or >100MB |
| Single requirements.txt for all optional deps | Every install pulls unnecessary packages | Optional dependency groups in pyproject.toml | >30 dependencies |
| Re-running full test suite after every file move | Hours of CI time per PR | Incremental test selection, only run affected tests | >1000 tests or >10min suite runtime |

---

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Archiving .env files with credentials | Credentials committed to git in .archive/ | Add .archive/**/.env to .gitignore, document why env files excluded |
| Database connection strings in archived configs | Production credentials leaked in history | Scrub credentials before archival, use vault references |
| Hardcoded API keys in legacy scripts | Keys committed when consolidating old projects | Audit with `rg "api_key|secret|password" .archive/` before committing |
| Copying .git/ into archive | Entire repo history duplicated, bloats size | Only archive source code, never .git directories |
| Preserving test credentials | Test database passwords become production targets | Replace with dummy values in archive, document in manifest |

---

## UX Pitfalls

Common user experience mistakes in this domain.

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Silent import path changes | Code breaks in production after update | Provide deprecated import shims that warn before breaking |
| No migration guide | Users must reverse-engineer changes from git log | Publish MIGRATION.md with old→new path mappings and timeline |
| Breaking CLI commands | User scripts fail after update | Keep old commands working with deprecation warnings for 2 versions |
| Losing example scripts | Tutorials no longer work | Migrate examples with same care as production code |
| Changing package name | `import old_name` fails, confusing error | Keep old package as thin wrapper importing from new location |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **File moves complete:** Often missing: tests still importing from old paths — verify `rg "from (Data_Tools|ProjectTT)"` returns zero results
- [ ] **Import paths updated:** Often missing: dynamic imports in `importlib.import_module()` calls — verify with runtime execution, not just static grep
- [ ] **Tests passing:** Often missing: tests passing because pytest can't discover them — verify `pytest --collect-only` shows expected count
- [ ] **Documentation updated:** Often missing: docstrings in moved files still show old import examples — verify by building docs and checking examples
- [ ] **Archive created:** Often missing: manifest mapping archive to current code — verify `ARCHIVE_MANIFEST.md` has entry for every archived file
- [ ] **Git history preserved:** Often missing: history preserved for move but not for files modified before move — verify `git log --follow --all <path>` shows full history
- [ ] **Dependencies unified:** Often missing: conflicting version pins between old and new code — verify `pip check` passes after consolidation
- [ ] **CI passing:** Often missing: CI uses cached dependencies from before consolidation — verify CI runs with fresh environment
- [ ] **Memory bank updated:** Often missing: AI context still references old structure — verify memory regeneration for moved modules

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Namespace collision detected | LOW | 1. Rename conflicting module with domain prefix<br>2. Update all imports with `rg --files-with-matches "old_name" -g "*.py" \| xargs sed -i "s/old_name/new_name/g"`<br>3. Test with `pytest tests/`<br>4. Commit rename separately |
| Circular import introduced | MEDIUM | 1. Use `pycycle` to identify cycle<br>2. Extract shared code to new module<br>3. Convert type-only imports to TYPE_CHECKING<br>4. Test import order independence with `pytest --random-order` |
| Git history lost | HIGH | 1. Cannot fully recover (preventative only)<br>2. Partial recovery: `git rebase -i` to split mixed commit into move + refactor<br>3. Add note in ARCHIVE_MANIFEST.md linking to last good commit before move |
| Test discovery broken | MEDIUM | 1. Add `__init__.py` to all test directories<br>2. Convert to absolute imports<br>3. Reinstall package: `pip install -e .`<br>4. Verify: `pytest --collect-only` |
| Archive unmaintainable | MEDIUM | 1. Retroactively create ARCHIVE_MANIFEST.md<br>2. Use `git log --follow` to reconstruct mappings<br>3. Reorganize archive with date partitioning<br>4. Add README to each archive subdirectory |
| Dependency conflict | HIGH | 1. If resolvable: update version ranges in pyproject.toml<br>2. If not resolvable: keep projects separate (monorepo but independent packages)<br>3. Document incompatibility in PROJECT.md<br>4. Consider containerization to isolate environments |
| Documentation stale | MEDIUM | 1. Grep for all path references: `rg "(Data_Tools|ProjectTT|fredtools)" --type md`<br>2. Create bulk find-replace script with verification<br>3. Test all code examples in docs<br>4. Add import verification to CI |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Silent import breakage | Phase 1: Pre-Move Analysis | Run `python -c "import ta_lab2.X"` for all new paths, verify no ModuleNotFoundError and correct module loaded |
| Circular imports | Phase 2: Dependency Analysis | Run `pycycle --here src/ta_lab2` returns zero cycles |
| Git history corruption | Phase 3: Structured Migration | Every moved file passes `git log --follow <new_path>` showing >1 commit |
| Test discovery broken | Phase 4: Test Migration | `pytest --collect-only` count equals pre-migration test count |
| Archive corruption | Phase 5: Archive Management | Every entry in `find .archive/ -type f` has corresponding ARCHIVE_MANIFEST.md entry |
| Dependency conflicts | Phase 1: Pre-Move Analysis | `pip install -e .[all]` succeeds without conflicts |
| Stale documentation | Phase 6: Documentation Update | All doc examples pass when run, zero references to old paths in docs/ |

---

## Sources

### Web Search Results (Verified)

**Python Project Reorganization:**
- [Structuring Your Project — The Hitchhiker's Guide to Python](https://docs.python-guide.org/writing/structure/)
- [Python Refactoring: Techniques, Tools, and Best Practices](https://www.codesee.io/learning-center/python-refactoring)
- [Refactoring Python Applications for Simplicity – Real Python](https://realpython.com/python-refactoring/)

**Package Consolidation & Breaking Changes:**
- [The State of Python Packaging in 2026: A Comprehensive Guide](https://learn.repoforge.io/posts/the-state-of-python-packaging-in-2026/)
- [8 Common Python Package Management Mistakes to Avoid](https://envelope.dev/blog/8-common-python-package-management-mistakes-to-avoid)
- [Python Packaging Best Practices: setuptools, Poetry, and Hatch in 2026](https://dasroot.net/posts/2026/01/python-packaging-best-practices-setuptools-poetry-hatch/)

**Monorepo Migration:**
- [Python monorepos](https://graphite.com/guides/python-monorepos)
- [Moving all our Python code to a monorepo: pytendi](https://attendi.nl/moving-all-our-python-code-to-a-monorepo-pytendi/)
- [Python Monorepo: an Example. Part 1: Structure and Tooling - Tweag](https://www.tweag.io/blog/2023-04-04-python-monorepo-1/)

**Git History Preservation:**
- [Git Move Files: Practical Renames, Refactors, and History Preservation in 2026](https://thelinuxcode.com/git-move-files-practical-renames-refactors-and-history-preservation-in-2026/)

**Testing & Import Verification:**
- [Good Integration Practices — pytest documentation](https://docs.pytest.org/en/7.1.x/explanation/goodpractices.html)
- [Testing Your Code — The Hitchhiker's Guide to Python](https://docs.python-guide.org/writing/tests/)

**Namespace Packages:**
- [Packaging namespace packages - Python Packaging User Guide](https://packaging.python.org/en/latest/guides/packaging-namespace-packages/)
- [Support multiple packages with overlapping namespaces · Issue #2882 · microsoft/pyright](https://github.com/microsoft/pyright/issues/2882)

**Circular Imports:**
- [Python Circular Import: Causes, Fixes, and Best Practices | DataCamp](https://www.datacamp.com/tutorial/python-circular-import)
- [Circular Imports in Python: The Architecture Killer That Breaks Production](https://dev.to/vivekjami/circular-imports-in-python-the-architecture-killer-that-breaks-production-539j)
- [Pycycle: Find and fix circular imports in python projects](https://github.com/bndr/pycycle)

**__init__.py Migration:**
- [It's Been a Decade Since Python Made __init__.py Optional. Do You Know Why?](https://medium.com/@jelanmathewjames1234/its-been-a-decade-since-python-made-init-py-optional-do-you-know-why-6cc4db808255)
- [Understanding Python imports, __init__.py and pythonpath — once and for all](https://medium.com/data-science/understanding-python-imports-init-py-and-pythonpath-once-and-for-all-4c5249ab6355)

### Project Context (Observed)

**Existing ta_lab2 Codebase Analysis:**
- Project uses `src/` layout with `src/ta_lab2/` package structure
- Already has `.original` and `*_refactored.py` files demonstrating archive management challenges
- Uses pyproject.toml with optional dependency groups (good pattern for consolidation)
- Import style is primarily absolute imports (`from ta_lab2.X import Y`)
- Test structure uses pytest with conftest.py
- Multiple `__init__.py` files establishing clear package boundaries

**Risk Factors Identified:**
- 4 directories to consolidate (Data_Tools, ProjectTT, fredtools2, fedtools2)
- Working v0.4.0 codebase must not break during migration
- Strict NO DELETION constraint requiring comprehensive archival strategy
- AI orchestrator memory system contains path-specific context
- Existing backup artifacts pattern suggests previous reorganization attempts

---

*Pitfalls research for: Python Project Reorganization (ta_lab2 v0.5.0 Ecosystem Consolidation)*
*Researched: 2026-02-02*
*Overall confidence: HIGH (Web search verified with official sources, patterns observed in actual codebase)*
