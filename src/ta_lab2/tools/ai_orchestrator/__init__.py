"""
Multi-AI Orchestrator for ta_lab2

Routes tasks to Claude Code, ChatGPT, and Gemini based on:
- Task type and complexity
- Platform strengths
- Cost optimization (free tier first)
- Quota availability

Usage:
    from ta_lab2.tools.ai_orchestrator import Orchestrator

    orch = Orchestrator()
    result = orch.execute(Task(type="code_generation", prompt="Add tests"))
"""

from .core import Orchestrator, Task, TaskType, Platform
from .adapters import ClaudeCodeAdapter, ChatGPTAdapter, GeminiAdapter
from .routing import TaskRouter
from .quota import QuotaTracker, QuotaLimit, QuotaAlert
from .persistence import QuotaPersistence, load_quota_state, save_quota_state

__all__ = [
    "Orchestrator",
    "Task",
    "TaskType",
    "Platform",
    "ClaudeCodeAdapter",
    "ChatGPTAdapter",
    "GeminiAdapter",
    "TaskRouter",
    "QuotaTracker",
    "QuotaLimit",
    "QuotaAlert",
    "QuotaPersistence",
    "load_quota_state",
    "save_quota_state",
]
