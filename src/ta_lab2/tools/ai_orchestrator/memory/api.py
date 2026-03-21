"""FastAPI REST API for MCP memory server health check.

The /api/v1/memory/* REST routes have been removed (they called ChromaDB
which is not available in Docker -- only Qdrant via Mem0 is available).
MCP tools (/mcp/) are the correct interface for all memory operations.

Run server:
    uvicorn ta_lab2.tools.ai_orchestrator.memory.server:app --host 0.0.0.0 --port 8080
"""

import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def create_memory_api(lifespan=None) -> FastAPI:
    """Create FastAPI application for memory server.

    Args:
        lifespan: Optional ASGI lifespan context manager. When mounting with
            FastMCP, pass mcp_app.lifespan to share session management.

    Returns:
        FastAPI application instance with /health endpoint only.
    """
    app = FastAPI(
        title="ta_lab2 Memory Server",
        description="MCP memory server backed by Mem0 + Qdrant",
        version="2.0.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health_check():
        """Health check using Qdrant backend (Docker-compatible)."""
        try:
            from .mem0_client import get_mem0_client

            client = get_mem0_client()
            count = client.memory_count
            return {"status": "healthy", "memories": count}
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"status": "unhealthy", "error": str(e)}

    return app


# Create app instance for uvicorn (standalone, without MCP mount)
app = create_memory_api()
