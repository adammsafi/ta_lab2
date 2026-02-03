"""Dynamic import validation tests for all ta_lab2 modules.

Uses pkgutil.walk_packages for automatic discovery of all modules to test.
Replaces static test_smoke_imports.py with dynamic parametrized approach.
"""
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

    # Walk the package tree, only return leaf modules (not packages)
    for info in pkgutil.walk_packages(
        [str(package_path)], prefix=f"{package_name}.", onerror=handle_import_error
    ):
        modules.append(info.name)

    return sorted(modules)


# Discover modules at collection time (before tests run)
PROJECT_ROOT = Path(__file__).parent.parent
SRC_PATH = PROJECT_ROOT / "src"
TESTS_PATH = PROJECT_ROOT / "tests"

# Core ta_lab2 modules (excluding tools which are tested separately)
TA_LAB2_MODULES = [
    m
    for m in discover_package_modules("ta_lab2", SRC_PATH / "ta_lab2")
    if not m.startswith("ta_lab2.tools.")
]

# Tools modules (may have optional dependencies)
TOOLS_MODULES = discover_package_modules(
    "ta_lab2.tools", SRC_PATH / "ta_lab2" / "tools"
)

# Test modules
TEST_MODULES = discover_package_modules("tests", TESTS_PATH)


@pytest.mark.parametrize("module_name", TA_LAB2_MODULES)
def test_ta_lab2_module_import(module_name):
    """Test that each core ta_lab2 module can be imported."""
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"Failed to import {module_name}: {e}")


@pytest.mark.parametrize("module_name", TOOLS_MODULES)
def test_tools_module_import(module_name):
    """Test that each ta_lab2.tools module can be imported.

    Note: Some tools modules may require optional dependencies.
    Use pytest markers to skip when dependencies unavailable.
    """
    # Skip orchestrator modules if dependencies not available
    if "ai_orchestrator" in module_name:
        pytest.skip(
            f"Orchestrator module {module_name} - use @pytest.mark.orchestrator tests"
        )

    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"Failed to import {module_name}: {e}")


@pytest.mark.orchestrator
def test_orchestrator_imports():
    """Test orchestrator modules requiring chromadb/mem0ai.

    Marked with @pytest.mark.orchestrator to allow selective execution:
    - pytest -m "not orchestrator" - core tests only
    - pytest -m "orchestrator" - optional dependency tests only
    - pytest - all tests (skips orchestrator if deps missing)
    """
    # Skip if dependencies not installed
    chromadb = pytest.importorskip(
        "chromadb", reason="chromadb required for orchestrator"
    )
    mem0 = pytest.importorskip("mem0ai", reason="mem0ai required for orchestrator")

    # Now import orchestrator modules that depend on these
    orchestrator_modules = [
        "ta_lab2.tools.ai_orchestrator",
        "ta_lab2.tools.ai_orchestrator.memory",
        "ta_lab2.tools.ai_orchestrator.core",
    ]

    for module_name in orchestrator_modules:
        try:
            importlib.import_module(module_name)
        except ImportError as e:
            pytest.fail(f"Failed to import {module_name}: {e}")


@pytest.mark.parametrize("module_name", TEST_MODULES)
def test_test_module_import(module_name):
    """Test that test modules can be imported.

    This validates test files themselves don't have import issues.
    """
    try:
        importlib.import_module(module_name)
    except ImportError as e:
        pytest.fail(f"Failed to import test module {module_name}: {e}")
