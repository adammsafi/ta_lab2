"""Validation utilities for ChromaDB memory store integrity."""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .client import MemoryClient, get_memory_client

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
    client: Optional[MemoryClient] = None,
    expected_count: int = 3763,
    expected_dimensions: int = 1536,
    sample_size: int = 10,
) -> MemoryValidationResult:
    """Validate ChromaDB memory store integrity.

    Checks:
    1. Total count matches expected (3,763 memories)
    2. Sample embeddings have correct dimensions (1536)
    3. Sample metadata contains required fields
    4. Distance metric configuration (should be cosine)

    Args:
        client: MemoryClient instance. If None, uses get_memory_client().
        expected_count: Expected number of memories
        expected_dimensions: Expected embedding dimensions
        sample_size: Number of samples to validate

    Returns:
        MemoryValidationResult with validation details
    """
    if client is None:
        client = get_memory_client()

    issues = []
    collection = client.collection

    # Check 1: Count validation
    actual_count = collection.count()
    count_valid = actual_count >= expected_count
    if not count_valid:
        issues.append(
            f"Count mismatch: expected >={expected_count}, got {actual_count}"
        )

    # Check 2: Distance metric
    metadata = collection.metadata or {}
    distance_metric = metadata.get("hnsw:space", "l2")  # ChromaDB defaults to L2
    if distance_metric != "cosine":
        issues.append(
            f"Distance metric is '{distance_metric}', recommended 'cosine' for text embeddings"
        )

    # Check 3: Sample embedding dimensions
    sample_results = collection.get(
        limit=sample_size, include=["embeddings", "metadatas", "documents"]
    )

    sample_valid = True
    detected_dimensions = 0

    embeddings = sample_results.get("embeddings")
    if embeddings is not None and len(embeddings) > 0:
        for i, emb in enumerate(embeddings):
            if emb is None:
                issues.append(f"Sample {i}: embedding is None")
                sample_valid = False
            elif len(emb) != expected_dimensions:
                issues.append(
                    f"Sample {i}: dimension {len(emb)}, expected {expected_dimensions}"
                )
                sample_valid = False
            else:
                detected_dimensions = len(emb)
    else:
        issues.append("No embeddings returned in sample")
        sample_valid = False

    # Check 4: Metadata completeness
    metadata_complete = True
    for i, meta in enumerate(sample_results.get("metadatas", [])):
        if not meta:
            issues.append(f"Sample {i}: metadata is empty")
            metadata_complete = False

    # Determine overall validity
    # Note: We don't fail on L2 distance (just warn) since existing data may use it
    is_valid = count_valid and sample_valid and metadata_complete

    result = MemoryValidationResult(
        is_valid=is_valid,
        total_count=actual_count,
        expected_count=expected_count,
        sample_valid=sample_valid,
        metadata_complete=metadata_complete,
        distance_metric=distance_metric,
        embedding_dimensions=detected_dimensions
        if detected_dimensions
        else expected_dimensions,
        issues=issues,
    )

    logger.info(f"Memory validation complete: {result}")
    return result


def quick_health_check(client: Optional[MemoryClient] = None) -> bool:
    """Quick health check for memory store.

    Returns True if store is accessible and has memories.
    Use validate_memory_store() for detailed validation.
    """
    try:
        if client is None:
            client = get_memory_client()
        return client.count() > 0
    except Exception as e:
        logger.error(f"Memory health check failed: {e}")
        return False
