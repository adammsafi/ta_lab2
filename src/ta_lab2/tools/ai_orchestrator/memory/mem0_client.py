"""Mem0 client wrapper for intelligent memory operations.

Wraps mem0.Memory with singleton pattern, providing LLM-powered conflict
detection, duplicate prevention, and CRUD operations on existing ChromaDB.
"""
import logging
from typing import Optional, Any
from mem0 import Memory

logger = logging.getLogger(__name__)

# Module-level singleton instance
_mem0_client: Optional["Mem0Client"] = None


class Mem0Client:
    """Singleton wrapper for Mem0 Memory with ChromaDB backend.

    Provides intelligent memory operations including conflict detection,
    duplicate prevention, and semantic search on existing 3,763 memories
    from Phase 2.

    Use get_mem0_client() factory function for access.

    Example:
        >>> client = get_mem0_client()
        >>> client.add(
        ...     messages=[{"role": "user", "content": "EMA uses 20 periods"}],
        ...     user_id="orchestrator"
        ... )
        >>> results = client.search("EMA", user_id="orchestrator", limit=5)
    """

    def __init__(self, config: Optional[dict] = None):
        """Initialize Mem0Client.

        Args:
            config: Optional Mem0 config dict. If None, uses create_mem0_config().
        """
        self._config = config
        self._memory: Optional[Memory] = None
        logger.info("Mem0Client initialized (lazy loading enabled)")

    @property
    def memory(self) -> Memory:
        """Get or create Memory instance (lazy initialization).

        Returns:
            Initialized Memory instance
        """
        if self._memory is None:
            if self._config is None:
                from ta_lab2.tools.ai_orchestrator.memory.mem0_config import create_mem0_config
                self._config = create_mem0_config()

            try:
                self._memory = Memory.from_config(self._config)
                logger.info("Mem0 Memory initialized with ChromaDB backend")
            except Exception as e:
                logger.error(f"Failed to initialize Mem0 Memory: {e}")
                raise

        return self._memory

    def add(
        self,
        messages: list[dict],
        user_id: str,
        metadata: Optional[dict] = None,
        infer: bool = True
    ) -> dict:
        """Add memory with conflict detection.

        Args:
            messages: List of message dicts with 'role' and 'content'
            user_id: User ID for memory isolation
            metadata: Optional metadata dict (created_at, category, etc.)
            infer: Enable LLM conflict detection (default: True)

        Returns:
            Result dict with memory ID and operation (ADD/UPDATE/DELETE/NOOP)

        Raises:
            Exception: If Mem0 add operation fails

        Example:
            >>> result = client.add(
            ...     messages=[
            ...         {"role": "user", "content": "EMA window is 20"},
            ...         {"role": "assistant", "content": "Noted: EMA uses 20-period window"}
            ...     ],
            ...     user_id="orchestrator",
            ...     metadata={"category": "technical_analysis"}
            ... )
        """
        try:
            result = self.memory.add(
                messages=messages,
                user_id=user_id,
                metadata=metadata,
                infer=infer
            )
            logger.info(f"Added memory for user_id={user_id}, infer={infer}")
            return result
        except Exception as e:
            logger.error(f"Failed to add memory for user_id={user_id}: {e}")
            raise

    def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        filters: Optional[dict] = None,
        limit: int = 10
    ) -> list:
        """Search memories by semantic similarity.

        Args:
            query: Search query text
            user_id: Optional user ID for filtering
            filters: Optional metadata filters
            limit: Maximum results to return

        Returns:
            List of memory dicts with id, memory, metadata, and similarity score

        Example:
            >>> results = client.search(
            ...     query="EMA calculation",
            ...     user_id="orchestrator",
            ...     limit=5
            ... )
        """
        try:
            # Build search kwargs
            search_kwargs = {"query": query, "limit": limit}
            if user_id:
                search_kwargs["user_id"] = user_id
            if filters:
                search_kwargs["filters"] = filters

            results = self.memory.search(**search_kwargs)
            logger.info(f"Search returned {len(results)} results for query: {query[:50]}")
            return results
        except Exception as e:
            logger.error(f"Search failed for query '{query}': {e}")
            raise

    def update(
        self,
        memory_id: str,
        data: str,
        metadata: Optional[dict] = None
    ) -> dict:
        """Update existing memory.

        Args:
            memory_id: Memory ID to update
            data: New memory content
            metadata: Optional updated metadata

        Returns:
            Result dict with updated memory details

        Example:
            >>> result = client.update(
            ...     memory_id="mem_123",
            ...     data="EMA window is 20 (updated from 14)",
            ...     metadata={"last_verified": "2026-01-28"}
            ... )
        """
        try:
            update_kwargs = {"memory_id": memory_id, "data": data}
            if metadata:
                update_kwargs["metadata"] = metadata

            result = self.memory.update(**update_kwargs)
            logger.info(f"Updated memory: {memory_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to update memory {memory_id}: {e}")
            raise

    def delete(self, memory_id: str) -> dict:
        """Delete memory by ID.

        Args:
            memory_id: Memory ID to delete

        Returns:
            Result dict confirming deletion

        Example:
            >>> result = client.delete("mem_123")
        """
        try:
            result = self.memory.delete(memory_id=memory_id)
            logger.info(f"Deleted memory: {memory_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to delete memory {memory_id}: {e}")
            raise

    def get_all(self, user_id: Optional[str] = None) -> list:
        """Get all memories for a user.

        Args:
            user_id: Optional user ID for filtering

        Returns:
            List of all memory dicts

        Example:
            >>> memories = client.get_all(user_id="orchestrator")
        """
        try:
            get_kwargs = {}
            if user_id:
                get_kwargs["user_id"] = user_id

            results = self.memory.get_all(**get_kwargs)
            logger.info(f"Retrieved {len(results)} memories")
            return results
        except Exception as e:
            logger.error(f"Failed to get all memories: {e}")
            raise

    @property
    def memory_count(self) -> int:
        """Get total memory count from underlying ChromaDB collection.

        Returns:
            Number of memories in collection
        """
        try:
            # Access underlying ChromaDB collection
            # Mem0 stores collection in memory.vector_store.client
            collection = self.memory.vector_store.client.get_collection(
                name=self._config["vector_store"]["config"]["collection_name"]
            )
            count = collection.count()
            return count
        except Exception as e:
            logger.error(f"Failed to get memory count: {e}")
            # Fallback: return 0 if count fails
            return 0


def get_mem0_client(config: Optional[dict] = None) -> Mem0Client:
    """Factory function to get or create Mem0Client singleton.

    Args:
        config: Optional Mem0 config dict. If None, uses create_mem0_config().

    Returns:
        Mem0Client instance

    Example:
        >>> client = get_mem0_client()
        >>> results = client.search("EMA")
    """
    global _mem0_client

    if _mem0_client is None:
        _mem0_client = Mem0Client(config=config)
        logger.info("Created Mem0Client singleton")

    return _mem0_client


def reset_mem0_client() -> None:
    """Reset singleton for testing. Do not use in production.

    Example:
        >>> reset_mem0_client()
        >>> client = get_mem0_client()  # Fresh instance
    """
    global _mem0_client
    _mem0_client = None
    logger.info("Reset Mem0Client singleton")


__all__ = ["Mem0Client", "get_mem0_client", "reset_mem0_client"]
