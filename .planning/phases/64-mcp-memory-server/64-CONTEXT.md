# Phase 64: MCP Memory Server — Connect Qdrant to Claude Code - Context

**Gathered:** 2026-03-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Build an MCP server that wraps the existing Mem0/Qdrant memory store (3,763+ memories) and registers it as a Docker service alongside Qdrant. Exposes both MCP (SSE transport) and REST interfaces so Claude Code, OpenAI Codex, Google Gemini, and plain scripts can all access project memories via semantic search. This is the proof-of-concept that validates the Phase 1-5 orchestrator infrastructure.

</domain>

<decisions>
## Implementation Decisions

### Tool interface design
- **Granularity:** Claude's discretion — pick the right number of tools based on what the existing Mem0Client/injection.py code supports
- **Two search modes:** One tool for raw search results (text + metadata + similarity score), another for formatted RAG context injection (using existing injection.py pipeline)
- **Health tools:** Expose memory_stats and health_check so AI can flag stale or conflicting memories
- **Category discovery:** Include a list_categories tool so AI can discover what memory types exist and filter intelligently

### Retrieval behavior
- **Default top-k:** 10 (broader) — caller can override to narrow
- **Similarity threshold:** 0.6 (medium) — balance precision and recall
- **Deprecated memories:** Claude's discretion on handling (include-but-flag vs exclude)
- **Similarity scores:** Always included in results so AI can weigh confidence

### Session integration
- **Runtime model:** Docker container with SSE transport for MCP, running alongside Qdrant
- **Multi-consumer:** MCP (SSE) for Claude Code, Codex, Gemini; REST (existing api.py) for scripts
- **Docker setup:** Single docker-compose.yml with both Qdrant and MCP/REST server — one `docker compose up` starts everything
- **Context guidance:** Guided on-demand — CLAUDE.md + MEMORY.md cross-reference tells Claude when/how to query memories (e.g., "before starting unfamiliar tasks, search memories"). No automatic queries.

### Memory lifecycle
- **Read + Write:** AI sessions can both search and store new memories
- **Conflict detection:** Enabled — new memories go through Mem0's infer=True pipeline (GPT-4o-mini) to prevent duplicates and resolve conflicts
- **Category guardrails:** None — AI can write to any category
- **Source tagging:** Every AI-written memory gets metadata source tag (e.g., source='claude_code', source='codex') for filtering and auditing

### Claude's Discretion
- Exact tool count and parameter design (based on existing code)
- Deprecated memory handling strategy (include-but-flag vs exclude)
- MCP SDK choice and SSE transport implementation details
- Dockerfile and docker-compose configuration specifics
- How to structure the CLAUDE.md guidance section

</decisions>

<specifics>
## Specific Ideas

- MCP is now an industry standard (Linux Foundation, 1.0 spec) — Claude Code, Codex, and Gemini all support it natively
- The existing `api.py` (FastAPI) already has `/search`, `/context`, `/health`, `/conflicts` endpoints — enhance rather than rewrite
- The existing `injection.py` has a complete RAG pipeline (`inject_memory_context()` → format → inject) — wrap it, don't rebuild
- Mem0Client is a singleton with lazy init — the MCP server and REST API should share the same instance
- Qdrant is already running in Docker on localhost:6333

</specifics>

<deferred>
## Deferred Ideas

- Automated daily briefing (post-refresh LLM summary via Telegram) — future phase
- Alert enrichment (context-rich Telegram messages for drift/risk events) — future phase
- Research copilot (NL interface over DB) — future phase
- Feature ideation (LLM-generated expression engine candidates) — future phase
- SessionStart hook for automatic memory priming — evaluate after PoC validates retrieval quality

</deferred>

---

*Phase: 64-mcp-memory-server*
*Context gathered: 2026-03-02*
