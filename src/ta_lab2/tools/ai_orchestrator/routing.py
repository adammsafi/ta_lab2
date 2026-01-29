"""Task routing logic - maps task types to optimal AI platforms."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Task, Platform
    from .quota import QuotaTracker
    from .validation import AdapterValidator

from .core import TaskType, Platform as Plat


# Routing matrix: task type -> prioritized platform list
ROUTING_MATRIX = {
    TaskType.CODE_GENERATION: [Plat.CLAUDE_CODE, Plat.CHATGPT, Plat.GEMINI],
    TaskType.REFACTORING: [Plat.CLAUDE_CODE, Plat.GEMINI, Plat.CHATGPT],
    TaskType.RESEARCH: [Plat.CHATGPT, Plat.GEMINI, Plat.CLAUDE_CODE],
    TaskType.DATA_ANALYSIS: [Plat.GEMINI, Plat.CLAUDE_CODE, Plat.CHATGPT],
    TaskType.DOCUMENTATION: [Plat.CHATGPT, Plat.CLAUDE_CODE, Plat.GEMINI],
    TaskType.CODE_REVIEW: [Plat.GEMINI, Plat.CLAUDE_CODE, Plat.CHATGPT],
    TaskType.SQL_DB_WORK: [Plat.CLAUDE_CODE, Plat.GEMINI, Plat.CHATGPT],
    TaskType.TESTING: [Plat.CLAUDE_CODE, Plat.CHATGPT, Plat.GEMINI],
    TaskType.DEBUGGING: [Plat.CLAUDE_CODE, Plat.GEMINI, Plat.CHATGPT],
    TaskType.PLANNING: [Plat.CLAUDE_CODE, Plat.CHATGPT, Plat.GEMINI],
}

# Cost tiers in priority order (use cheapest first)
COST_PRIORITY = [
    # Tier 1: Free CLI quota (use first)
    {"platform": "gemini", "method": "cli", "quota_key": "gemini_cli", "cost": 0},

    # Tier 2: Included in subscriptions (already paid, effectively free)
    {"platform": "claude_code", "method": "desktop", "quota_key": "claude_code", "cost": 0},
    {"platform": "chatgpt", "method": "web", "quota_key": "chatgpt_plus", "cost": 0},

    # Tier 3: Free API tiers
    {"platform": "gemini", "method": "api_free", "quota_key": "gemini_api_free", "cost": 0},

    # Tier 4: Paid APIs (last resort)
    {"platform": "claude", "method": "api", "quota_key": "claude_api", "cost": "variable"},
    {"platform": "openai", "method": "api", "quota_key": "openai_api", "cost": "variable"},
]

# Cost tiers with Platform enum and priority structure for route_cost_optimized
COST_TIERS = [
    # Tier 1: Gemini CLI free tier (1500 req/day) - ALWAYS try first
    {"platform": Plat.GEMINI, "quota_key": "gemini_cli", "cost_per_req": 0.0, "priority": 1},

    # Tier 2: Subscription-included (already paid, effectively free)
    {"platform": Plat.CLAUDE_CODE, "quota_key": "claude_code", "cost_per_req": 0.0, "priority": 2},
    {"platform": Plat.CHATGPT, "quota_key": "chatgpt_plus", "cost_per_req": 0.0, "priority": 2},

    # Tier 3: Paid APIs (last resort)
    {"platform": Plat.GEMINI, "quota_key": "gemini_api", "cost_per_req": 0.0001, "priority": 3},
    {"platform": Plat.CHATGPT, "quota_key": "openai_api", "cost_per_req": 0.002, "priority": 3},
]


class TaskRouter:
    """Routes tasks to optimal AI platforms."""

    def __init__(self, validator: AdapterValidator = None):
        """
        Initialize router with validator.

        Args:
            validator: AdapterValidator for filtering available platforms
        """
        self.validator = validator

    def route(self, task: Task, quota_tracker: QuotaTracker) -> Platform:
        """
        Route task to best available platform.

        FIRST VALIDATION CHECKPOINT: Filters out stubs and unavailable adapters.

        Priority:
        1. Filter by implementation status (exclude stubs)
        2. Honor platform_hint if provided and available
        3. Use routing matrix for task type
        4. Filter by quota availability (prefer free)
        5. Fall back to default if needed

        Args:
            task: Task to route
            quota_tracker: Quota tracking instance

        Returns:
            Platform to execute on

        Raises:
            RuntimeError: If no platforms are available
        """
        # FIRST CHECKPOINT: Get only implemented platforms
        if self.validator:
            available_platforms = self.validator.get_available_platforms()
            if not available_platforms:
                unavailable = self.validator.get_unavailable_platforms()
                unavailable_names = [p.value for p in unavailable]
                raise RuntimeError(
                    f"No implemented adapters available. "
                    f"Stubs that need implementation: {', '.join(unavailable_names)}. "
                    f"Please implement at least one adapter before routing tasks."
                )
        else:
            # No validator, allow all platforms (backward compatibility)
            available_platforms = [Plat.CLAUDE_CODE, Plat.CHATGPT, Plat.GEMINI]

        # Honor hint if provided, implemented, and quota available
        if task.platform_hint:
            if task.platform_hint in available_platforms:
                if quota_tracker.can_use(task.platform_hint.value):
                    return task.platform_hint

        # Get candidates from routing matrix
        candidates = ROUTING_MATRIX.get(task.type, [Plat.CLAUDE_CODE])

        # Filter by implementation status AND quota availability
        available = [
            p for p in candidates
            if p in available_platforms and quota_tracker.can_use(p.value)
        ]

        if not available:
            # Try to find any implemented platform with quota
            fallback = [
                p for p in available_platforms
                if quota_tracker.can_use(p.value)
            ]
            if fallback:
                return fallback[0]

            # All quotas exhausted, fall back to Claude Code if implemented
            if Plat.CLAUDE_CODE in available_platforms:
                return Plat.CLAUDE_CODE

            # No platforms available at all
            raise RuntimeError(
                f"No available platforms with quota remaining. "
                f"Implemented platforms: {[p.value for p in available_platforms]}"
            )

        # Prefer free tier if available
        for tier in COST_PRIORITY:
            platform_name = tier["platform"]

            # Map platform name to Platform enum
            if platform_name == "claude_code" and Plat.CLAUDE_CODE in available:
                return Plat.CLAUDE_CODE
            elif platform_name == "chatgpt" and Plat.CHATGPT in available:
                return Plat.CHATGPT
            elif platform_name == "gemini" and Plat.GEMINI in available:
                return Plat.GEMINI

        # Default to first available candidate
        return available[0]

    def route_cost_optimized(self, task: Task, quota_tracker: QuotaTracker) -> Platform:
        """
        Route to cheapest available platform per ROADMAP success criteria #1.

        Priority:
        1. Honor platform_hint if specified and available (advisory - fallback allowed)
        2. Try Gemini CLI free tier first
        3. Fall back to subscriptions (Claude Code, ChatGPT Plus)
        4. Last resort: paid APIs

        Args:
            task: Task to route
            quota_tracker: QuotaTracker instance

        Returns:
            Platform enum for cheapest available platform

        Raises:
            RuntimeError: If no platforms available (all quotas exhausted)
        """
        # Priority 1: Honor platform_hint if specified and available
        if task.platform_hint:
            if quota_tracker.can_use(task.platform_hint.value):
                return task.platform_hint

        # Sort by priority (lower number = higher priority)
        sorted_tiers = sorted(COST_TIERS, key=lambda t: t["priority"])

        # Priority 2-4: Iterate through cost tiers
        for tier in sorted_tiers:
            platform = tier["platform"]
            quota_key = tier["quota_key"]

            # Check if quota available for this tier
            if quota_tracker.can_use(quota_key):
                return platform

        # No platforms available - all quotas exhausted
        raise RuntimeError(
            "No platforms available - all quotas exhausted. "
            "Please wait for quota reset or enable paid APIs."
        )

    def warn_quota_threshold(self, quota_tracker: QuotaTracker, threshold: int = 90) -> list[str]:
        """
        Return warning messages for quotas above threshold percent.

        Args:
            quota_tracker: QuotaTracker instance
            threshold: Percentage threshold (default 90)

        Returns:
            List of warning messages
        """
        warnings = []
        summary = quota_tracker.get_daily_summary()

        for platform, status in summary.items():
            if status["limit"] != "unlimited":
                percent_used = status.get("percent_used", 0.0)
                if percent_used >= threshold:
                    warnings.append(
                        f"WARNING: {platform} quota at {percent_used:.1f}% "
                        f"({status['used']}/{status['limit']})"
                    )

        return warnings
