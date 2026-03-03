---
created: 2026-03-03T18:00
title: Clean up stale REST API routes in MCP memory server
area: api
files:
  - src/ta_lab2/tools/ai_orchestrator/memory/api.py
  - src/ta_lab2/tools/ai_orchestrator/memory/client.py
  - src/ta_lab2/tools/ai_orchestrator/memory/mcp_server.py
---

## Problem

The MCP memory server has two API surfaces:

1. **MCP tools** (via `mcp_server.py`) — use Mem0/Qdrant, fully functional, used by Claude Code and OpenAI Codex
2. **REST routes** (`/api/v1/memory/*` via `api.py`) — still call ChromaDB-based modules (`client.py` uses `chromadb.PersistentClient`), return HTTP 500 with "Collection [project_memories] does not exist"

The REST routes are leftover from the pre-Phase-64 ChromaDB era. Nothing actively consumes them, but they confuse tools that probe the server (Gemini CLI, Codex diagnostics) and give a false impression of broken infrastructure.

## Solution

Either:
- **Remove** the REST routes entirely (preferred — nothing consumes them, MCP is the interface)
- **Rewire** them to use Mem0/Qdrant if there's a future use case for REST access

Also consider removing or archiving `client.py` (ChromaDB PersistentClient) since it's dead code.
