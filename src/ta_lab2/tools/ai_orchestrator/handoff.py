"""AI-to-AI handoff mechanism for task chains."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Task, Result

from .core import Task, Result, TaskType


@dataclass
class HandoffContext:
    """
    Context passed between tasks in a chain.

    Per CONTEXT.md: Hybrid (pointer + summary) - Task A includes small summary
    inline for quick reference, full context stored in memory with pointer.
    """

    memory_id: str  # Pointer to full context in memory
    summary: str  # Brief inline summary for quick reference
    parent_task_id: str  # Track genealogy (Task A -> B -> C)
    chain_id: str  # Workflow-level ID for cost attribution
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_context_dict(self) -> dict:
        """Convert to dict for task.context field."""
        return {
            "handoff_memory_id": self.memory_id,
            "handoff_summary": self.summary,
            "parent_task_id": self.parent_task_id,
            "chain_id": self.chain_id,
        }


@dataclass
class TaskChain:
    """
    Tracks a workflow's task genealogy.

    Per CONTEXT.md: Explicit chain tracking for debugging, visualization,
    and cost attribution.
    """

    chain_id: str
    tasks: List[str] = field(default_factory=list)  # task_ids in order
    total_cost: float = 0.0
    total_tokens: int = 0
    root_task_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def add_task(self, task_id: str, cost: float = 0.0, tokens: int = 0):
        """Add a task to this chain."""
        self.tasks.append(task_id)
        self.total_cost += cost
        self.total_tokens += tokens
        if self.root_task_id is None:
            self.root_task_id = task_id

    @property
    def depth(self) -> int:
        """Return chain depth (number of tasks)."""
        return len(self.tasks)


class ChainTracker:
    """
    Manages task chains for workflow cost attribution.

    Maintains in-memory tracking of active chains. For persistence,
    use CostTracker (Plan 04) which writes to SQLite.
    """

    def __init__(self):
        self._chains: Dict[str, TaskChain] = {}

    def get_or_create_chain(self, chain_id: str) -> TaskChain:
        """Get existing chain or create new one."""
        if chain_id not in self._chains:
            self._chains[chain_id] = TaskChain(chain_id=chain_id)
        return self._chains[chain_id]

    def record_task(
        self, chain_id: str, task_id: str, cost: float = 0.0, tokens: int = 0
    ):
        """Record a task in a chain."""
        chain = self.get_or_create_chain(chain_id)
        chain.add_task(task_id, cost, tokens)

    def get_chain(self, chain_id: str) -> Optional[TaskChain]:
        """Get chain by ID, or None if not found."""
        return self._chains.get(chain_id)

    def get_chain_cost(self, chain_id: str) -> float:
        """Get total cost for a workflow chain."""
        chain = self._chains.get(chain_id)
        return chain.total_cost if chain else 0.0

    def get_all_chains(self) -> Dict[str, TaskChain]:
        """Get all tracked chains."""
        return dict(self._chains)


async def spawn_child_task(
    parent_result: Result,
    child_prompt: str,
    child_type: TaskType = None,
    chain_id: Optional[str] = None,
    max_summary_length: int = 500,
) -> tuple[Task, HandoffContext]:
    """
    Create child task with context from parent.

    Per CONTEXT.md: Hybrid (pointer + summary) - stores full context in memory,
    passes pointer + brief summary to child task.

    Args:
        parent_result: Result from parent task
        child_prompt: Prompt for child task
        child_type: TaskType for child (defaults to parent type)
        chain_id: Optional chain ID (generated if not provided)
        max_summary_length: Max chars for inline summary (default 500)

    Returns:
        Tuple of (child_task, handoff_context)

    Raises:
        RuntimeError: If memory storage fails
    """
    # Import here to avoid circular dependency
    from .memory.update import add_memory

    # Generate IDs
    parent_task_id = parent_result.task.task_id or "unknown"
    memory_id = f"handoff_{parent_task_id}_{uuid.uuid4().hex[:8]}"
    effective_chain_id = (
        chain_id or parent_result.task.metadata.get("chain_id") or uuid.uuid4().hex
    )

    # Store full context in memory
    full_context = f"Parent task output:\n{parent_result.output}"
    try:
        add_memory(
            memory_id=memory_id,
            content=full_context,
            metadata={
                "type": "handoff",
                "parent_task_id": parent_task_id,
                "chain_id": effective_chain_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as e:
        raise RuntimeError(f"Failed to store handoff context in memory: {e}")

    # Create brief summary for inline reference
    output_text = parent_result.output
    if len(output_text) > max_summary_length:
        summary = output_text[:max_summary_length] + "..."
    else:
        summary = output_text

    # Create handoff context
    handoff = HandoffContext(
        memory_id=memory_id,
        summary=summary,
        parent_task_id=parent_task_id,
        chain_id=effective_chain_id,
    )

    # Create child task with context pointer
    child_task = Task(
        type=child_type or parent_result.task.type,
        prompt=child_prompt,
        context=handoff.to_context_dict(),
        platform_hint=parent_result.task.platform_hint,  # Preserve hint
        metadata={"chain_id": effective_chain_id},
    )

    return child_task, handoff


async def load_handoff_context(task: Task) -> str:
    """
    Load full context from memory for a child task.

    Per CONTEXT.md: Fail Task B immediately if context can't be retrieved.

    Args:
        task: Child task with handoff context

    Returns:
        Full context string from memory

    Raises:
        RuntimeError: If memory lookup fails (per CONTEXT.md decision)
    """
    from .memory.query import get_memory_by_id

    memory_id = task.context.get("handoff_memory_id")
    if not memory_id:
        raise RuntimeError("Task has no handoff_memory_id in context")

    result = get_memory_by_id(memory_id)
    if result is None:
        # Per CONTEXT.md: Fail Task B immediately if memory lookup fails
        raise RuntimeError(f"Handoff context not found in memory: {memory_id}")

    return (
        result.content
        if hasattr(result, "content")
        else result.get("content", "")
        if isinstance(result, dict)
        else str(result)
    )


def has_handoff_context(task: Task) -> bool:
    """Check if task has handoff context from parent."""
    return "handoff_memory_id" in task.context
