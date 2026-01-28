"""Semantic search API for ChromaDB memory store."""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Individual search result from memory query."""

    memory_id: str
    content: str
    metadata: Dict[str, Any]
    similarity: float  # 0.0 to 1.0, higher is better
    distance: float    # Raw ChromaDB distance (lower is better)

    def __str__(self) -> str:
        return f"Memory({self.memory_id[:8]}..., sim={self.similarity:.2f})"


@dataclass
class SearchResponse:
    """Response from memory search operation."""

    query: str
    results: List[SearchResult]
    total_found: int  # Before threshold filtering
    filtered_count: int  # After threshold filtering
    search_time_ms: float
    threshold_used: float

    def __str__(self) -> str:
        return (
            f"Search: '{self.query[:30]}...' -> "
            f"{self.filtered_count}/{self.total_found} results "
            f"(threshold={self.threshold_used})"
        )


def search_memories(
    query: str,
    max_results: int = 10,
    min_similarity: float = 0.7,
    memory_type: Optional[str] = None,
    metadata_filter: Optional[Dict[str, Any]] = None,
    client=None
) -> SearchResponse:
    """Search memories using semantic similarity.

    ChromaDB returns DISTANCE (lower = more similar), not similarity.
    This function converts to similarity (higher = better) for intuitive use.

    Requirement MEMO-02: relevance threshold >0.7 similarity.

    Args:
        query: Natural language search query
        max_results: Maximum number of results to return (top-K)
        min_similarity: Minimum similarity threshold (0.0-1.0, default 0.7)
                       Internally converted to distance: threshold = 1.0 - min_similarity
        memory_type: Optional filter by 'type' metadata field
        metadata_filter: Optional custom metadata filter (ChromaDB where clause)
        client: Optional MemoryClient instance

    Returns:
        SearchResponse with filtered results

    Example:
        >>> results = search_memories("How do I handle multi-timeframe EMAs?")
        >>> for r in results.results:
        ...     print(f"{r.similarity:.2f}: {r.content[:50]}...")
    """
    import time
    start_time = time.perf_counter()

    # Get client
    if client is None:
        from .client import get_memory_client
        client = get_memory_client()

    collection = client.collection

    # Build metadata filter
    where_filter = None
    if memory_type:
        where_filter = {"type": {"$eq": memory_type}}
    elif metadata_filter:
        where_filter = metadata_filter

    # Query ChromaDB
    # Note: ChromaDB returns distance, not similarity
    raw_results = collection.query(
        query_texts=[query],
        n_results=max_results,
        where=where_filter,
        include=["documents", "metadatas", "distances"]
    )

    # Convert distance to similarity and filter
    # For cosine distance: similarity = 1 - distance
    # For L2 distance: similarity approximation (less accurate)
    max_distance = 1.0 - min_similarity  # threshold conversion

    results: List[SearchResult] = []
    total_found = len(raw_results["ids"][0]) if raw_results["ids"] else 0

    for i in range(total_found):
        distance = raw_results["distances"][0][i]
        similarity = 1.0 - distance  # Convert to similarity

        # Filter by threshold
        if distance > max_distance:
            continue

        results.append(SearchResult(
            memory_id=raw_results["ids"][0][i],
            content=raw_results["documents"][0][i],
            metadata=raw_results["metadatas"][0][i] or {},
            similarity=round(similarity, 4),
            distance=round(distance, 4)
        ))

    elapsed_ms = (time.perf_counter() - start_time) * 1000

    response = SearchResponse(
        query=query,
        results=results,
        total_found=total_found,
        filtered_count=len(results),
        search_time_ms=round(elapsed_ms, 2),
        threshold_used=min_similarity
    )

    logger.debug(f"Memory search: {response}")
    return response


def get_memory_by_id(memory_id: str, client=None) -> Optional[SearchResult]:
    """Retrieve a specific memory by ID.

    Args:
        memory_id: The memory ID to retrieve
        client: Optional MemoryClient instance

    Returns:
        SearchResult if found, None otherwise
    """
    if client is None:
        from .client import get_memory_client
        client = get_memory_client()

    results = client.collection.get(
        ids=[memory_id],
        include=["documents", "metadatas", "embeddings"]
    )

    if not results["ids"]:
        return None

    return SearchResult(
        memory_id=results["ids"][0],
        content=results["documents"][0],
        metadata=results["metadatas"][0] or {},
        similarity=1.0,  # Exact match
        distance=0.0
    )


def get_memory_types(client=None, sample_size: int = 100) -> List[str]:
    """Get list of unique memory types from metadata.

    Args:
        client: Optional MemoryClient instance
        sample_size: Number of memories to sample for types

    Returns:
        List of unique type values
    """
    if client is None:
        from .client import get_memory_client
        client = get_memory_client()

    results = client.collection.get(
        limit=sample_size,
        include=["metadatas"]
    )

    types = set()
    for meta in results.get("metadatas", []):
        if meta and "type" in meta:
            types.add(meta["type"])

    return sorted(list(types))
