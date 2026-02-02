"""Archive tooling for v0.5.0 reorganization.

Provides utilities for archiving files with git history preservation,
manifest tracking, and zero data loss validation.

Example:
    >>> from ta_lab2.tools.archive import FileEntry, create_manifest
    >>> entry = FileEntry(...)
    >>> manifest = create_manifest([entry], "2026-02-02", "deprecated")
"""
from ta_lab2.tools.archive.types import (
    FileEntry,
    ArchiveResult,
    ValidationSnapshot,
)
from ta_lab2.tools.archive.manifest import (
    MANIFEST_SCHEMA,
    MANIFEST_VERSION,
    VALID_ACTIONS,
    compute_file_checksum,
    create_file_entry,
    create_manifest,
    save_manifest,
    validate_manifest,
    load_manifest,
)

__all__ = [
    # Types
    "FileEntry",
    "ArchiveResult",
    "ValidationSnapshot",
    # Manifest functions
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
