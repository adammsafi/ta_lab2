"""Manifest creation and validation for archive operations.

Provides functions for creating versioned JSON manifests that track
archived files with checksums and metadata. Uses hashlib.file_digest()
(Python 3.11+) for efficient checksum computation.
"""
import hashlib
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ta_lab2.tools.archive.types import FileEntry

logger = logging.getLogger(__name__)

# Manifest schema version
MANIFEST_SCHEMA = "https://ta_lab2.local/schemas/archive-manifest/v1.0.0"
MANIFEST_VERSION = "1.0.0"

# Valid archive actions
VALID_ACTIONS = {"deprecated", "refactored", "migrated"}


def compute_file_checksum(file_path: Path) -> str:
    """Compute SHA256 checksum using hashlib.file_digest() (Python 3.11+).

    Uses optimized I/O that bypasses Python buffers for large files.

    Args:
        file_path: Path to file to checksum

    Returns:
        Lowercase hexadecimal SHA256 checksum (64 characters)

    Raises:
        FileNotFoundError: If file does not exist
        PermissionError: If file cannot be read

    Example:
        >>> checksum = compute_file_checksum(Path("README.md"))
        >>> len(checksum)
        64
    """
    with file_path.open("rb") as f:
        digest = hashlib.file_digest(f, "sha256")
    return digest.hexdigest()


def create_file_entry(
    original_path: Path,
    archive_path: Path,
    action: str,
    project_root: Optional[Path] = None,
) -> FileEntry:
    """Create a FileEntry for a file that has been archived.

    Computes checksum and size from the archived file (not original).

    Args:
        original_path: Original file path (relative or absolute)
        archive_path: Archive destination path (must exist)
        action: Archive action (deprecated, refactored, migrated)
        project_root: Project root for relative paths (default: cwd)

    Returns:
        FileEntry with computed checksum and size

    Raises:
        ValueError: If action is not valid
        FileNotFoundError: If archive_path does not exist

    Example:
        >>> entry = create_file_entry(
        ...     Path("src/old.py"),
        ...     Path(".archive/2026-02-02/deprecated/old.py"),
        ...     "deprecated"
        ... )
    """
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action '{action}'. Must be one of: {VALID_ACTIONS}")

    if project_root is None:
        project_root = Path.cwd()

    # Resolve paths relative to project root
    if original_path.is_absolute():
        original_rel = original_path.relative_to(project_root)
    else:
        original_rel = original_path

    if archive_path.is_absolute():
        archive_abs = archive_path
        archive_rel = archive_path.relative_to(project_root)
    else:
        archive_abs = project_root / archive_path
        archive_rel = archive_path

    if not archive_abs.exists():
        raise FileNotFoundError(f"Archive path does not exist: {archive_abs}")

    return FileEntry(
        original_path=str(original_rel),
        archive_path=str(archive_rel),
        action=action,
        timestamp=datetime.now(timezone.utc).isoformat(),
        sha256_checksum=compute_file_checksum(archive_abs),
        size_bytes=archive_abs.stat().st_size,
    )


def create_manifest(entries: list[FileEntry], archive_date: str, category: str) -> dict:
    """Create versioned manifest for archive category.

    Creates a JSON-serializable manifest following the archive-manifest
    schema with $schema versioning for future compatibility.

    Args:
        entries: List of FileEntry objects for archived files
        archive_date: ISO 8601 date (YYYY-MM-DD)
        category: Archive category (deprecated, refactored, migrated)

    Returns:
        Dict ready for JSON serialization with schema and version info

    Example:
        >>> entries = [entry1, entry2]
        >>> manifest = create_manifest(entries, "2026-02-02", "deprecated")
        >>> manifest["$schema"]
        'https://ta_lab2.local/schemas/archive-manifest/v1.0.0'
    """
    return {
        "$schema": MANIFEST_SCHEMA,
        "version": MANIFEST_VERSION,
        "archive_date": archive_date,
        "category": category,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "total_files": len(entries),
        "total_size_bytes": sum(e.size_bytes for e in entries),
        "files": [asdict(e) for e in entries],
    }


def save_manifest(manifest: dict, manifest_path: Path) -> None:
    """Save manifest to JSON file with readable formatting.

    Creates parent directories if needed. Uses 2-space indentation
    and sorted keys for readable git diffs.

    Args:
        manifest: Manifest dict from create_manifest()
        manifest_path: Path to write manifest file

    Example:
        >>> manifest = create_manifest(entries, "2026-02-02", "deprecated")
        >>> save_manifest(manifest, Path(".archive/2026-02-02/deprecated/manifest.json"))
    """
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    logger.info(f"Saved manifest to {manifest_path}")


def validate_manifest(manifest_path: Path) -> tuple[bool, list[str]]:
    """Validate manifest structure and file checksums.

    Checks:
    1. Valid JSON structure
    2. Required fields present ($schema, version, archive_date, files)
    3. All file entries have required fields
    4. All archived files exist at archive_path
    5. All checksums match current file content

    Args:
        manifest_path: Path to manifest.json file

    Returns:
        Tuple of (is_valid, issues) where issues is empty list if valid

    Example:
        >>> valid, issues = validate_manifest(Path(".archive/2026-02-02/manifest.json"))
        >>> if not valid:
        ...     print("Issues:", issues)
    """
    issues = []

    # Check manifest exists
    if not manifest_path.exists():
        return False, [f"Manifest not found: {manifest_path}"]

    # Parse JSON
    try:
        manifest = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        return False, [f"Invalid JSON: {e}"]

    # Check required top-level fields
    required_fields = ["$schema", "version", "archive_date", "files"]
    for field in required_fields:
        if field not in manifest:
            issues.append(f"Missing required field: {field}")

    if issues:
        return False, issues

    # Validate each file entry
    entry_required = [
        "original_path",
        "archive_path",
        "action",
        "sha256_checksum",
        "size_bytes",
    ]

    for idx, entry in enumerate(manifest.get("files", [])):
        # Check required entry fields
        for field in entry_required:
            if field not in entry:
                issues.append(f"File entry {idx} missing field: {field}")
                continue

        # Verify archive_path exists
        archive_path = Path(entry.get("archive_path", ""))
        if not archive_path.exists():
            issues.append(f"Archived file not found: {archive_path}")
            continue

        # Verify checksum matches
        try:
            actual_checksum = compute_file_checksum(archive_path)
            expected_checksum = entry.get("sha256_checksum", "")
            if actual_checksum != expected_checksum:
                issues.append(
                    f"Checksum mismatch for {archive_path}: "
                    f"expected {expected_checksum[:16]}..., got {actual_checksum[:16]}..."
                )
        except Exception as e:
            issues.append(f"Failed to verify checksum for {archive_path}: {e}")

        # Verify size matches
        actual_size = archive_path.stat().st_size
        expected_size = entry.get("size_bytes", 0)
        if actual_size != expected_size:
            issues.append(
                f"Size mismatch for {archive_path}: "
                f"expected {expected_size}, got {actual_size}"
            )

    return len(issues) == 0, issues


def load_manifest(manifest_path: Path) -> Optional[dict]:
    """Load and parse a manifest file.

    Args:
        manifest_path: Path to manifest.json file

    Returns:
        Parsed manifest dict, or None if file doesn't exist or is invalid

    Example:
        >>> manifest = load_manifest(Path(".archive/2026-02-02/manifest.json"))
        >>> if manifest:
        ...     print(f"Contains {manifest['total_files']} files")
    """
    if not manifest_path.exists():
        logger.warning(f"Manifest not found: {manifest_path}")
        return None

    try:
        return json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse manifest {manifest_path}: {e}")
        return None


__all__ = [
    "MANIFEST_SCHEMA",
    "MANIFEST_VERSION",
    "VALID_ACTIONS",
    "compute_file_checksum",
    "create_file_entry",
    "create_manifest",
    "save_manifest",
    "validate_manifest",
    "load_manifest",
]
