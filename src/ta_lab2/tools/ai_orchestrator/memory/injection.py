"""Context injection utilities for AI prompts.

Formats retrieved memories for inclusion in Claude/ChatGPT/Gemini prompts.
Implements MEMO-03: Context injection system retrieves top-K memories.
"""
import logging
from typing import List, Optional

from .query import search_memories, SearchResult, SearchResponse

logger = logging.getLogger(__name__)


def format_memories_for_prompt(
    results: List[SearchResult],
    max_length: int = 4000,
    include_metadata: bool = True,
    include_similarity: bool = True
) -> str:
    """Format search results for AI prompt injection.

    Args:
        results: List of SearchResult from search_memories()
        max_length: Maximum total character length (to respect token limits)
        include_metadata: Include type and source metadata
        include_similarity: Include similarity score

    Returns:
        Formatted string ready for prompt injection
    """
    if not results:
        return "# No relevant memories found for this query.\n"

    lines = ["# Relevant Project Memories\n"]
    current_length = len(lines[0])

    for i, result in enumerate(results, 1):
        # Build memory block
        header = f"\n## Memory {i}"
        if include_similarity:
            header += f" (Relevance: {result.similarity:.0%})"
        header += "\n"

        meta_lines = []
        if include_metadata:
            if result.metadata.get("type"):
                meta_lines.append(f"**Type:** {result.metadata['type']}")
            if result.metadata.get("source_path"):
                meta_lines.append(f"**Source:** {result.metadata['source_path']}")

        content = result.content.strip()

        # Assemble block
        block_parts = [header]
        if meta_lines:
            block_parts.append("\n".join(meta_lines) + "\n")
        block_parts.append(f"\n{content}\n")
        block = "".join(block_parts)

        # Check length limit
        if current_length + len(block) > max_length:
            lines.append(f"\n*({len(results) - i + 1} more memories truncated)*\n")
            break

        lines.append(block)
        current_length += len(block)

    return "".join(lines)


def inject_memory_context(
    query: str,
    max_memories: int = 5,
    min_similarity: float = 0.7,
    memory_type: Optional[str] = None,
    max_length: int = 4000,
    client=None
) -> str:
    """Retrieve relevant memories and format for AI prompt context.

    This is the main entry point for RAG context injection.
    Combines search_memories() + format_memories_for_prompt().

    Args:
        query: The user query or task description
        max_memories: Maximum number of memories to retrieve (top-K)
        min_similarity: Minimum similarity threshold (default 0.7 per MEMO-02)
        memory_type: Optional filter by memory type
        max_length: Maximum character length for output
        client: Optional MemoryClient instance

    Returns:
        Formatted string ready to inject into AI prompt

    Example:
        >>> context = inject_memory_context("How do I backtest a strategy?")
        >>> prompt = f"Given this context:\n{context}\n\nQuestion: ..."
    """
    response = search_memories(
        query=query,
        max_results=max_memories,
        min_similarity=min_similarity,
        memory_type=memory_type,
        client=client
    )

    logger.info(
        f"Context injection: query='{query[:30]}...', "
        f"found={response.filtered_count} memories"
    )

    return format_memories_for_prompt(
        results=response.results,
        max_length=max_length
    )


def build_augmented_prompt(
    user_query: str,
    system_prompt: str = "",
    max_memories: int = 5,
    min_similarity: float = 0.7,
    memory_type: Optional[str] = None,
    client=None
) -> dict:
    """Build a complete RAG-augmented prompt structure.

    Returns a dict suitable for API calls to Claude/ChatGPT/Gemini.

    Args:
        user_query: The user's question or task
        system_prompt: Optional base system prompt
        max_memories: Maximum number of memories to retrieve
        min_similarity: Minimum similarity threshold
        memory_type: Optional filter by memory type
        client: Optional MemoryClient instance

    Returns:
        Dict with 'system', 'context', 'user' keys for prompt construction

    Example:
        >>> prompt = build_augmented_prompt("Explain EMA crossover strategy")
        >>> # Use prompt['system'] + prompt['context'] + prompt['user']
    """
    memory_context = inject_memory_context(
        query=user_query,
        max_memories=max_memories,
        min_similarity=min_similarity,
        memory_type=memory_type,
        client=client
    )

    return {
        "system": system_prompt or "You are a helpful assistant for the ta_lab2 project.",
        "context": memory_context,
        "user": user_query,
        "full_prompt": (
            f"{system_prompt}\n\n"
            f"{memory_context}\n\n"
            f"User Query: {user_query}"
        ) if system_prompt else f"{memory_context}\n\nUser Query: {user_query}"
    }


def estimate_context_tokens(text: str) -> int:
    """Estimate token count for context budgeting.

    Uses simple heuristic: ~4 characters per token for English.
    For accurate counts, use tiktoken library.

    Args:
        text: Text to estimate

    Returns:
        Estimated token count
    """
    # Rough heuristic - for accuracy use tiktoken
    return len(text) // 4
