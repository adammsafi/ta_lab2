---
phase: 64-mcp-memory-server
plan: 02
subsystem: infra
tags: [docker, docker-compose, mcp, claude-code, qdrant]

# Dependency graph
requires:
  - phase: 64-01
    provides: "FastMCP tools (mcp_server.py) + combined ASGI app (server.py)"
provides:
  - "Docker Compose orchestration for Qdrant + memory-server containers"
  - "Dockerfile building ta_lab2 with orchestrator + fastmcp + uvicorn"
  - ".mcp.json Streamable HTTP registration for Claude Code discovery"
  - "CLAUDE.md with MCP tool usage guidance (when/how to query memories)"
affects: [64-03-testing]

# Tech tracking
tech-stack:
  added: ["docker-compose v2"]
  patterns: ["Named volume for Qdrant data persistence", "Optional env_file for compose validation without secrets"]

key-files:
  created:
    - "docker/Dockerfile"
    - "docker/docker-compose.yml"
    - "docker/.env.example"
    - ".mcp.json"
    - "CLAUDE.md"
  modified:
    - ".memory/MEMORY.md (Claude auto-memory, outside repo)"

key-decisions:
  - "Named Docker volume (not bind mount) for Qdrant -- avoids Windows POSIX path incompatibility"
  - "env_file marked required: false so compose config validates without .env present"
  - "Streamable HTTP transport (type: http) instead of deprecated SSE for MCP registration"
  - "CLAUDE.md includes explicit when-to-query and when-NOT-to-query guidance to prevent over-querying"

patterns-established:
  - "Docker Compose with optional env_file for local dev without secrets"
  - "CLAUDE.md as project-scoped Claude Code instruction file"

# Metrics
duration: 3min
completed: 2026-03-02
---

# Phase 64 Plan 02: Docker Infrastructure + MCP Registration Summary

**Docker Compose for Qdrant + memory-server, .mcp.json Streamable HTTP registration, and CLAUDE.md with MCP usage guidance**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-02T22:30:44Z
- **Completed:** 2026-03-02T22:34:03Z
- **Tasks:** 2
- **Files modified:** 5 created

## Accomplishments
- Created Docker infrastructure: Dockerfile (Python 3.11-slim), docker-compose.yml (Qdrant + memory-server with health checks), .env.example template
- Created .mcp.json with Streamable HTTP transport pointing to localhost:8080/mcp/ for automatic Claude Code discovery
- Created CLAUDE.md with comprehensive MCP tool reference table, when-to-query/when-not-to-query guidance, and key project conventions
- Updated MEMORY.md auxiliary files section with CLAUDE.md cross-reference

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Docker infrastructure** - `f507a621` (feat)
2. **Task 2: Create .mcp.json and CLAUDE.md** - `7385f874` (feat)

## Files Created/Modified
- `docker/Dockerfile` - Python 3.11-slim image with orchestrator + fastmcp + uvicorn deps
- `docker/docker-compose.yml` - Qdrant + memory-server services with named volume, health checks, optional env_file
- `docker/.env.example` - Template documenting OPENAI_API_KEY and optional overrides
- `.mcp.json` - Streamable HTTP MCP server registration for Claude Code
- `CLAUDE.md` - MCP usage guidance with tool reference, query guidance, and key conventions

## Decisions Made
- **Named volume over bind mount:** Docker named volume `qdrant-storage` avoids Windows POSIX path incompatibility that would occur with host bind mounts.
- **Optional env_file:** Marked `required: false` in docker-compose.yml so `docker compose config` validates even without a `.env` file. Users create it from `.env.example` when ready.
- **Streamable HTTP transport:** Used `"type": "http"` in .mcp.json (the recommended transport) instead of deprecated SSE. Matches MCP spec 2025-03-26.
- **Explicit non-query guidance:** CLAUDE.md includes "When NOT to Query" section to prevent unnecessary API calls during routine tasks.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Made env_file optional in docker-compose.yml**
- **Found during:** Task 1 (docker compose config validation)
- **Issue:** `env_file: .env` caused compose config to fail when docker/.env doesn't exist (expected -- users create from template)
- **Fix:** Changed to `path: .env` with `required: false` per Docker Compose v2 spec
- **Files modified:** docker/docker-compose.yml
- **Verification:** `docker compose config` validates successfully without .env file
- **Committed in:** f507a621 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Minor syntax fix for compose validation. No scope creep.

## Issues Encountered

- Pre-commit `mixed-line-ending` hook triggered on both commits (Windows CRLF vs LF). The hook auto-fixed the line endings; re-staging and re-committing resolved it cleanly.

## User Setup Required

Before using the MCP memory server:
1. Copy `docker/.env.example` to `docker/.env` and set `OPENAI_API_KEY`
2. If existing Qdrant data lives in another Docker volume, migrate it (see comments in docker-compose.yml)
3. Run `docker compose -f docker/docker-compose.yml up -d`

## Next Phase Readiness
- All infrastructure is in place for Plan 03 (smoke testing and integration verification)
- Server can be started with a single `docker compose up -d` command
- Claude Code will auto-discover the MCP server via `.mcp.json` when Docker is running

---
*Phase: 64-mcp-memory-server*
*Completed: 2026-03-02*
