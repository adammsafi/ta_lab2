"""Test for circular dependencies using import-linter.

Runs lint-imports command and fails if any circular imports detected.
Configuration is in pyproject.toml [tool.importlinter] section.
"""
import subprocess
import pytest


def test_no_circular_dependencies():
    """Run import-linter to detect circular dependencies.

    Fails if any circular imports detected. Configuration in pyproject.toml.
    Uses strict zero-cycle policy - no exceptions even for TYPE_CHECKING blocks.
    """
    # Check if import-linter is installed
    try:
        import importlinter
    except ImportError:
        pytest.skip("import-linter not installed (pip install import-linter)")

    # Use lint-imports command instead of python -m importlinter
    # (importlinter doesn't have __main__ module)
    result = subprocess.run(
        ["lint-imports"],
        capture_output=True,
        text=True,
        shell=True,  # Required on Windows to find lint-imports in PATH
        cwd=".",  # Run from project root
    )

    if result.returncode != 0:
        # import-linter found violations
        pytest.fail(
            f"Circular dependencies detected:\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )
