"""Batch memory operations with rate limiting for snapshot indexing.

Provides batch processing infrastructure for adding memories to Mem0/Qdrant,
with rate limiting, error handling, and standardized metadata for snapshots.
"""
import logging
import time
from dataclasses import dataclass
from typing import Optional
from ta_lab2.tools.ai_orchestrator.memory.metadata import create_metadata

logger = logging.getLogger(__name__)


@dataclass
class BatchIndexResult:
    """Result tracking for batch memory indexing operations.

    Similar to MigrationResult from migration.py, provides detailed tracking
    of batch processing success, failures, and overall statistics.

    Attributes:
        total: Total memories attempted
        added: Memories successfully added
        skipped: Memories skipped (duplicates, etc.)
        errors: Memories that failed to add
        error_ids: List of IDs/identifiers for failed memories

    Example:
        >>> result = BatchIndexResult(total=100, added=95, skipped=3, errors=2, error_ids=["file1.py", "file2.py"])
        >>> print(result)
        Batch Index Result:
          Total: 100
          Added: 95
          Skipped: 3
          Errors: 2
          Success Rate: 98.0%
    """
    total: int
    added: int
    skipped: int
    errors: int
    error_ids: list[str]

    def __str__(self) -> str:
        """Human-readable summary."""
        success_rate = (self.added + self.skipped) / self.total * 100 if self.total > 0 else 0
        return (
            f"Batch Index Result:\n"
            f"  Total: {self.total}\n"
            f"  Added: {self.added}\n"
            f"  Skipped: {self.skipped}\n"
            f"  Errors: {self.errors}\n"
            f"  Success Rate: {success_rate:.1f}%"
        )


def batch_add_memories(
    client,
    memories: list[dict],
    batch_size: int = 50,
    delay_seconds: float = 0.5
) -> BatchIndexResult:
    """Add memories in batches with rate limiting and error handling.

    Processes memories in configurable batches, with delays between batches
    to avoid rate limits. Continues processing on errors (doesn't fail entire batch).

    Args:
        client: Mem0Client instance (from get_mem0_client())
        memories: List of dicts with {"content": str, "metadata": dict}
        batch_size: Number of memories per batch (default: 50)
        delay_seconds: Delay between batches in seconds (default: 0.5)

    Returns:
        BatchIndexResult with counts and error details

    Example:
        >>> from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
        >>> client = get_mem0_client()
        >>> memories = [
        ...     {"content": "File: src/ema.py...", "metadata": {"source": "pre_reorg_v0.5.0"}},
        ...     {"content": "File: src/bar.py...", "metadata": {"source": "pre_reorg_v0.5.0"}}
        ... ]
        >>> result = batch_add_memories(client, memories, batch_size=50, delay_seconds=0.5)
        >>> print(result)

    Note:
        Uses infer=False to disable LLM conflict detection for bulk operations,
        significantly improving performance for snapshot indexing.
    """
    results = BatchIndexResult(
        total=len(memories),
        added=0,
        skipped=0,
        errors=0,
        error_ids=[]
    )

    logger.info(f"Starting batch indexing: {results.total} memories, batch_size={batch_size}")

    for i in range(0, len(memories), batch_size):
        batch = memories[i:i+batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(memories) + batch_size - 1) // batch_size

        for memory in batch:
            memory_id = memory.get("id", memory.get("content", "")[:50])

            try:
                # Add to Mem0 with infer=False for bulk operations
                client.add(
                    messages=[{"role": "user", "content": memory["content"]}],
                    user_id="orchestrator",
                    metadata=memory["metadata"],
                    infer=False  # Disable LLM conflict detection for performance
                )
                results.added += 1

            except KeyError as e:
                logger.error(f"Memory missing required field {e}: {memory_id}")
                results.errors += 1
                results.error_ids.append(memory_id)

            except Exception as e:
                logger.error(f"Failed to add memory '{memory_id}': {e}")
                results.errors += 1
                results.error_ids.append(memory_id)

        # Log progress after each batch
        logger.info(
            f"Batch {batch_num}/{total_batches}: "
            f"{results.added}/{results.total} memories added "
            f"(errors={results.errors})"
        )

        # Rate limiting: sleep between batches (except after last batch)
        if i + batch_size < len(memories):
            time.sleep(delay_seconds)

    logger.info(f"Batch indexing complete: {results}")
    return results


def create_snapshot_metadata(
    source: str,
    directory: str,
    file_type: str,
    file_path: str,
    **kwargs
) -> dict:
    """Create standardized metadata for snapshot memories.

    Extends create_metadata() from metadata.py with snapshot-specific fields
    including milestone, phase, directory, file_type, and file_path.

    Args:
        source: Memory source tag (e.g., "pre_reorg_v0.5.0")
        directory: Source directory name (e.g., "ta_lab2", "Data_Tools")
        file_type: File type (e.g., "source_code", "test", "config", "documentation")
        file_path: Relative path to file
        **kwargs: Additional metadata fields (function_count, class_count, commit_hash, etc.)

    Returns:
        Dict with enhanced metadata including tags and structured metadata

    Example:
        >>> metadata = create_snapshot_metadata(
        ...     source="pre_reorg_v0.5.0",
        ...     directory="ta_lab2",
        ...     file_type="source_code",
        ...     file_path="src/ta_lab2/features/ema.py",
        ...     function_count=5,
        ...     class_count=2,
        ...     commit_hash="49499eb"
        ... )
        >>> print(metadata["milestone"])
        v0.5.0
        >>> print("pre_reorg_v0.5.0" in metadata.get("tags", []))
        True
    """
    # Use existing create_metadata as base
    metadata = create_metadata(
        source=source,
        category="codebase_snapshot"
    )

    # Add snapshot-specific fields
    metadata.update({
        "milestone": "v0.5.0",
        "phase": "pre_reorg",
        "directory": directory,
        "file_type": file_type,
        "file_path": file_path
    })

    # Add simple tag for easy filtering
    if "tags" not in metadata:
        metadata["tags"] = []
    if source not in metadata["tags"]:
        metadata["tags"].append(source)

    # Add any additional kwargs (function_count, class_count, commit_hash, etc.)
    metadata.update(kwargs)

    return metadata


def format_file_content_for_memory(file_info: dict) -> str:
    """Format file analysis into human-readable text for memory content.

    Takes dict from extract_code_structure (merged with git metadata)
    and formats into concise, searchable text suitable for embedding.

    Args:
        file_info: Dict with code_structure and git_metadata keys

    Returns:
        Formatted string (max ~500 chars for efficient embedding)

    Example:
        >>> file_info = {
        ...     "relative_path": "src/ta_lab2/features/ema.py",
        ...     "code_structure": {
        ...         "functions": [{"name": "calculate_ema"}, {"name": "get_ema_state"}],
        ...         "classes": [{"name": "EMACalculator"}],
        ...         "line_count": 150
        ...     },
        ...     "git_metadata": {
        ...         "commit_hash": "49499eb"
        ...     }
        ... }
        >>> content = format_file_content_for_memory(file_info)
        >>> print(content)
        File: src/ta_lab2/features/ema.py
        Directory: features
        Lines: 150
        Functions: calculate_ema, get_ema_state
        Classes: EMACalculator
        Commit: 49499eb

        Summary: Python module with 2 functions, 1 classes.
    """
    # Extract fields
    relative_path = file_info.get("relative_path", file_info.get("file", "unknown"))
    code_structure = file_info.get("code_structure", {})
    git_metadata = file_info.get("git_metadata", {})

    # Get directory name from path
    path_parts = relative_path.replace("\\", "/").split("/")
    directory_name = path_parts[-2] if len(path_parts) > 1 else "root"

    # Extract function and class names
    functions = code_structure.get("functions", [])
    function_names = [f["name"] for f in functions][:10]  # Max 10

    classes = code_structure.get("classes", [])
    class_names = [c["name"] for c in classes][:10]  # Max 10

    # Get line count and commit hash
    line_count = code_structure.get("line_count", 0)
    commit_hash = git_metadata.get("commit_hash", "N/A")

    # Format content
    content_lines = [
        f"File: {relative_path}",
        f"Directory: {directory_name}",
        f"Lines: {line_count}",
        f"Functions: {', '.join(function_names) if function_names else 'None'}",
        f"Classes: {', '.join(class_names) if class_names else 'None'}",
        f"Commit: {commit_hash}",
        "",
        f"Summary: Python module with {len(functions)} functions, {len(classes)} classes."
    ]

    return "\n".join(content_lines)


__all__ = [
    "BatchIndexResult",
    "batch_add_memories",
    "create_snapshot_metadata",
    "format_file_content_for_memory"
]
