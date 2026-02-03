"""Incremental memory update pipeline.

Adds new memories without breaking existing embeddings.
Implements MEMO-07: Incremental update pipeline.
"""
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Embedding model constants (from existing 3,763 memories)
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536


@dataclass
class MemoryInput:
    """Input for adding a new memory."""

    memory_id: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryUpdateResult:
    """Result of memory update operation."""

    added: int = 0
    updated: int = 0
    failed: int = 0
    errors: List[str] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def total_processed(self) -> int:
        return self.added + self.updated + self.failed

    def __str__(self) -> str:
        return (
            f"MemoryUpdate: added={self.added}, updated={self.updated}, "
            f"failed={self.failed}, duration={self.duration_ms:.1f}ms"
        )


def get_embedding(texts: List[str], model: str = EMBEDDING_MODEL) -> List[List[float]]:
    """Generate embeddings using OpenAI API.

    Args:
        texts: List of texts to embed
        model: OpenAI embedding model name

    Returns:
        List of embedding vectors (1536 dimensions each)

    Raises:
        ValueError: If OpenAI API key not configured
        Exception: If API call fails
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("openai package required. Install with: pip install openai")

    import os

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        from ta_lab2.tools.ai_orchestrator.config import load_config

        config = load_config()
        api_key = config.openai_api_key

    if not api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    client = OpenAI(api_key=api_key)

    # Clean texts (replace newlines with spaces)
    cleaned_texts = [text.replace("\n", " ").strip() for text in texts]

    response = client.embeddings.create(input=cleaned_texts, model=model)

    embeddings = [item.embedding for item in response.data]

    # Validate dimensions
    for i, emb in enumerate(embeddings):
        if len(emb) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Embedding {i} has {len(emb)} dimensions, expected {EMBEDDING_DIMENSIONS}"
            )

    return embeddings


def add_memory(
    memory_id: str, content: str, metadata: Optional[Dict[str, Any]] = None, client=None
) -> MemoryUpdateResult:
    """Add a single memory to the store.

    Uses upsert to handle duplicates gracefully.

    Args:
        memory_id: Unique identifier for the memory
        content: Text content of the memory
        metadata: Optional metadata dict
        client: Optional MemoryClient instance

    Returns:
        MemoryUpdateResult with operation details
    """
    return add_memories(
        memories=[
            MemoryInput(memory_id=memory_id, content=content, metadata=metadata or {})
        ],
        client=client,
    )


def add_memories(
    memories: List[MemoryInput], batch_size: int = 50, client=None
) -> MemoryUpdateResult:
    """Add multiple memories with batch embedding generation.

    Uses ChromaDB upsert for atomic add-or-update operations.
    Validates embedding dimensions before insertion.

    Args:
        memories: List of MemoryInput objects
        batch_size: Batch size for embedding generation (default 50)
        client: Optional MemoryClient instance

    Returns:
        MemoryUpdateResult with stats and any errors
    """
    import time

    start_time = time.perf_counter()

    if client is None:
        from .client import get_memory_client

        client = get_memory_client()

    result = MemoryUpdateResult()
    collection = client.collection

    # Process in batches
    for batch_start in range(0, len(memories), batch_size):
        batch = memories[batch_start : batch_start + batch_size]
        batch_num = batch_start // batch_size + 1

        try:
            # Prepare data
            ids = [m.memory_id for m in batch]
            documents = [m.content for m in batch]
            metadatas = [m.metadata for m in batch]

            # Generate embeddings
            try:
                embeddings = get_embedding(documents)
            except Exception as e:
                error_msg = f"Batch {batch_num}: Embedding generation failed: {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)
                result.failed += len(batch)
                continue

            # Check which IDs already exist
            try:
                existing = collection.get(ids=ids, include=[])
                existing_ids = set(existing.get("ids", []))
            except Exception:
                existing_ids = set()

            # Upsert (atomic add-or-update)
            try:
                collection.upsert(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas,
                )

                # Count adds vs updates
                for memory_id in ids:
                    if memory_id in existing_ids:
                        result.updated += 1
                    else:
                        result.added += 1

                logger.info(f"Batch {batch_num}: Processed {len(batch)} memories")

            except Exception as e:
                error_msg = f"Batch {batch_num}: Upsert failed: {e}"
                logger.error(error_msg)
                result.errors.append(error_msg)
                result.failed += len(batch)

        except Exception as e:
            error_msg = f"Batch {batch_num}: Unexpected error: {e}"
            logger.error(error_msg)
            result.errors.append(error_msg)
            result.failed += len(batch)

    result.duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(f"Memory update complete: {result}")
    return result


def delete_memory(memory_id: str, client=None) -> bool:
    """Delete a memory by ID.

    Args:
        memory_id: ID of memory to delete
        client: Optional MemoryClient instance

    Returns:
        True if deleted, False if not found
    """
    if client is None:
        from .client import get_memory_client

        client = get_memory_client()

    try:
        # Check if exists
        existing = client.collection.get(ids=[memory_id], include=[])
        if not existing.get("ids"):
            return False

        client.collection.delete(ids=[memory_id])
        logger.info(f"Deleted memory: {memory_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to delete memory {memory_id}: {e}")
        return False
