"""Validation utilities for ChromaDB memory store integrity.

NOTE: This module was written against ChromaDB (MemoryClient). ChromaDB has
been replaced by Mem0 + Qdrant. The validate_memory_store() and
quick_health_check() functions are retained for reference but ChromaDB
is no longer available -- the functions will raise ImportError if called.

For live health checks use server.py /health which calls mem0_client directly.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List

logger = logging.getLogger(__name__)


@dataclass
class MemoryValidationResult:
    """Result of memory store validation."""

    is_valid: bool
    total_count: int
    expected_count: int
    sample_valid: bool
    metadata_complete: bool
    distance_metric: str
    embedding_dimensions: int
    issues: List[str] = field(default_factory=list)
    validated_at: datetime = field(default_factory=datetime.now)

    def __str__(self) -> str:
        status = "VALID" if self.is_valid else "INVALID"
        return (
            f"MemoryValidation: {status}\n"
            f"  Count: {self.total_count}/{self.expected_count}\n"
            f"  Distance: {self.distance_metric}\n"
            f"  Dimensions: {self.embedding_dimensions}\n"
            f"  Issues: {len(self.issues)}"
        )


def validate_memory_store(
    client=None,
    expected_count: int = 3763,
    expected_dimensions: int = 1536,
    sample_size: int = 10,
) -> MemoryValidationResult:
    """Validate ChromaDB memory store integrity.

    DEPRECATED: ChromaDB has been replaced by Mem0 + Qdrant.
    This function is retained for reference only and will raise ImportError.
    """
    raise ImportError(
        "validate_memory_store() requires ChromaDB which has been replaced by "
        "Mem0 + Qdrant. Use mem0_client.get_mem0_client().memory_count for "
        "live health checks."
    )


def quick_health_check(client=None) -> bool:
    """Quick health check for memory store.

    DEPRECATED: ChromaDB has been replaced by Mem0 + Qdrant.
    Returns True if Qdrant/Mem0 backend is accessible and has memories.
    """
    try:
        from .mem0_client import get_mem0_client

        mem0 = get_mem0_client()
        return mem0.memory_count > 0
    except Exception as e:
        logger.error(f"Memory health check failed: {e}")
        return False
