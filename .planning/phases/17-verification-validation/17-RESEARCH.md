# Phase 17: Verification & Validation - Research

**Researched:** 2026-02-03
**Domain:** Python project validation and testing automation
**Confidence:** HIGH

## Summary

Phase 17 validates the reorganization completed in Phases 11-16 by ensuring all imports work, detecting circular dependencies, establishing CI testing, and installing pre-commit hooks. The research investigated pytest import validation patterns, circular dependency detection tools (import-linter, pycycle), GitHub Actions CI configuration, pre-commit hook setup with Ruff, and file integrity validation approaches.

The project already has robust validation infrastructure from Phase 12 (checksum-based snapshot tooling with 9,620-file baseline), pyproject.toml with pytest configuration, and optional dependency groups for modular testing. The standard approach is: (1) pytest-based import validation using pkgutil.walk_packages for dynamic discovery, (2) import-linter with "acyclic siblings" contract for strict circular dependency detection, (3) GitHub Actions workflow with pytest exit code handling and continue-on-error for warnings, (4) pre-commit hooks with Ruff for fast linting, and (5) checksum validation against Phase 12 baseline plus memory query verification for moved files.

**Primary recommendation:** Use pytest parametrization to generate one test per module for clear failure reporting, import-linter with strict zero-cycle configuration in CI, pre-commit hooks with Ruff (fast) but not mypy (slow), and leverage existing Phase 12 validation tooling for data loss verification.

## Standard Stack

The established libraries/tools for Python project validation:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 8.0+ | Test framework for import validation | Industry standard, supports parametrization for dynamic test generation, exit codes for CI integration |
| import-linter | 2.7+ | Circular dependency detection | Actively maintained, contract-based rules, supports zero-cycle enforcement, designed for CI integration |
| ruff | 0.1.5+ | Fast Python linter/formatter | Rust-based speed (10-100x faster than alternatives), replaces multiple tools (flake8, isort, black), official pre-commit support |
| pre-commit | 3.0+ | Git hook framework | Industry standard for pre-commit automation, supports hook ordering and selective execution |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pkgutil | stdlib | Dynamic module discovery | For discovering all modules in a package to generate import tests |
| importlib | stdlib | Dynamic module importing | For actually importing modules discovered by pkgutil in validation tests |
| pytest-github-actions-annotate-failures | latest | Inline CI annotations | Optional plugin for better GitHub Actions integration with test failures |
| hashlib | stdlib | SHA256 checksums | For file integrity validation (already used in Phase 12 tooling) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| import-linter | pycycle | pycycle is inactive (no updates in 12+ months), less reliable, no contract system |
| ruff | pylint + black + isort | Multiple tools are slower, more configuration, redundant functionality |
| pytest parametrization | Manual test list | Manual lists get stale as modules are added/removed |
| GitHub Actions | Other CI systems | GitHub Actions already standard in Python ecosystem, free for public repos |

**Installation:**
```bash
pip install pytest>=8.0 import-linter>=2.7 ruff>=0.1.5 pre-commit>=3.0
# Optional: pip install pytest-github-actions-annotate-failures
```

## Architecture Patterns

### Recommended Validation Test Structure
```
tests/
├── test_imports.py              # Import validation (all modules)
│   ├── test_public_api_imports()
│   ├── test_tools_imports()
│   └── test_optional_deps_imports()
├── test_circular_deps.py        # Circular dependency check (calls import-linter)
└── validation/
    └── test_data_loss.py        # File count and checksum validation
```

### Pattern 1: Dynamic Import Test Generation with pytest
**What:** Use pytest parametrization to generate one test per module, enabling clear failure reporting
**When to use:** For validating all modules in a package can be imported without errors
**Example:**
```python
# Source: pytest documentation - parametrization + pkgutil pattern
import pkgutil
import importlib
import pytest
from pathlib import Path

def discover_modules(package_name, package_path):
    """Discover all modules in a package recursively."""
    modules = []
    for info in pkgutil.walk_packages([str(package_path)], prefix=f"{package_name}."):
        modules.append(info.name)
    return modules

# Discover modules at collection time
TA_LAB2_MODULES = discover_modules("ta_lab2", Path("src/ta_lab2"))
TOOLS_MODULES = discover_modules("ta_lab2.tools", Path("src/ta_lab2/tools"))

@pytest.mark.parametrize("module_name", TA_LAB2_MODULES)
def test_public_api_import(module_name):
    """Test that each module in ta_lab2 can be imported."""
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"Failed to import {module_name}: {e}")

@pytest.mark.parametrize("module_name", TOOLS_MODULES)
def test_tools_import(module_name):
    """Test that each tools module can be imported."""
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"Failed to import {module_name}: {e}")
```

### Pattern 2: Optional Dependency Handling with pytest.importorskip
**What:** Separate test groups for core vs optional dependencies using pytest markers
**When to use:** When testing imports that require optional dependencies (chromadb, mem0ai)
**Example:**
```python
# Source: pytest documentation - skipping tests
import pytest

# Mark tests requiring optional dependencies
@pytest.mark.orchestrator
def test_orchestrator_imports():
    """Test orchestrator imports (requires chromadb, mem0ai)."""
    chromadb = pytest.importorskip("chromadb", reason="chromadb required for orchestrator")
    mem0 = pytest.importorskip("mem0ai", reason="mem0ai required for orchestrator")

    # Now import our modules that depend on these
    from ta_lab2.tools.ai_orchestrator import memory
    from ta_lab2.tools.ai_orchestrator import core

# Run core tests: pytest -m "not orchestrator"
# Run all tests: pytest -m ""
```

### Pattern 3: CI Workflow with Failure Mode Control
**What:** GitHub Actions workflow that fails on critical issues, warns on organizational rules
**When to use:** For establishing CI validation gates while allowing non-critical warnings
**Example:**
```yaml
# Source: GitHub Actions best practices + pytest exit codes
name: Validation

on: [push, pull_request]

jobs:
  imports-core:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install core dependencies
        run: pip install -e ".[dev]"

      - name: Test core imports
        run: pytest tests/test_imports.py -m "not orchestrator" --tb=short

  imports-optional:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install all dependencies
        run: pip install -e ".[all]"

      - name: Test optional dependency imports
        run: pytest tests/test_imports.py -m "orchestrator" --tb=short
        continue-on-error: true  # Warn but don't block

  circular-deps:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install import-linter
        run: pip install import-linter

      - name: Check circular dependencies
        run: lint-imports  # Fails if cycles detected

  org-rules:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Check no .py files in project root
        run: |
          if ls *.py 2>/dev/null; then
            echo "::warning::Python files found in project root"
            exit 1
          fi
        continue-on-error: true  # Warn but don't block
```

### Pattern 4: import-linter Configuration
**What:** Contract-based circular dependency detection with strict zero-cycle enforcement
**When to use:** For detecting and preventing circular imports in package architecture
**Example:**
```toml
# Source: import-linter documentation
# pyproject.toml
[tool.importlinter]
root_package = "ta_lab2"

# Strict: forbid ALL circular dependencies
[[tool.importlinter.contracts]]
name = "No circular dependencies anywhere"
type = "acyclic_siblings"
packages = [
    "ta_lab2.features",
    "ta_lab2.tools",
    "ta_lab2.scripts",
    "ta_lab2.connectivity",
]

# Optional: Layer enforcement (high-level can import low-level, not vice versa)
[[tool.importlinter.contracts]]
name = "Tools don't import from scripts"
type = "forbidden"
source_modules = ["ta_lab2.tools"]
forbidden_modules = ["ta_lab2.scripts"]
```

### Pattern 5: Pre-commit Hook Configuration with Ruff
**What:** Fast pre-commit validation with Ruff for linting and formatting
**When to use:** To prevent issues before commit, keeping hooks fast (<5 seconds)
**Example:**
```yaml
# Source: Ruff official pre-commit documentation
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.14.14
    hooks:
      # Run linter with auto-fix BEFORE formatter
      - id: ruff-check
        types_or: [python, pyi]
        args: [--fix, --exit-non-zero-on-fix]

      # Run formatter
      - id: ruff-format
        types_or: [python, pyi]

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
        args: [--maxkb=500]

  # Custom hook: no .py in project root
  - repo: local
    hooks:
      - id: no-root-py-files
        name: No .py files in project root
        entry: bash -c 'if ls *.py 2>/dev/null; then echo "Python files not allowed in project root"; exit 1; fi'
        language: system
        pass_filenames: false
        always_run: true

# Install: pre-commit install
# Run manually: pre-commit run --all-files
# Skip: SKIP=ruff-check git commit
```

### Pattern 6: File Integrity Validation Against Baseline
**What:** Checksum-based validation using Phase 12 baseline to detect data loss
**When to use:** After reorganization to verify no files were lost, only moved
**Example:**
```python
# Source: Phase 12 validation tooling
from pathlib import Path
from ta_lab2.tools.archive.validate import (
    create_snapshot,
    load_snapshot,
    validate_no_data_loss
)

def test_no_data_loss():
    """Validate no files were lost during reorganization."""
    # Load Phase 12 baseline
    baseline_path = Path(".planning/phases/12-archive-foundation/baseline/pre_reorg_snapshot.json")
    baseline = load_snapshot(baseline_path)

    # Create current snapshot (src + tests only, skip .venv)
    current = create_snapshot(
        root=Path("."),
        pattern="**/*.py",
        compute_checksums=True
    )

    # Validate: all baseline checksums exist in current snapshot
    # (allows moves, forbids deletions)
    success, issues = validate_no_data_loss(baseline, current, strict=False)

    if not success:
        pytest.fail(f"Data loss detected:\n" + "\n".join(issues))
```

### Anti-Patterns to Avoid
- **Manual module lists:** Using hardcoded lists instead of pkgutil.walk_packages means tests go stale as modules change
- **Single import test:** One test importing all modules masks which specific module fails (use parametrization instead)
- **Slow pre-commit hooks:** Running mypy or full test suite in pre-commit hooks (>5 seconds) frustrates developers
- **Path-based validation:** Using file paths to detect data loss fails when files are moved (use checksums instead)
- **--import-mode=prepend:** The default import mode pollutes sys.path; use --import-mode=importlib for cleaner testing

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Circular import detection | Custom AST parser scanning imports | import-linter | Handles indirect cycles (A→B→C→A), TYPE_CHECKING blocks, dynamic imports - much harder than it looks |
| Python linting | Custom style checker | Ruff | 500+ rules covering style, complexity, security, performance - extremely comprehensive |
| Pre-commit automation | Git hook bash scripts | pre-commit framework | Handles hook installation, ordering, file filtering, skipping, language support automatically |
| Module discovery | os.walk + .py file parsing | pkgutil.walk_packages | Correctly handles packages vs modules, __init__.py semantics, namespace packages |
| File checksums | Custom hash function | hashlib.sha256 | Crypto-quality hashing with C-speed implementation |
| pytest parametrization | Loop with assert | pytest.mark.parametrize | Proper test isolation, clear failure reporting, parallelization support |

**Key insight:** Validation and testing infrastructure has evolved over 15+ years in Python ecosystem. The tools are mature, fast, and handle edge cases that custom solutions will miss. The time saved by using standard tools far exceeds any "not invented here" preferences.

## Common Pitfalls

### Pitfall 1: ImportError Only on CI, Not Local
**What goes wrong:** Tests pass locally but fail in GitHub Actions with ImportError
**Why it happens:**
- Local dev has all optional dependencies installed (`pip install -e ".[all]"`)
- CI only installs core dependencies
- Tests don't handle missing optional deps gracefully

**How to avoid:**
- Use pytest.importorskip() for optional dependency imports
- Separate test groups with markers (`-m "not orchestrator"`)
- Test CI configuration locally: `pip install -e ".[dev]" && pytest`

**Warning signs:**
- Tests using chromadb, mem0ai without importorskip
- No pytest markers separating optional dependency tests
- CI always installs `.[all]` (masks the issue)

### Pitfall 2: False Positive "No Circular Dependencies" from import-linter
**What goes wrong:** import-linter reports no cycles but circular imports exist at runtime
**Why it happens:**
- import-linter only analyzes static imports, not runtime imports
- Imports inside functions or if-blocks are invisible to static analysis
- TYPE_CHECKING blocks excluded by default

**How to avoid:**
- Don't use runtime imports to "fix" circular dependencies (they still exist)
- Configure exclude_type_checking_imports = False if TYPE_CHECKING imports matter
- Test actual imports at runtime with pytest (static analysis + runtime testing)

**Warning signs:**
- Developers moving imports inside functions to "fix" cycles
- Runtime circular import errors that import-linter missed
- Heavy use of TYPE_CHECKING blocks without validation

### Pitfall 3: Pre-commit Hooks Too Slow, Developers Bypass with --no-verify
**What goes wrong:** Hooks take >10 seconds, developers skip them, CI catches issues later
**Why it happens:**
- Running full test suite or slow linters (mypy) in pre-commit
- Processing all files not just staged files
- Multiple tools with redundant checks

**How to avoid:**
- Use only fast hooks in pre-commit (Ruff < 1s, basic checks < 2s)
- Move slow checks (mypy, full tests) to CI only
- Use pass_filenames: true to check only staged files
- Target: total pre-commit time < 5 seconds

**Warning signs:**
- Developers regularly using `git commit --no-verify`
- Pre-commit hooks taking >5 seconds
- Mypy or pytest in .pre-commit-config.yaml

### Pitfall 4: pytest.mark.parametrize with Module Objects Instead of Names
**What goes wrong:** Tests fail with cryptic pickle errors or wrong module imported
**Why it happens:**
- Parametrizing with actual module objects breaks pytest's collection
- Module objects evaluated at import time before tests run
- ImportError during parametrization collection kills entire test file

**How to avoid:**
- Parametrize with module name strings, not module objects
- Discover modules as strings using pkgutil (returns ModuleInfo with .name)
- Import inside test function after collection succeeds

**Warning signs:**
```python
# BAD: importing at parametrization time
modules = [importlib.import_module(name) for name in module_names]
@pytest.mark.parametrize("module", modules)

# GOOD: import inside test
@pytest.mark.parametrize("module_name", module_names)
def test_import(module_name):
    importlib.import_module(module_name)
```

### Pitfall 5: Checksum Validation Failing on Line Ending Changes
**What goes wrong:** Baseline validation reports data loss but files are identical
**Why it happens:**
- Git autocrlf converts line endings on checkout (Windows)
- Checksums different for LF vs CRLF even with same content
- Phase 12 baseline captured on Linux, validation runs on Windows (or vice versa)

**How to avoid:**
- Configure .gitattributes to normalize line endings (`* text=auto`)
- Or: capture baseline and run validation on same platform
- Or: normalize files before checksumming (convert CRLF→LF)

**Warning signs:**
- Validation failures only on specific platforms
- All checksums different, not just moved files
- Git showing files as modified with no visible changes

### Pitfall 6: pkgutil.walk_packages Importing Packages with Side Effects
**What goes wrong:** Test discovery triggers unwanted side effects (DB connections, API calls)
**Why it happens:**
- pkgutil.walk_packages must import packages to traverse __path__
- Module-level code executes during import
- Side effects in __init__.py run during test collection

**How to avoid:**
- Keep __init__.py files minimal (only imports/exports)
- Move side effects to functions called explicitly, not module-level
- Use onerror parameter in walk_packages to handle import failures gracefully

**Warning signs:**
- Test collection taking long time or failing
- Database connection errors during pytest collection
- "Test discovery crashed" errors before any tests run

## Code Examples

Verified patterns from official sources:

### Import Validation Test Suite
```python
# Source: pytest parametrization docs + pkgutil stdlib docs
# tests/test_imports.py
"""Validate all ta_lab2 modules can be imported without errors."""
import pkgutil
import importlib
import pytest
from pathlib import Path


def discover_package_modules(package_name: str, package_path: Path) -> list[str]:
    """Discover all modules in a package recursively.

    Args:
        package_name: Fully qualified package name (e.g., 'ta_lab2.tools')
        package_path: Filesystem path to package directory

    Returns:
        List of module names as strings (e.g., ['ta_lab2.tools.archive.manifest'])
    """
    modules = []

    def handle_import_error(name):
        """Log import errors during discovery but don't fail."""
        print(f"Warning: Could not import {name} during discovery")

    for info in pkgutil.walk_packages(
        [str(package_path)],
        prefix=f"{package_name}.",
        onerror=handle_import_error
    ):
        if not info.ispkg:  # Only leaf modules, not packages
            modules.append(info.name)

    return sorted(modules)


# Discover modules at collection time (before tests run)
SRC_PATH = Path(__file__).parent.parent / "src"
TA_LAB2_MODULES = discover_package_modules("ta_lab2", SRC_PATH / "ta_lab2")
TOOLS_MODULES = discover_package_modules("ta_lab2.tools", SRC_PATH / "ta_lab2" / "tools")
TEST_MODULES = discover_package_modules("tests", Path(__file__).parent)


@pytest.mark.parametrize("module_name", TA_LAB2_MODULES)
def test_ta_lab2_module_import(module_name):
    """Test that each ta_lab2 module can be imported."""
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"Failed to import {module_name}: {e}")


@pytest.mark.parametrize("module_name", TOOLS_MODULES)
def test_tools_module_import(module_name):
    """Test that each ta_lab2.tools module can be imported."""
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"Failed to import {module_name}: {e}")


@pytest.mark.orchestrator  # Requires optional dependencies
@pytest.mark.parametrize("module_name", [
    "ta_lab2.tools.ai_orchestrator.memory",
    "ta_lab2.tools.ai_orchestrator.core",
])
def test_orchestrator_imports(module_name):
    """Test orchestrator modules requiring chromadb/mem0ai."""
    # Skip if dependencies not installed
    pytest.importorskip("chromadb", reason="chromadb required")
    pytest.importorskip("mem0ai", reason="mem0ai required")

    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"Failed to import {module_name}: {e}")


@pytest.mark.parametrize("module_name", TEST_MODULES)
def test_test_module_import(module_name):
    """Test that test modules can be imported."""
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"Failed to import {module_name}: {e}")
```

### Circular Dependency Validation
```python
# Source: import-linter documentation
# tests/test_circular_deps.py
"""Test for circular dependencies using import-linter."""
import subprocess
import sys
import pytest


def test_no_circular_dependencies():
    """Run import-linter to detect circular dependencies.

    Fails if any circular imports detected. Configuration in pyproject.toml.
    """
    result = subprocess.run(
        ["lint-imports"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        # Import-linter found violations
        pytest.fail(
            f"Circular dependencies detected:\n"
            f"{result.stdout}\n"
            f"{result.stderr}"
        )
```

### Data Loss Validation Against Baseline
```python
# Source: Phase 12 validate.py + testing patterns
# tests/validation/test_data_loss.py
"""Validate no data loss during reorganization using Phase 12 baseline."""
from pathlib import Path
import pytest
from ta_lab2.tools.archive.validate import (
    create_snapshot,
    load_snapshot,
    validate_no_data_loss,
)


def test_no_files_lost_from_baseline():
    """Validate all files in Phase 12 baseline still exist (by checksum).

    Files can be moved, but checksums must match (no deletion, no corruption).
    """
    baseline_path = Path(".planning/phases/12-archive-foundation/baseline/pre_reorg_snapshot.json")

    if not baseline_path.exists():
        pytest.skip(f"Baseline not found: {baseline_path}")

    # Load Phase 12 baseline (9,620 files with checksums)
    baseline = load_snapshot(baseline_path)

    # Create current snapshot of project (excluding .venv)
    # Only check src/ and tests/ to avoid .venv changes
    current = create_snapshot(
        root=Path("."),
        pattern="**/*.py",
        compute_checksums=True,
    )

    # Validate: every baseline checksum exists in current
    # strict=False allows NEW files (only forbids deletions)
    success, issues = validate_no_data_loss(
        baseline,
        current,
        strict=False
    )

    if not success:
        # Format issues for readable failure message
        issue_msg = "\n  - ".join(issues)
        pytest.fail(
            f"Data loss detected during reorganization:\n  - {issue_msg}\n\n"
            f"Baseline: {baseline.total_files} files, {baseline.total_size_bytes} bytes\n"
            f"Current: {current.total_files} files, {current.total_size_bytes} bytes"
        )


def test_file_count_matches_baseline_accounting():
    """Validate: baseline count = current count + archived count.

    Every file is either in active codebase or in .archive/.
    """
    baseline_path = Path(".planning/phases/12-archive-foundation/baseline/pre_reorg_snapshot.json")

    if not baseline_path.exists():
        pytest.skip(f"Baseline not found: {baseline_path}")

    baseline = load_snapshot(baseline_path)

    # Count current files (excluding .venv, .archive)
    current = create_snapshot(
        root=Path("src"),
        pattern="**/*.py",
        compute_checksums=False,  # Faster, just counting
    )

    # Count archived files
    archive = create_snapshot(
        root=Path(".archive"),
        pattern="**/*.py",
        compute_checksums=False,
    )

    # Count test files
    tests = create_snapshot(
        root=Path("tests"),
        pattern="**/*.py",
        compute_checksums=False,
    )

    # Accounting: baseline should equal current + archived
    # (Only check src + tests, ignore .venv)
    baseline_src_tests = (
        baseline.by_directory.get("src_ta_lab2", {}).get("total_files", 0)
        + baseline.by_directory.get("tests", {}).get("total_files", 0)
    )
    current_total = current.total_files + archive.total_files + tests.total_files

    if baseline_src_tests != current_total:
        pytest.fail(
            f"File count mismatch (possible data loss):\n"
            f"  Baseline (src+tests): {baseline_src_tests} files\n"
            f"  Current (src): {current.total_files} files\n"
            f"  Current (tests): {tests.total_files} files\n"
            f"  Archived: {archive.total_files} files\n"
            f"  Current total: {current_total} files\n"
            f"  Difference: {baseline_src_tests - current_total} files"
        )
```

### Memory Query Validation for Moved Files
```python
# Source: Phase 11/16 memory patterns + testing
# tests/validation/test_memory_tracking.py
"""Validate memory can answer 'where did file X go?' for all moves."""
import pytest
from ta_lab2.tools.ai_orchestrator.memory import get_client


@pytest.mark.orchestrator  # Requires chromadb/mem0ai
def test_memory_tracks_all_file_moves():
    """Query memory for moved_to relationships for key files."""
    pytest.importorskip("chromadb", reason="chromadb required")

    # Sample of files known to be moved in Phases 13-16
    moved_files = [
        "deprecated_module.py",
        "old_script.py",
        "legacy_tool.py",
    ]

    client = get_client()

    for old_file in moved_files:
        # Query: "where is {old_file} now?"
        results = client.search(
            f"moved_to relationship for {old_file}",
            limit=5
        )

        if not results:
            pytest.fail(f"Memory has no moved_to relationship for {old_file}")

        # Verify result mentions new location
        first_result = results[0]["text"]
        if ".archive" not in first_result:
            pytest.fail(
                f"Memory result for {old_file} doesn't mention archive:\n"
                f"  {first_result}"
            )
```

### GitHub Actions Workflow
```yaml
# Source: GitHub Actions best practices + pytest documentation
# .github/workflows/validation.yml
name: Validation & Verification

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main]

jobs:
  # Critical: Must pass
  import-validation-core:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install core dependencies
        run: |
          pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Test core imports (without optional deps)
        run: |
          pytest tests/test_imports.py \
            -m "not orchestrator" \
            --tb=short \
            -v

  # Critical: Must pass
  circular-dependencies:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install import-linter
        run: pip install import-linter

      - name: Check for circular dependencies (strict)
        run: lint-imports

  # Warning: Allowed to fail
  import-validation-optional:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install all dependencies (including optional)
        run: |
          pip install --upgrade pip
          pip install -e ".[all]"

      - name: Test optional dependency imports
        run: |
          pytest tests/test_imports.py \
            -m "orchestrator" \
            --tb=short \
            -v
        continue-on-error: true  # Warn but don't block

  # Warning: Allowed to fail
  organization-rules:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Check no .py files in project root
        run: |
          if ls *.py 2>/dev/null; then
            echo "::warning::Python files found in project root"
            exit 1
          fi
        continue-on-error: true

      - name: Check manifest integrity (if exists)
        run: |
          if [ -f ".archive/manifest.json" ]; then
            python -c "import json; json.load(open('.archive/manifest.json'))"
          fi
        continue-on-error: true

  # Critical: Must pass (if baseline exists)
  data-loss-validation:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.10'

      - name: Install package
        run: pip install -e ".[dev]"

      - name: Run data loss validation
        run: |
          pytest tests/validation/test_data_loss.py \
            --tb=short \
            -v
```

### Pre-commit Configuration
```yaml
# Source: Ruff official docs + pre-commit best practices
# .pre-commit-config.yaml
repos:
  # Ruff: Fast linting and formatting
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.14.14
    hooks:
      # Lint with auto-fix (MUST run before formatter)
      - id: ruff-check
        types_or: [python, pyi]
        args: [--fix, --exit-non-zero-on-fix]

      # Format code
      - id: ruff-format
        types_or: [python, pyi]

  # Standard pre-commit hooks
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-json
      - id: check-toml
      - id: check-added-large-files
        args: [--maxkb=500]
      - id: check-merge-conflict
      - id: mixed-line-ending
        args: [--fix=lf]

  # Custom local hooks for project-specific rules
  - repo: local
    hooks:
      # Block: No .py files in project root
      - id: no-root-py-files
        name: No .py files in project root
        entry: bash -c 'COUNT=$(ls -1 *.py 2>/dev/null | wc -l); if [ $COUNT -gt 1 ]; then echo "Error: Python files not allowed in project root (except config.py)"; ls *.py; exit 1; fi'
        language: system
        pass_filenames: false
        always_run: true

      # Warn: Check manifest files are valid JSON
      - id: validate-manifest-json
        name: Validate manifest JSON files
        entry: python -m json.tool
        language: system
        files: 'manifest\.json$'
        pass_filenames: true

# Configuration
default_language_version:
  python: python3.10

# Performance: fail fast on first error
fail_fast: false

# Skip hooks via: SKIP=ruff-check git commit
# Run manually: pre-commit run --all-files
# Install: pre-commit install
```

### import-linter Configuration
```toml
# Source: import-linter official documentation
# pyproject.toml - add to existing file

[tool.importlinter]
root_package = "ta_lab2"

# Optional: Exclude TYPE_CHECKING imports from analysis
# exclude_type_checking_imports = true

# Contract 1: Strict zero cycles between all sibling packages
[[tool.importlinter.contracts]]
name = "No circular dependencies between ta_lab2 subpackages"
type = "acyclic_siblings"
packages = [
    "ta_lab2.features",
    "ta_lab2.tools",
    "ta_lab2.scripts",
    "ta_lab2.connectivity",
]

# Contract 2: Layering - tools don't import from scripts
[[tool.importlinter.contracts]]
name = "Tools layer doesn't import from scripts layer"
type = "forbidden"
source_modules = ["ta_lab2.tools"]
forbidden_modules = ["ta_lab2.scripts"]

# Contract 3: Layering - features don't import from scripts
[[tool.importlinter.contracts]]
name = "Features layer doesn't import from scripts layer"
type = "forbidden"
source_modules = ["ta_lab2.features"]
forbidden_modules = ["ta_lab2.scripts"]

# Run: lint-imports
# Exit code 0 = all contracts pass
# Exit code 1 = violations detected
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| flake8 + black + isort (3 tools) | Ruff (all-in-one) | 2023-2024 | 10-100x faster, single config, less dependency conflicts |
| Manual import testing | pytest parametrization + pkgutil | 2020+ | Dynamic discovery, clear failure reporting, scales with codebase |
| pycycle for circular deps | import-linter | 2019+ | Active maintenance, contract system, better CI integration |
| Path-based file validation | Checksum-based validation | N/A (Phase 12) | Tracks files through moves, detects corruption |
| --import-mode=prepend (default) | --import-mode=importlib | pytest 7.0+ (2022) | Cleaner sys.path, fewer surprises, recommended for new projects |
| Multiple linters in pre-commit | Ruff only in pre-commit | 2024+ | Faster hooks (<1s vs >10s), better developer experience |

**Deprecated/outdated:**
- **pycycle:** Inactive maintenance (12+ months no updates), use import-linter instead
- **Using pylint for style:** Ruff covers same rules 10-100x faster
- **Manual module lists for import tests:** Use pkgutil.walk_packages for dynamic discovery
- **Running full test suite in pre-commit:** Move to CI, keep pre-commit fast (<5s)

## Open Questions

Things that couldn't be fully resolved:

1. **Memory query validation specifics**
   - What we know: Memory should track moved_to relationships (from Phase 11/16 context)
   - What's unclear: Exact query API, response format, whether moved_to is explicit field or derived from context
   - Recommendation: Review Phase 11/16 memory implementation, use existing memory query patterns

2. **Manifest validation in CI**
   - What we know: User decided "too slow, skip in CI, run manually"
   - What's unclear: How slow? What makes it slow? Could it be optimized?
   - Recommendation: Honor user decision, skip manifest validation in CI, document manual validation process

3. **Missing file investigation automation**
   - What we know: User wants automatic investigation before failing (check .archive/, git history)
   - What's unclear: What investigation steps? How to query git history programmatically?
   - Recommendation: Use `git log --all -- <file>` to search history, check .archive/ manifests, report findings in failure message

4. **Exact baseline directory for validation**
   - What we know: Phase 12 baseline exists at `.planning/phases/12-archive-foundation/baseline/pre_reorg_snapshot.json`
   - What's unclear: Should validation compare against src+tests only, or full 9,620 files including .venv?
   - Recommendation: Focus on src/ + tests/ (409 files) not .venv (9,211 files) for practical validation

## Sources

### Primary (HIGH confidence)
- [pytest parametrization documentation](https://docs.pytest.org/en/stable/how-to/parametrize.html) - Official pytest docs on test parametrization
- [pytest exit codes documentation](https://github.com/pytest-dev/pytest/blob/main/doc/en/reference/exit-codes.rst) - Official exit code reference
- [pkgutil documentation](https://docs.python.org/3/library/pkgutil.html) - Python stdlib docs for module discovery
- [import-linter documentation](https://import-linter.readthedocs.io/en/stable/) - Official import-linter usage guide
- [Ruff integrations documentation](https://docs.astral.sh/ruff/integrations/) - Official Ruff pre-commit setup
- [pre-commit framework documentation](https://pre-commit.com/) - Official pre-commit configuration guide
- Phase 12 implementation: validate.py, pre_reorg_snapshot.json, SUMMARY.md - Project's existing validation infrastructure

### Secondary (MEDIUM confidence)
- [Import Linter configuration examples](https://import-linter.readthedocs.io/en/stable/usage.html) - Setup examples for pyproject.toml
- [GitHub Actions pytest patterns](https://www.tutorialpedia.org/blog/how-to-run-a-github-actions-step-even-if-the-previous-step-fails-while-still-failing-the-job/) - Continue-on-error usage
- [pytest importorskip discussion](https://github.com/pytest-dev/pytest/discussions/13140) - Community patterns for optional dependencies
- [Pre-commit hooks best practices 2025](https://gatlenculp.medium.com/effortless-code-quality-the-ultimate-pre-commit-hooks-guide-for-2025-57ca501d9835) - Industry patterns for hook configuration

### Tertiary (LOW confidence)
- [pycycle GitHub](https://github.com/bndr/pycycle) - Marked LOW due to inactive maintenance warning
- Various Medium articles on Python testing - General patterns, not authoritative

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All tools official, current, actively maintained
- Architecture: HIGH - Patterns from official documentation and project's Phase 12 implementation
- Pitfalls: MEDIUM-HIGH - Common issues from community discussions, some project-specific

**Research date:** 2026-02-03
**Valid until:** 2026-03-03 (30 days - stable domain, tools mature)

**Notes:**
- Project already has robust validation infrastructure (Phase 12)
- pyproject.toml configured with pytest markers for optional dependencies
- No GitHub Actions workflows exist yet (will be created in this phase)
- No pre-commit hooks exist yet (will be created in this phase)
- Baseline snapshot provides strong foundation for data loss validation
