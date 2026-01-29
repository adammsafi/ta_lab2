"""Tests for cost-optimized routing."""
import pytest
from unittest.mock import Mock, MagicMock

from ta_lab2.tools.ai_orchestrator.routing import TaskRouter, COST_TIERS
from ta_lab2.tools.ai_orchestrator.core import Task, TaskType, Platform
from ta_lab2.tools.ai_orchestrator.quota import QuotaTracker


class TestCostTiers:
    """Test COST_TIERS configuration."""

    def test_gemini_free_is_first_priority(self):
        """Gemini CLI free tier should be priority 1."""
        gemini_free = [t for t in COST_TIERS if t["quota_key"] == "gemini_cli"]
        assert len(gemini_free) == 1
        assert gemini_free[0]["priority"] == 1
        assert gemini_free[0]["platform"] == Platform.GEMINI
        assert gemini_free[0]["cost_per_req"] == 0.0

    def test_subscriptions_are_second_priority(self):
        """Claude Code and ChatGPT Plus should be priority 2."""
        subscriptions = [t for t in COST_TIERS if t["priority"] == 2]
        assert len(subscriptions) == 2

        platforms = {t["platform"] for t in subscriptions}
        assert Platform.CLAUDE_CODE in platforms
        assert Platform.CHATGPT in platforms

        # Both should be zero cost (included in subscription)
        for tier in subscriptions:
            assert tier["cost_per_req"] == 0.0

    def test_paid_apis_are_last_priority(self):
        """Paid APIs should be priority 3."""
        paid_apis = [t for t in COST_TIERS if t["priority"] == 3]
        assert len(paid_apis) == 2

        # Should have non-zero cost
        for tier in paid_apis:
            assert tier["cost_per_req"] > 0.0

    def test_cost_tiers_sorted_by_priority(self):
        """COST_TIERS should be in ascending priority order."""
        priorities = [t["priority"] for t in COST_TIERS]
        assert priorities == sorted(priorities)


class TestRouteCostOptimized:
    """Test TaskRouter.route_cost_optimized method."""

    def test_routes_to_gemini_free_first_when_available(self):
        """When Gemini free tier has quota, route there."""
        router = TaskRouter()
        task = Task(type=TaskType.CODE_GENERATION, prompt="Test prompt")

        # Mock QuotaTracker - all quotas available
        quota_tracker = Mock(spec=QuotaTracker)
        quota_tracker.can_use = Mock(return_value=True)

        result = router.route_cost_optimized(task, quota_tracker)

        assert result == Platform.GEMINI
        # Verify it checked gemini_cli quota
        quota_tracker.can_use.assert_any_call("gemini_cli")

    def test_honors_platform_hint_when_available(self):
        """Platform hint should be respected if quota available."""
        router = TaskRouter()
        task = Task(
            type=TaskType.CODE_GENERATION,
            prompt="Test prompt",
            platform_hint=Platform.CLAUDE_CODE
        )

        # Mock QuotaTracker - all quotas available
        quota_tracker = Mock(spec=QuotaTracker)
        quota_tracker.can_use = Mock(return_value=True)

        result = router.route_cost_optimized(task, quota_tracker)

        # Should honor hint and return Claude Code, not Gemini
        assert result == Platform.CLAUDE_CODE
        # Verify it checked the hinted platform
        quota_tracker.can_use.assert_any_call("claude_code")

    def test_falls_back_from_hint_when_quota_exhausted(self):
        """Should fall back when hinted platform has no quota."""
        router = TaskRouter()
        task = Task(
            type=TaskType.CODE_GENERATION,
            prompt="Test prompt",
            platform_hint=Platform.CLAUDE_CODE
        )

        # Mock QuotaTracker - Claude Code exhausted, others available
        def can_use_side_effect(platform):
            return platform != "claude_code"

        quota_tracker = Mock(spec=QuotaTracker)
        quota_tracker.can_use = Mock(side_effect=can_use_side_effect)

        result = router.route_cost_optimized(task, quota_tracker)

        # Should fall back to Gemini (first priority)
        assert result == Platform.GEMINI

    def test_routes_to_subscription_when_free_exhausted(self):
        """When Gemini free exhausted, route to Claude Code or ChatGPT."""
        router = TaskRouter()
        task = Task(type=TaskType.CODE_GENERATION, prompt="Test prompt")

        # Mock QuotaTracker - Gemini free exhausted, subscriptions available
        def can_use_side_effect(quota_key):
            return quota_key != "gemini_cli"

        quota_tracker = Mock(spec=QuotaTracker)
        quota_tracker.can_use = Mock(side_effect=can_use_side_effect)

        result = router.route_cost_optimized(task, quota_tracker)

        # Should route to a subscription platform (priority 2)
        assert result in [Platform.CLAUDE_CODE, Platform.CHATGPT]

    def test_routes_to_paid_api_as_last_resort(self):
        """Paid APIs only when all free/subscription exhausted."""
        router = TaskRouter()
        task = Task(type=TaskType.CODE_GENERATION, prompt="Test prompt")

        # Mock QuotaTracker - only paid APIs available
        def can_use_side_effect(quota_key):
            # Only paid API keys available
            return quota_key in ["gemini_api", "openai_api"]

        quota_tracker = Mock(spec=QuotaTracker)
        quota_tracker.can_use = Mock(side_effect=can_use_side_effect)

        result = router.route_cost_optimized(task, quota_tracker)

        # Should route to a paid API platform (priority 3)
        assert result in [Platform.GEMINI, Platform.CHATGPT]

    def test_raises_when_all_exhausted(self):
        """RuntimeError when no platforms available."""
        router = TaskRouter()
        task = Task(type=TaskType.CODE_GENERATION, prompt="Test prompt")

        # Mock QuotaTracker - all quotas exhausted
        quota_tracker = Mock(spec=QuotaTracker)
        quota_tracker.can_use = Mock(return_value=False)

        with pytest.raises(RuntimeError) as exc_info:
            router.route_cost_optimized(task, quota_tracker)

        assert "No platforms available" in str(exc_info.value)
        assert "all quotas exhausted" in str(exc_info.value)

    def test_routes_with_no_hint_follows_cost_order(self):
        """Without hint, should follow cost tier priority order."""
        router = TaskRouter()
        task = Task(type=TaskType.CODE_GENERATION, prompt="Test prompt")

        # Mock QuotaTracker - track which quotas were checked
        checked_quotas = []

        def can_use_side_effect(quota_key):
            checked_quotas.append(quota_key)
            # Only chatgpt_plus available
            return quota_key == "chatgpt_plus"

        quota_tracker = Mock(spec=QuotaTracker)
        quota_tracker.can_use = Mock(side_effect=can_use_side_effect)

        result = router.route_cost_optimized(task, quota_tracker)

        # Should return ChatGPT (first available)
        assert result == Platform.CHATGPT

        # Should have checked in priority order
        assert checked_quotas[0] == "gemini_cli"  # Priority 1


class TestQuotaWarnings:
    """Test quota threshold warning functionality."""

    def test_warn_at_90_percent(self):
        """Warn when quota above 90%."""
        router = TaskRouter()

        # Create real QuotaTracker with high usage
        quota_tracker = QuotaTracker(persistence_path=None)
        quota_tracker.limits["gemini_cli"].used = 1350  # 90% of 1500
        quota_tracker.limits["gemini_cli"].limit = 1500

        warnings = router.warn_quota_threshold(quota_tracker, threshold=90)

        assert len(warnings) > 0
        assert any("gemini_cli" in w for w in warnings)
        assert any("90" in w for w in warnings)

    def test_no_warn_below_threshold(self):
        """No warning when below threshold."""
        router = TaskRouter()

        # Create real QuotaTracker with low usage
        quota_tracker = QuotaTracker(persistence_path=None)
        quota_tracker.limits["gemini_cli"].used = 100  # ~7% of 1500
        quota_tracker.limits["gemini_cli"].limit = 1500

        warnings = router.warn_quota_threshold(quota_tracker, threshold=90)

        # Should not warn about gemini_cli
        assert not any("gemini_cli" in w for w in warnings)

    def test_warn_at_custom_threshold(self):
        """Should support custom threshold percentages."""
        router = TaskRouter()

        # Create real QuotaTracker with 60% usage
        quota_tracker = QuotaTracker(persistence_path=None)
        quota_tracker.limits["gemini_cli"].used = 900  # 60% of 1500
        quota_tracker.limits["gemini_cli"].limit = 1500

        # Should warn at 50% threshold
        warnings_50 = router.warn_quota_threshold(quota_tracker, threshold=50)
        assert len(warnings_50) > 0

        # Should NOT warn at 90% threshold
        warnings_90 = router.warn_quota_threshold(quota_tracker, threshold=90)
        assert len(warnings_90) == 0

    def test_warn_multiple_platforms(self):
        """Should warn about all platforms above threshold."""
        router = TaskRouter()

        # Create real QuotaTracker with high usage on multiple platforms
        quota_tracker = QuotaTracker(persistence_path=None)
        quota_tracker.limits["gemini_cli"].used = 1400  # 93% of 1500
        quota_tracker.limits["gemini_cli"].limit = 1500
        quota_tracker.limits["claude_api"].used = 950000  # 95% of 1M
        quota_tracker.limits["claude_api"].limit = 1000000

        warnings = router.warn_quota_threshold(quota_tracker, threshold=90)

        # Should warn about both platforms
        assert len(warnings) >= 2
        assert any("gemini_cli" in w for w in warnings)
        assert any("claude_api" in w for w in warnings)

    def test_ignores_unlimited_quotas(self):
        """Should not warn about unlimited quotas."""
        router = TaskRouter()

        # Create real QuotaTracker
        quota_tracker = QuotaTracker(persistence_path=None)

        # claude_code is unlimited by default
        warnings = router.warn_quota_threshold(quota_tracker, threshold=0)

        # Should not warn about claude_code or chatgpt_plus (unlimited)
        assert not any("claude_code" in w for w in warnings)
        assert not any("chatgpt_plus" in w for w in warnings)

    def test_warning_message_format(self):
        """Warning messages should include platform, percentage, and usage."""
        router = TaskRouter()

        # Create real QuotaTracker with 95% usage
        quota_tracker = QuotaTracker(persistence_path=None)
        quota_tracker.limits["gemini_cli"].used = 1425  # 95% of 1500
        quota_tracker.limits["gemini_cli"].limit = 1500

        warnings = router.warn_quota_threshold(quota_tracker, threshold=90)

        assert len(warnings) > 0
        warning = warnings[0]

        # Should include all key information
        assert "gemini_cli" in warning
        assert "95" in warning  # Percentage
        assert "1425" in warning  # Used
        assert "1500" in warning  # Limit
        assert "WARNING" in warning
