"""Mem0 configuration with Qdrant vector store.

Configures Mem0 with Qdrant persistent local storage. Uses same embedding
model as Phase 2 (text-embedding-3-small, 1536 dimensions) for compatibility.

NOTE: mem0ai 1.0.2 doesn't support ChromaDB provider (only Qdrant). Mem0
provides the intelligence layer (conflict detection, dedup) while Qdrant
handles vector storage. Future migration to ChromaDB backend possible when
supported.
"""
import os
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Mem0Config:
    """Configuration for Mem0 with ChromaDB backend.

    Attributes:
        chromadb_path: Path to existing ChromaDB storage
        collection_name: ChromaDB collection name
        llm_model: LLM for conflict detection (default: gpt-4o-mini)
        embedder_model: Embedding model (MUST be text-embedding-3-small for compatibility)
        openai_api_key: OpenAI API key for LLM and embeddings
    """
    chromadb_path: str
    collection_name: str = "project_memories"
    llm_model: str = "gpt-4o-mini"
    embedder_model: str = "text-embedding-3-small"
    openai_api_key: Optional[str] = None


def create_mem0_config(config: Optional[Mem0Config] = None) -> dict:
    """Create Mem0 configuration dict for Memory.from_config().

    Configures Mem0 with Qdrant vector store (local persistent storage).
    Uses text-embedding-3-small to match Phase 2 embeddings (1536-dim).

    NOTE: mem0ai 1.0.2 doesn't support ChromaDB provider. Using Qdrant
    with local storage provides Mem0 intelligence layer (conflict detection,
    dedup) with persistent vector storage.

    Args:
        config: Optional Mem0Config. If None, loads from OrchestratorConfig.

    Returns:
        Configuration dict for Memory.from_config()

    Raises:
        ValueError: If base path doesn't exist or API key missing

    Example:
        >>> from mem0 import Memory
        >>> config = create_mem0_config()
        >>> memory = Memory.from_config(config)
    """
    if config is None:
        # Load from OrchestratorConfig
        from ta_lab2.tools.ai_orchestrator.config import load_config
        orchestrator_config = load_config()

        config = Mem0Config(
            chromadb_path=orchestrator_config.chromadb_path,
            collection_name=orchestrator_config.chromadb_collection_name,
            openai_api_key=orchestrator_config.openai_api_key
        )

    # Validate base path exists (parent directory for Qdrant storage)
    chromadb_path = Path(config.chromadb_path)
    base_path = chromadb_path.parent if chromadb_path.exists() else chromadb_path
    if not base_path.exists():
        # Create parent directory if it doesn't exist
        base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Created base directory for Mem0 storage: {base_path}")

    # Validate API key
    api_key = config.openai_api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY not found in config or environment. "
            "Required for Mem0 LLM and embedding operations."
        )

    # Validate embedding model (critical for dimension compatibility)
    if config.embedder_model != "text-embedding-3-small":
        logger.warning(
            f"Embedder model is {config.embedder_model}, but Phase 2 uses "
            "text-embedding-3-small (1536-dim). This may cause dimension mismatch."
        )

    logger.info(
        f"Creating Mem0 config with ChromaDB backend: {config.chromadb_path}, "
        f"collection: {config.collection_name}"
    )

    # NOTE: mem0ai 1.0.2 doesn't support "chromadb" provider (only qdrant).
    # Using Qdrant with persistent server storage for reliable persistence.
    # This allows Mem0 intelligence layer while preserving embeddings.

    # Check for QDRANT_HOST environment variable (server mode)
    qdrant_host = os.environ.get("QDRANT_HOST", "localhost")
    qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
    use_server_mode = os.environ.get("QDRANT_SERVER_MODE", "true").lower() == "true"

    if use_server_mode:
        logger.info(
            f"Using Qdrant server mode at {qdrant_host}:{qdrant_port} "
            "(reliable persistence)"
        )
        qdrant_config = {
            "collection_name": config.collection_name,
            "embedding_model_dims": 1536,  # Match text-embedding-3-small
            "host": qdrant_host,
            "port": qdrant_port,
        }
    else:
        # Fallback to local embedded mode (has persistence limitations on Windows)
        qdrant_path = chromadb_path.parent / "qdrant_mem0"
        qdrant_path.mkdir(parents=True, exist_ok=True)
        logger.warning(
            f"Using Qdrant local embedded mode at {qdrant_path} "
            "(has persistence limitations - use server mode for production)"
        )
        qdrant_config = {
            "collection_name": config.collection_name,
            "embedding_model_dims": 1536,
            "path": str(qdrant_path),
        }

    # Return configuration dict for Memory.from_config()
    return {
        "vector_store": {
            "provider": "qdrant",
            "config": qdrant_config
        },
        "llm": {
            "provider": "openai",
            "config": {
                "model": config.llm_model,
                "api_key": api_key
            }
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "model": config.embedder_model,
                "api_key": api_key
            }
        }
    }


__all__ = ["Mem0Config", "create_mem0_config"]
