# Phase 11: Memory Preparation - Context

**Gathered:** 2026-02-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Capture complete snapshot of current codebase state (ta_lab2, Data_Tools, ProjectTT, fredtools2, fedtools2) in memory system before any file reorganization begins. This creates the audit trail foundation for tracking what moves where during v0.5.0 reorganization.

**What's in scope:**
- Memory indexing of all 5 directories
- v0.4.0 conversation history extraction
- Pre-reorganization baseline snapshots
- Memory validation and query verification

**What's out of scope:**
- File moves (Phase 12+)
- Archive creation (Phase 12)
- Import path updates (Phase 14+)

</domain>

<decisions>
## Implementation Decisions

### Memory Extraction Scope
- **Depth for ta_lab2**: Full AST analysis (files, functions, classes, dependencies, call relationships)
- **Depth for external dirs**: Same as ta_lab2 - full AST analysis for Data_Tools, ProjectTT code, fredtools2, fedtools2
- **Documentation files (ProjectTT)**: Extract text content using pypandoc from .docx, extract table data from Excel files
- **Git metadata**: Include commit hash, author, last modified date for traceability
- **Test files**: Same depth as source code - full AST analysis
- **Configuration files**: Index with full content (pyproject.toml, .gitignore, etc.)
- **File statistics**: Capture file size, line count, function count for complexity metrics
- **Deduplication strategy**: Create parallel snapshots - keep existing memories, create new pre_reorg versions for full audit trail

**Exclusions (explicitly skip):**
- Data files (.csv, .xlsx, .json data files)
- Python environments (.venv, venv, env directories)
- Build artifacts (__pycache__, .pyc, dist/ directories)
- Git internals (.git directory)

### Conversation History Handling
- **Session scope**: All v0.4.0 phases (1-10) - complete conversation history
- **Phase boundaries**: Use both SUMMARY.md files AND git commit timestamps to identify phase boundaries
- **Conversation detail**: Full conversation context - capture complete flow including questions, answers, iterations
- **Conversation-code links**: Yes, create links between discussions and resulting code changes for full traceability

### Metadata Tagging Strategy
- **Tag structure**: Both simple tags (pre_reorg_v0.5.0) AND structured metadata (milestone, phase, timestamp)
- **Directory tags**: Explicit source tags - differentiate ta_lab2, Data_Tools, ProjectTT, fredtools2, fedtools2
- **File type tags**: Include type information (source_code, test, config, documentation) for query flexibility
- **Versioning**: Dual versioning - both ISO timestamp (2026-02-02T10:30:00Z) AND git commit hash

**Example tag structure:**
```json
{
  "tags": ["pre_reorg_v0.5.0"],
  "metadata": {
    "milestone": "v0.5.0",
    "phase": "pre_reorg",
    "source": "ta_lab2",
    "file_type": "source_code",
    "timestamp": "2026-02-02T10:30:00Z",
    "commit_hash": "552a78c"
  }
}
```

### Memory Validation Approach
- **Required queries before Phase 12**:
  - File inventory queries: List all files in directory X, count files by type
  - Function lookup queries: Find function X, show what calls function Y
  - Time-based queries: Show pre_reorg snapshot, compare to current state
  - Cross-reference queries: Find similar functions, show dependencies between files

- **Coverage threshold**: 100% files indexed (excluding explicit exclusions above) - no gaps allowed
- **Validation report**: Detailed report with file counts, function counts, memory sizes per directory - full audit
- **Failure handling**: Claude's discretion - determine if gaps are acceptable based on query functionality

### Claude's Discretion
- AST analysis depth for binary files (if any encountered)
- Exact similarity threshold for duplicate function detection
- Memory chunking strategy for large files
- Failure handling for validation gaps (document vs block)
- Embedding model selection (reuse existing or optimize for this task)

</decisions>

<specifics>
## Specific Ideas

- Memory system already exists (Mem0 + Qdrant from v0.4.0) - extend, don't rebuild
- Existing 3,763 memories should remain intact - parallel snapshots preserve audit trail
- Conversation boundaries from SUMMARY.md + git commits enables phase-level rollback
- Git metadata integration ties memory to source control for complete traceability
- Validation report should answer: "Can I query the state of any file before reorganization?"

</specifics>

<deferred>
## Deferred Ideas

None - discussion stayed within phase scope.

</deferred>

---

*Phase: 11-memory-preparation*
*Context gathered: 2026-02-02*
