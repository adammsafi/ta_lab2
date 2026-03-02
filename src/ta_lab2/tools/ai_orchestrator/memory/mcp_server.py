"""FastMCP tool definitions for ta_lab2 memory server.

Defines 6 MCP tools wrapping Mem0Client and formatting utilities.
All tools use the Mem0/Qdrant backend exclusively (never ChromaDB).

Tools:
    memory_search   - Semantic search returning raw results with scores
    memory_context  - Formatted RAG context for prompt injection
    memory_store    - Store new memories with conflict detection
    memory_stats    - Memory store statistics
    memory_health   - Health report with staleness detection
    list_categories - Discover available memory categories

Run standalone:
    fastmcp run ta_lab2.tools.ai_orchestrator.memory.mcp_server:mcp

Mount in combined server:
    from .mcp_server import mcp
    mcp_app = mcp.http_app(path="/")
"""

import logging
from typing import Annotated, Optional

from fastmcp import FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)

mcp = FastMCP(
    name="ta-lab2-memory",
    instructions=(
        "Memory server for the ta_lab2 trading system project. "
        "Search memories for project context, patterns, gotchas, and decisions. "
        "Use memory_search for targeted lookups with raw results. "
        "Use memory_context for formatted RAG context blocks. "
        "Use memory_store to persist new knowledge with conflict detection."
    ),
)


@mcp.tool
def memory_search(
    query: Annotated[str, "Natural language search query"],
    top_k: Annotated[
        int, Field(description="Maximum results to return", ge=1, le=50)
    ] = 10,
    min_similarity: Annotated[
        float,
        Field(description="Minimum similarity threshold 0.0-1.0", ge=0.0, le=1.0),
    ] = 0.6,
    category: Annotated[Optional[str], "Filter by memory category"] = None,
) -> dict:
    """Search project memories by semantic similarity.

    Returns raw results with text, metadata, and similarity scores.
    Use for targeted lookups when you need specific project facts.
    """
    from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client

    client = get_mem0_client()

    filters = {"category": category} if category else None
    results = client.search(query=query, limit=top_k, filters=filters)

    # Mem0 search returns either a list or {"results": [...]} dict
    raw_list = results if isinstance(results, list) else results.get("results", [])

    # Results from Mem0 have keys: id, memory (not content), metadata, score
    formatted = []
    for r in raw_list:
        score = r.get("score", 0.0)
        if score >= min_similarity:
            formatted.append(
                {
                    "id": r.get("id"),
                    "content": r.get("memory"),
                    "metadata": r.get("metadata", {}),
                    "similarity": round(score, 4),
                }
            )

    return {"query": query, "results": formatted, "count": len(formatted)}


@mcp.tool
def memory_context(
    query: Annotated[str, "Query for context retrieval"],
    max_memories: Annotated[
        int, Field(description="Max memories to include", ge=1, le=20)
    ] = 10,
    min_similarity: Annotated[
        float,
        Field(description="Minimum similarity threshold 0.0-1.0", ge=0.0, le=1.0),
    ] = 0.6,
) -> dict:
    """Get formatted RAG context for prompt injection.

    Returns memories formatted as markdown, ready to use as context.
    Use this when you need a formatted context block for decision-making.

    This tool uses Mem0Client for search, then adapts results through
    the existing format_memories_for_prompt pipeline.
    """
    from ta_lab2.tools.ai_orchestrator.memory.injection import (
        format_memories_for_prompt,
    )
    from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
    from ta_lab2.tools.ai_orchestrator.memory.query import SearchResult

    client = get_mem0_client()
    results = client.search(query=query, limit=max_memories)

    # Mem0 search returns either a list or {"results": [...]} dict
    raw_list = results if isinstance(results, list) else results.get("results", [])

    # Adapt Mem0 results to SearchResult dataclass for format_memories_for_prompt
    adapted_results = []
    for r in raw_list:
        score = r.get("score", 0.0)
        if score >= min_similarity:
            adapted_results.append(
                SearchResult(
                    memory_id=r["id"],
                    content=r["memory"],
                    metadata=r.get("metadata", {}),
                    similarity=score,
                    distance=1.0 - score,
                )
            )

    context = format_memories_for_prompt(results=adapted_results)

    return {"query": query, "context": context}


@mcp.tool
def memory_store(
    content: Annotated[str, "Memory content to store"],
    source: Annotated[
        str, "AI consumer identifier (e.g., 'claude_code', 'codex')"
    ] = "claude_code",
    category: Annotated[Optional[str], "Memory category"] = None,
    user_id: Annotated[str, "User ID for memory isolation"] = "orchestrator",
) -> dict:
    """Store a new memory with conflict detection.

    Uses Mem0's LLM-powered conflict resolution (GPT-4o-mini) to prevent
    duplicates and resolve contradictions. Returns the operation performed
    (ADD/UPDATE/DELETE/NOOP).
    """
    from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client

    client = get_mem0_client()

    metadata = {"source": source}
    if category:
        metadata["category"] = category

    messages = [{"role": "user", "content": content}]
    result = client.add(
        messages=messages, user_id=user_id, metadata=metadata, infer=True
    )

    return result


@mcp.tool
def memory_stats() -> dict:
    """Get memory store statistics (total count, collection info)."""
    from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client

    client = get_mem0_client()

    return {
        "total_memories": client.memory_count,
        "collection_name": "project_memories",
        "backend": "qdrant",
    }


@mcp.tool
def memory_health(
    staleness_days: Annotated[
        int, Field(description="Days threshold for staleness", ge=1)
    ] = 90,
) -> dict:
    """Generate memory health report showing stale and deprecated memories.

    Returns counts of healthy, stale, deprecated, and metadata-incomplete
    memories along with age distribution buckets.
    """
    from ta_lab2.tools.ai_orchestrator.memory.health import MemoryHealthMonitor

    monitor = MemoryHealthMonitor(staleness_days=staleness_days)
    report = monitor.generate_health_report()

    return {
        "total_memories": report.total_memories,
        "healthy": report.healthy,
        "stale": report.stale,
        "deprecated": report.deprecated,
        "missing_metadata": report.missing_metadata,
        "age_distribution": report.age_distribution,
    }


@mcp.tool
def list_categories() -> dict:
    """List available memory categories for filtering.

    Scans all memories and extracts unique category values from metadata.
    Use this to discover what categories exist before filtering searches.
    """
    from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client

    client = get_mem0_client()

    all_memories = client.get_all(user_id="orchestrator")
    categories: set[str] = set()
    for mem in all_memories:
        cat = mem.get("metadata", {}).get("category")
        if cat:
            categories.add(cat)

    return {"categories": sorted(categories), "count": len(categories)}


__all__ = ["mcp"]
