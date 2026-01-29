# Phase 5: Orchestrator Coordination - Research

**Researched:** 2026-01-29
**Domain:** Task routing, parallel execution, AI-to-AI handoffs, cost tracking, and CLI orchestration
**Confidence:** HIGH

## Summary

Phase 5 builds the coordination layer that connects the async adapters from Phase 4 into an intelligent orchestration system. The research reveals that Python's asyncio TaskGroup (Python 3.11+) provides the optimal foundation for parallel execution with proper error handling. Cost tracking is well-supported by existing libraries (tokencost, LiteLLM) but the hybrid approach (estimate expensive, track actual) decided in CONTEXT.md can be implemented with simple per-model pricing tables.

Key findings:
- **asyncio.TaskGroup** is the recommended approach for parallel task execution (fail-fast semantics, automatic cancellation, ExceptionGroup for multi-error handling)
- **Semaphores** should limit concurrent requests to prevent quota exhaustion and rate limit errors
- **Typer** is the modern CLI framework but existing ta_lab2 CLI uses argparse - should extend existing patterns for consistency
- **Handoff pattern**: Task A writes memory, returns context pointer (memory_id + brief summary), Task B retrieves via existing ChromaDB client
- **Cost tracking**: Database table with per-task, per-platform, and per-chain aggregation as decided in CONTEXT.md

**Primary recommendation:** Build an AsyncOrchestrator class with TaskGroup-based parallel execution, semaphore-controlled concurrency, and memory-backed handoffs using existing ChromaDB infrastructure.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncio | stdlib (3.11+) | TaskGroup, Semaphore, task management | Python standard library with structured concurrency |
| sqlite3 | stdlib | Cost tracking persistence | Lightweight, file-based, already decided in CONTEXT.md |
| argparse | stdlib | CLI framework | Already in use by ta_lab2 CLI, extend existing patterns |
| rich | latest | CLI output formatting, progress bars | Already a Typer dependency, can use standalone |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| tiktoken | latest | Token estimation | For cost estimation threshold (>10k tokens) |
| tenacity | latest | Retry with backoff | Already in use by Phase 4 adapters |
| dataclasses | stdlib | Data structures | Task, Result, CostRecord, Handoff objects |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| argparse | Typer | Typer is more modern but ta_lab2 already uses argparse - consistency wins |
| SQLite | PostgreSQL | PostgreSQL better for analytics but SQLite simpler for single-user orchestrator |
| Custom cost tracking | tokencost library | Custom gives full control over hybrid pricing (free tier + paid) |

**Installation:**
```bash
# Most dependencies already installed from Phase 4
pip install tiktoken rich
# SQLite is stdlib, no install needed
```

## Architecture Patterns

### Recommended Project Structure
```
src/ta_lab2/tools/ai_orchestrator/
+-- adapters.py          # Async adapters (from Phase 4) - EXISTING
+-- core.py              # Task/Result/TaskStatus (from Phase 4) - EXISTING
+-- routing.py           # TaskRouter (existing) - EXTEND with cost optimization
+-- quota.py             # QuotaTracker (from Phase 1) - EXISTING
+-- retry.py             # Retry decorators (from Phase 4) - EXISTING
+-- streaming.py         # StreamingResult (from Phase 4) - EXISTING
+-- memory/              # Memory infrastructure (from Phase 2-3) - EXISTING
|
+-- execution.py         # NEW: AsyncOrchestrator, parallel execution engine
+-- handoff.py           # NEW: TaskChain, HandoffContext, spawn_child_task
+-- cost.py              # NEW: CostTracker, CostRecord, cost persistence
+-- cli.py               # NEW: Orchestrator CLI commands
```

### Pattern 1: AsyncOrchestrator with TaskGroup
**What:** Central orchestrator using TaskGroup for parallel execution with fail-independent semantics
**When to use:** When executing batches of independent tasks across platforms
**Example:**
```python
# Source: Python asyncio docs + CONTEXT.md decisions
from asyncio import TaskGroup, Semaphore
from typing import List

class AsyncOrchestrator:
    def __init__(self, adapters: dict, router: TaskRouter, quota: QuotaTracker, max_concurrent: int = 10):
        self.adapters = adapters
        self.router = router
        self.quota = quota
        self.semaphore = Semaphore(max_concurrent)
        self.cost_tracker = CostTracker()

    async def execute_parallel(self, tasks: List[Task]) -> List[Result]:
        """Execute tasks in parallel with fail-independent semantics."""
        results: dict[str, Result] = {}
        errors: dict[str, Exception] = {}

        async def execute_one(task: Task, task_idx: int):
            async with self.semaphore:  # Limit concurrency
                try:
                    platform = self.router.route(task, self.quota)
                    adapter = self.adapters[platform]
                    async with adapter:
                        task_id = await adapter.submit_task(task)
                        result = await adapter.get_result(task_id)
                        results[task_idx] = result
                        self.cost_tracker.record(task, result)
                except Exception as e:
                    errors[task_idx] = e

        # Fail-independent: collect all results, don't cancel on first error
        try:
            async with TaskGroup() as tg:
                for idx, task in enumerate(tasks):
                    tg.create_task(execute_one(task, idx))
        except ExceptionGroup as eg:
            # TaskGroup bundles all exceptions - already collected in errors dict
            pass

        # Build ordered results list
        return [results.get(i) or self._error_result(tasks[i], errors.get(i))
                for i in range(len(tasks))]
```

### Pattern 2: Handoff with Memory Pointer
**What:** Task A writes to memory, returns HandoffContext with memory_id + summary, Task B uses pointer
**When to use:** For sequential task chains where context must flow between tasks
**Example:**
```python
# Source: CONTEXT.md decision on hybrid (pointer + summary) handoff
from dataclasses import dataclass
from typing import Optional
import uuid

@dataclass
class HandoffContext:
    """Context passed between tasks in a chain."""
    memory_id: str              # Pointer to full context in ChromaDB
    summary: str                # Brief inline summary for quick reference
    parent_task_id: str         # Track genealogy (Task A -> B -> C)
    chain_id: str               # Workflow-level ID for cost attribution
    created_at: datetime

async def spawn_child_task(
    parent_result: Result,
    child_prompt: str,
    chain_id: Optional[str] = None,
) -> tuple[Task, HandoffContext]:
    """Create child task with context from parent."""
    from .memory.update import add_memory
    from .memory.query import get_memory_by_id

    # Generate memory ID for full context
    memory_id = f"handoff_{parent_result.task.task_id}_{uuid.uuid4().hex[:8]}"

    # Store full context in memory
    add_memory(
        memory_id=memory_id,
        content=f"Parent task output:\n{parent_result.output}",
        metadata={
            "type": "handoff",
            "parent_task_id": parent_result.task.task_id,
            "chain_id": chain_id or uuid.uuid4().hex,
        }
    )

    # Create brief summary for inline reference
    summary = parent_result.output[:500] + "..." if len(parent_result.output) > 500 else parent_result.output

    handoff = HandoffContext(
        memory_id=memory_id,
        summary=summary,
        parent_task_id=parent_result.task.task_id,
        chain_id=chain_id or uuid.uuid4().hex,
        created_at=datetime.now(timezone.utc)
    )

    # Create child task with context pointer
    child_task = Task(
        type=parent_result.task.type,  # or specify new type
        prompt=child_prompt,
        context={
            "handoff_memory_id": memory_id,
            "handoff_summary": summary,
            "parent_task_id": parent_result.task.task_id,
        },
        metadata={"chain_id": handoff.chain_id}
    )

    return child_task, handoff


async def load_handoff_context(task: Task) -> Optional[str]:
    """Load full context from memory for a child task."""
    from .memory.query import get_memory_by_id

    memory_id = task.context.get("handoff_memory_id")
    if not memory_id:
        return None

    result = get_memory_by_id(memory_id)
    if result is None:
        # CONTEXT.md decision: fail Task B if memory lookup fails
        raise RuntimeError(f"Handoff context not found: {memory_id}")

    return result.content
```

### Pattern 3: Cost-Optimized Router
**What:** Routes tasks following Gemini CLI free tier -> subscriptions -> paid APIs priority
**When to use:** For all task routing (default behavior per ROADMAP success criteria #1)
**Example:**
```python
# Source: CONTEXT.md routing decisions + existing routing.py
# Cost tiers in strict priority order
COST_TIERS = [
    # Tier 1: Gemini CLI free tier (1500 req/day)
    {"platform": "gemini", "quota_key": "gemini_cli", "cost_per_req": 0.0, "priority": 1},

    # Tier 2: Subscription-included (already paid)
    {"platform": "claude_code", "quota_key": "claude_code", "cost_per_req": 0.0, "priority": 2},
    {"platform": "chatgpt", "quota_key": "chatgpt_plus", "cost_per_req": 0.0, "priority": 2},

    # Tier 3: Paid APIs (last resort)
    {"platform": "gemini", "quota_key": "gemini_api", "cost_per_req": 0.0001, "priority": 3},
    {"platform": "openai", "quota_key": "openai_api", "cost_per_req": 0.002, "priority": 3},
]

def route_cost_optimized(task: Task, quota: QuotaTracker) -> Platform:
    """Route to cheapest available platform respecting hints."""
    # Honor platform hint if specified and available (advisory, fallback allowed)
    if task.platform_hint:
        if quota.can_use(task.platform_hint.value):
            return task.platform_hint

    # Otherwise, iterate through cost tiers
    for tier in sorted(COST_TIERS, key=lambda t: t["priority"]):
        platform_enum = Platform(tier["platform"])
        if quota.can_use(tier["quota_key"]):
            return platform_enum

    # All quotas exhausted - fall back to Claude Code (subscription)
    return Platform.CLAUDE_CODE
```

### Pattern 4: Adaptive Concurrency with Semaphore
**What:** Dynamic concurrency limits based on available quota and rate limits
**When to use:** For parallel execution batches to prevent quota exhaustion
**Example:**
```python
# Source: asyncio docs + WebSearch on semaphore patterns
from asyncio import Semaphore

class AdaptiveConcurrencyManager:
    """Manages concurrency limits based on quota and rate limits."""

    def __init__(self, quota: QuotaTracker, base_limit: int = 10):
        self.quota = quota
        self.base_limit = base_limit
        self._semaphore: Optional[Semaphore] = None

    def get_semaphore(self, platform: Platform) -> Semaphore:
        """Get semaphore with limit adjusted for platform quota."""
        # Get remaining quota
        status = self.quota.get_status()
        platform_key = self.quota._platform_to_quota_key(platform.value)

        available = status.get(platform_key, {}).get("available", "unlimited")

        if available == "unlimited":
            limit = self.base_limit
        else:
            # Don't exceed 50% of remaining quota in one batch
            limit = min(self.base_limit, max(1, available // 2))

        return Semaphore(limit)
```

### Pattern 5: Task Chain Tracking
**What:** Maintain task genealogy (Task A -> B -> C) for debugging and cost attribution
**When to use:** For all handoff scenarios to enable workflow-level cost reporting
**Example:**
```python
# Source: CONTEXT.md decision on explicit chain tracking
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class TaskChain:
    """Tracks a workflow's task genealogy."""
    chain_id: str
    tasks: List[str] = field(default_factory=list)  # task_ids in order
    total_cost: float = 0.0
    total_tokens: int = 0
    root_task_id: Optional[str] = None

    def add_task(self, task_id: str, cost: float, tokens: int):
        self.tasks.append(task_id)
        self.total_cost += cost
        self.total_tokens += tokens
        if self.root_task_id is None:
            self.root_task_id = task_id

class ChainTracker:
    """Manages task chains for workflow cost attribution."""

    def __init__(self):
        self._chains: dict[str, TaskChain] = {}

    def get_or_create_chain(self, chain_id: str) -> TaskChain:
        if chain_id not in self._chains:
            self._chains[chain_id] = TaskChain(chain_id=chain_id)
        return self._chains[chain_id]

    def record_task(self, chain_id: str, task_id: str, cost: float, tokens: int):
        chain = self.get_or_create_chain(chain_id)
        chain.add_task(task_id, cost, tokens)

    def get_chain_cost(self, chain_id: str) -> float:
        """Get total cost for a workflow chain."""
        return self._chains.get(chain_id, TaskChain(chain_id)).total_cost
```

### Anti-Patterns to Avoid
- **Using gather() for fail-fast:** Use TaskGroup instead - gather doesn't cancel remaining tasks on first error
- **Unlimited concurrency:** Always use Semaphore to limit concurrent requests - prevents quota exhaustion and rate limit errors
- **Storing full context in handoff:** Use pointer + summary pattern - full context can be huge, memory lookup is fast
- **Synchronous cost tracking:** Record costs asynchronously or batch writes - don't block task execution
- **Hard-coding cost thresholds:** Make token threshold for cost estimation configurable (default 10k per CONTEXT.md)

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Token counting | Character-based estimation | tiktoken library | Accurate model-specific tokenization, handles edge cases |
| Retry logic | While loops with sleep | tenacity decorators (already in retry.py) | Exponential backoff, jitter, max attempts, exception filtering |
| Memory storage | New storage layer | ChromaDB client (already in memory/) | Already has 3,763 memories, embedding infrastructure |
| Async context managers | Manual resource tracking | async with protocol (already in adapters) | Cleanup guarantees, exception safety |
| CLI output formatting | print() with ANSI codes | rich library | Tables, progress bars, error formatting |

**Key insight:** Phase 4 already built the async adapter infrastructure. Phase 5 should COMPOSE these adapters with routing and execution logic, not rebuild them. The memory infrastructure from Phase 2-3 provides the handoff storage layer.

## Common Pitfalls

### Pitfall 1: TaskGroup Cancels All Tasks on Error
**What goes wrong:** A single failed task cancels the entire batch, losing partial results
**Why it happens:** TaskGroup's default behavior is fail-fast (structured concurrency)
**How to avoid:** For fail-independent semantics, catch exceptions inside each task wrapper and store errors separately
**Warning signs:** Parallel batches return empty results when one task fails
**Example:**
```python
# WRONG - fail-fast loses other results
async with TaskGroup() as tg:
    for task in tasks:
        tg.create_task(execute_task(task))  # First error cancels all

# RIGHT - fail-independent collects all results
results, errors = {}, {}
async def safe_execute(idx, task):
    try:
        results[idx] = await execute_task(task)
    except Exception as e:
        errors[idx] = e

async with TaskGroup() as tg:
    for idx, task in enumerate(tasks):
        tg.create_task(safe_execute(idx, task))
# ExceptionGroup is raised but results and errors are populated
```

### Pitfall 2: Memory Lookup Failure Handling
**What goes wrong:** Child task proceeds with missing context, produces garbage output
**Why it happens:** Silent failure on memory lookup, returning None instead of raising
**How to avoid:** Per CONTEXT.md decision, fail Task B immediately if memory lookup fails
**Warning signs:** Child tasks produce outputs unrelated to parent task
**Example:**
```python
# WRONG - silent failure
context = get_memory_by_id(memory_id)
if context is None:
    context = ""  # Proceed with empty context

# RIGHT - fail fast per CONTEXT.md decision
context = get_memory_by_id(memory_id)
if context is None:
    raise RuntimeError(f"Handoff context not found: {memory_id}. Task cannot proceed.")
```

### Pitfall 3: Quota Warning Timing
**What goes wrong:** User warned about quota exhaustion AFTER submitting large batch
**Why it happens:** Checking quota after batch submission, not before
**How to avoid:** Per CONTEXT.md, warn at 90% threshold BEFORE batch execution
**Warning signs:** Expensive API calls happen before user can intervene
**Example:**
```python
# WRONG - check after submission
await orchestrator.execute_parallel(tasks)
if quota.get_used_percent("gemini") > 90:
    print("Warning: quota at 90%")

# RIGHT - check before, let user decide
if quota.get_used_percent("gemini") > 90:
    print("Warning: Gemini quota at 90%. Continue with paid platforms? [y/N]")
    if not user_confirms():
        return
await orchestrator.execute_parallel(tasks)
```

### Pitfall 4: Cost Attribution Without Chain Tracking
**What goes wrong:** Can't determine total cost of a workflow (Task A -> B -> C)
**Why it happens:** Only tracking per-task costs, not linking related tasks
**How to avoid:** Use chain_id to group related tasks, sum costs at chain level
**Warning signs:** "data pipeline" workflow shows 3 separate costs instead of total
**Example:**
```python
# WRONG - isolated cost tracking
cost_tracker.record(task_a, result_a)  # $0.50
cost_tracker.record(task_b, result_b)  # $0.75
cost_tracker.record(task_c, result_c)  # $0.25
# No way to know these are part of same workflow

# RIGHT - chain-aware tracking
chain_id = "data_pipeline_20260129_abc123"
cost_tracker.record(task_a, result_a, chain_id=chain_id)
cost_tracker.record(task_b, result_b, chain_id=chain_id)
cost_tracker.record(task_c, result_c, chain_id=chain_id)
# cost_tracker.get_chain_cost(chain_id) returns $1.50
```

### Pitfall 5: CLI Blocking on Long Tasks
**What goes wrong:** CLI hangs with no feedback during long-running orchestration
**Why it happens:** No progress indication or streaming output
**How to avoid:** Use rich progress bars for batch execution, stream results as they complete
**Warning signs:** User thinks CLI is frozen, kills process, loses results
**Example:**
```python
# WRONG - silent execution
results = await orchestrator.execute_parallel(tasks)
print(results)

# RIGHT - progress feedback with rich
from rich.progress import Progress
with Progress() as progress:
    task_bar = progress.add_task("[cyan]Executing tasks...", total=len(tasks))
    async for result in orchestrator.execute_parallel_streaming(tasks):
        progress.update(task_bar, advance=1)
        print(f"Completed: {result.task.task_id}")
```

## Code Examples

Verified patterns from official sources and existing codebase:

### Cost Tracking with SQLite
```python
# Source: CONTEXT.md decision on database table for cost persistence
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

@dataclass
class CostRecord:
    """Single cost record for persistence."""
    task_id: str
    platform: str
    chain_id: Optional[str]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: datetime

class CostTracker:
    """Track and persist task costs to SQLite."""

    # Model pricing (USD per 1M tokens) - update as needed
    PRICING = {
        "gemini_cli": {"input": 0.0, "output": 0.0},  # Free tier
        "gemini_api": {"input": 0.075, "output": 0.30},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "claude-sonnet": {"input": 3.00, "output": 15.00},
    }

    def __init__(self, db_path: str = ".memory/cost_tracking.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cost_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                chain_id TEXT,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cost_usd REAL NOT NULL,
                timestamp TEXT NOT NULL,
                UNIQUE(task_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chain ON cost_records(chain_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_platform ON cost_records(platform)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON cost_records(timestamp)")
        conn.commit()
        conn.close()

    def record(self, task: Task, result: Result, chain_id: Optional[str] = None):
        """Record cost from a completed task."""
        # Get model from result metadata
        model = result.metadata.get("model", "unknown")
        pricing = self.PRICING.get(model, {"input": 0.0, "output": 0.0})

        input_tokens = result.metadata.get("input_tokens", 0)
        output_tokens = result.metadata.get("output_tokens", result.tokens_used)

        cost = (
            input_tokens * pricing["input"] / 1_000_000 +
            output_tokens * pricing["output"] / 1_000_000
        )

        record = CostRecord(
            task_id=task.task_id or "unknown",
            platform=result.platform.value,
            chain_id=chain_id or task.metadata.get("chain_id"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            timestamp=datetime.utcnow()
        )

        self._persist(record)

    def _persist(self, record: CostRecord):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT OR REPLACE INTO cost_records
            (task_id, platform, chain_id, input_tokens, output_tokens, cost_usd, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            record.task_id, record.platform, record.chain_id,
            record.input_tokens, record.output_tokens, record.cost_usd,
            record.timestamp.isoformat()
        ))
        conn.commit()
        conn.close()

    def get_chain_cost(self, chain_id: str) -> float:
        """Get total cost for a workflow chain."""
        conn = sqlite3.connect(self.db_path)
        result = conn.execute(
            "SELECT SUM(cost_usd) FROM cost_records WHERE chain_id = ?",
            (chain_id,)
        ).fetchone()
        conn.close()
        return result[0] or 0.0

    def get_session_summary(self) -> dict:
        """Get cost summary for current session."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("""
            SELECT platform, COUNT(*) as tasks, SUM(cost_usd) as total_cost,
                   SUM(input_tokens + output_tokens) as total_tokens
            FROM cost_records
            WHERE date(timestamp) = date('now')
            GROUP BY platform
        """).fetchall()
        conn.close()
        return {
            row[0]: {"tasks": row[1], "cost": row[2], "tokens": row[3]}
            for row in rows
        }
```

### CLI Commands with argparse
```python
# Source: Existing ta_lab2/cli.py patterns
import argparse
import asyncio
from typing import Optional

def build_orchestrator_parser() -> argparse.ArgumentParser:
    """Build CLI parser for orchestrator commands."""
    ap = argparse.ArgumentParser(
        prog="ta-lab2 orchestrator",
        description="AI Orchestrator CLI"
    )
    sub = ap.add_subparsers(dest="orch_cmd", required=True)

    # Submit single task
    p_submit = sub.add_parser("submit", help="Submit a task for execution")
    p_submit.add_argument("--prompt", "-p", required=True, help="Task prompt")
    p_submit.add_argument("--type", "-t", default="code_generation",
                         choices=["code_generation", "research", "data_analysis"])
    p_submit.add_argument("--platform", default=None,
                         help="Platform hint (claude_code, chatgpt, gemini)")
    p_submit.add_argument("--chain-id", default=None, help="Workflow chain ID")
    p_submit.set_defaults(func=cmd_submit)

    # Execute batch from file
    p_batch = sub.add_parser("batch", help="Execute batch of tasks from JSON file")
    p_batch.add_argument("--input", "-i", required=True, help="Input JSON file")
    p_batch.add_argument("--output", "-o", help="Output JSON file")
    p_batch.add_argument("--parallel", type=int, default=5, help="Max parallel tasks")
    p_batch.set_defaults(func=cmd_batch)

    # Show status
    p_status = sub.add_parser("status", help="Show orchestrator status")
    p_status.add_argument("--format", choices=["text", "json"], default="text")
    p_status.set_defaults(func=cmd_status)

    # Show costs
    p_costs = sub.add_parser("costs", help="Show cost summary")
    p_costs.add_argument("--chain-id", help="Filter by chain ID")
    p_costs.add_argument("--format", choices=["text", "json"], default="text")
    p_costs.set_defaults(func=cmd_costs)

    return ap


def cmd_submit(args: argparse.Namespace) -> int:
    """Submit a single task."""
    from .core import Task, TaskType, Platform
    from .execution import AsyncOrchestrator

    task = Task(
        type=TaskType(args.type),
        prompt=args.prompt,
        platform_hint=Platform(args.platform) if args.platform else None,
        metadata={"chain_id": args.chain_id} if args.chain_id else {}
    )

    async def run():
        async with AsyncOrchestrator() as orch:
            result = await orch.execute_single(task)
            print(f"Task ID: {result.task.task_id}")
            print(f"Platform: {result.platform.value}")
            print(f"Success: {result.success}")
            print(f"Cost: ${result.cost:.4f}")
            print(f"\nOutput:\n{result.output}")
            return 0 if result.success else 1

    return asyncio.run(run())
```

### Result Aggregation for Parallel Tasks
```python
# Source: ROADMAP success criteria #7 - result aggregation
from typing import List, Dict, Any
from dataclasses import dataclass

@dataclass
class AggregatedResult:
    """Combined results from parallel task execution."""
    results: List[Result]
    total_cost: float
    total_tokens: int
    total_duration: float
    success_count: int
    failure_count: int
    by_platform: Dict[str, List[Result]]

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.0

def aggregate_results(results: List[Result]) -> AggregatedResult:
    """Aggregate results from parallel execution."""
    by_platform: Dict[str, List[Result]] = {}

    for result in results:
        platform = result.platform.value
        if platform not in by_platform:
            by_platform[platform] = []
        by_platform[platform].append(result)

    return AggregatedResult(
        results=results,
        total_cost=sum(r.cost for r in results),
        total_tokens=sum(r.tokens_used for r in results),
        total_duration=sum(r.duration_seconds for r in results),
        success_count=sum(1 for r in results if r.success),
        failure_count=sum(1 for r in results if not r.success),
        by_platform=by_platform
    )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| asyncio.gather() for parallel | asyncio.TaskGroup | Python 3.11 (2022) | Structured concurrency, proper cancellation, ExceptionGroup |
| Manual retry loops | tenacity decorators | Library mature 2020+ | Already adopted in Phase 4 |
| Global concurrency limits | Semaphore per-platform | Always best practice | Prevents quota exhaustion |
| Print statements for CLI | rich library | 2020+ | Progress bars, tables, colored output |
| JSON file for costs | SQLite database | Decision in CONTEXT.md | Better queries, aggregation |

**Deprecated/outdated:**
- **asyncio.gather() for error handling:** Use TaskGroup for proper cancellation semantics
- **subprocess.run() in async:** Use asyncio.create_subprocess_exec() (already done in Phase 4)
- **Manual exception handling in gather:** Use ExceptionGroup with except* syntax (Python 3.11+)

## Open Questions

Things that couldn't be fully resolved:

1. **Fan-out Implementation Scope**
   - What we know: CONTEXT.md leaves fan-out (Task A spawns B and C) as Claude's discretion
   - What's unclear: Whether this is needed for Phase 5 MVP or can be deferred
   - Recommendation: Implement basic fan-out (spawn_children plural) if straightforward, otherwise defer to integration phase

2. **Exact Token Threshold for Cost Estimation**
   - What we know: CONTEXT.md says "estimate when prompt > threshold (e.g., 10k tokens)"
   - What's unclear: Optimal threshold value, whether to make it configurable
   - Recommendation: Start with 10k tokens as default, make configurable via config.py

3. **Fail-Fast vs Fail-Independent Selection**
   - What we know: CONTEXT.md leaves this as Claude's discretion
   - What's unclear: Best default for typical orchestrator use cases
   - Recommendation: Default to fail-independent (collect all results), add option for fail-fast when needed

4. **Concurrency Scaling Algorithm**
   - What we know: CONTEXT.md says adaptive based on quota and rate limits
   - What's unclear: Exact formula for calculating optimal concurrency
   - Recommendation: Start with min(base_limit, remaining_quota // 2), tune based on testing

## Sources

### Primary (HIGH confidence)
- [Python asyncio docs](https://docs.python.org/3/library/asyncio-task.html) - TaskGroup, Semaphore, gather (Python 3.14.2)
- [Existing ta_lab2 adapters.py](file://src/ta_lab2/tools/ai_orchestrator/adapters.py) - AsyncBasePlatformAdapter implementation
- [Existing ta_lab2 routing.py](file://src/ta_lab2/tools/ai_orchestrator/routing.py) - COST_PRIORITY tiers
- [Existing ta_lab2 cli.py](file://src/ta_lab2/cli.py) - argparse patterns to follow

### Secondary (MEDIUM confidence)
- [TaskGroup vs gather comparison](https://www.geeksforgeeks.org/python/python-taskgroups-with-asyncio/) - Error handling differences
- [Semaphore concurrency patterns](https://rednafi.com/python/limit-concurrency-with-semaphore/) - Rate limiting best practices
- [Rich library](https://rich.readthedocs.io/) - CLI output formatting
- [tokencost library](https://github.com/AgentOps-AI/tokencost) - Token counting patterns

### Tertiary (LOW confidence - verify before using)
- LangChain/LangGraph patterns for workflow orchestration - may be overkill for this use case
- External AI workflow orchestration tools (Prefect, Dagster) - too heavy for single-user orchestrator

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All based on stdlib or already-installed dependencies
- Architecture: HIGH - Patterns derived from existing Phase 4 code and Python official docs
- Pitfalls: HIGH - Based on CONTEXT.md decisions and asyncio documentation
- Code examples: HIGH - Adapted from existing codebase patterns

**Research date:** 2026-01-29
**Valid until:** 2026-02-28 (30 days - asyncio APIs stable, but validate against Python version updates)

**Key dependencies verified:**
- asyncio TaskGroup available in Python 3.11+ (project uses 3.12+)
- SQLite stdlib available
- rich already a dependency (via Typer)
- tiktoken available on PyPI

**Existing infrastructure to leverage:**
- AsyncBasePlatformAdapter, AsyncChatGPTAdapter, AsyncClaudeCodeAdapter, AsyncGeminiAdapter (adapters.py)
- QuotaTracker with check_and_reserve(), release_and_record() (quota.py)
- TaskRouter with ROUTING_MATRIX and COST_PRIORITY (routing.py)
- MemoryClient, add_memory(), search_memories(), get_memory_by_id() (memory/)
- StreamingResult, collect_stream() (streaming.py)
- retry_on_rate_limit() decorator (retry.py)
