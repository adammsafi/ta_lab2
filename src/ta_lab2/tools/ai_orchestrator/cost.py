"""Cost tracking for orchestrator tasks with SQLite persistence."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Task, Result


# Model pricing (USD per 1M tokens)
# Per CONTEXT.md: Track at all levels (per-task, per-platform, per-chain, session)
PRICING = {
    # Gemini models (free tier uses request count, not tokens)
    "gemini_cli": {"input": 0.0, "output": 0.0},  # Free tier
    "gemini-2.0-flash-exp": {"input": 0.0, "output": 0.0},  # Free tier
    "gemini_api": {"input": 0.075, "output": 0.30},  # Paid API

    # OpenAI models
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},

    # Claude models
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-opus": {"input": 15.00, "output": 75.00},
    "claude-3-haiku": {"input": 0.25, "output": 1.25},

    # Default/unknown
    "unknown": {"input": 0.0, "output": 0.0},
}


@dataclass
class CostRecord:
    """Single cost record for persistence."""
    task_id: str
    platform: str
    chain_id: Optional[str]
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: datetime


class CostTracker:
    """
    Track and persist task costs to SQLite.

    Per CONTEXT.md decisions:
    - Granularity: All levels (per-task, per-platform, per-chain, session)
    - Persistence: Database table (SQLite for queries/analytics)
    - Budget limits: Soft warnings only (user stays in control)
    """

    def __init__(self, db_path: str = ".memory/cost_tracking.db"):
        """
        Initialize cost tracker.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._ensure_dir()
        self._init_db()

    def _ensure_dir(self):
        """Ensure parent directory exists."""
        path = Path(self.db_path)
        path.parent.mkdir(parents=True, exist_ok=True)

    def _init_db(self):
        """Initialize database schema."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cost_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                chain_id TEXT,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cost_usd REAL NOT NULL,
                timestamp TEXT NOT NULL,
                UNIQUE(task_id)
            )
        """)
        # Indexes for common queries
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chain ON cost_records(chain_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_platform ON cost_records(platform)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON cost_records(timestamp)")
        conn.commit()
        conn.close()

    def record(
        self,
        task: Task,
        result: Result,
        chain_id: Optional[str] = None
    ):
        """
        Record cost from a completed task.

        Args:
            task: The executed task
            result: Result from execution
            chain_id: Optional chain ID (overrides task metadata)
        """
        # Extract model and token info from result
        model = result.metadata.get("model", "unknown")
        pricing = PRICING.get(model, PRICING["unknown"])

        input_tokens = result.metadata.get("input_tokens", 0)
        output_tokens = result.metadata.get("output_tokens", result.tokens_used)

        # Calculate cost
        cost = (
            input_tokens * pricing["input"] / 1_000_000 +
            output_tokens * pricing["output"] / 1_000_000
        )

        # Create record
        record = CostRecord(
            task_id=task.task_id or f"unknown_{datetime.now().timestamp()}",
            platform=result.platform.value,
            chain_id=chain_id or task.metadata.get("chain_id"),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            timestamp=datetime.now(timezone.utc)
        )

        self._persist(record)

    def _persist(self, record: CostRecord):
        """Persist a cost record to database."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT OR REPLACE INTO cost_records
            (task_id, platform, chain_id, model, input_tokens, output_tokens, cost_usd, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.task_id,
            record.platform,
            record.chain_id,
            record.model,
            record.input_tokens,
            record.output_tokens,
            record.cost_usd,
            record.timestamp.isoformat()
        ))
        conn.commit()
        conn.close()

    def get_task_cost(self, task_id: str) -> Optional[float]:
        """Get cost for a specific task."""
        conn = sqlite3.connect(self.db_path)
        result = conn.execute(
            "SELECT cost_usd FROM cost_records WHERE task_id = ?",
            (task_id,)
        ).fetchone()
        conn.close()
        return result[0] if result else None

    def get_chain_cost(self, chain_id: str) -> float:
        """Get total cost for a workflow chain."""
        conn = sqlite3.connect(self.db_path)
        result = conn.execute(
            "SELECT SUM(cost_usd) FROM cost_records WHERE chain_id = ?",
            (chain_id,)
        ).fetchone()
        conn.close()
        return result[0] or 0.0

    def get_platform_totals(self, since: Optional[datetime] = None) -> Dict[str, float]:
        """
        Get total costs by platform.

        Args:
            since: Optional datetime to filter records (default: all time)

        Returns:
            Dict of platform -> total cost USD
        """
        conn = sqlite3.connect(self.db_path)
        if since:
            rows = conn.execute(
                """SELECT platform, SUM(cost_usd) as total
                   FROM cost_records
                   WHERE timestamp >= ?
                   GROUP BY platform""",
                (since.isoformat(),)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT platform, SUM(cost_usd) as total
                   FROM cost_records
                   GROUP BY platform"""
            ).fetchall()
        conn.close()
        return {row[0]: row[1] for row in rows}

    def get_session_summary(self, date: Optional[datetime] = None) -> Dict:
        """
        Get cost summary for a session (default: today).

        Returns:
            Dict with per-platform stats and totals
        """
        target_date = date or datetime.now(timezone.utc)
        date_str = target_date.strftime("%Y-%m-%d")

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("""
            SELECT platform,
                   COUNT(*) as tasks,
                   SUM(cost_usd) as total_cost,
                   SUM(input_tokens + output_tokens) as total_tokens
            FROM cost_records
            WHERE date(timestamp) = date(?)
            GROUP BY platform
        """, (date_str,)).fetchall()
        conn.close()

        summary = {
            "date": date_str,
            "by_platform": {},
            "total_cost": 0.0,
            "total_tasks": 0,
            "total_tokens": 0,
        }

        for row in rows:
            platform, tasks, cost, tokens = row
            summary["by_platform"][platform] = {
                "tasks": tasks,
                "cost": cost or 0.0,
                "tokens": tokens or 0,
            }
            summary["total_cost"] += cost or 0.0
            summary["total_tasks"] += tasks
            summary["total_tokens"] += tokens or 0

        return summary

    def get_chain_tasks(self, chain_id: str) -> List[CostRecord]:
        """Get all task records for a chain."""
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute("""
            SELECT task_id, platform, chain_id, model,
                   input_tokens, output_tokens, cost_usd, timestamp
            FROM cost_records
            WHERE chain_id = ?
            ORDER BY timestamp
        """, (chain_id,)).fetchall()
        conn.close()

        return [
            CostRecord(
                task_id=row[0],
                platform=row[1],
                chain_id=row[2],
                model=row[3],
                input_tokens=row[4],
                output_tokens=row[5],
                cost_usd=row[6],
                timestamp=datetime.fromisoformat(row[7])
            )
            for row in rows
        ]

    def estimate_cost(self, prompt: str, model: str = "gpt-4o-mini") -> float:
        """
        Estimate cost for a prompt before execution.

        Per CONTEXT.md: Estimate for expensive only (>10k tokens).
        This method can be called to check if estimation is needed.

        Args:
            prompt: Prompt text
            model: Model to estimate for

        Returns:
            Estimated cost in USD
        """
        # Rough token estimate: ~4 chars per token
        estimated_input_tokens = len(prompt) // 4
        # Assume output ~= input for estimation
        estimated_output_tokens = estimated_input_tokens

        pricing = PRICING.get(model, PRICING["unknown"])
        return (
            estimated_input_tokens * pricing["input"] / 1_000_000 +
            estimated_output_tokens * pricing["output"] / 1_000_000
        )

    def should_warn_cost(self, prompt: str, threshold_tokens: int = 10000) -> bool:
        """
        Check if prompt is large enough to warrant cost warning.

        Per CONTEXT.md: Estimate cost when prompt > threshold (e.g., 10k tokens).

        Args:
            prompt: Prompt text
            threshold_tokens: Token threshold for warning (default 10k)

        Returns:
            True if cost estimation/warning recommended
        """
        estimated_tokens = len(prompt) // 4
        return estimated_tokens > threshold_tokens

    def display_summary(self, date: Optional[datetime] = None) -> str:
        """Format cost summary for CLI display."""
        summary = self.get_session_summary(date)

        lines = [
            f"Cost Summary for {summary['date']}",
            "=" * 50,
            f"\nTotal: ${summary['total_cost']:.4f} ({summary['total_tasks']} tasks, {summary['total_tokens']:,} tokens)",
            "\nBy Platform:",
        ]

        for platform, stats in summary["by_platform"].items():
            lines.append(
                f"  {platform}: ${stats['cost']:.4f} "
                f"({stats['tasks']} tasks, {stats['tokens']:,} tokens)"
            )

        return "\n".join(lines)
