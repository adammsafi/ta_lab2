# Phase 64: MCP Memory Server - Research

**Researched:** 2026-03-02
**Domain:** MCP server development, Docker containerization, memory system integration
**Confidence:** HIGH

## Summary

This phase builds an MCP server that wraps the existing Mem0/Qdrant memory store (3,763+ memories) and exposes it to Claude Code, Codex, Gemini, and scripts. The research establishes the standard stack (FastMCP 3.x for MCP protocol, FastAPI for REST), architecture for mounting both in a single process, Docker Compose configuration for Qdrant + the server, and Claude Code registration via `.mcp.json`.

The key insight is that **FastMCP 3.x can be mounted directly into the existing FastAPI app as an ASGI sub-application**, meaning a single `uvicorn` process serves both the MCP endpoint (at `/mcp/`) and the REST API (at `/api/v1/`). This avoids running two processes or two ports. The server connects to Qdrant in a sibling Docker container via Docker networking.

**Primary recommendation:** Use FastMCP 3.x (`pip install fastmcp`) with `mcp.http_app()` mounted into FastAPI, serve with uvicorn in Docker, register in Claude Code via `.mcp.json` with `"type": "http"` transport pointing to `http://localhost:8080/mcp/`.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| fastmcp | 3.0.2 | MCP server framework | 70% of MCP servers use FastMCP; decorator-based tool registration, automatic schema generation |
| fastapi | >=0.104.0 | REST API framework | Already in project (`api.py`), Pydantic models already defined |
| uvicorn | >=0.24.0 | ASGI server | Standard for FastAPI/Starlette apps, handles both HTTP and streaming |
| mem0ai | >=1.0.2 | Memory intelligence layer | Already in project, wraps Qdrant with LLM-powered conflict detection |
| qdrant/qdrant | latest | Vector database | Already in use, Docker image with REST+gRPC on 6333/6334 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | >=2.0.0 | Request/response models | Already in project, FastMCP auto-generates schemas from type annotations |
| python-dotenv | >=1.0.0 | Environment loading | Already in project, loads `.env` for OPENAI_API_KEY etc. |
| docker compose | v2 | Multi-container orchestration | Qdrant + MCP server in one `docker compose up` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| fastmcp (standalone) | mcp SDK (`from mcp.server.fastmcp`) | SDK includes older FastMCP 1.x; standalone is 3.x with latest features, 5x faster development |
| Streamable HTTP transport | SSE transport | SSE is deprecated in MCP spec (2025-03-26). Both work in Claude Code, but HTTP is the recommended path |
| Single process (FastAPI+MCP) | Two separate processes | Single process shares the Mem0Client singleton; two processes would need separate connections |

**Installation:**
```bash
pip install "fastmcp>=3.0.0" "fastapi>=0.104.0" "uvicorn[standard]>=0.24.0"
```

Note: `mem0ai`, `pydantic`, `python-dotenv` are already in the project's `[project.optional-dependencies] orchestrator` group.

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/tools/ai_orchestrator/memory/
    api.py              # Existing FastAPI REST API (enhanced, not rewritten)
    mcp_server.py       # NEW: FastMCP tool definitions
    server.py           # NEW: Combined ASGI app (mounts MCP + REST)
    mem0_client.py      # Existing Mem0Client (shared singleton)
    injection.py        # Existing RAG pipeline (wrapped by MCP tool)
    health.py           # Existing health monitoring (wrapped by MCP tool)
    conflict.py         # Existing conflict detection (used by write tool)
    ...

docker/
    docker-compose.yml  # NEW: Qdrant + MCP/REST server
    Dockerfile          # NEW: Python server image
    .env.example        # NEW: Template for required env vars
```

### Pattern 1: FastMCP + FastAPI Mount (Single Process)
**What:** Mount the FastMCP ASGI app into FastAPI as a sub-application, so both MCP and REST share the same port and process.
**When to use:** Always, for this phase. This is the recommended FastMCP pattern.
**Example:**
```python
# Source: https://gofastmcp.com/deployment/http
from fastapi import FastAPI
from fastmcp import FastMCP

# Create MCP server with tools
mcp = FastMCP("ta-lab2-memory")

@mcp.tool
def memory_search(query: str, top_k: int = 10, min_similarity: float = 0.6) -> dict:
    """Search project memories by semantic similarity."""
    from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
    client = get_mem0_client()
    results = client.search(query=query, limit=top_k)
    return {"results": results, "count": len(results)}

# Create the MCP ASGI app
mcp_app = mcp.http_app(path="/")

# Create FastAPI app with MCP lifespan (CRITICAL)
from ta_lab2.tools.ai_orchestrator.memory.api import create_memory_api
api = create_memory_api()

# Mount MCP under /mcp path
api.router.lifespan_context = mcp_app.lifespan  # Share lifespan
api.mount("/mcp", mcp_app)

# Result:
#   http://localhost:8080/mcp/     -> MCP Streamable HTTP endpoint
#   http://localhost:8080/api/v1/  -> REST API (existing)
#   http://localhost:8080/health   -> Health check (existing)
```

### Pattern 2: FastMCP Tool Definition with Type Annotations
**What:** FastMCP automatically generates MCP tool schemas from Python type annotations and docstrings.
**When to use:** For all tool definitions in this phase.
**Example:**
```python
# Source: https://gofastmcp.com/servers/tools
from typing import Annotated, Optional
from pydantic import Field
from fastmcp import FastMCP

mcp = FastMCP("ta-lab2-memory")

@mcp.tool
def memory_search(
    query: Annotated[str, "Natural language search query"],
    top_k: Annotated[int, Field(description="Maximum results to return", ge=1, le=50)] = 10,
    min_similarity: Annotated[float, Field(description="Minimum similarity threshold 0.0-1.0", ge=0.0, le=1.0)] = 0.6,
    category: Annotated[Optional[str], "Filter by memory category"] = None,
) -> dict:
    """Search project memories using semantic similarity.

    Returns matching memories with content, metadata, and similarity scores.
    Use this to find relevant project context before starting unfamiliar tasks.
    """
    ...
```

### Pattern 3: Docker Compose with Named Volumes (Windows)
**What:** Use Docker named volumes instead of bind mounts for Qdrant on Windows to avoid POSIX compatibility issues.
**When to use:** Always on Windows with Docker/WSL.
**Example:**
```yaml
# docker-compose.yml
services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant-storage:/qdrant/storage
    restart: unless-stopped

  memory-server:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8080:8080"
    environment:
      - QDRANT_HOST=qdrant
      - QDRANT_PORT=6333
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on:
      - qdrant
    restart: unless-stopped

volumes:
  qdrant-storage:
```

### Pattern 4: Claude Code Registration via .mcp.json
**What:** Register the MCP server in Claude Code's project-scoped `.mcp.json` file.
**When to use:** For project-level sharing; checked into version control.
**Example:**
```json
{
  "mcpServers": {
    "ta-lab2-memory": {
      "type": "http",
      "url": "http://localhost:8080/mcp/"
    }
  }
}
```

Alternative via CLI:
```bash
claude mcp add --transport http ta-lab2-memory http://localhost:8080/mcp/
```

### Anti-Patterns to Avoid
- **Running MCP and REST on separate ports:** Wastes resources, complicates Docker config, prevents shared singleton. Mount into same ASGI app instead.
- **Using SSE transport for new servers:** SSE is deprecated in MCP spec (2025-03-26). Use Streamable HTTP (`type: "http"`).
- **Bind-mounting Qdrant storage on Windows:** File system incompatibility causes data loss. Use Docker named volumes.
- **Rewriting existing code:** The MCP tools should be thin wrappers around existing `mem0_client.py`, `injection.py`, `health.py`. Never duplicate logic.
- **Blocking async tools with sync Mem0 calls:** FastMCP runs sync tools in a threadpool automatically, so sync functions are fine and will not block the event loop.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| MCP protocol compliance | Custom SSE/HTTP handler | FastMCP 3.x | Protocol is complex (session mgmt, capability negotiation, tool schemas). FastMCP handles all of it. |
| Tool schema generation | Manual JSON Schema definitions | FastMCP type annotations | FastMCP auto-generates schemas from Python type hints + docstrings |
| Conflict detection | Custom dedup logic | Mem0 `infer=True` | Mem0 uses GPT-4o-mini for semantic conflict detection; handles ADD/UPDATE/DELETE/NOOP |
| RAG context formatting | Custom memory formatting | Existing `injection.py` | Already formats memories with metadata, similarity scores, truncation |
| Memory health scanning | Custom staleness checker | Existing `health.py` | Already handles age distribution, staleness thresholds, deprecated memory detection |
| Docker networking | Manual network config | Docker Compose `depends_on` + service names | Compose auto-creates a network; services reference each other by name |

**Key insight:** This entire phase is a thin MCP wrapper around existing infrastructure. The value is in the integration glue, not new logic.

## Common Pitfalls

### Pitfall 1: Missing Lifespan Context When Mounting
**What goes wrong:** MCP tools fail with session manager errors (500s, connection drops).
**Why it happens:** FastMCP requires its lifespan context to initialize session management. When mounting into FastAPI, the MCP lifespan must be passed to the parent app.
**How to avoid:** Always pass `mcp_app.lifespan` to FastAPI when mounting:
```python
mcp_app = mcp.http_app(path="/")
api = FastAPI(lifespan=mcp_app.lifespan)
api.mount("/mcp", mcp_app)
```
**Warning signs:** "Session not found" errors, 500 responses on MCP endpoint.

### Pitfall 2: Qdrant Data Migration from Local to Docker
**What goes wrong:** Existing 3,763 memories stored in local Qdrant become inaccessible when switching to Docker Qdrant.
**Why it happens:** The existing Mem0 config uses `QDRANT_SERVER_MODE=true` with `localhost:6333`. If Qdrant was previously running as a standalone Docker container (not via Compose), its data volume may not be the same as the Compose-managed volume.
**How to avoid:** Before switching to Docker Compose: (1) verify where existing Qdrant data lives, (2) either mount the same storage path or create a Qdrant snapshot and restore it in the new container.
**Warning signs:** `memory_count` returns 0 after Docker Compose startup.

### Pitfall 3: OPENAI_API_KEY Not Available in Docker
**What goes wrong:** Mem0 fails to initialize because it cannot find the OpenAI API key for embeddings and LLM operations.
**Why it happens:** The API key is in the host's environment or `.env` file but not passed to the Docker container.
**How to avoid:** Pass via `docker-compose.yml` environment section with `${OPENAI_API_KEY}` expansion, and document the `.env` file requirement.
**Warning signs:** "OPENAI_API_KEY not found" errors on startup.

### Pitfall 4: FastMCP Sub-Path Routing Issues
**What goes wrong:** MCP endpoint returns 404 or client can't establish connection.
**Why it happens:** When FastMCP is mounted at a sub-path (e.g., `/mcp`), the internal SSE/HTTP endpoint URLs may not include the mount prefix correctly.
**How to avoid:** Use `mcp.http_app(path="/")` when mounting, so FastMCP generates root-relative paths and the mount point handles the prefix. If issues persist, the `fastmcp-mount` ASGI middleware package can fix path rewriting.
**Warning signs:** MCP client connects but receives 404 on tool calls; SSE stream never starts.

### Pitfall 5: Windows Docker + WSL Volume Mount Data Loss
**What goes wrong:** Qdrant data silently corrupts or disappears.
**Why it happens:** Mounting a Windows host folder into a WSL-based Docker container creates a shared mount that is not fully POSIX-compatible.
**How to avoid:** Use Docker named volumes (not bind mounts) for Qdrant storage on Windows. Named volumes are stored inside the Linux VM, avoiding the incompatibility.
**Warning signs:** Data present after write but missing after container restart.

### Pitfall 6: Two Client Singletons (ChromaDB vs Mem0)
**What goes wrong:** MCP tools call the wrong client and get different results from the REST API.
**Why it happens:** The codebase has two memory clients: `client.py` (ChromaDB, used by `query.py`) and `mem0_client.py` (Mem0/Qdrant). The existing `api.py` REST endpoints use the ChromaDB path for search/stats but Mem0 for health/conflict.
**How to avoid:** MCP tools should consistently use `Mem0Client` (`mem0_client.py`) for all operations. This is the canonical path with 3,763+ memories in Qdrant. The ChromaDB client is the older backend.
**Warning signs:** Different memory counts between MCP and REST endpoints; search returning different results.

## Code Examples

Verified patterns from official sources:

### Complete MCP Server with Tools
```python
# Source: https://gofastmcp.com/servers/tools + https://gofastmcp.com/deployment/http
from typing import Annotated, Optional
from pydantic import Field
from fastmcp import FastMCP

mcp = FastMCP(
    name="ta-lab2-memory",
    instructions=(
        "Memory server for the ta_lab2 trading system project. "
        "Search memories for project context, patterns, gotchas, and decisions. "
        "Use memory_search before starting unfamiliar tasks."
    ),
)


@mcp.tool
def memory_search(
    query: Annotated[str, "Natural language search query"],
    top_k: Annotated[int, Field(description="Max results", ge=1, le=50)] = 10,
    min_similarity: Annotated[float, Field(description="Min similarity 0.0-1.0", ge=0.0, le=1.0)] = 0.6,
    category: Annotated[Optional[str], "Filter by memory category/type"] = None,
) -> dict:
    """Search project memories by semantic similarity.

    Returns raw results with text, metadata, and similarity scores.
    Use for targeted lookups when you need specific project facts.
    """
    from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
    client = get_mem0_client()

    filters = {"category": category} if category else None
    results = client.search(query=query, limit=top_k, filters=filters)

    # Results from Mem0 search: list of dicts with id, memory, metadata, score
    formatted = []
    for r in (results if isinstance(results, list) else results.get("results", [])):
        score = r.get("score", 0.0)
        if score >= min_similarity:
            formatted.append({
                "id": r.get("id"),
                "content": r.get("memory"),
                "metadata": r.get("metadata", {}),
                "similarity": round(score, 4),
            })

    return {"query": query, "results": formatted, "count": len(formatted)}


@mcp.tool
def memory_context(
    query: Annotated[str, "Query for context retrieval"],
    max_memories: Annotated[int, Field(description="Max memories to include", ge=1, le=20)] = 10,
    min_similarity: Annotated[float, Field(ge=0.0, le=1.0)] = 0.6,
) -> dict:
    """Get formatted RAG context for prompt injection.

    Returns memories formatted as markdown, ready to use as context.
    Use this when you need a formatted context block for decision-making.
    """
    from ta_lab2.tools.ai_orchestrator.memory.injection import inject_memory_context

    context = inject_memory_context(
        query=query,
        max_memories=max_memories,
        min_similarity=min_similarity,
    )

    return {"query": query, "context": context}


@mcp.tool
def memory_store(
    content: Annotated[str, "Memory content to store"],
    source: Annotated[str, "AI consumer identifier (e.g., 'claude_code', 'codex')"] = "claude_code",
    category: Annotated[Optional[str], "Memory category"] = None,
    user_id: Annotated[str, "User ID for memory isolation"] = "orchestrator",
) -> dict:
    """Store a new memory with conflict detection.

    Uses Mem0's LLM-powered conflict resolution (GPT-4o-mini) to prevent
    duplicates and resolve contradictions. Returns the operation performed
    (ADD/UPDATE/DELETE/NOOP).
    """
    from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
    client = get_mem0_client()

    metadata = {"source": source}
    if category:
        metadata["category"] = category

    messages = [{"role": "user", "content": content}]
    result = client.add(messages=messages, user_id=user_id, metadata=metadata, infer=True)

    return result


@mcp.tool
def memory_stats() -> dict:
    """Get memory store statistics (total count, collection info)."""
    from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
    client = get_mem0_client()

    return {
        "total_memories": client.memory_count,
        "collection_name": "project_memories",
        "backend": "qdrant",
    }


@mcp.tool
def memory_health(
    staleness_days: Annotated[int, Field(description="Days threshold for staleness", ge=1)] = 90,
) -> dict:
    """Generate memory health report showing stale and deprecated memories."""
    from ta_lab2.tools.ai_orchestrator.memory.health import MemoryHealthMonitor

    monitor = MemoryHealthMonitor(staleness_days=staleness_days)
    report = monitor.generate_health_report()

    return {
        "total_memories": report.total_memories,
        "healthy": report.healthy,
        "stale": report.stale,
        "deprecated": report.deprecated,
        "missing_metadata": report.missing_metadata,
        "age_distribution": report.age_distribution,
    }


@mcp.tool
def list_categories() -> dict:
    """List available memory categories/types for filtering."""
    from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
    client = get_mem0_client()

    # Sample memories to discover categories
    all_memories = client.get_all(user_id="orchestrator")
    categories = set()
    for mem in all_memories:
        cat = mem.get("metadata", {}).get("category")
        if cat:
            categories.add(cat)

    return {"categories": sorted(categories), "count": len(categories)}
```

### Combined ASGI Application (server.py)
```python
# Source: https://gofastmcp.com/deployment/http
from fastapi import FastAPI
from .mcp_server import mcp
from .api import create_memory_api

def create_app() -> FastAPI:
    """Create combined ASGI app with MCP + REST."""
    # Create MCP ASGI app
    mcp_app = mcp.http_app(path="/")

    # Create FastAPI app with MCP lifespan (REQUIRED)
    api = create_memory_api()

    # Override lifespan to include MCP session management
    api.router.lifespan_context = mcp_app.lifespan

    # Mount MCP at /mcp/
    api.mount("/mcp", mcp_app)

    return api

app = create_app()

# Run: uvicorn ta_lab2.tools.ai_orchestrator.memory.server:app --host 0.0.0.0 --port 8080
```

### Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc && \
    rm -rf /var/lib/apt/lists/*

# Copy project and install
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir ".[orchestrator]" "fastmcp>=3.0.0" "uvicorn[standard]"

# Expose port
EXPOSE 8080

# Run combined server
CMD ["uvicorn", "ta_lab2.tools.ai_orchestrator.memory.server:app", \
     "--host", "0.0.0.0", "--port", "8080"]
```

### Docker Compose
```yaml
version: "3.8"

services:
  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant-storage:/qdrant/storage
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:6333/healthz"]
      interval: 10s
      timeout: 5s
      retries: 3

  memory-server:
    build:
      context: ../../../..
      dockerfile: docker/Dockerfile
    ports:
      - "8080:8080"
    environment:
      - QDRANT_HOST=qdrant
      - QDRANT_PORT=6333
      - QDRANT_SERVER_MODE=true
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on:
      qdrant:
        condition: service_healthy
    restart: unless-stopped

volumes:
  qdrant-storage:
```

### Claude Code .mcp.json
```json
{
  "mcpServers": {
    "ta-lab2-memory": {
      "type": "http",
      "url": "http://localhost:8080/mcp/"
    }
  }
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| SSE transport for remote MCP | Streamable HTTP (`type: "http"`) | MCP spec 2025-03-26 | SSE deprecated; HTTP is simpler (single endpoint), more reliable |
| `mcp` SDK FastMCP (v1.x bundled) | Standalone `fastmcp` package (v3.x) | FastMCP 2.0 mid-2025, 3.0 Jan 2026 | Standalone has more features, faster iteration, 3.x adds auth/versioning |
| Custom MCP protocol handling | FastMCP decorator-based tools | 2024-2025 | 5x reduction in boilerplate; auto schema generation |
| Claude Code SSE config | Claude Code HTTP config (`"type": "http"`) | 2025 | HTTP is the recommended transport; SSE still works but deprecated |

**Deprecated/outdated:**
- SSE transport: Deprecated in MCP spec 2025-03-26. Use Streamable HTTP. Claude Code still supports SSE but recommends HTTP.
- `mcp.server.fastmcp.FastMCP` (SDK-bundled): Older version. Use standalone `fastmcp` package (v3.x) for latest features.

## Open Questions

Things that couldn't be fully resolved:

1. **Existing Qdrant Data Location**
   - What we know: Qdrant runs on `localhost:6333` with `QDRANT_SERVER_MODE=true`. Config references `chromadb_path` for base storage but Qdrant uses its own storage directory.
   - What's unclear: How is Qdrant currently started? Standalone Docker container? Windows service? Where exactly is the 3,763-memory collection stored?
   - Recommendation: Before building Docker Compose, manually inspect `docker ps` (when Docker Desktop is running) to find the existing Qdrant container and its volume mount. The migration plan depends on this.

2. **FastAPI Lifespan Integration Detail**
   - What we know: FastMCP docs say "you must pass the lifespan context from the FastMCP app to the resulting Starlette app."
   - What's unclear: Whether `api.router.lifespan_context = mcp_app.lifespan` works with FastAPI's `create_memory_api()` pattern, or whether the lifespan needs to be set at `FastAPI()` construction time.
   - Recommendation: Test this early in implementation. If setting lifespan post-construction fails, refactor `create_memory_api()` to accept a lifespan parameter.

3. **ChromaDB vs Mem0 Client Path in api.py**
   - What we know: The existing `api.py` uses `client.py` (ChromaDB) for search/stats and `mem0_client.py` for health/conflict. The MCP server should use Mem0Client exclusively.
   - What's unclear: Whether the ChromaDB path in `api.py` should be migrated to Mem0Client in this phase, or left as-is.
   - Recommendation: MCP tools use Mem0Client only. Leave `api.py` REST endpoints as-is for backward compatibility unless they need to be in the same Docker container (then they need Mem0 too, since ChromaDB path won't exist in Docker).

4. **FastMCP Version Compatibility with `mcp` SDK**
   - What we know: `fastmcp` 3.0.2 is standalone, `mcp` SDK 1.26.0 bundles older FastMCP. Both can coexist.
   - What's unclear: Whether installing both `fastmcp` and `mcp` causes import conflicts.
   - Recommendation: Install only `fastmcp>=3.0.0` (it pulls in `mcp` SDK as a dependency). Do not install `mcp` separately.

## Sources

### Primary (HIGH confidence)
- [FastMCP documentation](https://gofastmcp.com/) - Server creation, tool definition, HTTP deployment, FastAPI mounting
- [FastMCP 3.0.2 on PyPI](https://pypi.org/project/fastmcp/) - Version, Python >=3.10, Apache-2.0 license
- [MCP Python SDK on GitHub](https://github.com/modelcontextprotocol/python-sdk) - Official SDK, v1.26.0
- [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp) - .mcp.json format, transport types, registration commands
- [Qdrant quickstart](https://qdrant.tech/documentation/quickstart/) - Docker image, ports 6333/6334, volume persistence

### Secondary (MEDIUM confidence)
- [MCP Streamable HTTP specification](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports) - SSE deprecation, Streamable HTTP as replacement
- [MCP SSE deprecation analysis](https://blog.fka.dev/blog/2025-06-06-why-mcp-deprecated-sse-and-go-with-streamable-http/) - Rationale for transport change
- [FastMCP FastAPI mounting pattern](https://codesignal.com/learn/courses/advanced-mcp-server-and-agent-integration-in-python/lessons/mounting-an-mcp-server-in-a-fastapi-asgi-application) - ASGI integration details, lifespan requirement
- [Qdrant Docker Hub](https://hub.docker.com/r/qdrant/qdrant) - Image tags, volume mount guidance

### Tertiary (LOW confidence)
- Windows Docker volume issues with Qdrant - Community reports of POSIX incompatibility with bind mounts; named volumes recommended. Not verified against official Qdrant docs but consistent across multiple sources.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - FastMCP 3.x is verified on PyPI (3.0.2), Claude Code HTTP transport documented officially
- Architecture: HIGH - FastMCP mounting into FastAPI is documented in official FastMCP docs with code examples
- Docker setup: MEDIUM - Docker Compose pattern is standard, but Windows volume behavior is from community sources
- Pitfalls: HIGH - Lifespan requirement is documented in FastMCP docs; data migration concern is based on project-specific analysis

**Research date:** 2026-03-02
**Valid until:** 2026-04-01 (FastMCP 3.x is stable; MCP spec unlikely to change in 30 days)
