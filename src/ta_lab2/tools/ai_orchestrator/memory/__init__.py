"""Memory integration for AI orchestrator.

Provides ChromaDB client, semantic search, and context injection
for RAG (Retrieval-Augmented Generation) with AI platforms.
"""
from .client import MemoryClient, get_memory_client, reset_memory_client
from .validation import (
    MemoryValidationResult,
    validate_memory_store,
    quick_health_check
)
from .update import (
    MemoryInput,
    MemoryUpdateResult,
    add_memory,
    add_memories,
    delete_memory,
    get_embedding,
    EMBEDDING_MODEL,
    EMBEDDING_DIMENSIONS,
)
from .query import (
    SearchResult,
    SearchResponse,
    search_memories,
    get_memory_by_id,
    get_memory_types
)
from .injection import (
    format_memories_for_prompt,
    inject_memory_context,
    build_augmented_prompt,
    estimate_context_tokens
)

__all__ = [
    # Client
    "MemoryClient",
    "get_memory_client",
    "reset_memory_client",
    # Validation
    "MemoryValidationResult",
    "validate_memory_store",
    "quick_health_check",
    # Update
    "MemoryInput",
    "MemoryUpdateResult",
    "add_memory",
    "add_memories",
    "delete_memory",
    "get_embedding",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIMENSIONS",
    # Query
    "SearchResult",
    "SearchResponse",
    "search_memories",
    "get_memory_by_id",
    "get_memory_types",
    # Injection
    "format_memories_for_prompt",
    "inject_memory_context",
    "build_augmented_prompt",
    "estimate_context_tokens",
]
