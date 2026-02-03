"""Validation tools for zero data loss during archive operations.

Provides functions for creating filesystem snapshots before operations
and validating that no data was lost after operations complete.
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ta_lab2.tools.archive.types import ValidationSnapshot
from ta_lab2.tools.archive.manifest import compute_file_checksum

logger = logging.getLogger(__name__)

# Default patterns for different file types
DEFAULT_PATTERNS = {
    "python": "**/*.py",
    "all_code": "**/*.py",
    "documentation": "**/*.md",
    "configs": "**/*.{json,yaml,yml,toml}",
}

# Directories to exclude from checksumming
EXCLUDE_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "*.egg-info",
}


def should_exclude(path: Path) -> bool:
    """Check if a path should be excluded from snapshot.

    Args:
        path: Path to check

    Returns:
        True if path should be excluded
    """
    for part in path.parts:
        if part in EXCLUDE_DIRS or part.endswith(".egg-info"):
            return True
    return False


def create_snapshot(
    root: Path,
    pattern: str = "**/*.py",
    compute_checksums: bool = True,
    progress_every: int = 100,
) -> ValidationSnapshot:
    """Create filesystem state snapshot for validation.

    Captures file counts, sizes, and optionally checksums for all files
    matching the pattern under root directory.

    Args:
        root: Root directory to snapshot
        pattern: Glob pattern for files to include (default: **/*.py)
        compute_checksums: If True, compute SHA256 for each file (slower but complete)
        progress_every: Log progress every N files (default: 100)

    Returns:
        ValidationSnapshot with file counts, sizes, and checksums

    Example:
        >>> snapshot = create_snapshot(Path("src"), pattern="**/*.py")
        >>> print(f"Found {snapshot.total_files} Python files")
    """
    root = Path(root).resolve()
    logger.info(f"Creating snapshot of {root} with pattern '{pattern}'")

    files = [f for f in root.glob(pattern) if f.is_file() and not should_exclude(f)]

    total_size = 0
    checksums: dict[str, str] = {}
    processed = 0

    for file_path in files:
        try:
            stat = file_path.stat()
            total_size += stat.st_size

            if compute_checksums:
                rel_path = str(file_path.relative_to(root))
                checksums[rel_path] = compute_file_checksum(file_path)

            processed += 1
            if processed % progress_every == 0:
                logger.info(f"Progress: {processed}/{len(files)} files processed")

        except (PermissionError, OSError) as e:
            logger.warning(f"Skipping {file_path}: {e}")

    snapshot = ValidationSnapshot(
        root=root,
        pattern=pattern,
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_files=len(files),
        total_size_bytes=total_size,
        file_checksums=checksums,
    )

    logger.info(
        f"Snapshot complete: {snapshot.total_files} files, {snapshot.total_size_bytes:,} bytes"
    )
    return snapshot


def validate_no_data_loss(
    pre: ValidationSnapshot, post: ValidationSnapshot, strict: bool = False
) -> tuple[bool, list[str]]:
    """Validate that no data was lost between snapshots.

    Compares pre and post snapshots to ensure all files from pre-snapshot
    exist in post-snapshot (possibly at different paths). Uses checksums
    to track files that moved.

    Args:
        pre: Snapshot before archive operation
        post: Snapshot after archive operation (should cover wider scope)
        strict: If True, require exact file count match (no additions)

    Returns:
        Tuple of (success, issues) where issues lists any problems

    Example:
        >>> pre = create_snapshot(Path("src"))
        >>> # ... perform archiving ...
        >>> post = create_snapshot(Path("."))  # Check entire project
        >>> success, issues = validate_no_data_loss(pre, post)
        >>> if not success:
        ...     print("Data loss detected!")
    """
    issues = []

    # Check file counts
    if post.total_files < pre.total_files:
        missing = pre.total_files - post.total_files
        issues.append(
            f"File count decreased by {missing} "
            f"({pre.total_files} -> {post.total_files})"
        )
    elif strict and post.total_files != pre.total_files:
        diff = post.total_files - pre.total_files
        issues.append(
            f"File count changed by {diff:+d} "
            f"({pre.total_files} -> {post.total_files})"
        )

    # Check total size
    if post.total_size_bytes < pre.total_size_bytes:
        lost_bytes = pre.total_size_bytes - post.total_size_bytes
        issues.append(
            f"Total size decreased by {lost_bytes:,} bytes "
            f"({pre.total_size_bytes:,} -> {post.total_size_bytes:,})"
        )

    # Check that all pre-checksums exist in post (files may have moved)
    if pre.file_checksums and post.file_checksums:
        pre_checksums = set(pre.file_checksums.values())
        post_checksums = set(post.file_checksums.values())
        missing_checksums = pre_checksums - post_checksums

        if missing_checksums:
            # Find which files are missing
            missing_files = [
                path
                for path, checksum in pre.file_checksums.items()
                if checksum in missing_checksums
            ]
            issues.append(
                f"{len(missing_files)} file(s) missing (checksum not found in post-snapshot):"
            )
            for path in missing_files[:10]:  # Show first 10
                issues.append(f"  - {path}")
            if len(missing_files) > 10:
                issues.append(f"  ... and {len(missing_files) - 10} more")

    return len(issues) == 0, issues


def save_snapshot(snapshot: ValidationSnapshot, output_path: Path) -> None:
    """Save snapshot to JSON file.

    Args:
        snapshot: ValidationSnapshot to save
        output_path: Path for output JSON file

    Example:
        >>> snapshot = create_snapshot(Path("src"))
        >>> save_snapshot(snapshot, Path("baseline.json"))
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to serializable dict
    data = {
        "root": str(snapshot.root),
        "pattern": snapshot.pattern,
        "timestamp": snapshot.timestamp,
        "total_files": snapshot.total_files,
        "total_size_bytes": snapshot.total_size_bytes,
        "file_checksums": snapshot.file_checksums,
    }

    output_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    logger.info(f"Saved snapshot to {output_path}")


def load_snapshot(input_path: Path) -> Optional[ValidationSnapshot]:
    """Load snapshot from JSON file.

    Args:
        input_path: Path to JSON snapshot file

    Returns:
        ValidationSnapshot, or None if file doesn't exist or is invalid

    Example:
        >>> snapshot = load_snapshot(Path("baseline.json"))
        >>> if snapshot:
        ...     print(f"Loaded {snapshot.total_files} files")
    """
    if not input_path.exists():
        logger.warning(f"Snapshot file not found: {input_path}")
        return None

    try:
        data = json.loads(input_path.read_text())
        return ValidationSnapshot(
            root=Path(data["root"]),
            pattern=data["pattern"],
            timestamp=data["timestamp"],
            total_files=data["total_files"],
            total_size_bytes=data["total_size_bytes"],
            file_checksums=data.get("file_checksums", {}),
        )
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"Failed to load snapshot {input_path}: {e}")
        return None


def create_multi_directory_snapshot(
    directories: list[Path], pattern: str = "**/*.py", compute_checksums: bool = True
) -> dict[str, ValidationSnapshot]:
    """Create snapshots for multiple directories.

    Useful for capturing baseline of several areas at once.

    Args:
        directories: List of directories to snapshot
        pattern: Glob pattern for files
        compute_checksums: If True, compute checksums

    Returns:
        Dict mapping directory name to ValidationSnapshot

    Example:
        >>> snapshots = create_multi_directory_snapshot([Path("src"), Path("tests")])
        >>> for name, snap in snapshots.items():
        ...     print(f"{name}: {snap.total_files} files")
    """
    snapshots = {}
    for directory in directories:
        if directory.exists():
            name = directory.name
            snapshots[name] = create_snapshot(
                directory, pattern=pattern, compute_checksums=compute_checksums
            )
        else:
            logger.warning(f"Directory not found, skipping: {directory}")
    return snapshots


__all__ = [
    "DEFAULT_PATTERNS",
    "EXCLUDE_DIRS",
    "create_snapshot",
    "validate_no_data_loss",
    "save_snapshot",
    "load_snapshot",
    "create_multi_directory_snapshot",
]
