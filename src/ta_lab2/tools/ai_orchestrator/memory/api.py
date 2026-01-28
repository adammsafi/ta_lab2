"""FastAPI REST API for cross-platform memory access.

Exposes memory search to Claude/ChatGPT/Gemini via HTTP.
Implements MEMO-04: Cross-platform memory sharing.

FastAPI is REQUIRED for Phase 2 - not optional.

Run server:
    uvicorn ta_lab2.tools.ai_orchestrator.memory.api:app --port 8080
"""
import logging
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Request/Response Models
class MemorySearchRequest(BaseModel):
    """Request body for memory search."""
    query: str = Field(..., description="Search query text")
    max_results: int = Field(5, ge=1, le=20, description="Maximum results")
    min_similarity: float = Field(0.7, ge=0.0, le=1.0, description="Minimum similarity")
    memory_type: Optional[str] = Field(None, description="Filter by memory type")


class MemoryResult(BaseModel):
    """Individual memory result."""
    memory_id: str
    content: str
    metadata: dict
    similarity: float


class MemorySearchResponse(BaseModel):
    """Response from memory search."""
    query: str
    memories: List[MemoryResult]
    count: int
    threshold_used: float


class MemoryStatsResponse(BaseModel):
    """Response from stats endpoint."""
    total_memories: int
    collection_name: str
    distance_metric: str
    is_valid: bool


class ContextInjectionRequest(BaseModel):
    """Request for formatted context injection."""
    query: str = Field(..., description="Query for context retrieval")
    max_memories: int = Field(5, ge=1, le=10, description="Maximum memories")
    min_similarity: float = Field(0.7, ge=0.0, le=1.0, description="Minimum similarity")
    max_length: int = Field(4000, ge=100, le=10000, description="Maximum context length")


class ContextInjectionResponse(BaseModel):
    """Response with formatted context."""
    query: str
    context: str
    memory_count: int
    estimated_tokens: int


def create_memory_api() -> FastAPI:
    """Create FastAPI application for memory API.

    Returns:
        FastAPI application instance
    """
    app = FastAPI(
        title="ta_lab2 Memory API",
        description="Semantic memory search for cross-platform AI access",
        version="1.0.0"
    )

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        from .validation import quick_health_check
        is_healthy = quick_health_check()
        return {"status": "healthy" if is_healthy else "unhealthy"}

    @app.get("/api/v1/memory/stats", response_model=MemoryStatsResponse)
    async def get_stats():
        """Get memory store statistics."""
        try:
            from .client import get_memory_client
            from .validation import validate_memory_store

            client = get_memory_client()
            validation = validate_memory_store(client)

            return MemoryStatsResponse(
                total_memories=validation.total_count,
                collection_name=client._collection_name,
                distance_metric=validation.distance_metric,
                is_valid=validation.is_valid
            )
        except Exception as e:
            logger.error(f"Stats failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/v1/memory/search", response_model=MemorySearchResponse)
    async def search_memories_endpoint(request: MemorySearchRequest):
        """Semantic search endpoint for cross-platform memory access.

        Used by Claude, ChatGPT, Gemini to retrieve relevant project memories.
        """
        try:
            from .query import search_memories

            response = search_memories(
                query=request.query,
                max_results=request.max_results,
                min_similarity=request.min_similarity,
                memory_type=request.memory_type
            )

            return MemorySearchResponse(
                query=request.query,
                memories=[
                    MemoryResult(
                        memory_id=r.memory_id,
                        content=r.content,
                        metadata=r.metadata,
                        similarity=r.similarity
                    )
                    for r in response.results
                ],
                count=response.filtered_count,
                threshold_used=response.threshold_used
            )
        except Exception as e:
            logger.error(f"Search failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/v1/memory/context", response_model=ContextInjectionResponse)
    async def get_context(request: ContextInjectionRequest):
        """Get formatted context for AI prompt injection.

        Returns memories formatted and ready to inject into prompts.
        """
        try:
            from .injection import inject_memory_context, estimate_context_tokens
            from .query import search_memories

            # Get search results for count
            search_response = search_memories(
                query=request.query,
                max_results=request.max_memories,
                min_similarity=request.min_similarity
            )

            # Get formatted context
            context = inject_memory_context(
                query=request.query,
                max_memories=request.max_memories,
                min_similarity=request.min_similarity,
                max_length=request.max_length
            )

            return ContextInjectionResponse(
                query=request.query,
                context=context,
                memory_count=search_response.filtered_count,
                estimated_tokens=estimate_context_tokens(context)
            )
        except Exception as e:
            logger.error(f"Context injection failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/v1/memory/types")
    async def get_memory_types():
        """Get list of available memory types."""
        try:
            from .query import get_memory_types
            types = get_memory_types()
            return {"types": types, "count": len(types)}
        except Exception as e:
            logger.error(f"Get types failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return app


# Create app instance for uvicorn
app = create_memory_api()
