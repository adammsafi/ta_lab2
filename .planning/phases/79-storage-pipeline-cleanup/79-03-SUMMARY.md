---
phase: 79-storage-pipeline-cleanup
plan: 03
subsystem: infra
tags: [mcp, fastapi, chromadb, qdrant, mem0, memory-server, dead-code-removal]

# Dependency graph
requires:
  - phase: 79-01
    provides: table/script cleanup for storage pipeline
  - phase: 79-02
    provides: related storage pipeline cleanup context
provides:
  - Dead REST routes /api/v1/memory/* fully removed from memory server
  - client.py (ChromaDB PersistentClient) deleted
  - api.py reduced to single /health endpoint using Qdrant/Mem0
  - server.py simplified -- no more /health override needed
  - __init__.py cleaned of client imports and dead Pydantic model exports
  - validation.py migrated: quick_health_check() now uses Qdrant, validate_memory_store() raises ImportError
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "MCP-only surface: memory server exposes MCP tools at /mcp/ and /health only -- no REST routes"
    - "Health check via mem0_client.memory_count (Qdrant) not ChromaDB client.count()"

key-files:
  created: []
  modified:
    - src/ta_lab2/tools/ai_orchestrator/memory/api.py
    - src/ta_lab2/tools/ai_orchestrator/memory/server.py
    - src/ta_lab2/tools/ai_orchestrator/memory/__init__.py
    - src/ta_lab2/tools/ai_orchestrator/memory/validation.py
  deleted:
    - src/ta_lab2/tools/ai_orchestrator/memory/client.py

key-decisions:
  - "Dead REST routes (/api/v1/memory/*) removed from api.py -- they all called ChromaDB which is unavailable in Docker, returned HTTP 500, had zero consumers"
  - "client.py deleted: ChromaDB PersistentClient fully replaced by Mem0+Qdrant"
  - "Lazy imports in deferred modules (query.py, update.py, migration.py) left intact -- they won't fail at import time; only fail if called (zero active consumers in deferred orchestrator)"
  - "validation.py quick_health_check() migrated to Qdrant; validate_memory_store() raises ImportError with clear migration note"
  - "api.py create_memory_api() retained as entry point but now produces /health-only app"
  - "server.py simplified: no longer overrides /health since api.py now provides the correct Qdrant-backed check"

patterns-established:
  - "Deferred (Phases 1-10) code preserved, not deleted -- lazy imports survive even when dependency is removed"

# Metrics
duration: 6min
completed: 2026-03-21
---

# Phase 79 Plan 03: MCP Memory Server Dead Route Removal Summary

**Dead /api/v1/memory/* REST routes purged from memory server -- ChromaDB client.py deleted, health check migrated to Qdrant via Mem0, MCP tools at /mcp/ remain the sole memory interface**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-03-21T16:26:55Z
- **Completed:** 2026-03-21T16:32:35Z
- **Tasks:** 2
- **Files modified:** 4 (+ 1 deleted)

## Accomplishments
- Removed all 9 dead `/api/v1/memory/*` route handlers from `api.py` that were returning HTTP 500 (called ChromaDB, which doesn't exist in Docker)
- Deleted `client.py` (ChromaDB PersistentClient singleton) -- fully superseded by Mem0+Qdrant
- Migrated `validation.py` and `__init__.py` to remove top-level ChromaDB imports that would break at import time
- `server.py` simplified -- no longer needs to replace the `/health` endpoint since `api.py` now provides the correct Qdrant-backed check from the start

## Task Commits

Each task was committed atomically:

1. **Task 1: Remove dead REST routes and strip ChromaDB from api.py/server.py** - `0de56f09` (refactor)
2. **Task 2: Delete client.py and clean up dependent imports** - `54539bf2` (refactor)

## Files Created/Modified
- `src/ta_lab2/tools/ai_orchestrator/memory/api.py` - Stripped to /health-only FastAPI app; no /api/v1/ routes; health uses Qdrant via mem0_client
- `src/ta_lab2/tools/ai_orchestrator/memory/server.py` - Simplified; mounts MCP at /mcp/, delegates /health to api.py (no override needed)
- `src/ta_lab2/tools/ai_orchestrator/memory/__init__.py` - Removed `from .client import` and dead Pydantic model exports from api.py
- `src/ta_lab2/tools/ai_orchestrator/memory/validation.py` - `quick_health_check()` uses Qdrant; `validate_memory_store()` raises ImportError with migration note
- `src/ta_lab2/tools/ai_orchestrator/memory/client.py` - DELETED (ChromaDB PersistentClient)

## Decisions Made
- Lazy imports in deferred modules (`query.py`, `update.py`, `migration.py`) referencing the now-deleted `client.py` are left intact. They are inside function bodies and only fail at call time. Since these modules have zero active consumers (deferred Phases 1-10 orchestrator), no breakage occurs.
- `validate_memory_store()` raises `ImportError` with a clear message pointing to `mem0_client` instead of being silently removed, so any future caller gets an actionable error.
- `api.py` `create_memory_api()` function retained (not deleted) because `server.py` calls it; stripping the route handlers was sufficient.

## Deviations from Plan

None - plan executed exactly as written. The `__init__.py` cleanup was done as part of Task 2 (planned). The `validation.py` fix was flagged in the plan as a required top-level import fix.

## Issues Encountered
- Ruff auto-removed unused `Optional` import from `validation.py` during pre-commit hook on Task 2 commit. Re-staged the ruff-modified file and committed successfully on second attempt.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 79 Plan 03 is the final plan in Phase 79 (v1.1.0 last phase)
- MCP memory server is now clean: single API surface (MCP tools), health endpoint uses live Qdrant backend
- No blockers for phase completion

---
*Phase: 79-storage-pipeline-cleanup*
*Completed: 2026-03-21*
