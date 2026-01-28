"""Conflict detection and resolution for contradictory memories.

Uses Mem0's LLM-powered conflict resolver to detect and handle contradictions
automatically via infer=True parameter. Distinguishes context-dependent truths
from actual conflicts using metadata scoping.

Key capabilities:
- Semantic similarity detection for potential conflicts
- LLM-powered resolution (ADD/UPDATE/DELETE/NOOP)
- Context-dependent truth handling via metadata
- Audit logging for manual review

Example:
    >>> from ta_lab2.tools.ai_orchestrator.memory.conflict import resolve_conflict
    >>> result = resolve_conflict(
    ...     new_content="EMA window is 20 periods",
    ...     user_id="orchestrator",
    ...     metadata={"asset_class": "crypto"}
    ... )
    >>> print(f"Operation: {result.operation}, Confidence: {result.confidence}")
"""
import logging
import json
from datetime import datetime
from dataclasses import dataclass, asdict
from typing import Optional, Any
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ConflictResult:
    """Result of conflict detection and resolution.

    Attributes:
        memory_id: ID of memory involved in operation
        operation: Resolution type (ADD/UPDATE/DELETE/NOOP)
        confidence: Confidence score 0.0-1.0 for resolution
        reason: Human-readable explanation of why this operation was chosen
        original_content: The new content that was checked for conflicts
        conflicting_memory: Optional ID of existing memory it conflicts with
        conflicting_content: Optional content of conflicting memory
        timestamp: ISO 8601 timestamp when conflict was detected
    """
    memory_id: str
    operation: str
    confidence: float
    reason: str
    original_content: str
    timestamp: str
    conflicting_memory: Optional[str] = None
    conflicting_content: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return asdict(self)


def detect_conflicts(
    content: str,
    user_id: str = "orchestrator",
    client: Any = None,
    similarity_threshold: float = 0.85
) -> list[dict]:
    """Detect potential conflicts by finding semantically similar memories.

    Searches for existing memories with high semantic similarity that might
    contradict the new content. Does not perform resolution - use resolve_conflict
    for that.

    Args:
        content: New content to check for conflicts
        user_id: User ID for memory isolation (default: "orchestrator")
        client: Optional Mem0Client instance. If None, uses get_mem0_client()
        similarity_threshold: Minimum similarity score to flag as potential conflict (default: 0.85)

    Returns:
        List of potential conflict dicts containing:
        - memory_id: ID of similar memory
        - content: Content of similar memory
        - similarity: Similarity score (0.0-1.0)
        - metadata: Memory metadata

    Example:
        >>> conflicts = detect_conflicts(
        ...     content="EMA uses 20 periods",
        ...     user_id="orchestrator",
        ...     similarity_threshold=0.85
        ... )
        >>> for conflict in conflicts:
        ...     print(f"Found similar memory: {conflict['content']}")
    """
    if client is None:
        from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
        client = get_mem0_client()

    try:
        # Search for semantically similar memories
        results = client.search(
            query=content,
            user_id=user_id,
            limit=10
        )

        # Filter by similarity threshold
        potential_conflicts = []
        for result in results:
            # Mem0 search returns dict with 'id', 'memory', 'metadata', 'score'
            # Score is typically 0-1 where higher = more similar
            similarity = result.get("score", 0.0)

            if similarity >= similarity_threshold:
                potential_conflicts.append({
                    "memory_id": result.get("id"),
                    "content": result.get("memory"),
                    "similarity": similarity,
                    "metadata": result.get("metadata", {})
                })

        logger.info(
            f"Detected {len(potential_conflicts)} potential conflicts "
            f"above threshold {similarity_threshold} for content: {content[:50]}..."
        )
        return potential_conflicts

    except Exception as e:
        logger.error(f"Failed to detect conflicts for content '{content[:50]}...': {e}")
        raise


def resolve_conflict(
    new_content: str,
    user_id: str = "orchestrator",
    metadata: Optional[dict] = None,
    client: Any = None
) -> ConflictResult:
    """Resolve conflicts using Mem0's LLM-powered infer=True capability.

    Uses Mem0's built-in conflict detection which:
    1. Searches for semantically similar memories
    2. Uses GPT-4o-mini to determine if content conflicts
    3. Decides operation: ADD (new), UPDATE (replace), DELETE (remove), NOOP (duplicate)
    4. Executes the operation automatically

    Context-dependent truths (different metadata) are treated as separate facts.

    Args:
        new_content: New content to add/check
        user_id: User ID for memory isolation (default: "orchestrator")
        metadata: Optional metadata for context scoping (e.g., {"asset_class": "crypto"})
        client: Optional Mem0Client instance. If None, uses get_mem0_client()

    Returns:
        ConflictResult with operation details and resolution reasoning

    Example:
        >>> result = resolve_conflict(
        ...     new_content="EMA window is 20 periods",
        ...     user_id="orchestrator",
        ...     metadata={"asset_class": "crypto"}
        ... )
        >>> print(f"Resolved as: {result.operation}")
    """
    if client is None:
        from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
        client = get_mem0_client()

    try:
        # Use Mem0's add() with infer=True for automatic conflict resolution
        # Format content as message list per Mem0 API
        messages = [
            {"role": "user", "content": new_content}
        ]

        result = client.add(
            messages=messages,
            user_id=user_id,
            metadata=metadata,
            infer=True  # Enable LLM-powered conflict detection
        )

        # Parse Mem0's response
        # Result typically contains: {'results': [{'memory': str, 'event': str, 'id': str}]}
        # Event can be: 'ADD', 'UPDATE', 'DELETE', 'NOOP'

        # Extract operation and memory details
        if isinstance(result, dict) and "results" in result:
            result_list = result["results"]
            if result_list and len(result_list) > 0:
                first_result = result_list[0]
                operation = first_result.get("event", "UNKNOWN")
                memory_id = first_result.get("id", "unknown")
                memory_content = first_result.get("memory", new_content)
            else:
                # Empty results - treat as NOOP
                operation = "NOOP"
                memory_id = "none"
                memory_content = new_content
        else:
            # Unexpected format - default to ADD
            operation = "ADD"
            memory_id = result.get("id", "unknown") if isinstance(result, dict) else "unknown"
            memory_content = new_content

        # Build conflict result
        conflict_result = ConflictResult(
            memory_id=memory_id,
            operation=operation,
            confidence=0.9,  # Mem0 doesn't provide explicit confidence, assume high
            reason=_generate_reason(operation, new_content),
            original_content=new_content,
            timestamp=datetime.utcnow().isoformat() + "Z"
        )

        logger.info(
            f"Conflict resolved: operation={operation}, memory_id={memory_id}, "
            f"content={new_content[:50]}..."
        )

        return conflict_result

    except Exception as e:
        logger.error(f"Failed to resolve conflict for content '{new_content[:50]}...': {e}")
        raise


def add_with_conflict_check(
    messages: list[dict],
    user_id: str = "orchestrator",
    metadata: Optional[dict] = None,
    client: Any = None,
    log_conflicts: bool = True
) -> dict:
    """Add memory with automatic conflict detection and logging.

    Wrapper around resolve_conflict that logs resolution results to audit trail.

    Args:
        messages: List of message dicts with 'role' and 'content' keys
        user_id: User ID for memory isolation (default: "orchestrator")
        metadata: Optional metadata for context scoping
        client: Optional Mem0Client instance. If None, uses get_mem0_client()
        log_conflicts: Whether to write resolution to .memory/conflict_log.jsonl

    Returns:
        Mem0 add result dict

    Example:
        >>> result = add_with_conflict_check(
        ...     messages=[{"role": "user", "content": "EMA is 20 periods"}],
        ...     user_id="orchestrator",
        ...     metadata={"asset_class": "crypto"}
        ... )
    """
    if client is None:
        from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
        client = get_mem0_client()

    # Extract content from messages (Mem0 expects message list)
    content = " ".join([msg.get("content", "") for msg in messages if msg.get("content")])

    # Resolve conflict
    conflict_result = resolve_conflict(
        new_content=content,
        user_id=user_id,
        metadata=metadata,
        client=client
    )

    # Log conflict if enabled
    if log_conflicts:
        _log_conflict(conflict_result)

    # Return the full add result from Mem0
    # Note: resolve_conflict already called client.add(), so we return the conflict result
    return {
        "memory_id": conflict_result.memory_id,
        "operation": conflict_result.operation,
        "confidence": conflict_result.confidence,
        "reason": conflict_result.reason
    }


def _generate_reason(operation: str, content: str) -> str:
    """Generate human-readable reason for operation.

    Args:
        operation: Operation type (ADD/UPDATE/DELETE/NOOP)
        content: Memory content

    Returns:
        Human-readable explanation
    """
    reasons = {
        "ADD": "No conflict detected - new unique memory added",
        "UPDATE": "Contradiction detected - updated existing memory",
        "DELETE": "Memory marked for deletion by conflict resolver",
        "NOOP": "Duplicate detected - no action taken",
        "UNKNOWN": "Operation type unclear from Mem0 response"
    }

    reason = reasons.get(operation, f"Unknown operation: {operation}")
    return f"{reason} (content: {content[:80]}...)"


def _log_conflict(conflict_result: ConflictResult) -> None:
    """Log conflict resolution to audit trail.

    Appends conflict result to .memory/conflict_log.jsonl (one JSON object per line).

    Args:
        conflict_result: ConflictResult to log
    """
    try:
        log_file = Path(".memory") / "conflict_log.jsonl"

        # Ensure .memory directory exists
        log_file.parent.mkdir(exist_ok=True)

        # Append conflict result as JSON line
        with open(log_file, "a", encoding="utf-8") as f:
            json.dump(conflict_result.to_dict(), f)
            f.write("\n")

        logger.debug(f"Logged conflict to {log_file}: {conflict_result.operation}")

    except Exception as e:
        # Don't fail the operation if logging fails
        logger.warning(f"Failed to log conflict to audit trail: {e}")


__all__ = [
    "ConflictResult",
    "detect_conflicts",
    "resolve_conflict",
    "add_with_conflict_check"
]
