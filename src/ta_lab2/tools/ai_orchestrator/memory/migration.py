"""Metadata migration script for enriching existing memories.

Provides idempotent migration to add enhanced metadata (created_at, last_verified,
deprecated_since) to all memories. Supports dry-run mode and error handling.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from ta_lab2.tools.ai_orchestrator.memory.mem0_client import Mem0Client, get_mem0_client
from ta_lab2.tools.ai_orchestrator.memory.metadata import create_metadata, validate_metadata

logger = logging.getLogger(__name__)


@dataclass
class MigrationResult:
    """Result of metadata migration operation.

    Attributes:
        total: Total memories processed
        updated: Memories with metadata added/enriched
        skipped: Memories already had valid metadata
        errors: Memories that failed during update
        error_ids: List of memory IDs that failed (for debugging)

    Example:
        >>> result = MigrationResult(total=100, updated=90, skipped=10, errors=0, error_ids=[])
        >>> print(f"{result.updated}/{result.total} memories updated")
        90/100 memories updated
    """
    total: int
    updated: int
    skipped: int
    errors: int
    error_ids: list[str]

    def __str__(self) -> str:
        """Human-readable summary."""
        success_rate = (self.updated + self.skipped) / self.total * 100 if self.total > 0 else 0
        return (
            f"Migration Result:\n"
            f"  Total: {self.total}\n"
            f"  Updated: {self.updated}\n"
            f"  Skipped: {self.skipped} (already valid)\n"
            f"  Errors: {self.errors}\n"
            f"  Success Rate: {success_rate:.1f}%"
        )


def migrate_metadata(
    client: Optional[Mem0Client] = None,
    batch_size: int = 100,
    dry_run: bool = False
) -> MigrationResult:
    """Migrate metadata for all memories (idempotent).

    Enriches memories with created_at, last_verified, and other metadata fields.
    Preserves existing created_at if present. Safe to run multiple times.

    Args:
        client: Mem0Client instance. If None, uses get_mem0_client()
        batch_size: Log progress every N memories (default: 100)
        dry_run: If True, validate but don't write updates (default: False)

    Returns:
        MigrationResult with counts and error details

    Example:
        >>> # Dry run to preview
        >>> result = migrate_metadata(dry_run=True)
        >>> print(f"Would update {result.updated} memories")

        >>> # Actual migration
        >>> result = migrate_metadata()
        >>> print(result)

    Note:
        Migration is idempotent - running multiple times is safe.
        Memories with valid metadata are skipped automatically.
    """
    if client is None:
        client = get_mem0_client()

    logger.info(f"Starting metadata migration (dry_run={dry_run})")

    # Initialize counters
    total = 0
    updated = 0
    skipped = 0
    errors = 0
    error_ids = []

    try:
        # Get all memories for orchestrator user
        memories = client.get_all(user_id="orchestrator")
        total = len(memories)
        logger.info(f"Found {total} memories to process")

        # Process each memory
        for idx, memory in enumerate(memories, 1):
            memory_id = memory.get("id")
            if not memory_id:
                logger.warning(f"Memory at index {idx} has no ID, skipping")
                errors += 1
                continue

            try:
                # Get existing metadata
                existing_metadata = memory.get("metadata", {})

                # Validate existing metadata
                is_valid, issues = validate_metadata(existing_metadata)

                if is_valid:
                    # Metadata already valid, skip
                    skipped += 1
                    logger.debug(f"Memory {memory_id} already has valid metadata, skipping")
                else:
                    # Enrich metadata
                    enhanced_metadata = create_metadata(
                        source="chromadb_phase2",  # Default source for existing memories
                        category=existing_metadata.get("category"),
                        existing=existing_metadata
                    )

                    if not dry_run:
                        # Update memory with enhanced metadata
                        # Note: Mem0 update() requires data parameter, so we need to get the memory text
                        memory_text = memory.get("memory", "")
                        if not memory_text:
                            logger.warning(f"Memory {memory_id} has no text content, skipping update")
                            errors += 1
                            error_ids.append(memory_id)
                            continue

                        client.update(
                            memory_id=memory_id,
                            data=memory_text,  # Keep same content
                            metadata=enhanced_metadata
                        )
                        logger.debug(f"Updated memory {memory_id} with enhanced metadata")

                    updated += 1

                # Log progress
                if idx % batch_size == 0:
                    logger.info(
                        f"Progress: {idx}/{total} memories processed "
                        f"(updated={updated}, skipped={skipped}, errors={errors})"
                    )

            except Exception as e:
                logger.error(f"Failed to process memory {memory_id}: {e}")
                errors += 1
                error_ids.append(memory_id)
                # Continue processing remaining memories

        # Final summary
        logger.info(
            f"Migration {'dry run ' if dry_run else ''}complete: "
            f"total={total}, updated={updated}, skipped={skipped}, errors={errors}"
        )

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise

    return MigrationResult(
        total=total,
        updated=updated,
        skipped=skipped,
        errors=errors,
        error_ids=error_ids
    )


def validate_migration(
    client: Optional[Mem0Client] = None,
    sample_size: int = 100
) -> tuple[bool, str]:
    """Validate migration by sampling random memories.

    Args:
        client: Mem0Client instance. If None, uses get_mem0_client()
        sample_size: Number of memories to sample (default: 100)

    Returns:
        Tuple of (success, message)
        - success: True if all sampled memories have valid metadata
        - message: Summary message with validation details

    Example:
        >>> success, message = validate_migration(sample_size=50)
        >>> print(message)
        Validated 50 memories: 50 valid, 0 invalid
    """
    if client is None:
        client = get_mem0_client()

    try:
        # Get all memories for orchestrator user
        memories = client.get_all(user_id="orchestrator")
        total_count = len(memories)

        if total_count == 0:
            return True, "No memories to validate"

        # Sample memories (up to sample_size)
        import random
        sample = random.sample(memories, min(sample_size, total_count))

        # Validate each sample
        valid_count = 0
        invalid_count = 0
        invalid_ids = []

        for memory in sample:
            memory_id = memory.get("id")
            metadata = memory.get("metadata", {})

            is_valid, issues = validate_metadata(metadata)

            if is_valid:
                valid_count += 1
            else:
                invalid_count += 1
                invalid_ids.append(memory_id)
                logger.warning(f"Memory {memory_id} has invalid metadata: {issues}")

        success = invalid_count == 0
        message = (
            f"Validated {len(sample)} memories: "
            f"{valid_count} valid, {invalid_count} invalid"
        )

        if not success:
            message += f"\nInvalid memory IDs: {invalid_ids[:10]}"  # Show first 10

        return success, message

    except Exception as e:
        logger.error(f"Validation failed: {e}")
        return False, f"Validation failed: {e}"


if __name__ == "__main__":
    """CLI entrypoint for running migration."""
    import sys

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Check for dry-run flag
    dry_run = "--dry-run" in sys.argv

    # Run migration
    print(f"Running metadata migration (dry_run={dry_run})...")
    result = migrate_metadata(dry_run=dry_run)
    print()
    print(result)

    # Validate if not dry run
    if not dry_run and result.errors == 0:
        print("\nValidating migration...")
        success, message = validate_migration()
        print(message)
        sys.exit(0 if success else 1)


__all__ = [
    "MigrationResult",
    "migrate_metadata",
    "validate_migration"
]
