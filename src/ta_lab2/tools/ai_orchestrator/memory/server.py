"""Combined ASGI application mounting MCP on the same port as health check.

Serves:
    /mcp/     - MCP Streamable HTTP endpoint (for Claude Code, Codex, Gemini)
    /health   - Health check endpoint (Qdrant-backed)

The /api/v1/memory/* REST routes have been removed -- they called ChromaDB
which is not available in Docker. Use MCP tools (/mcp/) for all memory ops.

Run:
    uvicorn ta_lab2.tools.ai_orchestrator.memory.server:app --host 0.0.0.0 --port 8080
"""

import logging

from fastapi import FastAPI

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create combined ASGI app with MCP mounted at /mcp/.

    The FastAPI base app provides /health (Qdrant-backed).
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
    # api.py health endpoint already uses Qdrant via mem0_client
    api = create_memory_api(lifespan=mcp_app.lifespan)

    # Mount MCP endpoint at /mcp/
    api.mount("/mcp", mcp_app)

    logger.info("Combined ASGI app created: MCP at /mcp/, health at /health")

    return api


app = create_app()

__all__ = ["create_app", "app"]
