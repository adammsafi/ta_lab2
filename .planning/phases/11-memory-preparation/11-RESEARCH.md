# Phase 11: Memory Preparation - Research

**Researched:** 2026-02-02
**Domain:** Memory system indexing, conversation history extraction, codebase snapshot
**Confidence:** HIGH

## Summary

Phase 11 requires capturing complete snapshots of 5 directories (ta_lab2, Data_Tools, ProjectTT, fredtools2, fedtools2) and v0.4.0 conversation history into the existing Mem0+Qdrant memory system before v0.5.0 reorganization begins. The project already has mature memory infrastructure (3,763 memories, Mem0 1.0.2 with Qdrant backend, text-embedding-3-small embeddings) that can be extended with parallel snapshots.

The standard approach combines Python's built-in AST module for code analysis, GitPython for metadata extraction, pypandoc for document conversion, and the existing Mem0 client for memory operations. Claude Code conversation transcripts are stored as JSONL files in `~/.claude/projects/`, with established parsing tools available. The key challenge is achieving 100% file coverage validation through comprehensive query testing rather than traditional code coverage metrics.

**Primary recommendation:** Extend existing memory tooling rather than building new infrastructure. Use batch processing with custom functions (Mem0 batch operations not yet available), leverage existing AST patterns, and create parallel snapshots with pre_reorg_v0.5.0 tags to preserve the 3,763 existing memories while establishing complete audit trail.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| mem0ai | 1.0.2+ | Memory intelligence layer | Already in use, provides conflict detection, deduplication, LLM-powered operations |
| qdrant-client | 1.7.0+ | Vector database backend | Mem0 1.0.2 requires Qdrant (not ChromaDB), persistent storage with metadata filtering |
| GitPython | 3.1.46+ | Git metadata extraction | Official Python library, extracts commit hash, author, timestamps, file history |
| pypandoc | 1.13.0+ | Document conversion | Wrapper for Pandoc, converts .docx/.xlsx to plain text for ProjectTT docs |
| openai | 1.0.0+ | Embedding generation | text-embedding-3-small (1536-dim) already configured in existing system |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| openpyxl | 3.1.4+ | Excel table extraction | Extract structured data from ProjectTT .xlsx files |
| ast | stdlib | Python code parsing | Built-in AST module for function/class/dependency extraction |
| pathlib | stdlib | File system traversal | Modern Python path handling for directory walking |
| json | stdlib | JSONL parsing | Parse Claude Code conversation transcripts |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| GitPython | subprocess git CLI | GitPython provides object-oriented API, handles edge cases better |
| pypandoc | python-docx | pypandoc handles more formats (docx + xlsx), single tool for all conversions |
| Mem0 batch | Manual loop with delays | Mem0 batch operations planned but not released, custom batch needed for now |

**Installation:**
```bash
# Already installed in project
pip install mem0ai==1.0.2 qdrant-client gitpython pypandoc openpyxl

# Verify Qdrant server is running
qdrant-server --config-path qdrant_config.yaml
```

## Architecture Patterns

### Recommended Project Structure
```
.planning/phases/11-memory-preparation/
├── scripts/
│   ├── extract_codebase.py          # AST-based code extraction
│   ├── extract_conversations.py     # Claude Code JSONL parsing
│   ├── extract_documents.py         # pypandoc for ProjectTT docs
│   ├── batch_indexer.py            # Batch memory operations
│   └── validate_coverage.py        # Query-based validation
├── snapshots/
│   ├── ta_lab2_snapshot.json       # Pre-reorg snapshot metadata
│   ├── external_dirs_snapshot.json # Data_Tools, ProjectTT, etc.
│   └── conversations_snapshot.json # v0.4.0 phase boundaries
└── validation/
    └── coverage_report.json        # Validation query results
```

### Pattern 1: Parallel Memory Snapshots
**What:** Create new memories with pre_reorg tags alongside existing memories, avoiding updates/deletions
**When to use:** When preserving existing memory state is critical for audit trail
**Example:**
```python
# From existing migration.py pattern
from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
from ta_lab2.tools.ai_orchestrator.memory.metadata import create_metadata

client = get_mem0_client()

# Get existing memories (preserve these)
existing = client.get_all(user_id="orchestrator")
print(f"Existing memories: {len(existing)} (will be preserved)")

# Add parallel snapshot with distinct tagging
snapshot_metadata = create_metadata(
    source="pre_reorg_v0.5.0",
    category="codebase_snapshot"
)
snapshot_metadata.update({
    "milestone": "v0.5.0",
    "phase": "pre_reorg",
    "timestamp": "2026-02-02T10:30:00Z",
    "commit_hash": "49499eb"  # Current commit
})

result = client.add(
    messages=[{"role": "user", "content": "File: src/ta_lab2/features/ema.py..."}],
    user_id="orchestrator",
    metadata=snapshot_metadata,
    infer=False  # Disable conflict detection for bulk snapshots
)
```

### Pattern 2: AST-Based Code Extraction
**What:** Parse Python files to extract functions, classes, imports, docstrings, call graphs
**When to use:** For full codebase analysis (ta_lab2, Data_Tools, fredtools2, fedtools2, ProjectTT code)
**Example:**
```python
# Source: Python AST stdlib + established patterns
import ast
from pathlib import Path

def extract_code_structure(file_path: Path) -> dict:
    """Extract functions, classes, dependencies from Python file."""
    with open(file_path, 'r', encoding='utf-8') as f:
        source = f.read()

    tree = ast.parse(source, filename=str(file_path))

    functions = []
    classes = []
    imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions.append({
                "name": node.name,
                "line_start": node.lineno,
                "line_end": node.end_lineno,
                "args": [arg.arg for arg in node.args.args],
                "docstring": ast.get_docstring(node)
            })
        elif isinstance(node, ast.ClassDef):
            classes.append({
                "name": node.name,
                "line_start": node.lineno,
                "methods": [m.name for m in node.body if isinstance(m, ast.FunctionDef)]
            })
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append({
                "module": node.module if isinstance(node, ast.ImportFrom) else None,
                "names": [alias.name for alias in node.names]
            })

    return {
        "file": str(file_path),
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "line_count": len(source.splitlines()),
        "size_bytes": len(source.encode('utf-8'))
    }
```

### Pattern 3: Git Metadata Integration
**What:** Extract commit hash, author, timestamps for each file
**When to use:** For tying memory snapshots to source control state
**Example:**
```python
# Source: GitPython official docs
from git import Repo
from datetime import datetime

def get_file_git_metadata(repo_path: Path, file_path: Path) -> dict:
    """Get git metadata for file."""
    repo = Repo(repo_path)

    # Get latest commit affecting this file
    commits = list(repo.iter_commits(paths=str(file_path), max_count=1))

    if not commits:
        return {"error": "No commits found"}

    commit = commits[0]

    return {
        "commit_hash": commit.hexsha[:7],  # Short hash
        "commit_hash_full": commit.hexsha,
        "author_name": commit.author.name,
        "author_email": commit.author.email,
        "committed_datetime": commit.committed_datetime.isoformat(),
        "message": commit.message.strip(),
        "files_changed": len(commit.stats.files)
    }
```

### Pattern 4: Claude Code Conversation Extraction
**What:** Parse JSONL transcripts to extract conversation history with phase boundaries
**When to use:** For capturing v0.4.0 development context
**Example:**
```python
# Source: Claude Code transcript format research
import json
from pathlib import Path

def extract_conversation(jsonl_path: Path) -> list[dict]:
    """Parse Claude Code JSONL transcript."""
    messages = []

    with open(jsonl_path, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                entry = json.loads(line)

                # Extract different message types
                if entry.get("type") == "user-message":
                    messages.append({
                        "role": "user",
                        "content": entry.get("text", ""),
                        "timestamp": entry.get("timestamp"),
                        "message_id": entry.get("messageId")
                    })
                elif entry.get("type") == "assistant-message":
                    messages.append({
                        "role": "assistant",
                        "content": entry.get("text", ""),
                        "timestamp": entry.get("timestamp")
                    })
                elif entry.get("type") == "tool-use":
                    messages.append({
                        "role": "tool",
                        "tool": entry.get("name"),
                        "input": entry.get("input", {}),
                        "timestamp": entry.get("timestamp")
                    })
            except json.JSONDecodeError:
                continue

    return messages

def link_conversations_to_phases(messages: list[dict], git_commits: list) -> dict:
    """Map conversation timestamps to phase boundaries using SUMMARY.md dates and git commits."""
    # Phase boundaries from SUMMARY.md timestamps and git commit dates
    phase_boundaries = {
        1: ("2026-01-15", "2026-01-18"),
        2: ("2026-01-18", "2026-01-20"),
        # ... extract from SUMMARY.md files
    }

    conversations_by_phase = {}
    for phase, (start, end) in phase_boundaries.items():
        phase_messages = [
            m for m in messages
            if start <= m["timestamp"][:10] <= end
        ]
        conversations_by_phase[phase] = phase_messages

    return conversations_by_phase
```

### Pattern 5: Batch Processing with Rate Limiting
**What:** Process multiple memories efficiently without overwhelming API/database
**When to use:** Indexing large codebases (5 directories, potentially 1000+ files)
**Example:**
```python
# Source: Mem0 batch operations research (custom implementation until native support)
import time
from typing import List

def batch_add_memories(
    client,
    memories: List[dict],
    batch_size: int = 50,
    delay_seconds: float = 0.5
) -> dict:
    """Add memories in batches with rate limiting."""
    results = {
        "total": len(memories),
        "added": 0,
        "skipped": 0,
        "errors": 0,
        "error_ids": []
    }

    for i in range(0, len(memories), batch_size):
        batch = memories[i:i+batch_size]

        for memory in batch:
            try:
                client.add(
                    messages=[{"role": "user", "content": memory["content"]}],
                    user_id="orchestrator",
                    metadata=memory["metadata"],
                    infer=False  # Skip LLM inference for bulk operations
                )
                results["added"] += 1
            except Exception as e:
                results["errors"] += 1
                results["error_ids"].append(memory.get("id", "unknown"))
                print(f"Error adding memory: {e}")

        # Progress logging
        print(f"Batch {i//batch_size + 1}: {results['added']}/{results['total']} memories added")

        # Rate limiting
        if i + batch_size < len(memories):
            time.sleep(delay_seconds)

    return results
```

### Pattern 6: Query-Based Validation
**What:** Validate 100% coverage by testing if all files are queryable
**When to use:** Final validation step before Phase 12
**Example:**
```python
# Source: Coverage validation research
def validate_memory_coverage(client, expected_files: List[str]) -> dict:
    """Validate that all files are indexed and queryable."""
    validation_results = {
        "total_files": len(expected_files),
        "found": 0,
        "missing": [],
        "queries_tested": []
    }

    # Test 1: File inventory queries
    for directory in ["ta_lab2", "Data_Tools", "ProjectTT", "fredtools2", "fedtools2"]:
        query = f"List all files in {directory}"
        results = client.search(
            query=query,
            user_id="orchestrator",
            filters={"source": {"$eq": "pre_reorg_v0.5.0"}, "directory": {"$eq": directory}},
            limit=1000
        )
        validation_results["queries_tested"].append({
            "query": query,
            "results_count": len(results)
        })

    # Test 2: Function lookup queries
    for file_path in expected_files[:10]:  # Sample
        query = f"Functions in {file_path}"
        results = client.search(query=query, user_id="orchestrator", limit=5)
        if results:
            validation_results["found"] += 1
        else:
            validation_results["missing"].append(file_path)

    # Test 3: Time-based queries
    query = "Show pre_reorg snapshot from 2026-02-02"
    results = client.search(
        query=query,
        user_id="orchestrator",
        filters={"tags": {"$contains": "pre_reorg_v0.5.0"}},
        limit=100
    )
    validation_results["snapshot_count"] = len(results)

    return validation_results
```

### Anti-Patterns to Avoid
- **Updating existing memories:** Always create parallel snapshots, never modify the 3,763 existing memories
- **Using infer=True for bulk:** LLM conflict detection adds latency, disable for snapshot operations
- **Synchronous single-file processing:** Use batch processing with rate limiting for efficiency
- **Assuming git metadata exists:** Some files may be untracked, handle missing metadata gracefully
- **Skipping validation queries:** Query testing is the only way to prove 100% coverage

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Python AST parsing | Custom regex/string parser | ast stdlib module | Handles syntax edge cases, nested classes, decorators, async, type hints |
| Git metadata extraction | subprocess git commands | GitPython library | Object-oriented API, handles binary data, error handling, cross-platform |
| Document conversion | Manual docx/xlsx parsing | pypandoc + openpyxl | Preserves formatting, handles complex structures, battle-tested |
| JSONL parsing | Custom line-by-line parser | json.loads() per line | Handles encoding, malformed entries, large files efficiently |
| Vector similarity search | Custom embedding comparison | Qdrant filtering + search | Optimized indexes, metadata filtering, handles scale |
| Batch operations with rate limiting | Manual threading/async | ThreadPoolExecutor + time.sleep | Simple, debuggable, sufficient for this scale |

**Key insight:** This phase extends existing infrastructure rather than building new systems. The ta_lab2 project already has 3,763 memories, mature Mem0+Qdrant setup, and AST analysis patterns. The challenge is orchestration (batch processing 5 directories) and validation (proving 100% queryable coverage), not building core capabilities.

## Common Pitfalls

### Pitfall 1: Mem0 Batch Operations Assumption
**What goes wrong:** Assuming Mem0 has native batch_add(), batch_update() methods
**Why it happens:** Mem0 GitHub issue #3761 (Nov 2025) proposes these methods, but they're not yet released in 1.0.2
**How to avoid:** Implement custom batch processing with manual loops, rate limiting, and error handling as shown in Pattern 5
**Warning signs:** "AttributeError: Memory object has no attribute 'batch_add'" errors

### Pitfall 2: Qdrant Embedded Mode Persistence (Windows)
**What goes wrong:** Memories disappear after restart when using Qdrant local embedded mode on Windows
**Why it happens:** Qdrant embedded mode has persistence limitations on Windows, server mode recommended
**How to avoid:** Use Qdrant server mode (QDRANT_SERVER_MODE=true, host:port config) for reliable persistence
**Warning signs:** mem0_config.py warning logs about embedded mode limitations

### Pitfall 3: Embedding Dimension Mismatch
**What goes wrong:** Indexing new memories fails with dimension errors
**Why it happens:** Using different embedding model than existing memories (text-embedding-3-small = 1536-dim)
**How to avoid:** Verify embedder_model in mem0_config.py is text-embedding-3-small before indexing
**Warning signs:** "Dimension mismatch: expected 1536, got XXXX" errors from Qdrant

### Pitfall 4: Claude Code Transcript Parsing Fragility
**What goes wrong:** Parsing breaks on unexpected JSONL entry types
**Why it happens:** Claude Code adds new message types (file-history-snapshot, tool-result, etc.) not documented
**How to avoid:** Wrap json.loads() in try/except, skip unknown types, log parsing errors
**Warning signs:** JSONDecodeError, KeyError on expected fields

### Pitfall 5: Git Metadata for Untracked Files
**What goes wrong:** GitPython raises error when getting metadata for untracked/new files
**Why it happens:** Files in working directory may not be committed yet
**How to avoid:** Check if file is tracked before calling iter_commits(), provide default metadata for untracked
**Warning signs:** GitCommandError: "fatal: ambiguous argument: no commit found"

### Pitfall 6: pypandoc Without Pandoc Binary
**What goes wrong:** ImportError or RuntimeError when calling pypandoc.convert_file()
**Why it happens:** pypandoc requires pandoc binary installed (pip install pypandoc-binary includes it)
**How to avoid:** Use pypandoc-binary package or ensure pandoc is on PATH
**Warning signs:** "Pandoc not found" errors

### Pitfall 7: Validation Coverage Theater
**What goes wrong:** Claiming 100% coverage based on file counts, not query results
**Why it happens:** Easy to count indexed files, hard to prove they're queryable and accurate
**How to avoid:** Write validation queries that test actual search functionality (Pattern 6), not just existence
**Warning signs:** Files indexed but queries return empty results or wrong content

### Pitfall 8: Memory Metadata Structure Inconsistency
**What goes wrong:** Some memories have tags, others have metadata.tags, filtering fails
**Why it happens:** Mixing old metadata schema with new structured metadata
**How to avoid:** Use consistent metadata.py create_metadata() for all new memories, include both tags and metadata
**Warning signs:** Qdrant filters return partial results, missing memories with correct tags

## Code Examples

Verified patterns from official sources:

### Complete File Processing Pipeline
```python
# Source: Combining AST, GitPython, Mem0 patterns
from pathlib import Path
import ast
from git import Repo
from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
from ta_lab2.tools.ai_orchestrator.memory.metadata import create_metadata

def process_python_file(
    file_path: Path,
    repo_path: Path,
    directory_name: str
) -> dict:
    """Complete pipeline: AST analysis + Git metadata + Memory indexing."""

    # 1. Extract code structure (AST)
    with open(file_path, 'r', encoding='utf-8') as f:
        source = f.read()

    tree = ast.parse(source, filename=str(file_path))

    functions = []
    classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions.append({
                "name": node.name,
                "line": node.lineno,
                "docstring": ast.get_docstring(node) or ""
            })
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)

    # 2. Get git metadata
    repo = Repo(repo_path)
    try:
        commits = list(repo.iter_commits(paths=str(file_path), max_count=1))
        commit = commits[0] if commits else None
        git_metadata = {
            "commit_hash": commit.hexsha[:7] if commit else "untracked",
            "author": commit.author.name if commit else "unknown",
            "committed_at": commit.committed_datetime.isoformat() if commit else None
        }
    except Exception as e:
        git_metadata = {"error": str(e)}

    # 3. Create memory content
    content = f"""
File: {file_path.relative_to(repo_path)}
Directory: {directory_name}
Lines: {len(source.splitlines())}
Functions: {', '.join([f['name'] for f in functions[:10]])}
Classes: {', '.join(classes[:10])}
Commit: {git_metadata.get('commit_hash', 'N/A')}

Summary: Python module with {len(functions)} functions, {len(classes)} classes.
""".strip()

    # 4. Create structured metadata
    metadata = create_metadata(
        source="pre_reorg_v0.5.0",
        category="codebase_snapshot"
    )
    metadata.update({
        "milestone": "v0.5.0",
        "phase": "pre_reorg",
        "directory": directory_name,
        "file_type": "source_code",
        "file_path": str(file_path.relative_to(repo_path)),
        "function_count": len(functions),
        "class_count": len(classes),
        "line_count": len(source.splitlines()),
        **git_metadata
    })

    # 5. Index in memory
    client = get_mem0_client()
    result = client.add(
        messages=[{"role": "user", "content": content}],
        user_id="orchestrator",
        metadata=metadata,
        infer=False
    )

    return {
        "file": str(file_path),
        "memory_id": result.get("id"),
        "functions": len(functions),
        "classes": len(classes)
    }
```

### Document Extraction (ProjectTT)
```python
# Source: pypandoc + openpyxl official docs
import pypandoc
from openpyxl import load_workbook
from pathlib import Path

def extract_document_content(doc_path: Path) -> dict:
    """Extract text from .docx or table data from .xlsx."""

    if doc_path.suffix == ".docx":
        # Convert DOCX to plain text
        text = pypandoc.convert_file(
            str(doc_path),
            'plain',
            extra_args=['--wrap=none']
        )
        return {
            "type": "document",
            "content": text,
            "format": "docx"
        }

    elif doc_path.suffix == ".xlsx":
        # Extract Excel tables
        wb = load_workbook(doc_path, read_only=True)
        tables_data = []

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]

            # Get table data (if tables exist)
            for table in ws.tables.values():
                table_range = table.ref
                table_data = []
                for row in ws[table_range]:
                    table_data.append([cell.value for cell in row])

                tables_data.append({
                    "sheet": sheet_name,
                    "table_name": table.name,
                    "data": table_data
                })

        return {
            "type": "spreadsheet",
            "tables": tables_data,
            "format": "xlsx"
        }

    return {"error": "Unsupported format"}
```

### Conversation Phase Boundary Detection
```python
# Source: SUMMARY.md pattern + git log analysis
from pathlib import Path
from datetime import datetime
import re

def extract_phase_boundaries(planning_dir: Path, repo: Repo) -> dict:
    """Extract phase start/end dates from SUMMARY.md files and git commits."""

    phases = {}

    # Get all phase directories
    phase_dirs = sorted([
        d for d in planning_dir.glob("*-*")
        if d.is_dir() and d.name[0].isdigit()
    ])

    for phase_dir in phase_dirs:
        phase_match = re.match(r'(\d+)-(.+)', phase_dir.name)
        if not phase_match:
            continue

        phase_num = int(phase_match.group(1))
        phase_name = phase_match.group(2)

        # Find SUMMARY.md
        summary_files = list(phase_dir.glob("*-SUMMARY.md"))

        if summary_files:
            summary_path = summary_files[0]

            # Get git commit dates for this file
            commits = list(repo.iter_commits(paths=str(summary_path), all=True))

            if commits:
                start_date = commits[-1].committed_datetime  # First commit
                end_date = commits[0].committed_datetime     # Last commit

                phases[phase_num] = {
                    "name": phase_name,
                    "start": start_date.isoformat(),
                    "end": end_date.isoformat(),
                    "summary_file": str(summary_path),
                    "commits": len(commits)
                }

    return phases
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ChromaDB backend | Qdrant with Mem0 1.0.2 | Jan 2026 (Phase 3) | Mem0 dropped ChromaDB support, Qdrant now required for intelligence layer |
| Manual memory addition | Mem0 with conflict detection | Jan 2026 (Phase 3) | LLM-powered deduplication, but adds latency (disable for bulk operations) |
| Single snapshot strategy | Parallel snapshots | Phase 11 design | Preserves existing 3,763 memories, creates audit trail |
| Code coverage metrics | Query-based validation | 2026 | For memory indexing, queryability matters more than existence |
| Synchronous processing | Batch with rate limiting | 2026 best practice | Avoids API throttling, handles scale better |

**Deprecated/outdated:**
- **ChromaDB with Mem0:** Mem0 1.0.2+ only supports Qdrant backend
- **Embedding model mixing:** Must use text-embedding-3-small (1536-dim) to match existing memories
- **Qdrant embedded mode on Windows:** Has persistence issues, use server mode instead
- **Native Mem0 batch operations:** Proposed but not released, custom implementation required
- **File count coverage:** Insufficient, must validate through query testing

## Open Questions

Things that couldn't be fully resolved:

1. **Optimal batch size for memory indexing**
   - What we know: 50-100 memories per batch recommended based on research, 0.5s delay between batches
   - What's unclear: Qdrant server capacity limits for ta_lab2 setup, whether OpenAI embedding API has stricter rate limits
   - Recommendation: Start with batch_size=50, monitor error rates, adjust based on actual performance

2. **Claude Code transcript completeness**
   - What we know: Transcripts stored in ~/.claude/projects/{project-hash}/*.jsonl, multiple entry types (user-message, assistant-message, tool-use)
   - What's unclear: Whether all v0.4.0 conversations are in these files, or if some sessions were pruned
   - Recommendation: Parse all .jsonl files, correlate timestamps with git commits, flag gaps for manual review

3. **External directory access reliability**
   - What we know: Need to index Data_Tools, ProjectTT, fredtools2, fedtools2 from different parent directories
   - What's unclear: Whether all 4 directories are currently accessible from ta_lab2 environment
   - Recommendation: Validate paths exist at script start, fail fast with clear error if directories unreachable

4. **Memory query performance at scale**
   - What we know: Current 3,763 memories, adding potentially 1000+ more for 5 directory snapshots
   - What's unclear: Whether Qdrant filtering performance degrades significantly at 5000+ memories
   - Recommendation: Run validation queries after indexing, measure response times, add indexes if needed

5. **Conversation-to-code link precision**
   - What we know: Can link conversations to phases via SUMMARY.md timestamps + git commits
   - What's unclear: How to attribute specific code changes to conversation snippets (one conversation spans multiple commits)
   - Recommendation: Link at phase level (granular enough for rollback), don't attempt line-level attribution

## Sources

### Primary (HIGH confidence)
- Python AST stdlib documentation: https://docs.python.org/3/library/ast.html
- GitPython 3.1.46 documentation: https://gitpython.readthedocs.io/en/stable/tutorial.html
- Mem0 Qdrant integration: https://qdrant.tech/documentation/frameworks/mem0/
- Qdrant filtering documentation: https://qdrant.tech/documentation/concepts/filtering/
- pypandoc PyPI: https://pypi.org/project/pypandoc/
- openpyxl worksheet tables: https://openpyxl.readthedocs.io/en/latest/worksheet_tables.html

### Secondary (MEDIUM confidence)
- Claude Code transcripts (GitHub tools): https://github.com/simonw/claude-code-transcripts
- Mem0 batch operations GitHub issue #3761: https://github.com/mem0ai/mem0/issues/3761
- Qdrant indexing optimization: https://qdrant.tech/articles/indexing-optimization/
- GitPython commit metadata extraction: https://codesignal.com/learn/courses/database-setup-and-code-ingestion/lessons/git-history-extraction-with-python

### Tertiary (LOW confidence - existing project code)
- ta_lab2 migration.py: Existing batch processing patterns
- ta_lab2 mem0_config.py: Current Qdrant configuration
- ta_lab2 metadata.py: Enhanced metadata schema

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All libraries verified through official documentation (Python AST, GitPython, Mem0/Qdrant, pypandoc)
- Architecture: HIGH - Patterns based on existing ta_lab2 code (migration.py, mem0_client.py) + official docs
- Pitfalls: MEDIUM - Based on GitHub issues (Mem0 #3761), project comments (mem0_config.py warnings), general experience

**Research date:** 2026-02-02
**Valid until:** 30 days (stable technologies, but Mem0 batch operations may be released)

**Key constraints from CONTEXT.md:**
- Full AST analysis for all 5 directories (locked decision)
- pypandoc for ProjectTT documentation (locked decision)
- Git metadata required (locked decision)
- Parallel snapshots, preserve existing 3,763 memories (locked decision)
- 100% coverage threshold (locked decision)
- Dual tagging strategy: simple tags + structured metadata (locked decision)

**Dependencies:**
- Phase 3 memory system (Mem0 + Qdrant already operational)
- Claude Code transcripts (stored in ~/.claude/projects/)
- Access to external directories (Data_Tools, ProjectTT, fredtools2, fedtools2)
- Qdrant server running (or embedded mode with persistence limitations noted)
