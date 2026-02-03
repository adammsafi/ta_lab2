"""Migration tool for detecting old economic package imports.

Scans Python files for imports from archived fredtools2/fedtools2 packages
and suggests replacements with ta_lab2.integrations.economic.

Usage:
    python -m ta_lab2.integrations.economic.migration_tool /path/to/code
    python -m ta_lab2.integrations.economic.migration_tool .  # Current directory
"""
import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set


@dataclass
class ImportIssue:
    """An import that needs migration."""
    file_path: Path
    line_number: int
    import_text: str
    old_module: str
    suggested_replacement: str


# Mapping of old imports to new imports
MIGRATION_MAP = {
    # fredtools2 imports
    "fredtools2": "ta_lab2.integrations.economic",
    "fredtools2.config": "os (use os.getenv('FRED_API_KEY'))",
    "fredtools2.fred_api": "ta_lab2.integrations.economic.FredProvider",
    "fredtools2.db": "sqlalchemy or pandas.to_sql",
    "fredtools2.jobs.releases": "ta_lab2.integrations.economic.FredProvider.get_releases",
    "fredtools2.jobs.series": "ta_lab2.integrations.economic.FredProvider.get_series",

    # fedtools2 imports
    "fedtools2": "ta_lab2.utils.economic",
    "fedtools2.etl": "ta_lab2.utils.economic (extract TARGET_MID logic manually)",
    "fedtools2.utils.consolidation": "ta_lab2.utils.economic.combine_timeframes",
    "fedtools2.utils.io": "ta_lab2.utils.economic.read_csv, ensure_dir",
    "fedtools2.sql_sink_example": "pandas.to_sql or sqlalchemy",
}


def scan_file_for_imports(file_path: Path) -> List[ImportIssue]:
    """Scan a Python file for old package imports.

    Args:
        file_path: Path to Python file

    Returns:
        List of ImportIssue objects for problematic imports
    """
    issues = []

    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)
    except (SyntaxError, UnicodeDecodeError) as e:
        # Skip files that can't be parsed
        return issues

    for node in ast.walk(tree):
        # Check import statements: import fredtools2
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name
                if module_name.startswith(("fredtools2", "fedtools2")):
                    replacement = _get_replacement(module_name)
                    issues.append(ImportIssue(
                        file_path=file_path,
                        line_number=node.lineno,
                        import_text=f"import {module_name}",
                        old_module=module_name,
                        suggested_replacement=replacement,
                    ))

        # Check from imports: from fredtools2 import ...
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith(("fredtools2", "fedtools2")):
                module_name = node.module
                replacement = _get_replacement(module_name)
                names = ", ".join(alias.name for alias in node.names)
                issues.append(ImportIssue(
                    file_path=file_path,
                    line_number=node.lineno,
                    import_text=f"from {module_name} import {names}",
                    old_module=module_name,
                    suggested_replacement=replacement,
                ))

    return issues


def _get_replacement(module_name: str) -> str:
    """Get suggested replacement for an old module."""
    # Check exact match first
    if module_name in MIGRATION_MAP:
        return MIGRATION_MAP[module_name]

    # Check prefix matches
    for old, new in MIGRATION_MAP.items():
        if module_name.startswith(old):
            return new

    return "ta_lab2.integrations.economic (check ALTERNATIVES.md)"


def scan_directory(
    directory: Path,
    recursive: bool = True,
    exclude_patterns: Optional[Set[str]] = None
) -> List[ImportIssue]:
    """Scan a directory for Python files with old imports.

    Args:
        directory: Directory to scan
        recursive: Whether to scan subdirectories
        exclude_patterns: Directory names to skip (e.g., {"__pycache__", ".venv"})

    Returns:
        List of all ImportIssue objects found
    """
    if exclude_patterns is None:
        exclude_patterns = {"__pycache__", ".venv", ".git", "node_modules", ".archive"}

    all_issues = []
    pattern = "**/*.py" if recursive else "*.py"

    for py_file in directory.glob(pattern):
        # Skip excluded directories
        if any(excluded in py_file.parts for excluded in exclude_patterns):
            continue

        issues = scan_file_for_imports(py_file)
        all_issues.extend(issues)

    return all_issues


def format_report(issues: List[ImportIssue], verbose: bool = False) -> str:
    """Format issues as a readable report.

    Args:
        issues: List of ImportIssue objects
        verbose: Include detailed replacement suggestions

    Returns:
        Formatted report string
    """
    if not issues:
        return "No deprecated imports found. Your code is ready!"

    lines = [
        "=" * 60,
        "ECONOMIC DATA MIGRATION REPORT",
        "=" * 60,
        f"\nFound {len(issues)} deprecated import(s):\n",
    ]

    # Group by file
    by_file = {}
    for issue in issues:
        file_key = str(issue.file_path)
        if file_key not in by_file:
            by_file[file_key] = []
        by_file[file_key].append(issue)

    for file_path, file_issues in sorted(by_file.items()):
        lines.append(f"\n{file_path}")
        lines.append("-" * len(file_path))

        for issue in file_issues:
            lines.append(f"  Line {issue.line_number}: {issue.import_text}")
            if verbose:
                lines.append(f"    -> Replace with: {issue.suggested_replacement}")

    lines.extend([
        "\n" + "=" * 60,
        "MIGRATION STEPS:",
        "=" * 60,
        "1. Install new dependencies: pip install ta_lab2[fred]",
        "2. Update imports as suggested above",
        "3. Set FRED_API_KEY environment variable",
        "4. See docs/migration/ECONOMIC_DATA.md for detailed guide",
        "",
    ])

    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point for migration tool.

    Args:
        argv: Command line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code (0 = no issues or informational, 1 = issues found)
    """
    parser = argparse.ArgumentParser(
        description="Scan code for deprecated fredtools2/fedtools2 imports"
    )
    parser.add_argument(
        "path",
        type=Path,
        help="File or directory to scan"
    )
    parser.add_argument(
        "-r", "--recursive",
        action="store_true",
        default=True,
        help="Scan directories recursively (default: True)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed replacement suggestions"
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        help="Don't scan subdirectories"
    )

    args = parser.parse_args(argv)

    path = args.path.resolve()
    recursive = args.recursive and not args.no_recursive

    if path.is_file():
        issues = scan_file_for_imports(path)
    elif path.is_dir():
        issues = scan_directory(path, recursive=recursive)
    else:
        print(f"Error: {path} does not exist", file=sys.stderr)
        return 1

    report = format_report(issues, verbose=args.verbose)
    print(report)

    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
