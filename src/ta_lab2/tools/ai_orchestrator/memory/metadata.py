"""Enhanced metadata schema for memory health monitoring.

Provides MemoryMetadata dataclass and utilities for creating, validating,
and managing memory metadata including timestamps, source tracking, and
deprecation support (MEMO-08).

All timestamps are ISO 8601 format for consistent parsing and storage.
"""
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class MemoryMetadata:
    """Enhanced metadata schema for memory health monitoring.

    Attributes:
        created_at: ISO 8601 timestamp of memory creation (required)
        last_verified: ISO 8601 timestamp of last verification (required)
        deprecated_since: ISO 8601 timestamp when memory flagged stale (optional)
        deprecation_reason: Reason for deprecation (optional)
        source: Memory origin (chromadb_phase2, manual, conversation, etc.)
        category: Memory category (pipeline_schedule, api_design, decision, etc.)
        migration_version: Schema version for future migrations (default: 1)

    Example:
        >>> meta = MemoryMetadata(
        ...     created_at="2026-01-28T15:00:00",
        ...     last_verified="2026-01-28T15:00:00",
        ...     source="manual",
        ...     category="technical_analysis"
        ... )
    """

    created_at: str
    last_verified: str
    deprecated_since: Optional[str] = None
    deprecation_reason: Optional[str] = None
    source: str = "unknown"
    category: Optional[str] = None
    migration_version: int = 1

    def to_dict(self) -> dict:
        """Convert to dict for Mem0 metadata parameter.

        Returns:
            Dict suitable for Mem0 add/update operations
        """
        return {k: v for k, v in asdict(self).items() if v is not None}


def create_metadata(
    source: str = "manual",
    category: Optional[str] = None,
    existing: Optional[dict] = None,
) -> dict:
    """Create or enrich memory metadata with timestamps.

    Preserves existing created_at if present, generates new one if missing.
    Always updates last_verified to current UTC time.

    Args:
        source: Memory origin (manual, chromadb_phase2, conversation, etc.)
        category: Optional memory category (pipeline_schedule, api_design, etc.)
        existing: Optional existing metadata dict to enrich

    Returns:
        Dict with enhanced metadata suitable for Mem0

    Example:
        >>> # New memory
        >>> meta = create_metadata(source="manual", category="decision")
        >>> print(meta.keys())
        dict_keys(['created_at', 'last_verified', 'source', 'category', 'migration_version'])

        >>> # Enrich existing memory (preserves created_at)
        >>> existing = {"created_at": "2025-01-01T00:00:00"}
        >>> meta = create_metadata(existing=existing, source="chromadb_phase2")
        >>> meta['created_at']  # Preserved
        '2025-01-01T00:00:00'
    """
    now = datetime.now(timezone.utc).isoformat()

    # Preserve existing created_at if present, otherwise use current time
    created_at = now
    if existing and "created_at" in existing:
        created_at = existing["created_at"]

    # Build metadata object
    metadata = MemoryMetadata(
        created_at=created_at,
        last_verified=now,  # Always update last_verified
        source=source,
        category=category,
        migration_version=1,
    )

    # Preserve deprecated_since and deprecation_reason if present
    if existing:
        if "deprecated_since" in existing:
            metadata.deprecated_since = existing["deprecated_since"]
        if "deprecation_reason" in existing:
            metadata.deprecation_reason = existing["deprecation_reason"]

    return metadata.to_dict()


def validate_metadata(metadata: dict) -> tuple[bool, list[str]]:
    """Validate memory metadata has required fields and valid timestamps.

    Args:
        metadata: Metadata dict to validate

    Returns:
        Tuple of (is_valid, issues_list)
        - is_valid: True if all required fields present and valid
        - issues_list: List of validation error messages (empty if valid)

    Example:
        >>> meta = create_metadata(source="test")
        >>> valid, issues = validate_metadata(meta)
        >>> print(valid, issues)
        True []

        >>> invalid = {"source": "test"}
        >>> valid, issues = validate_metadata(invalid)
        >>> print(valid)
        False
        >>> "created_at" in issues[0]
        True
    """
    issues = []

    # Check required fields
    required_fields = ["created_at", "last_verified", "source", "migration_version"]
    for field in required_fields:
        if field not in metadata:
            issues.append(f"Missing required field: {field}")

    # Validate timestamp fields are ISO 8601 format
    timestamp_fields = ["created_at", "last_verified", "deprecated_since"]
    for field in timestamp_fields:
        if field in metadata and metadata[field] is not None:
            try:
                # Try parsing as ISO 8601
                datetime.fromisoformat(metadata[field])
            except (ValueError, TypeError) as e:
                issues.append(
                    f"Invalid ISO 8601 timestamp for {field}: {metadata[field]} ({e})"
                )

    # Validate migration_version is int
    if "migration_version" in metadata:
        if not isinstance(metadata["migration_version"], int):
            issues.append(
                f"migration_version must be int, got {type(metadata['migration_version'])}"
            )

    # Validate deprecated_since and deprecation_reason consistency
    if metadata.get("deprecated_since") and not metadata.get("deprecation_reason"):
        issues.append("deprecated_since set but deprecation_reason missing")

    is_valid = len(issues) == 0
    return is_valid, issues


def mark_deprecated(metadata: dict, reason: str) -> dict:
    """Mark memory as deprecated with timestamp and reason.

    Args:
        metadata: Existing metadata dict
        reason: Deprecation reason (e.g., "Outdated pipeline config", "Superseded by new design")

    Returns:
        Updated metadata dict with deprecated_since and deprecation_reason

    Example:
        >>> meta = create_metadata(source="manual")
        >>> deprecated = mark_deprecated(meta, reason="Outdated config")
        >>> "deprecated_since" in deprecated
        True
        >>> deprecated["deprecation_reason"]
        'Outdated config'
    """
    # Create copy to avoid mutating input
    updated = metadata.copy()

    # Add deprecation fields
    updated["deprecated_since"] = datetime.now(timezone.utc).isoformat()
    updated["deprecation_reason"] = reason

    return updated


__all__ = ["MemoryMetadata", "create_metadata", "validate_metadata", "mark_deprecated"]
