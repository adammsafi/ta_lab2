"""Combined ASGI application mounting MCP and REST on the same port.

Serves both:
    /mcp/     - MCP Streamable HTTP endpoint (for Claude Code, Codex, Gemini)
    /api/v1/  - REST API endpoints (for scripts and direct HTTP access)
    /health   - Health check endpoint

Run:
    uvicorn ta_lab2.tools.ai_orchestrator.memory.server:app --host 0.0.0.0 --port 8080
"""

import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create combined ASGI app with MCP + REST.

    Mounts the FastMCP server at /mcp/ and keeps the existing REST API
    at /api/v1/. Both share the same process and Mem0Client singleton.

    The MCP lifespan context is passed to FastAPI at construction time
    to ensure proper session management for MCP connections.

    Returns:
        FastAPI application with MCP mounted at /mcp/
    """
    from .api import create_memory_api
    from .mcp_server import mcp

    # Create MCP ASGI app (mounted at root of its sub-path)
    mcp_app = mcp.http_app(path="/")

    # Create FastAPI app WITH MCP lifespan (CRITICAL for session management)
    api = create_memory_api(lifespan=mcp_app.lifespan)

    # Mount MCP endpoint at /mcp/
    api.mount("/mcp", mcp_app)

    # Replace health endpoint with Qdrant-aware check (api.py uses ChromaDB
    # which is not available in Docker — only Qdrant via Mem0)
    api.routes[:] = [r for r in api.routes if getattr(r, "path", None) != "/health"]

    @api.get("/health")
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

    logger.info("Combined ASGI app created: MCP at /mcp/, REST at /api/v1/")

    return api


app = create_app()

__all__ = ["create_app", "app"]
