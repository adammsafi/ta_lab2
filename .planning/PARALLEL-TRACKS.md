# Parallel Development Tracks

**Created:** 2026-01-26
**Status:** Active after Phase 1 completion

---

## Overview

The ta_lab2 project supports **three parallel development tracks** that can evolve independently after Phase 1 foundation is complete:

1. **Track 1: Memory Infrastructure** - Semantic memory with Mem0 + Vertex AI Memory Bank
2. **Track 2: AI Orchestrator** - Multi-platform task routing and execution
3. **Track 3: ta_lab2 Features** - Quant trading infrastructure (EMAs, bars, signals)

Each track has well-defined interfaces and stub implementations for testing without blocking on other tracks.

---

## Track 1: Memory Infrastructure

### Location
`src/ta_lab2/tools/memory/`

### Interface Contracts

```python
# Core Memory API
class MemoryManager:
    def add(self, content: str, metadata: dict) -> str:
        """
        Add content to memory.

        Args:
            content: Text to store
            metadata: Additional context (tags, source, etc.)

        Returns:
            memory_id: Unique identifier for retrieval
        """

    def search(self, query: str, threshold: float = 0.7, limit: int = 10) -> list[Memory]:
        """
        Search memory by semantic similarity.

        Args:
            query: Search query
            threshold: Minimum similarity score (0-1)
            limit: Max results to return

        Returns:
            List of Memory objects sorted by relevance
        """

    def get_context(self, memory_ids: list[str]) -> str:
        """
        Retrieve and format memories for context injection.

        Args:
            memory_ids: List of memory IDs to retrieve

        Returns:
            Formatted context string ready for prompt injection
        """

# Memory data structure
@dataclass
class Memory:
    id: str
    content: str
    metadata: dict
    embedding: list[float]  # Vector representation
    created_at: datetime
    relevance_score: float  # From search results
```

### Dependencies
- **Primary**: Mem0 (local), Vertex AI Memory Bank (cloud)
- **Storage**: ChromaDB (local), Cloud SQL (cloud)
- **Embeddings**: sentence-transformers (local), Vertex AI Embeddings (cloud)

### Stub for Testing

**File:** `tests/stubs/memory_stub.py`

```python
class MemoryStub(MemoryManager):
    """In-memory stub for testing without Mem0/Memory Bank."""

    def __init__(self):
        self.memories = {}

    def add(self, content: str, metadata: dict) -> str:
        memory_id = str(uuid.uuid4())
        self.memories[memory_id] = Memory(
            id=memory_id,
            content=content,
            metadata=metadata,
            embedding=[],  # Stub: no real embeddings
            created_at=datetime.now(),
            relevance_score=1.0
        )
        return memory_id

    def search(self, query: str, threshold: float = 0.7, limit: int = 10) -> list[Memory]:
        # Stub: return all memories (no semantic search)
        return list(self.memories.values())[:limit]
```

### Integration Point
**Phase 9:** Orchestrator calls `memory.search()` to inject context before routing tasks.

---

## Track 2: AI Orchestrator

### Location
`src/ta_lab2/tools/ai_orchestrator/`

### Interface Contracts

```python
# Core Orchestrator API
class Orchestrator:
    def execute(self, task: Task, pre_flight: bool = True) -> Result:
        """
        Execute a task on the optimal platform.

        Args:
            task: Task to execute (type, prompt, context)
            pre_flight: If True, run validation before execution

        Returns:
            Result with output, success status, cost, metadata
        """

    def validate_environment(self) -> dict[Platform, dict]:
        """
        Check which platforms are available.

        Returns:
            Dict mapping Platform to status (implemented, requirements)
        """

# Task input format
@dataclass
class Task:
    type: TaskType  # CODE_GENERATION, REFACTORING, etc.
    prompt: str
    context: dict[str, Any] = field(default_factory=dict)
    platform_hint: Optional[Platform] = None
    priority: int = 5
    requires_gsd: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

# Result output format
@dataclass
class Result:
    task: Task
    platform: Platform  # Which platform executed it
    output: str  # The AI's response
    success: bool
    error: Optional[str] = None
    cost: float = 0.0
    tokens_used: int = 0
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
```

### Dependencies
- **Primary**: anthropic (Claude), openai (ChatGPT), google-generativeai (Gemini)
- **Quota**: QuotaTracker (Phase 1), persistence layer
- **Validation**: AdapterValidator (Phase 1)

### Stub for Testing

**File:** `tests/stubs/orchestrator_stub.py`

```python
class OrchestratorStub(Orchestrator):
    """Mock orchestrator for testing without real AI calls."""

    def execute(self, task: Task, pre_flight: bool = True) -> Result:
        return Result(
            task=task,
            platform=Platform.CLAUDE_CODE,
            output=f"[STUB] Would execute: {task.prompt}",
            success=True,
            cost=0.0,
            tokens_used=0,
        )
```

### Integration Point
**Phase 9:** Orchestrator receives memory context, routes task, stores result in memory.

---

## Track 3: ta_lab2 Features

### Location
`src/ta_lab2/features/`, `src/ta_lab2/scripts/`

### Interface Contracts

```python
# SQL Schema Interfaces
# Tables: cmc_price_bars_*, cmc_ema_*, dim_sessions, dim_timeframe

# Python API (refresh scripts)
def refresh_ema_daily(symbols: list[str], date: datetime) -> DataFrame:
    """
    Refresh daily EMA calculations.

    Args:
        symbols: List of trading symbols
        date: Date to calculate EMAs for

    Returns:
        DataFrame with calculated EMAs
    """

# Query interface
def get_ema(symbol: str, date: datetime, timeframe: str = "1d") -> DataFrame:
    """
    Query EMA values for analysis.

    Args:
        symbol: Trading symbol
        date: Date to query
        timeframe: Timeframe (1d, 4h, 1h, etc.)

    Returns:
        DataFrame with EMA values
    """
```

### Dependencies
- **Primary**: PostgreSQL, Polars
- **Data source**: CoinMarketCap API
- **Time model**: dim_sessions, dim_timeframe (Phase 6)

### Stub for Testing

**File:** `tests/stubs/db_stub.py`

```python
class DBStub:
    """In-memory Polars DataFrames for testing without PostgreSQL."""

    def __init__(self):
        self.ema_data = pl.DataFrame({
            "symbol": [],
            "date": [],
            "ema_value": [],
        })

    def refresh_ema_daily(self, symbols: list[str], date: datetime) -> pl.DataFrame:
        # Stub: return mock data
        return pl.DataFrame({
            "symbol": symbols,
            "date": [date] * len(symbols),
            "ema_value": [100.0] * len(symbols),
        })
```

### Integration Point
**Phase 9:** Orchestrator automates refresh scripts, memory stores execution history.

---

## Development Independence Verification

### Track 1 (Memory) Develops Independently

**Can develop without Track 2/3 because:**
- Tests use `OrchestratorStub` for orchestrator calls
- No dependency on ta_lab2 tables (stores arbitrary content)
- Mem0 and Memory Bank work standalone

**Example test:**
```python
def test_memory_search():
    memory = MemoryManager()
    memory_id = memory.add("EMA calculation logic", {"type": "code"})
    results = memory.search("how to calculate EMA")
    assert len(results) > 0
```

### Track 2 (Orchestrator) Develops Independently

**Can develop without Track 1/3 because:**
- Tests use `MemoryStub` for memory operations
- Task routing works without ta_lab2 scripts (generic tasks)
- Adapters execute on any content, not just ta_lab2 code

**Example test:**
```python
def test_routing_to_claude():
    orch = Orchestrator()
    task = Task(type=TaskType.CODE_GENERATION, prompt="test")
    result = orch.execute(task)
    assert result.success
```

### Track 3 (ta_lab2) Develops Independently

**Can develop without Track 1/2 because:**
- Manual script execution doesn't need orchestrator
- Operates directly on PostgreSQL (no memory layer needed)
- EMA calculations are pure Python/SQL, no AI required

**Example workflow:**
```bash
# Run refresh script manually
python src/ta_lab2/scripts/emas/refresh_cmc_ema_multi_tf_from_bars.py --symbols BTC --date 2024-01-01
```

---

## Dependency Boundaries

### What Track 1 Provides to Others
- **To Track 2:** Context injection for tasks (`get_context()`)
- **To Track 3:** Query for past execution patterns

### What Track 2 Provides to Others
- **To Track 1:** Content to memorize (task results, decisions)
- **To Track 3:** Automated script execution

### What Track 3 Provides to Others
- **To Track 1:** Domain knowledge for memory (EMA formulas, SQL schemas)
- **To Track 2:** Tasks to automate (refresh scripts, analyses)

---

## Integration Phase (Phase 9)

When all three tracks converge, the system operates as:

### End-to-End Flow

1. **User submits task:** "Refresh EMAs for BTC and ETH"

2. **Orchestrator queries memory:**
   ```python
   context = memory.search("EMA refresh previous executions")
   task_with_context = Task(
       type=TaskType.SQL_DB_WORK,
       prompt="Refresh EMAs for BTC, ETH",
       context={"memory": context}
   )
   ```

3. **Orchestrator routes task:** Selects platform (Claude Code for DB work)

4. **Platform executes:** Runs `refresh_ema_daily.py` script

5. **Result stored in memory:**
   ```python
   memory.add(
       content=f"EMA refresh completed for BTC, ETH on {date}",
       metadata={"task_type": "ema_refresh", "symbols": ["BTC", "ETH"]}
   )
   ```

6. **User queries:** "What EMAs did we calculate today?"
   - Memory search returns recent executions
   - Orchestrator formats response

### Integration Tests

**File:** `tests/integration/test_end_to_end.py`

```python
def test_ema_refresh_with_memory():
    """End-to-end: User request → Memory context → Orchestration → ta_lab2 execution → Memory storage"""

    # Setup
    memory = MemoryManager()
    orch = Orchestrator()

    # User request
    task = Task(
        type=TaskType.SQL_DB_WORK,
        prompt="Refresh EMAs for BTC"
    )

    # Execute with memory context
    context = memory.search("previous EMA refreshes for BTC")
    task.context["memory"] = context
    result = orch.execute(task)

    # Store result
    memory.add(result.output, metadata={"task": "ema_refresh"})

    # Verify
    assert result.success
    history = memory.search("EMA refresh BTC")
    assert len(history) > 0
```

---

## Testing Strategy

### Unit Tests (Per Track)
- **Track 1:** Test memory add/search with stub orchestrator
- **Track 2:** Test routing/execution with stub memory
- **Track 3:** Test EMA calculations with in-memory DataFrames

### Integration Tests (Cross-Track)
- **Track 1 + 2:** Memory provides context to orchestrator
- **Track 2 + 3:** Orchestrator executes ta_lab2 scripts
- **Track 1 + 3:** Memory stores ta_lab2 execution history

### End-to-End Tests (All Tracks)
- Full flow: User request → Memory → Orchestrator → ta_lab2 → Memory

---

## Phase Roadmap Integration

### Phase 1 (Complete)
- **Outputs:** Orchestrator foundation, quota tracking, validation
- **Enables:** Track 2 can start parallel development

### Phase 2-3 (Memory)
- **Outputs:** Memory infrastructure (Mem0 + Memory Bank)
- **Enables:** Track 1 can start parallel development

### Phase 4-6 (Time Model)
- **Outputs:** dim_timeframe, dim_sessions tables
- **Enables:** Track 3 can reference time models

### Phase 7-8 (Features)
- **Outputs:** EMA calculations, bar processing
- **Enables:** Track 3 core functionality complete

### Phase 9 (Integration)
- **Convergence:** All tracks integrate
- **Tests:** End-to-end validation
- **Deliverable:** Automated quant workflow with memory

### Phase 10 (Optimization)
- **Polish:** Performance tuning, UX improvements
- **Scale:** Batch operations, parallel execution

---

## Stub Implementation Guide

### Creating a Stub

1. **Identify interface:** What methods does the real implementation expose?
2. **Create stub class:** Inherit from interface, implement minimal logic
3. **Return realistic data:** Stubs should mimic real behavior (not just `return None`)
4. **Document limitations:** Comments explain what's stubbed

### Example: Creating OrchestratorStub

```python
# tests/stubs/orchestrator_stub.py

from src.ta_lab2.tools.ai_orchestrator.core import Orchestrator, Task, Result, Platform

class OrchestratorStub(Orchestrator):
    """
    Stub orchestrator for testing memory without real AI calls.

    Limitations:
    - Always returns success=True
    - Output is mock data, not real AI response
    - No quota tracking
    """

    def __init__(self):
        # Don't call super().__init__() to avoid initializing real adapters
        self.calls = []  # Track calls for assertions

    def execute(self, task: Task, pre_flight: bool = True) -> Result:
        self.calls.append(task)
        return Result(
            task=task,
            platform=Platform.CLAUDE_CODE,
            output=f"[STUB] Executed: {task.prompt}",
            success=True,
        )
```

---

## Common Patterns

### Using Stubs in Tests

```python
# Track 1 test using stub orchestrator
def test_memory_with_orchestrator_stub():
    memory = MemoryManager()
    orch_stub = OrchestratorStub()

    # Memory calls orchestrator (which is stubbed)
    result = orch_stub.execute(Task(type=TaskType.CODE_GENERATION, prompt="test"))
    memory.add(result.output, metadata={"source": "orchestrator"})

    # Verify memory stored the stub output
    results = memory.search("STUB")
    assert len(results) > 0
```

### Switching to Real Implementation

```python
# In integration tests, replace stub with real implementation
def test_memory_with_real_orchestrator():
    memory = MemoryManager()
    orch = Orchestrator()  # Real orchestrator

    # Now using real AI platforms
    result = orch.execute(Task(type=TaskType.CODE_GENERATION, prompt="test"))
    memory.add(result.output, metadata={"source": "orchestrator"})
```

---

## Summary

| Track | Independence | Stub Available | Integration Phase |
|-------|-------------|----------------|-------------------|
| Memory | Full | OrchestratorStub, DBStub | Phase 9 |
| Orchestrator | Full | MemoryStub | Phase 9 |
| ta_lab2 | Full | MemoryStub, OrchestratorStub | Phase 9 |

**Key Insight:** Phase 1 completion enables all three tracks to develop in parallel without blocking. Integration in Phase 9 brings them together for end-to-end automation.

---

*Document version: 1.0*
*Last updated: 2026-01-26*
