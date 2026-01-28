"""Memory integration for AI orchestrator."""
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
]
