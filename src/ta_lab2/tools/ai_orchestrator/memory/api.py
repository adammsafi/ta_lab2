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


class HealthReportResponse(BaseModel):
    """Response from health monitoring endpoint."""
    total_memories: int
    healthy: int
    stale: int
    deprecated: int
    missing_metadata: int
    age_distribution: dict[str, int]
    scan_timestamp: str


class StaleMemoryResponse(BaseModel):
    """Individual stale memory for review."""
    id: str
    content_preview: str
    last_verified: Optional[str]
    age_days: Optional[int]


class RefreshRequest(BaseModel):
    """Request to refresh verification timestamps."""
    memory_ids: List[str] = Field(..., min_length=1, max_length=100)


class ConflictCheckRequest(BaseModel):
    """Request to check for conflicts."""
    content: str = Field(..., min_length=1, max_length=10000)
    user_id: str = Field(default="orchestrator")
    similarity_threshold: float = Field(default=0.85, ge=0.5, le=1.0)


class PotentialConflict(BaseModel):
    """Individual potential conflict."""
    memory_id: str
    content: str
    similarity: float
    metadata: Optional[dict] = None


class ConflictCheckResponse(BaseModel):
    """Response from conflict check endpoint."""
    has_conflicts: bool
    conflicts: List[PotentialConflict]


class AddWithConflictRequest(BaseModel):
    """Request to add memory with conflict resolution."""
    content: str = Field(..., min_length=1, max_length=10000)
    user_id: str = Field(default="orchestrator")
    metadata: Optional[dict] = None
    role: str = Field(default="user")


class ConflictResolutionResponse(BaseModel):
    """Response from add with conflict resolution."""
    memory_id: str
    operation: str
    confidence: float
    reason: str


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

    @app.get("/api/v1/memory/health", response_model=HealthReportResponse)
    async def get_memory_health(staleness_days: int = 90):
        """Generate memory health report showing stale and deprecated memories."""
        try:
            from .health import MemoryHealthMonitor
            monitor = MemoryHealthMonitor(staleness_days=staleness_days)
            report = monitor.generate_health_report()
            return HealthReportResponse(
                total_memories=report.total_memories,
                healthy=report.healthy,
                stale=report.stale,
                deprecated=report.deprecated,
                missing_metadata=report.missing_metadata,
                age_distribution=report.age_distribution,
                scan_timestamp=report.scan_timestamp
            )
        except Exception as e:
            logger.error(f"Health report failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/v1/memory/health/stale", response_model=List[StaleMemoryResponse])
    async def get_stale_memories(staleness_days: int = 90, limit: int = 50):
        """Get list of stale memories for review."""
        try:
            from .health import scan_stale_memories
            stale = scan_stale_memories(staleness_days=staleness_days)[:limit]
            return [
                StaleMemoryResponse(
                    id=m["id"],
                    content_preview=m["content"][:100],
                    last_verified=m.get("last_verified"),
                    age_days=m["age_days"]
                )
                for m in stale
            ]
        except Exception as e:
            logger.error(f"Get stale memories failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/v1/memory/health/refresh")
    async def refresh_verification(request: RefreshRequest):
        """Mark memories as verified (refreshes last_verified timestamp)."""
        try:
            from .health import MemoryHealthMonitor
            monitor = MemoryHealthMonitor()
            count = monitor.refresh_verification(request.memory_ids)
            return {"refreshed": count, "memory_ids": request.memory_ids}
        except Exception as e:
            logger.error(f"Refresh verification failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/v1/memory/conflict/check", response_model=ConflictCheckResponse)
    async def check_conflicts(request: ConflictCheckRequest):
        """Check if content conflicts with existing memories."""
        try:
            from .conflict import detect_conflicts
            conflicts = detect_conflicts(
                content=request.content,
                user_id=request.user_id,
                similarity_threshold=request.similarity_threshold
            )
            return ConflictCheckResponse(
                has_conflicts=len(conflicts) > 0,
                conflicts=[
                    PotentialConflict(
                        memory_id=c["memory_id"],
                        content=c["content"],
                        similarity=c["similarity"],
                        metadata=c.get("metadata")
                    )
                    for c in conflicts
                ]
            )
        except Exception as e:
            logger.error(f"Conflict check failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @app.post("/api/v1/memory/conflict/add", response_model=ConflictResolutionResponse)
    async def add_with_conflict_resolution(request: AddWithConflictRequest):
        """Add memory with automatic conflict detection and resolution."""
        try:
            from .conflict import add_with_conflict_check

            # Format as message for Mem0
            messages = [
                {"role": request.role, "content": request.content}
            ]

            result = add_with_conflict_check(
                messages=messages,
                user_id=request.user_id,
                metadata=request.metadata
            )

            return ConflictResolutionResponse(
                memory_id=result["memory_id"],
                operation=result["operation"],
                confidence=result["confidence"],
                reason=result["reason"]
            )
        except Exception as e:
            logger.error(f"Add with conflict resolution failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return app


# Create app instance for uvicorn
app = create_memory_api()
