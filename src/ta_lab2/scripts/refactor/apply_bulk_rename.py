"""Apply bulk cmc_ prefix renames across the entire Python/SQL codebase.

Usage:
    python -m ta_lab2.scripts.refactor.apply_bulk_rename [--dry-run]

Replaces all cmc_ table name references with stripped names, longest-first
to prevent partial matches. Skips alembic/versions/, old/, .git/, .planning/.

With --dry-run: reports changes without writing files.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ta_lab2.scripts.refactor.rename_cmc_prefix import (
    TABLE_RENAME_MAP,
    VIEW_RENAME_MAP,
    MATVIEW_RENAME_MAP,
    apply_renames_to_content,
)

PROJECT_ROOT = Path(__file__).resolve().parents[4]

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
    ".memory",
    ".archive",
}

SKIP_FILES = {
    "rename_cmc_prefix.py",
    "verify_rename_completeness.py",
    "apply_bulk_rename.py",
    "fix_cmc.txt",
}

EXTENSIONS = {".py", ".sql", ".yaml", ".yml", ".toml"}


def main() -> int:
    dry_run = "--dry-run" in sys.argv

    total_files = 0
    total_changes = 0

    for ext in EXTENSIONS:
        for path in PROJECT_ROOT.rglob(f"*{ext}"):
            # Skip directories
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            parts = rel.split("/")
            if any(skip in parts for skip in SKIP_DIRS):
                continue
            if path.name in SKIP_FILES:
                continue

            try:
                content = path.read_text(encoding="utf-8")
            except Exception:
                continue

            new_content = apply_renames_to_content(content)

            if new_content != content:
                total_files += 1
                # Count actual replacements
                changes = sum(content.count(old) for old in TABLE_RENAME_MAP)
                changes += sum(content.count(old) for old in VIEW_RENAME_MAP)
                changes += sum(content.count(old) for old in MATVIEW_RENAME_MAP)
                total_changes += changes

                if dry_run:
                    print(f"  WOULD CHANGE: {rel} ({changes} replacements)")
                else:
                    path.write_text(new_content, encoding="utf-8")
                    print(f"  CHANGED: {rel} ({changes} replacements)")

    print(f"\n{'=' * 60}")
    verb = "Would change" if dry_run else "Changed"
    print(f"  {verb} {total_files} files with {total_changes} total replacements")

    if dry_run:
        print("  (Run without --dry-run to apply changes)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
