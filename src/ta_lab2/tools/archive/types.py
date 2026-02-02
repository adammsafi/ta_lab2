"""Type definitions for archive operations.

Provides dataclasses for tracking archive operations, file entries,
and validation snapshots. Follows patterns from memory/migration.py.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class FileEntry:
    """Entry for a single archived file in manifest.

    Tracks the complete history of a file's archive operation,
    including original location, archive destination, and integrity data.

    Attributes:
        original_path: Original file path (relative to project root)
        archive_path: New path in .archive/ (relative to project root)
        action: Archive action type (deprecated, refactored, migrated)
        timestamp: ISO 8601 timestamp of archive operation
        sha256_checksum: SHA256 hash of file content for integrity verification
        size_bytes: File size in bytes

    Example:
        >>> entry = FileEntry(
        ...     original_path="src/old_module.py",
        ...     archive_path=".archive/2026-02-02/deprecated/old_module.py",
        ...     action="deprecated",
        ...     timestamp="2026-02-02T10:30:00",
        ...     sha256_checksum="abc123...",
        ...     size_bytes=1024
        ... )
    """
    original_path: str
    archive_path: str
    action: str  # deprecated, refactored, migrated
    timestamp: str  # ISO 8601
    sha256_checksum: str
    size_bytes: int


@dataclass
class ArchiveResult:
    """Result of batch archive operation.

    Tracks outcomes for batch archiving operations, following the
    MigrationResult pattern from memory/migration.py.

    Attributes:
        total: Total files in operation
        archived: Successfully archived files
        skipped: Files skipped (already archived or not found)
        errors: Files that failed during archive
        error_paths: List of paths that failed (for debugging)

    Example:
        >>> result = ArchiveResult(total=10, archived=8, skipped=1, errors=1)
        >>> print(result)
        Archive Result:
          Total: 10
          Archived: 8
          Skipped: 1 (already archived)
          Errors: 1
          Success Rate: 90.0%
    """
    total: int
    archived: int
    skipped: int
    errors: int
    error_paths: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        """Human-readable summary."""
        success_rate = (self.archived + self.skipped) / self.total * 100 if self.total > 0 else 0
        return (
            f"Archive Result:\n"
            f"  Total: {self.total}\n"
            f"  Archived: {self.archived}\n"
            f"  Skipped: {self.skipped} (already archived)\n"
            f"  Errors: {self.errors}\n"
            f"  Success Rate: {success_rate:.1f}%"
        )


@dataclass
class ValidationSnapshot:
    """Filesystem state snapshot for zero data loss validation.

    Captures the state of files at a point in time, enabling
    pre/post comparison to verify no data was lost during archiving.

    Attributes:
        root: Root directory that was snapshotted
        pattern: Glob pattern used to find files
        timestamp: ISO 8601 timestamp of snapshot
        total_files: Number of files found
        total_size_bytes: Total size of all files
        file_checksums: Dict mapping relative path to SHA256 checksum

    Example:
        >>> snapshot = ValidationSnapshot(
        ...     root=Path("src"),
        ...     pattern="**/*.py",
        ...     timestamp="2026-02-02T10:00:00",
        ...     total_files=100,
        ...     total_size_bytes=500000,
        ...     file_checksums={"module.py": "abc123..."}
        ... )
        >>> print(snapshot)
        Snapshot(src, pattern=**/*.py):
          Files: 100
          Size: 500,000 bytes
          Coverage: 100 checksums
    """
    root: Path
    pattern: str
    timestamp: str
    total_files: int
    total_size_bytes: int
    file_checksums: dict[str, str] = field(default_factory=dict)

    def __str__(self) -> str:
        """Human-readable summary."""
        return (
            f"Snapshot({self.root}, pattern={self.pattern}):\n"
            f"  Files: {self.total_files}\n"
            f"  Size: {self.total_size_bytes:,} bytes\n"
            f"  Coverage: {len(self.file_checksums)} checksums"
        )


__all__ = ["FileEntry", "ArchiveResult", "ValidationSnapshot"]
