# Phase 14: Tools Integration - Research

**Researched:** 2026-02-02
**Domain:** Python package migration, import refactoring, script integration
**Confidence:** HIGH

## Summary

Phase 14 migrates 51 Python scripts from an external Data_Tools directory into the ta_lab2 package structure under `src/ta_lab2/tools/data_tools/`. The primary technical challenges are: (1) refactoring import paths from external scripts to package-relative imports, (2) identifying and parameterizing hardcoded absolute paths, (3) organizing scripts by functional categories, and (4) validating migrated scripts through smoke tests.

The ta_lab2 project uses **src-layout** with editable installation (`pip install -e .`), which requires all imports to use absolute package paths (`from ta_lab2.tools...`) rather than relative filesystem paths. The migration must transform standalone scripts into package modules while preserving functionality.

The Data_Tools directory contains primarily chatgpt-related memory/embedding tools (39 scripts in chatgpt/ subdirectory) plus 12 root-level utilities including code analysis tools (generate_function_map, tree_structure) and EMA database utilities (write_daily_emas, upsert_new_emas).

**Primary recommendation:** Use absolute imports from ta_lab2 namespace, organize into functional subdirectories (memory/, analysis/, database_utils/), implement AST-based hardcoded path validation, and create parametrized smoke tests that verify basic imports and entry points.

## Standard Stack

The established libraries/tools for Python package migration and testing:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | >=8.0 | Testing framework | Already in ta_lab2, industry standard for Python testing |
| pathlib | stdlib | Path manipulation | Standard library, object-oriented path handling |
| ast | stdlib | Static code analysis | Built-in, used for detecting hardcoded paths |
| argparse | stdlib | CLI argument parsing | Already used in ta_lab2 scripts, standard CLI pattern |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-parametrize | builtin | Parametrized testing | Test multiple scripts with same pattern |
| logging | stdlib | Structured logging | Standardize logging across migrated scripts |
| python-dotenv | >=1.0.0 | Environment variables | Already in ta_lab2, for config management |
| ruff | >=0.1.5 | Import sorting/linting | Already in ta_lab2 dev deps, auto-format imports |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| absolute imports | relative imports | Absolute preferred for src-layout; clearer and more resilient to refactoring |
| pathlib.Path | os.path | pathlib is modern standard (Python 3.4+), object-oriented, safer |
| argparse | click/typer | argparse already in project; click adds dependency for marginal benefit |
| AST-based detection | regex for paths | AST is more accurate, understands Python semantics vs text patterns |

**Installation:**
```bash
# All dependencies already in ta_lab2 pyproject.toml
pip install -e .  # Editable install required for src-layout
```

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/tools/data_tools/
├── __init__.py              # Public API exports
├── README.md                # Migration notes, script index
├── memory/                  # AI memory/embedding tools (from chatgpt/)
│   ├── __init__.py
│   ├── embed_codebase.py
│   ├── generate_memories.py
│   ├── memory_bank_rest.py
│   └── ...
├── analysis/                # Code analysis utilities
│   ├── __init__.py
│   ├── generate_function_map.py
│   └── tree_structure.py
└── database_utils/          # Database/EMA utilities
    ├── __init__.py
    ├── write_daily_emas.py
    └── upsert_new_emas.py

tests/tools/data_tools/
├── conftest.py              # Shared fixtures
├── test_imports_smoke.py    # Smoke test: all modules import
└── test_hardcoded_paths.py  # Validation: no hardcoded paths remain
```

### Pattern 1: Absolute Imports for Src-Layout

**What:** Use absolute package imports starting from `ta_lab2` root

**When to use:** All imports in migrated scripts, all test files

**Why:** Src-layout requires installation to run; Python includes cwd in import path which can cause shadowing issues. Absolute imports from package root prevent accidental imports of local files.

**Example:**
```python
# Source: https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/

# BEFORE (external script, relative filesystem):
import sys
sys.path.append("../../ta_lab2/src")
from ta_lab2.features import ema

# AFTER (package module, absolute import):
from ta_lab2.features.ema import compute_ema
from ta_lab2.tools.dbtool import get_connection
```

### Pattern 2: Module-Level Logger with __name__

**What:** Every module creates logger with `logging.getLogger(__name__)`

**When to use:** All migrated scripts that need logging

**Why:** Creates hierarchical logger namespace matching package structure; prevents name collisions; enables per-module log level control.

**Example:**
```python
# Source: https://docs.python-guide.org/writing/logging/
import logging

logger = logging.getLogger(__name__)  # Will be 'ta_lab2.tools.data_tools.memory.embed_codebase'

def main():
    logger.info("Starting codebase embedding")
    # ... rest of code
```

### Pattern 3: Project-Relative Paths via config.project_root()

**What:** All file paths resolved relative to project root using centralized helper

**When to use:** Any script that reads/writes files in project directories

**Why:** Avoids hardcoded absolute paths; works regardless of where script is run from; already established pattern in ta_lab2 via config.py

**Example:**
```python
# Source: ta_lab2/config.py (existing pattern)
from config import project_root
from pathlib import Path

def load_data(relative_path: str) -> Path:
    """Load file relative to project root."""
    root = project_root()
    return root / relative_path  # e.g., root / "data" / "output.csv"
```

### Pattern 4: Parametrized Smoke Tests

**What:** Use pytest.mark.parametrize to test imports for multiple modules in one test

**When to use:** Validating that all migrated scripts can be imported successfully

**Why:** Single test definition covers all modules; easy to add new modules; clear failure messages identify exactly which module failed to import.

**Example:**
```python
# Source: https://docs.pytest.org/en/stable/how-to/parametrize.html
import pytest
import importlib

MIGRATED_MODULES = [
    "ta_lab2.tools.data_tools.memory.embed_codebase",
    "ta_lab2.tools.data_tools.analysis.tree_structure",
    "ta_lab2.tools.data_tools.database_utils.write_daily_emas",
]

@pytest.mark.parametrize("module_name", MIGRATED_MODULES)
def test_module_imports(module_name):
    """Smoke test: verify migrated module can be imported."""
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"Failed to import {module_name}: {e}")
```

### Pattern 5: AST-Based Hardcoded Path Detection

**What:** Use Python's ast module to walk syntax tree and detect string literals that look like absolute paths

**When to use:** Validation step after migration to ensure no hardcoded user-specific paths remain

**Why:** More accurate than regex; understands Python context (not just text patterns); can distinguish between paths and other strings.

**Example:**
```python
# Source: https://docs.python.org/3/library/ast.html
import ast
from pathlib import Path

def detect_hardcoded_paths(file_path: Path) -> list[str]:
    """Find potential hardcoded absolute paths in Python file."""
    source = file_path.read_text()
    tree = ast.parse(source)

    suspicious_paths = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            # Check for absolute path patterns
            if val.startswith(("C:\\", "C:/", "/home/", "/Users/")) and len(val) > 10:
                suspicious_paths.append((node.lineno, val))

    return suspicious_paths
```

### Anti-Patterns to Avoid

- **Modifying sys.path in modules:** Don't use `sys.path.append()` in migrated code. Src-layout requires proper installation; sys.path hacks break packaging and testing. Use absolute imports instead.

- **Relative imports from scripts:** Don't use `from . import module` in scripts meant to run standalone. Use absolute imports like `from ta_lab2.tools.data_tools import module` which works both standalone and as imported module.

- **Hardcoded cwd assumptions:** Don't use `Path("data/file.csv")` assuming script runs from project root. Use `project_root() / "data/file.csv"` to be explicit and portable.

- **Mixing argparse with config.py directly:** Don't import Settings in argparse-based scripts. Instead, pass paths/values as CLI args and let the script build what it needs, or use environment variables that config.py already reads.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Import validation | Manual try/except imports | pytest + importlib | pytest-parametrize tests all modules systematically; importlib is stdlib; explicit test failures |
| Path normalization | Custom path resolution logic | config.project_root() + pathlib | Already established in ta_lab2; handles edge cases (symlinks, relative paths); pathlib is safer than string manipulation |
| Hardcoded path detection | Regex on source text | ast module traversal | AST understands Python semantics; avoids false positives from strings in comments/docstrings; can check context (variable names, assignments) |
| Logging configuration | Per-script logging setup | getLogger(__name__) + centralized config | Hierarchical namespace automatic; single place to configure formats/handlers; supports per-module log levels |
| Import sorting | Manual organization | ruff or isort | Already in ta_lab2 dev deps; enforces PEP 8 ordering (stdlib, third-party, local); automatic grouping and sorting |

**Key insight:** Python packaging and testing has mature tooling; resist the temptation to write custom validation scripts when pytest + stdlib tools handle it better. The ast module in particular is powerful for static analysis but underused—it's the right tool for detecting hardcoded paths, not regex.

## Common Pitfalls

### Pitfall 1: Import Failures Due to Missing Editable Install

**What goes wrong:** Scripts fail with `ModuleNotFoundError: No module named 'ta_lab2'` after migration.

**Why it happens:** Src-layout requires `pip install -e .` to make package importable. Running scripts directly from repo root without installation won't work because Python can't find the ta_lab2 package.

**How to avoid:**
- Always run `pip install -e .` after cloning/pulling repo
- Document in README that editable install is required
- Add check in tests: `pytest.importorskip("ta_lab2")` at top of test files

**Warning signs:**
- Imports work from project root but fail from subdirectories
- Tests pass locally but fail in CI (forgot to install package in CI config)

### Pitfall 2: Hardcoded Paths Slip Through Text-Based Checks

**What goes wrong:** Path validation passes but scripts still have hardcoded paths like `C:\Users\asafi\...` that break for other users.

**Why it happens:** Regex-based checks miss paths in f-strings, Path() constructors, or multi-line strings. String matches also trigger false positives on URLs, hex strings, etc.

**How to avoid:**
- Use AST traversal to check all string literals in proper context
- Test validation script itself: create test files with known hardcoded paths and verify detection
- Check multiple patterns: Windows (`C:\`), Linux (`/home/`), Mac (`/Users/`)
- Flag for manual review: any string literal containing username or home directory markers

**Warning signs:**
- Validation script reports "all clear" but manual inspection finds hardcoded paths
- Scripts work for developer but fail immediately for others with "file not found"

### Pitfall 3: Circular Import Deadlocks After Restructuring

**What goes wrong:** Import errors like `ImportError: cannot import name 'X' from partially initialized module` appear after moving code.

**Why it happens:** Module A imports from B, B imports from A. In external scripts this worked because imports were sequential; in package structure, Python detects the cycle.

**How to avoid:**
- Keep imports at top of file (not inside functions unless breaking cycle)
- Refactor shared code into separate utility module
- Use dependency injection: pass instances as parameters rather than importing everywhere
- Review: if two modules import each other, one depends on the other—make hierarchy clear

**Warning signs:**
- Import works in Python REPL but fails when running script
- Error message mentions "partially initialized module"
- Removing one import fixes it, but functionality breaks

### Pitfall 4: Test Discovery Misses Migrated Script Tests

**What goes wrong:** Pytest runs but doesn't find tests for migrated scripts; coverage is incomplete.

**Why it happens:** Test file naming doesn't follow pytest conventions (`test_*.py` or `*_test.py`), or test functions don't start with `test_`.

**How to avoid:**
- Follow pytest naming: `test_<module_name>.py` for test files
- Name functions: `test_<what_it_tests>()`
- Use `pytest --collect-only` to see what pytest discovers
- Check conftest.py doesn't override collection rules in unexpected ways

**Warning signs:**
- Running pytest shows fewer tests than expected
- Tests exist but don't appear in pytest output
- Coverage report shows migrated modules as untested despite test files existing

### Pitfall 5: Module Exports Not Defined, Breaking External Imports

**What goes wrong:** After migration, imports like `from ta_lab2.tools.data_tools import embed_codebase` fail even though the module exists.

**Why it happens:** Missing `__init__.py` exports. Python allows directory imports only if `__init__.py` explicitly exports names or if using `from ta_lab2.tools.data_tools.memory import embed_codebase` (full path).

**How to avoid:**
- Define `__all__` in each `__init__.py` to control public API
- For nested packages, re-export key functions at higher levels for convenience
- Use absolute imports internally; let `__init__.py` handle external interface
- Test import patterns you expect users to use

**Warning signs:**
- Import works with full path but fails with shorter path
- `from package import *` imports nothing or unexpected items
- IDE autocomplete doesn't show expected functions after `from ... import`

## Code Examples

Verified patterns from official sources:

### Example 1: Module Migration Template

Complete transformation of standalone script to package module:

```python
# BEFORE: Data_Tools/chatgpt/embed_codebase.py
#!/usr/bin/env python3
import sys
import os
sys.path.append("../../ta_lab2/src")  # Fragile path hack

from openai import OpenAI
import logging

# Hardcoded paths
OUTPUT_DIR = "C:\\Users\\asafi\\Downloads\\Data_Tools\\artifacts"
logging.basicConfig(level=logging.INFO)

def embed_codebase(root_path: str):
    # ... implementation ...
    pass

if __name__ == "__main__":
    embed_codebase("/some/path")


# AFTER: src/ta_lab2/tools/data_tools/memory/embed_codebase.py
"""Codebase embedding tool for AI memory systems."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Any

from config import project_root

try:
    from openai import OpenAI
except ImportError:
    raise ImportError(
        "OpenAI library required. Install with: pip install 'ta_lab2[orchestrator]'"
    )

logger = logging.getLogger(__name__)  # Hierarchical logger


def embed_codebase(root_path: Path, output_dir: Path | None = None) -> list[dict[str, Any]]:
    """
    Generate embeddings for codebase files.

    Args:
        root_path: Root directory to scan for code files
        output_dir: Where to write embeddings; defaults to artifacts/embeddings

    Returns:
        List of embedding records
    """
    if output_dir is None:
        output_dir = project_root() / "artifacts" / "embeddings"

    output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Embedding codebase from {root_path} to {output_dir}")

    # ... implementation ...
    return []


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Embed codebase for AI memory")
    parser.add_argument("root_path", type=Path, help="Root directory to scan")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output directory (default: artifacts/embeddings)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    results = embed_codebase(args.root_path, args.output_dir)
    logger.info(f"Generated {len(results)} embeddings")


if __name__ == "__main__":
    main()
```

Key changes:
- Removed `sys.path` manipulation
- Changed to absolute imports (`from config import project_root`)
- Replaced hardcoded paths with Path objects and project_root()
- Added module-level logger with `__name__`
- Made functions testable (return values, default arguments)
- Added type hints for clarity
- Separated CLI logic (main) from core logic (embed_codebase)

### Example 2: Package __init__.py with Selective Exports

```python
# src/ta_lab2/tools/data_tools/__init__.py
"""
Data tools migrated from external Data_Tools directory.

Organized by function:
- memory: AI memory/embedding tools
- analysis: Code analysis utilities
- database_utils: Database/EMA utilities
"""
from ta_lab2.tools.data_tools.analysis.generate_function_map import (
    generate_function_map,
    FunctionInfo,
)
from ta_lab2.tools.data_tools.analysis.tree_structure import (
    generate_tree_structure,
    print_tree,
)

# Memory tools are complex; expose submodule
from ta_lab2.tools.data_tools import memory

__all__ = [
    # Analysis tools
    "generate_function_map",
    "FunctionInfo",
    "generate_tree_structure",
    "print_tree",
    # Memory submodule
    "memory",
]
```

### Example 3: Parametrized Import Smoke Tests

```python
# tests/tools/data_tools/test_imports_smoke.py
"""Smoke tests: verify all migrated data_tools modules import successfully."""
import importlib
import pytest

# Source: https://docs.pytest.org/en/stable/how-to/parametrize.html

MEMORY_MODULES = [
    "ta_lab2.tools.data_tools.memory.embed_codebase",
    "ta_lab2.tools.data_tools.memory.generate_memories_from_code",
    "ta_lab2.tools.data_tools.memory.memory_bank_rest",
]

ANALYSIS_MODULES = [
    "ta_lab2.tools.data_tools.analysis.generate_function_map",
    "ta_lab2.tools.data_tools.analysis.tree_structure",
]

DATABASE_MODULES = [
    "ta_lab2.tools.data_tools.database_utils.write_daily_emas",
    "ta_lab2.tools.data_tools.database_utils.upsert_new_emas",
]

ALL_MODULES = MEMORY_MODULES + ANALYSIS_MODULES + DATABASE_MODULES


@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_module_imports_successfully(module_name):
    """Smoke test: each migrated module can be imported without errors."""
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"Failed to import {module_name}: {e}")


@pytest.mark.parametrize("module_name", ALL_MODULES)
def test_module_has_docstring(module_name):
    """Each module should have a docstring explaining its purpose."""
    module = importlib.import_module(module_name)
    assert module.__doc__ is not None, f"{module_name} missing docstring"
    assert len(module.__doc__.strip()) > 10, f"{module_name} docstring too short"
```

### Example 4: AST-Based Hardcoded Path Validation

```python
# tests/tools/data_tools/test_hardcoded_paths.py
"""Validation: ensure no hardcoded absolute paths remain in migrated code."""
import ast
from pathlib import Path
import pytest

# Source: https://docs.python.org/3/library/ast.html

def find_hardcoded_paths(file_path: Path) -> list[tuple[int, str]]:
    """
    Scan Python file for potential hardcoded absolute paths.

    Returns list of (line_number, path_string) tuples.
    """
    source = file_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(file_path))

    suspicious = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            # Check for absolute path patterns
            if any(val.startswith(prefix) for prefix in ["C:\\", "C:/", "/home/", "/Users/"]):
                # Filter out short strings (likely not paths) and comments
                if len(val) > 10:
                    suspicious.append((node.lineno, val))

    return suspicious


def test_no_hardcoded_paths_in_migrated_modules():
    """Migrated modules must not contain hardcoded absolute paths."""
    data_tools_dir = Path(__file__).parent.parent.parent / "src" / "ta_lab2" / "tools" / "data_tools"
    python_files = list(data_tools_dir.rglob("*.py"))

    assert len(python_files) > 0, "No Python files found in data_tools"

    failures = []
    for py_file in python_files:
        if py_file.name == "__init__.py":
            continue  # __init__.py files often have import path strings

        hardcoded = find_hardcoded_paths(py_file)
        if hardcoded:
            failures.append((py_file, hardcoded))

    if failures:
        msg = "Found hardcoded absolute paths:\n"
        for file_path, paths in failures:
            msg += f"\n{file_path}:\n"
            for lineno, path in paths:
                msg += f"  Line {lineno}: {path}\n"
        pytest.fail(msg)


def test_all_paths_use_pathlib():
    """Migrated modules should use pathlib.Path, not string manipulation."""
    data_tools_dir = Path(__file__).parent.parent.parent / "src" / "ta_lab2" / "tools" / "data_tools"
    python_files = list(data_tools_dir.rglob("*.py"))

    for py_file in python_files:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Check if file uses pathlib
        imports_pathlib = any(
            isinstance(node, ast.ImportFrom) and node.module == "pathlib"
            for node in ast.walk(tree)
        )

        # Check if file manipulates paths (has os.path or file operations)
        has_path_operations = any(
            isinstance(node, ast.Call) and
            isinstance(node.func, ast.Attribute) and
            isinstance(node.func.value, ast.Name) and
            node.func.value.id in ["os"]
            for node in ast.walk(tree)
        )

        if has_path_operations and not imports_pathlib:
            pytest.fail(
                f"{py_file.name} uses path operations but doesn't import pathlib. "
                "Use pathlib.Path instead of os.path for modern path handling."
            )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| setup.py + requirements.txt | pyproject.toml with PEP 517/518 | ~2020-2022 | Single source of truth; standardized metadata; better tooling integration |
| Relative imports in scripts | Absolute imports from package root | Ongoing (src-layout adoption) | Clearer dependencies; works with editable install; prevents import shadowing |
| os.path string manipulation | pathlib.Path objects | Python 3.4+ (2014), mainstream 2020+ | Object-oriented; safer (explicit vs implicit); cross-platform by default |
| print() debugging | logging module with hierarchical loggers | Long-standing best practice | Configurable; filterable; production-ready; structured output |
| Manual test discovery | pytest auto-discovery + markers | pytest 2.0+ (mainstream) | Less boilerplate; conventional naming; powerful filtering via markers |

**Deprecated/outdated:**
- `python setup.py test`: Deprecated in setuptools; use pytest directly
- `from __future__ import absolute_import`: No longer needed in Python 3 (all imports absolute by default)
- `pkg_resources` for resource loading: Replaced by `importlib.resources` in Python 3.9+
- Flat layout without src/: Still works but src-layout is best practice for libraries/packages

## Open Questions

Things that couldn't be fully resolved:

1. **Data_Tools chatgpt/ subdirectory purpose and dependencies**
   - What we know: 39 of 51 scripts are in chatgpt/ subdirectory; many relate to memory/embedding operations; some reference OpenAI, ChromaDB, mem0
   - What's unclear: Which scripts are still actively used vs experimental? What external dependencies are required? Are there service dependencies (databases, vector stores)?
   - Recommendation: During migration, inspect each script's imports and docstrings; categorize as "migrate" vs "archive" based on: (1) presence of test/temp/experimental in name, (2) references to current ta_lab2 functionality, (3) last modified date. Default to migrate if uncertain.

2. **Optimal functional grouping strategy**
   - What we know: Preliminary categories are memory/, analysis/, database_utils/ based on quick scan
   - What's unclear: Whether chatgpt scripts should all go in memory/ or split further (embeddings/, conversation/, training_data/)? Whether 3 categories enough or need more granular split?
   - Recommendation: Start with 3 top-level categories; add subcategories if any category exceeds 10 modules. Can refactor later if structure proves unwieldy.

3. **Testing depth for complex scripts**
   - What we know: Smoke tests (import validation) are baseline; complex scripts may need functional tests
   - What's unclear: Which scripts are "complex enough" to justify beyond-smoke-test validation? What constitutes passing functional test for data processing script?
   - Recommendation: Phase 14 focuses on smoke tests only; functional test gaps become post-phase tasks. Mark scripts with external dependencies (OpenAI, databases) as needing deeper testing in gap closure plan.

4. **External dependency installation**
   - What we know: Some scripts import openai, chromadb, flask; ta_lab2 has [orchestrator] optional group with some of these
   - What's unclear: Should all Data_Tools dependencies go in [orchestrator] or new [data_tools] group? How to handle scripts with unique dependencies (flask, yoyo-migrations)?
   - Recommendation: Add dependencies to existing [orchestrator] group if memory/AI-related; create [data_tools] group only if scripts need dependencies orthogonal to orchestrator. Use try/except ImportError with helpful message pointing to install command.

## Sources

### Primary (HIGH confidence)
- [Python Packaging - src layout vs flat layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/) - Official Python packaging guide on src-layout advantages and import patterns
- [pytest - Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html) - Official pytest documentation on src-layout, test organization, import modes
- [Python ast module](https://docs.python.org/3/library/ast.html) - Official Python stdlib documentation for abstract syntax tree traversal
- [Python logging HOWTO](https://docs.python.org/3/howto/logging.html) - Official guide on logging best practices including getLogger(__name__)

### Secondary (MEDIUM confidence)
- [Python Logging Best Practices 2026](https://www.carmatec.com/blog/python-logging-best-practices-complete-guide/) - Comprehensive guide confirming getLogger(__name__) pattern and centralized config
- [Better Stack - Python Logging Best Practices](https://betterstack.com/community/guides/logging/python/python-logging-best-practices/) - Industry guide on module-level loggers and avoiding root logger
- [Real Python - Absolute vs Relative Imports](https://realpython.com/absolute-vs-relative-python-imports/) - Tutorial explaining when to use each import style
- [pytest parametrize documentation](https://docs.pytest.org/en/stable/how-to/parametrize.html) - Official guide on parametrized testing patterns
- [Python Packaging Best Practices 2026](https://dasroot.net/posts/2026/01/python-packaging-best-practices-setuptools-poetry-hatch/) - Recent overview of modern packaging tools and pyproject.toml standards

### Secondary (MEDIUM confidence - continued)
- [SQLPad - Absolute vs Relative Python Imports](https://sqlpad.io/tutorial/absolute-vs-relative-python-imports/) - Tutorial on import patterns for package organization
- [ArjanCodes - Organizing Python Code](https://arjancodes.com/blog/organizing-python-code-with-packages-and-modules/) - Best practices for functional grouping and module structure
- [Real Python - Python Path Guide](https://docs.python-guide.org/writing/structure/) - Hitchhiker's Guide patterns for project structure

### Tertiary (LOW confidence)
- [pytest-smoke plugin](https://pypi.org/project/pytest-smoke/) - Plugin for running smoke test subsets; pattern reference
- [package-smoke-test](https://pypi.org/project/package-smoke-test/) - Simple import verification tool; demonstrates smoke test concept
- [DeepSource - Python ASTs by Building Your Own Linter](https://deepsource.com/blog/python-asts-by-building-your-own-linter) - Tutorial on AST-based static analysis patterns
- [Bandit security tool](https://github.com/PyCQA/bandit) - Uses AST to detect security issues including hardcoded credentials; pattern reference for path detection

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All recommendations based on ta_lab2's existing dependencies and official Python/pytest docs
- Architecture: HIGH - Patterns from official packaging guides and verified in ta_lab2's existing code (config.py, tools/ structure)
- Pitfalls: HIGH - Common issues documented in official pytest/packaging guides and observed in project's existing patterns
- Data_Tools specifics: MEDIUM - Limited documentation in Data_Tools directory; conclusions drawn from file inspection and naming patterns

**Research date:** 2026-02-02
**Valid until:** 2026-03-02 (30 days; Python packaging standards stable, pytest patterns well-established)

**Notes:**
- Data_Tools inspection revealed 51 scripts with ~76% (39) in chatgpt/ subdirectory focused on AI memory/embedding
- ta_lab2 already uses src-layout with editable install, which simplifies migration (no layout conversion needed)
- Project has established patterns in config.py (project_root(), pathlib usage) and tools/ (archive, docs, ai_orchestrator) that migrated code should match
- Phase 13 (Documentation Consolidation) provides precedent for tools/ organization and memory update patterns
