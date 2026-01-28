"""Memory integration for AI orchestrator.

Provides ChromaDB client, semantic search, context injection,
incremental updates, and REST API for cross-platform access.

Quick start:
    from ta_lab2.tools.ai_orchestrator.memory import (
        search_memories,
        inject_memory_context,
        validate_memory_store
    )

    # Search memories
    results = search_memories("EMA calculation")

    # Get formatted context for AI prompt
    context = inject_memory_context("How do I backtest?")

Run API server:
    uvicorn ta_lab2.tools.ai_orchestrator.memory.api:app --port 8080
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
from .api import (
    create_memory_api,
    MemorySearchRequest,
    MemorySearchResponse,
    MemoryStatsResponse,
    ContextInjectionRequest,
    ContextInjectionResponse,
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
    # API
    "create_memory_api",
    "MemorySearchRequest",
    "MemorySearchResponse",
    "MemoryStatsResponse",
    "ContextInjectionRequest",
    "ContextInjectionResponse",
]
