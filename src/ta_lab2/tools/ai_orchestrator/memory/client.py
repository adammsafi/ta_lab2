"""ChromaDB client wrapper for ta_lab2 memory system."""
import logging
from typing import Optional
import chromadb
from chromadb.api.models.Collection import Collection

logger = logging.getLogger(__name__)


class MemoryClient:
    """Singleton wrapper for ChromaDB PersistentClient.

    Provides thread-safe access to the project_memories collection.
    Use get_memory_client() factory function for access.
    """

    _instance: Optional["MemoryClient"] = None

    def __init__(self, chroma_path: str, collection_name: str = "project_memories"):
        """Initialize ChromaDB client.

        Args:
            chroma_path: Path to ChromaDB persistent storage
            collection_name: Name of collection to use
        """
        self._client = chromadb.PersistentClient(path=chroma_path)
        self._collection_name = collection_name
        self._collection: Optional[Collection] = None
        logger.info(f"MemoryClient initialized with path: {chroma_path}")

    @property
    def collection(self) -> Collection:
        """Get or create the collection."""
        if self._collection is None:
            self._collection = self._client.get_collection(name=self._collection_name)
            logger.info(f"Loaded collection: {self._collection_name}")
        return self._collection

    @property
    def client(self) -> chromadb.ClientAPI:
        """Access underlying ChromaDB client."""
        return self._client

    def count(self) -> int:
        """Return total memory count."""
        return self.collection.count()

    def get_metadata(self) -> dict:
        """Return collection metadata including distance metric."""
        return self.collection.metadata or {}


def get_memory_client(config=None) -> MemoryClient:
    """Factory function to get or create MemoryClient singleton.

    Args:
        config: Optional OrchestratorConfig. If None, loads from environment.

    Returns:
        MemoryClient instance
    """
    if MemoryClient._instance is None:
        if config is None:
            from ta_lab2.tools.ai_orchestrator.config import load_config
            config = load_config()
        MemoryClient._instance = MemoryClient(
            chroma_path=config.chromadb_path,
            collection_name=config.chromadb_collection_name
        )
    return MemoryClient._instance


def reset_memory_client():
    """Reset singleton for testing. Do not use in production."""
    MemoryClient._instance = None
