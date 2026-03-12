"""Verify that cmc_ prefix stripping is complete.

Scans the codebase for remaining cmc_ references that should have been renamed.
Filters out:
- alembic/versions/ (historical migrations, never modify)
- old/ directories (archived code, never modify)
- Excluded tables (genuinely CMC-only, keep cmc_ prefix)
- This file and rename_cmc_prefix.py (tooling itself)

Usage:
    python -m ta_lab2.scripts.refactor.verify_rename_completeness
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from ta_lab2.scripts.refactor.rename_cmc_prefix import (
    EXCLUDED_TABLES,
    TABLE_RENAME_MAP,
)

# Root of the project
PROJECT_ROOT = (
    Path(__file__).resolve().parents[4]
)  # src/ta_lab2/scripts/refactor -> project root
SRC_ROOT = PROJECT_ROOT / "src"

# Directories to skip entirely
SKIP_DIRS = {
    "alembic",
    "old",
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".planning",
    "node_modules",
    ".claude",
    ".archive",
    "artifacts",
    ".logs",
    "reports",
    "gemini",
    "migration",
}

# Files to skip (tooling itself)
SKIP_FILES = {
    "rename_cmc_prefix.py",
    "verify_rename_completeness.py",
    "fix_cmc.txt",
    "apply_bulk_rename.py",
}

# Additional directories to skip
SKIP_SUBDIRS = {
    "artifacts",
    ".logs",
    "docs/guides/manual_parts",
}

# Patterns that are OK to have cmc_ (excluded tables, legitimate references)
OK_PATTERNS = set()
for t in EXCLUDED_TABLES:
    OK_PATTERNS.add(t)

# Also allow cmc_da_ids, cmc_price_histories7 etc in any context
OK_REGEX = re.compile(
    r"cmc_(?:da_ids|da_info|exchange_map|exchange_info|price_histories7)"
)

# Pattern to find cmc_ table-like references
CMC_REF_PATTERN = re.compile(r"\bcmc_[a-z_]+\b")


def _should_skip(path: Path) -> bool:
    parts = path.relative_to(PROJECT_ROOT).as_posix().split("/")
    for skip_dir in SKIP_DIRS:
        if skip_dir in parts or any(p == skip_dir for p in parts):
            return True
    if path.name in SKIP_FILES:
        return True
    return False


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    """Scan a file for unexpected cmc_ references. Returns (line_no, match, line)."""
    hits: list[tuple[int, str, str]] = []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return hits

    for line_no, line in enumerate(content.splitlines(), 1):
        for m in CMC_REF_PATTERN.finditer(line):
            ref = m.group(0)
            # Skip excluded tables
            if OK_REGEX.match(ref):
                continue
            # Skip if it's a known old name that should have been renamed
            if ref in TABLE_RENAME_MAP:
                hits.append((line_no, ref, line.strip()))
    return hits


def main() -> int:
    extensions = {
        ".py",
        ".sql",
        ".md",
        ".yaml",
        ".yml",
        ".toml",
        ".cfg",
        ".ini",
        ".txt",
    }
    total_hits = 0
    files_with_hits = 0

    for ext in extensions:
        for path in PROJECT_ROOT.rglob(f"*{ext}"):
            if _should_skip(path):
                continue
            hits = scan_file(path)
            if hits:
                files_with_hits += 1
                rel = path.relative_to(PROJECT_ROOT)
                print(f"\n  {rel}")
                for line_no, ref, line in hits:
                    print(f"    L{line_no}: {ref}")
                    print(f"      {line[:120]}")
                    total_hits += 1

    print(f"\n{'=' * 60}")
    if total_hits == 0:
        print("  OK: No unexpected cmc_ references found.")
        return 0
    else:
        print(
            f"  FAIL: {total_hits} unexpected cmc_ references in {files_with_hits} files."
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
