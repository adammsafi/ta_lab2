"""Mem0 configuration using existing ChromaDB backend.

Configures Mem0 to use ChromaDB as vector store without re-embedding
existing 3,763 memories. Maintains embedding model compatibility with
Phase 2 (text-embedding-3-small, 1536 dimensions).
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

    Configures Mem0 to use existing ChromaDB as vector backend, preserving
    all 3,763 embedded memories from Phase 2. Uses text-embedding-3-small
    to match existing 1536-dimension embeddings.

    Args:
        config: Optional Mem0Config. If None, loads from OrchestratorConfig.

    Returns:
        Configuration dict for Memory.from_config()

    Raises:
        ValueError: If ChromaDB path doesn't exist or API key missing

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

    # Validate ChromaDB path exists
    chromadb_path = Path(config.chromadb_path)
    if not chromadb_path.exists():
        raise ValueError(
            f"ChromaDB path does not exist: {config.chromadb_path}. "
            "Ensure Phase 2 ChromaDB setup is complete."
        )

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

    # Return configuration dict for Memory.from_config()
    return {
        "vector_store": {
            "provider": "chromadb",
            "config": {
                "collection_name": config.collection_name,
                "path": str(chromadb_path)
            }
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
