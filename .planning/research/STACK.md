# Stack Research: Python Project Reorganization Tools

**Domain:** Python project ecosystem consolidation (4 directories → 1 unified structure)
**Researched:** 2026-02-02
**Confidence:** HIGH

## Recommended Stack

### Core Technologies (Git History Preservation)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| git-filter-repo | 2.38+ | Repository history rewriting and merging | Industry standard for monorepo consolidation; 10-50x faster than git filter-branch; Python-based tool that rewrites history cleanly while preserving all commits. Recommended by Git project itself. |
| Git (native) | 2.47+ | Version control foundation | Existing infrastructure. git subtree and git bundle commands provide complementary merging strategies with full history preservation. |
| Git bundles | native | Full repository archiving | Creates portable repository archives with complete history (unlike git archive which only snapshots). Essential for .archive/ preservation requirement. |

**Rationale for git-filter-repo over git subtree:**
- Filter-repo provides cleaner history when consolidating multiple repos into subdirectories
- Handles path rewriting automatically with `--to-subdirectory-filter`
- Python-based, integrates with existing Python 3.12 environment
- Both approaches preserve full history; filter-repo offers more control for complex reorganizations

### File Migration & Validation

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| pathlib | stdlib 3.12 | Safe path operations | Built-in, cross-platform, type-safe path handling. Use `.resolve()` for absolute paths to prevent working directory issues during migrations. |
| shutil | stdlib 3.12 | High-level file operations | Standard library for atomic moves/copies. Critical: use staging directory pattern for transaction-like guarantees when moving multiple files. |
| ruff | 0.14.3+ | Import validation and linting | Already in ta_lab2. 1000x faster than pylint, catches unused imports and broken import paths. Essential for verifying reorganized imports work correctly. |
| pytest + importlib | 8.4.2+ | Package structure validation | Already in ta_lab2. Use `--import-mode=importlib` to test package imports as users will experience them. Validates src/ layout integrity after reorganization. |

**Why pathlib/shutil over rsync:**
- Pure Python solution (no external binary dependencies on Windows)
- Programmatic control for dry-run scripts and validation
- Better error handling and Windows compatibility
- Can integrate with git status checks in migration scripts

### Import Path Refactoring

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| rope | 1.13+ | AST-based refactoring | For automated import path updates if consolidating Data_Tools/fredtools2/fedtools2 scripts into ta_lab2 namespace. Handles rename operations at AST level. |
| pipreqs | 0.5.0+ | Import-based dependency detection | Generate requirements.txt from actual imports after consolidation. Validates no broken dependencies introduced by reorganization. |
| mypy | 1.18.2+ | Type checking and import verification | Already in ta_lab2. Static analysis catches import errors before runtime. Use with `--ignore-missing-imports` during staged migration. |

**Why NOT Bowler:**
- Bowler based on lib2to3 (deprecated in Python 3.13+)
- Project effectively inactive with uncertain future
- Rope has active maintenance and better Python 3.12+ support

### Documentation Migration

| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| pypandoc | 1.14+ | Python wrapper for Pandoc | Convert ProjectTT .docx files to Markdown for integration into ta_lab2 docs/. Handles Word → Markdown with embedded media extraction. |
| pandoc | 3.1+ | Universal document converter | Underlying engine. Command: `pandoc -t markdown_strict --extract-media='./attachments' file.docx -o file.md` |

**Alternative:** Manual conversion for critical docs, automated for bulk conversions.

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| pytest-cov | Track reorganization impact | Already in ta_lab2. Measure test coverage before/after to ensure nothing broken. |
| git diff --stat | Pre/post comparison | Show which files moved where. Use with `--name-status` for rename detection. |
| git log --follow | History verification | Confirms file history preserved through renames and moves. |

## Installation

```bash
# Git filter-repo (required for history-preserving merges)
pip install git-filter-repo

# Documentation conversion (if migrating ProjectTT docs)
pip install pypandoc
# Also requires system pandoc:
# Windows: choco install pandoc
# or download from https://pandoc.org/installing.html

# Import refactoring (if needed for Data_Tools/fred/fed tools)
pip install rope

# Dependency validation
pip install pipreqs

# Already in ta_lab2 (verify versions):
pip list | grep -E "ruff|pytest|mypy"
# Should show: ruff>=0.14.3, pytest>=8.4.2, mypy>=1.18.2
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| git-filter-repo | git subtree | Use subtree if you need to keep syncing changes from original repos post-merge (not our use case - we're doing one-time consolidation). |
| Git bundles | git archive | Never for history preservation - git archive creates snapshots without .git metadata. |
| rope | Bowler | Only if stuck on Python 3.10 and need fissix-based refactoring (not recommended for 3.12). |
| pypandoc | manual conversion | Use manual for <20 critical docs where formatting matters; automate for bulk conversions. |
| pathlib/shutil | rsync | Use rsync if migrating from Linux/Unix and need preserve permissions/timestamps exactly (not critical for Windows development). |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| git filter-branch | Deprecated, 10-50x slower than filter-repo, error-prone | git-filter-repo |
| git archive for .archive/ | Doesn't preserve .git history - creates dead snapshots | Git bundles or mirror clones |
| Bowler for import refactoring | Based on deprecated lib2to3, inactive project | rope |
| os.path | Legacy API, less safe than pathlib | pathlib.Path with .resolve() |
| Manual file moves | Risk of losing git history, human error | git-filter-repo with --to-subdirectory-filter |
| pigar | Unmaintained since 2020 | pipreqs (actively maintained) |

## Stack Patterns by Use Case

**Pattern 1: Consolidating Python packages (fredtools2/fedtools2 → ta_lab2)**

1. Use git-filter-repo to rewrite history: `git filter-repo --to-subdirectory-filter src/ta_lab2/economic_data/fred/`
2. Merge with `git merge --allow-unrelated-histories`
3. Use rope to update import paths: `from fredtools2.fetch → from ta_lab2.economic_data.fred.fetch`
4. Validate with pytest + ruff: `pytest tests/integration/ && ruff check src/ta_lab2/`
5. Generate updated requirements: `pipreqs src/ta_lab2/`

**Pattern 2: Archiving scattered utilities (Data_Tools → ta_lab2/tools/ + .archive/)**

1. Create git bundle before any changes: `git bundle create Data_Tools.bundle --all`
2. Copy useful scripts to ta_lab2/tools/ with git mv to preserve history
3. Move bundle to .archive/Data_Tools/
4. Add README.md in .archive/ explaining archive structure
5. Validate imports work: Test scripts import from new paths

**Pattern 3: Documentation consolidation (ProjectTT → ta_lab2/docs/)**

1. Bulk convert .docx to .md: `for f in *.docx; do pypandoc.convert_file(f, 'md', outputfile=f.replace('.docx', '.md')); done`
2. Manual review of converted docs for formatting issues
3. Organize into docs/ subdirectories (e.g., docs/research/, docs/architecture/)
4. Archive original .docx files: Create ProjectTT git bundle → .archive/ProjectTT/
5. Update docs/README.md with archive references

**Pattern 4: Root directory cleanup (backup artifacts → .archive/)**

1. Identify categories: *_refactored.py, .original files, temp scripts
2. Create .archive/ structure: `.archive/backups/`, `.archive/experiments/`, `.archive/deprecated/`
3. Use git mv to preserve history: `git mv *_refactored.py .archive/backups/`
4. Document in .archive/README.md: What each category contains, when archived, why
5. Verify nothing broken: Run full test suite

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| git-filter-repo 2.38+ | Git 2.47+ | Requires Git 2.22+ minimum; tested with ta_lab2's Git 2.47.1 |
| pypandoc 1.14+ | pandoc 3.1+ | Python wrapper version must match system pandoc major version |
| rope 1.13+ | Python 3.12 | Supports Python 3.8-3.13; integrates with ta_lab2's existing AST tooling |
| pytest 8.4.2 | pytest-cov 7.0+ | Already validated in ta_lab2 test suite |
| ruff 0.14.3 | pyproject.toml config | Already configured in ta_lab2; no additional setup needed |

## Critical Safety Patterns

**1. Staging Directory Pattern (Transaction-like File Moves)**

```python
from pathlib import Path
import shutil
import tempfile

def safe_multi_file_move(files: list[Path], target_dir: Path):
    """Move multiple files atomically using staging directory."""
    # Create staging in same filesystem as target (critical for atomic rename)
    staging = target_dir.parent / f".staging_{target_dir.name}"
    staging.mkdir(exist_ok=True)

    try:
        # Stage all files
        for src in files:
            dst = staging / src.name
            shutil.move(src, dst)

        # Atomic commit: rename staging → target (same filesystem)
        staging.rename(target_dir / "new_subdir")

    except Exception as e:
        # Rollback: move files back from staging
        for f in staging.iterdir():
            shutil.move(f, f.parent.parent)
        staging.rmdir()
        raise
```

**2. Dry-Run Pattern (Preview Before Executing)**

```python
def migration_script(dry_run: bool = True):
    """Use print() for dry-run, actual operations when dry_run=False."""
    moves = [
        ("src/old_module.py", "src/ta_lab2/new_location/module.py"),
        ("scripts/util.py", "src/ta_lab2/tools/util.py"),
    ]

    for src, dst in moves:
        if dry_run:
            print(f"Would move: {src} → {dst}")
        else:
            # Actual git mv to preserve history
            subprocess.run(["git", "mv", src, dst], check=True)
```

**3. Absolute Path Pattern (Prevent Working Directory Issues)**

```python
from pathlib import Path

# ALWAYS use absolute paths in migration scripts
repo_root = Path(__file__).parent.parent.resolve()  # .resolve() critical
src_dir = repo_root / "src" / "ta_lab2"
archive_dir = repo_root / ".archive"

# Verify before operations
assert repo_root.exists(), f"Repo root not found: {repo_root}"
assert (repo_root / ".git").exists(), "Not a git repository"
```

## Integration with Existing ta_lab2 Stack

**Validated Compatibility:**

1. **Git 2.47.1** (confirmed via `git --version`) → git-filter-repo requires 2.22+, fully compatible
2. **Python 3.12.7** (confirmed) → All recommended tools support 3.12
3. **pytest 8.4.2 + ruff 0.14.3 + mypy 1.18.2** (confirmed via pip list) → Already configured for import validation
4. **src/ layout** (confirmed in pyproject.toml) → Recommended for pytest importlib mode
5. **pyproject.toml config** (confirmed) → ruff and pytest already configured, no additional setup

**No Conflicts:**
- git-filter-repo is a standalone CLI tool (doesn't conflict with existing git setup)
- pypandoc is optional (only if migrating docs)
- rope is optional (only if automated import refactoring needed)
- All stdlib tools (pathlib, shutil) already available

## Verification Checklist (Post-Reorganization)

```bash
# 1. Test suite passes
pytest tests/ -v

# 2. Import validation (no unused imports, no broken paths)
ruff check src/ta_lab2/ --select F401,F811

# 3. Type checking (catches import errors)
mypy src/ta_lab2/ --ignore-missing-imports

# 4. Dependency validation (no missing imports)
pipreqs src/ta_lab2/ --print | diff - requirements.txt

# 5. Git history preserved (confirm file history follows renames)
git log --follow src/ta_lab2/tools/util.py

# 6. Archive bundles valid
git bundle verify .archive/Data_Tools/Data_Tools.bundle

# 7. Coverage unchanged (no tests broken by reorganization)
pytest --cov=src/ta_lab2 --cov-report=term-missing
```

## Sources

**HIGH Confidence (Official Documentation & Maintained Projects):**
- [GitHub - newren/git-filter-repo](https://github.com/newren/git-filter-repo) — Official git-filter-repo repository
- [Git Official Documentation - git-archive](https://git-scm.com/docs/git-archive) — Git archive limitations
- [Python Official Docs - pathlib](https://docs.python.org/3/library/pathlib.html) — pathlib module documentation
- [Python Official Docs - shutil](https://docs.python.org/3/library/shutil.html) — shutil module documentation
- [Ruff Official Docs](https://docs.astral.sh/ruff/) — Ruff linter and formatter
- [pytest Official Docs - Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html) — pytest importlib mode
- [pypandoc PyPI](https://pypi.org/project/pypandoc/) — Python wrapper for Pandoc
- [Pandoc Official Site](https://pandoc.org/) — Universal document converter
- [rope GitHub Repository](https://github.com/python-rope/rope) — Python refactoring library

**MEDIUM Confidence (Community Best Practices, Verified by Multiple Sources):**
- [Merging Multiple Git Repositories with Git-Filter-Repo](https://medium.com/@umerfarooq.dev/merging-multiple-git-repositories-into-a-mono-repository-with-git-filter-repo-e3a6722e824d) — Monorepo consolidation workflow
- [Git Merge Repositories with History](https://build5nines.com/git-merge-repositories-with-history/) — History preservation techniques
- [Python shutil.move() Guide (2026)](https://thelinuxcode.com/python-shutilmove-a-practical-guide-to-safe-file-and-directory-moves-2026/) — Safe file operations
- [Python Linters: Pylint, Black, and Ruff Explained](https://www.marketcalls.in/python/a-comprehensive-guide-to-python-linters-pylint-black-and-ruff-explained.html) — Linter comparison 2025-2026
- [Git Backup Best Practices](https://thescimus.com/blog/git-backup-best-practices/) — Git bundles and archiving
- [Automating Refactoring with Rope](https://medium.com/datamindedbe/automating-refactoring-across-teams-and-projects-5f141ccd634b) — AST-based refactoring patterns

**Verified through Existing ta_lab2 Setup:**
- Python 3.12.7 (confirmed via `python --version`)
- Git 2.47.1 (confirmed via `git --version`)
- pytest 8.4.2, ruff 0.14.3, mypy 1.18.2 (confirmed via `pip list`)
- src/ layout and pyproject.toml configuration (confirmed via file reads)

---
*Stack research for: Python project ecosystem reorganization*
*Researched: 2026-02-02*
*Focus: Consolidating 4 directories into ta_lab2 with full history preservation*
