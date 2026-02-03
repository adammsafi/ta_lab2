"""Validation: ensure no hardcoded absolute paths remain in migrated code."""
import ast
from pathlib import Path
import pytest


def find_hardcoded_paths(file_path: Path) -> list[tuple[int, str]]:
    """
    Scan Python file for potential hardcoded absolute paths.

    Returns list of (line_number, path_string) tuples.
    """
    source = file_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError:
        return []  # Skip files with syntax errors (will fail import tests)

    suspicious = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            val = node.value
            # Check for absolute path patterns
            if any(
                val.startswith(prefix)
                for prefix in ["C:\\", "C:/", "/home/", "/Users/", "D:\\", "E:\\"]
            ):
                # Filter out short strings (likely not paths) and URL-like patterns
                if len(val) > 10 and "://" not in val:
                    suspicious.append((node.lineno, val))

    return suspicious


def test_no_hardcoded_paths_in_migrated_modules():
    """Migrated modules must not contain hardcoded absolute paths."""
    data_tools_dir = (
        Path(__file__).parent.parent.parent.parent
        / "src"
        / "ta_lab2"
        / "tools"
        / "data_tools"
    )
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
            rel_path = file_path.relative_to(data_tools_dir.parent.parent.parent.parent)
            msg += f"\n{rel_path}:\n"
            for lineno, path in paths:
                msg += (
                    f"  Line {lineno}: {path[:50]}{'...' if len(path) > 50 else ''}\n"
                )
        pytest.fail(msg)


def test_no_sys_path_manipulation():
    """Migrated modules should not manipulate sys.path."""
    data_tools_dir = (
        Path(__file__).parent.parent.parent.parent
        / "src"
        / "ta_lab2"
        / "tools"
        / "data_tools"
    )
    python_files = list(data_tools_dir.rglob("*.py"))

    failures = []
    for py_file in python_files:
        source = py_file.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            # Check for sys.path.append() or sys.path.insert()
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("append", "insert")
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "path"
                and isinstance(node.func.value.value, ast.Name)
                and node.func.value.value.id == "sys"
            ):
                failures.append((py_file, node.lineno))

    if failures:
        msg = "Found sys.path manipulation:\n"
        for file_path, lineno in failures:
            rel_path = file_path.relative_to(data_tools_dir.parent.parent.parent.parent)
            msg += f"  {rel_path}: Line {lineno}\n"
        pytest.fail(msg)
