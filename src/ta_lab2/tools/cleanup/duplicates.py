"""Duplicate file detection via SHA256 checksums.

Provides tools for finding exact duplicate files across the codebase
using content-based hashing, not filename or path comparison.

Example:
    >>> from ta_lab2.tools.cleanup import find_duplicates
    >>> duplicates = find_duplicates(Path("."), pattern="**/*.py")
    >>> print(f"Found {len(duplicates)} duplicate groups")
"""
from pathlib import Path
from collections import defaultdict
import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Optional

# Import existing archive checksum function
from ta_lab2.tools.archive import compute_file_checksum

# Directories to exclude from scanning
EXCLUDE_DIRS = {".git", ".venv", ".venv311", "__pycache__", ".pytest_cache", "node_modules"}


@dataclass
class DuplicateGroup:
    """Group of files with identical content."""
    sha256: str
    size_bytes: int
    files: list[Path] = field(default_factory=list)
    canonical: Optional[Path] = None  # Preferred file to keep

    def __str__(self) -> str:
        return f"DuplicateGroup({len(self.files)} files, {self.size_bytes:,} bytes, sha256={self.sha256[:16]}...)"


def find_duplicates(
    root: Path,
    pattern: str = "**/*",
    min_size: int = 1,
    exclude_dirs: set[str] | None = None
) -> dict[str, DuplicateGroup]:
    """Find duplicate files by SHA256 hash.

    Args:
        root: Root directory to scan
        pattern: Glob pattern for files to include
        min_size: Minimum file size in bytes (skip tiny files)
        exclude_dirs: Directory names to exclude (defaults to EXCLUDE_DIRS)

    Returns:
        Dict mapping SHA256 hash to DuplicateGroup for files with duplicates
    """
    exclude = exclude_dirs or EXCLUDE_DIRS
    hash_to_files: dict[str, list[tuple[Path, int]]] = defaultdict(list)

    for file_path in root.glob(pattern):
        # Skip directories
        if not file_path.is_file():
            continue

        # Skip excluded directories
        if any(part in exclude for part in file_path.parts):
            continue

        # Skip small files
        try:
            size = file_path.stat().st_size
            if size < min_size:
                continue
        except OSError:
            continue

        # Hash file
        try:
            file_hash = compute_file_checksum(file_path)
            hash_to_files[file_hash].append((file_path, size))
        except (OSError, IOError):
            continue

    # Build DuplicateGroup for hashes with multiple files
    duplicates = {}
    for file_hash, files in hash_to_files.items():
        if len(files) >= 2:
            # Sort by path for consistent ordering
            files.sort(key=lambda x: str(x[0]))
            group = DuplicateGroup(
                sha256=file_hash,
                size_bytes=files[0][1],
                files=[f[0] for f in files]
            )
            # Prefer src/ file as canonical
            src_files = [f for f in group.files if "src" in f.parts]
            group.canonical = src_files[0] if src_files else group.files[0]
            duplicates[file_hash] = group

    return duplicates


def generate_duplicate_report(duplicates: dict[str, DuplicateGroup]) -> dict:
    """Generate JSON-serializable report of duplicates.

    Returns:
        Report dict with summary and duplicate groups categorized by type
    """
    report = {
        "$schema": "https://ta_lab2.local/schemas/duplicate-report/v1.0.0",
        "version": "1.0.0",
        "summary": {
            "total_duplicate_groups": len(duplicates),
            "total_duplicate_files": sum(len(g.files) for g in duplicates.values()),
            "total_wasted_bytes": sum(g.size_bytes * (len(g.files) - 1) for g in duplicates.values())
        },
        "src_canonical": [],  # Duplicates where src/ copy is canonical
        "non_src_duplicates": [],  # Duplicates with no src/ copy
    }

    for sha256, group in duplicates.items():
        entry = {
            "sha256": sha256,
            "size_bytes": group.size_bytes,
            "canonical": str(group.canonical),
            "duplicates": [str(f) for f in group.files if f != group.canonical]
        }

        if any("src" in f.parts for f in group.files):
            report["src_canonical"].append(entry)
        else:
            report["non_src_duplicates"].append(entry)

    return report
