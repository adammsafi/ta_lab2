"""Quota tracking for free tiers and API limits."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from .persistence import QuotaState, load_quota_state, save_quota_state

logger = logging.getLogger(__name__)


@dataclass
class QuotaLimit:
    """Represents a quota limit for a platform/method."""
    limit: Optional[int] = None  # Max requests/tokens per period
    used: int = 0
    resets_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    unlimited: bool = False
    reserved: int = 0  # Amount reserved but not yet used


@dataclass
class QuotaAlert:
    """Represents a quota threshold alert."""
    platform: str
    threshold: int  # Percentage (50, 80, 90)
    current_usage: int
    limit: int
    message: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class QuotaTracker:
    """Tracks usage quotas for all AI platforms."""

    def __init__(
        self,
        alert_thresholds: List[int] = None,
        on_alert: Optional[Callable[[QuotaAlert], None]] = None,
        persistence_path: Optional[str] = "./.memory/quota_state.json"
    ):
        """
        Initialize quota limits.

        Args:
            alert_thresholds: Percentage thresholds for alerts (default: [50, 80, 90])
            on_alert: Callback function called when threshold crossed
            persistence_path: Path to persistence file (None disables persistence)
        """
        self.alert_thresholds = alert_thresholds or [50, 80, 90]
        self.on_alert = on_alert
        self.persistence_path = persistence_path
        self.triggered_alerts: Dict[str, set] = {}  # Track which thresholds were triggered

        # Initialize default limits
        self.limits: Dict[str, QuotaLimit] = {
            # Free CLI quotas (reset daily at midnight UTC)
            "gemini_cli": QuotaLimit(
                limit=1500,
                resets_at=self._next_midnight_utc()
            ),
            "gemini_api_free": QuotaLimit(
                limit=1500,
                resets_at=self._next_midnight_utc()
            ),

            # Subscription quotas (effectively unlimited for paid users)
            "claude_code": QuotaLimit(unlimited=True),
            "chatgpt_plus": QuotaLimit(unlimited=True),

            # Paid API quotas (pay-per-use, soft limits)
            "claude_api": QuotaLimit(limit=1_000_000, unlimited=False),  # Soft limit
            "openai_api": QuotaLimit(limit=1_000_000, unlimited=False),  # Soft limit
        }

        # Load persisted state if available
        if self.persistence_path:
            self._load_state()

    def can_use(self, platform: str, amount: int = 1) -> bool:
        """
        Check if platform has available quota.

        Args:
            platform: Platform name (claude_code, gemini, chatgpt)
            amount: Amount of quota needed (default: 1)

        Returns:
            True if quota available
        """
        # Map platform to quota key
        quota_key = self._platform_to_quota_key(platform)

        if quota_key not in self.limits:
            return True  # Unknown platform, assume available

        quota = self.limits[quota_key]

        # Check if quota has reset
        self._check_and_reset(quota_key)

        # Check availability
        if quota.unlimited:
            return True

        # Account for both used and reserved quota
        total_committed = quota.used + quota.reserved
        return total_committed + amount <= quota.limit

    def record_usage(self, platform: str, tokens: int = 1, cost: float = 0.0):
        """
        Record usage for a platform.

        Args:
            platform: Platform name
            tokens: Number of tokens used (default 1 request)
            cost: Cost in USD
        """
        quota_key = self._platform_to_quota_key(platform)

        if quota_key not in self.limits:
            return  # Unknown platform, no tracking

        quota = self.limits[quota_key]

        # Check if quota needs reset
        self._check_and_reset(quota_key)

        # Release matching reservation if exists
        if quota.reserved > 0:
            released = min(tokens, quota.reserved)
            quota.reserved -= released

        # Record usage
        quota.used += tokens

        # Check thresholds and trigger alerts
        if not quota.unlimited and quota.limit:
            self._check_thresholds(quota_key)

        # Persist state
        if self.persistence_path:
            self._save_state()

    def get_status(self) -> Dict[str, Dict[str, any]]:
        """
        Get current quota status for all platforms.

        Returns:
            Dict of platform -> {used, limit, available, resets_at}
        """
        status = {}

        for key, quota in self.limits.items():
            if quota.unlimited:
                status[key] = {
                    "used": quota.used,
                    "limit": "unlimited",
                    "available": "unlimited",
                    "resets_at": None,
                }
            else:
                limit_value = quota.limit if quota.limit is not None else "unlimited"
                available_value = (
                    "unlimited" if quota.limit is None else quota.limit - quota.used
                )

                status[key] = {
                    "used": quota.used,
                    "limit": limit_value,
                    "available": available_value,
                    "resets_at": quota.resets_at.isoformat(),
                }

        return status

    def reserve(self, platform: str, amount: int = 1) -> bool:
        """
        Reserve quota before task execution.

        Args:
            platform: Platform name
            amount: Amount to reserve (default: 1)

        Returns:
            True if reservation successful, False if insufficient quota
        """
        quota_key = self._platform_to_quota_key(platform)

        if quota_key not in self.limits:
            return True  # Unknown platform, assume available

        quota = self.limits[quota_key]

        # Check if quota needs reset
        self._check_and_reset(quota_key)

        if quota.unlimited:
            return True

        # Check if reservation is possible
        total_committed = quota.used + quota.reserved
        if total_committed + amount > quota.limit:
            return False

        # Reserve quota
        quota.reserved += amount

        # Persist state
        if self.persistence_path:
            self._save_state()

        return True

    def release(self, platform: str, amount: int = 1):
        """
        Release reserved quota (e.g., if task cancelled).

        Args:
            platform: Platform name
            amount: Amount to release (default: 1)
        """
        quota_key = self._platform_to_quota_key(platform)

        if quota_key not in self.limits:
            return

        quota = self.limits[quota_key]
        quota.reserved = max(0, quota.reserved - amount)

        # Persist state
        if self.persistence_path:
            self._save_state()

    def get_daily_summary(self) -> Dict[str, Dict[str, Any]]:
        """
        Get daily summary of quota usage.

        Returns:
            Dict of platform -> {used, limit, remaining, percent_used, alerts_triggered}
        """
        summary = {}

        for key, quota in self.limits.items():
            if quota.unlimited:
                summary[key] = {
                    "used": quota.used,
                    "limit": "unlimited",
                    "remaining": "unlimited",
                    "percent_used": 0.0,
                    "alerts_triggered": []
                }
            else:
                remaining = quota.limit - quota.used
                percent_used = (quota.used / quota.limit * 100) if quota.limit else 0.0
                alerts = sorted(list(self.triggered_alerts.get(key, set())))

                summary[key] = {
                    "used": quota.used,
                    "limit": quota.limit,
                    "remaining": remaining,
                    "reserved": quota.reserved,
                    "percent_used": round(percent_used, 1),
                    "alerts_triggered": alerts
                }

        return summary

    def display_status(self) -> str:
        """
        Format quota status for CLI display.

        Returns:
            Multi-line formatted string showing all platforms
        """
        lines = ["Quota Status:", "=" * 60]

        for key, quota in self.limits.items():
            if quota.unlimited:
                lines.append(f"\n{key}: UNLIMITED")
                lines.append(f"  Used: {quota.used}")
            else:
                percent = (quota.used / quota.limit * 100) if quota.limit else 0
                bar_length = 30
                filled = int(bar_length * quota.used / quota.limit) if quota.limit else 0
                bar = "█" * filled + "░" * (bar_length - filled)

                lines.append(f"\n{key}:")
                lines.append(f"  [{bar}] {percent:.1f}%")
                lines.append(f"  Used: {quota.used}/{quota.limit} (Reserved: {quota.reserved})")

                # Show reset time for daily quotas
                if quota.resets_at:
                    now = datetime.now(timezone.utc)
                    time_until_reset = quota.resets_at - now
                    hours = int(time_until_reset.total_seconds() // 3600)
                    minutes = int((time_until_reset.total_seconds() % 3600) // 60)
                    lines.append(f"  Resets in: {hours}h {minutes}m")

        return "\n".join(lines)

    def _check_and_reset(self, quota_key: str):
        """Check if quota needs reset and reset if needed."""
        quota = self.limits[quota_key]

        if quota.resets_at and quota.resets_at < datetime.now(timezone.utc):
            quota.used = 0
            quota.reserved = 0
            quota.resets_at = self._next_midnight_utc()

            # Clear triggered alerts for this platform
            if quota_key in self.triggered_alerts:
                self.triggered_alerts[quota_key] = set()

            # Persist state
            if self.persistence_path:
                self._save_state()

    def _check_thresholds(self, quota_key: str):
        """Check if any alert thresholds have been crossed."""
        quota = self.limits[quota_key]

        if quota.unlimited or not quota.limit:
            return

        percent_used = (quota.used / quota.limit) * 100

        # Track which thresholds were already triggered
        if quota_key not in self.triggered_alerts:
            self.triggered_alerts[quota_key] = set()

        # Check each threshold
        for threshold in self.alert_thresholds:
            if percent_used >= threshold and threshold not in self.triggered_alerts[quota_key]:
                # Threshold crossed for first time
                self.triggered_alerts[quota_key].add(threshold)

                alert = QuotaAlert(
                    platform=quota_key,
                    threshold=threshold,
                    current_usage=quota.used,
                    limit=quota.limit,
                    message=f"Quota at {threshold}% for {quota_key}: {quota.used}/{quota.limit}"
                )

                # Call callback if provided
                if self.on_alert:
                    try:
                        self.on_alert(alert)
                    except Exception as e:
                        logger.error(f"Error in alert callback: {e}")

    def _load_state(self):
        """Load quota state from persistence."""
        try:
            state = load_quota_state(self.persistence_path)
            if state:
                # Restore limits from state
                for key, limit_data in state.limits.items():
                    if key in self.limits:
                        quota = self.limits[key]
                        quota.used = limit_data.get('used', 0)
                        quota.reserved = limit_data.get('reserved', 0)

                        # Parse resets_at
                        if 'resets_at' in limit_data and limit_data['resets_at']:
                            quota.resets_at = datetime.fromisoformat(limit_data['resets_at'])

                logger.debug(f"Loaded quota state from {self.persistence_path}")
        except Exception as e:
            logger.error(f"Failed to load quota state: {e}")

    def _save_state(self):
        """Save quota state to persistence."""
        try:
            # Serialize limits
            limits_data = {}
            for key, quota in self.limits.items():
                limits_data[key] = {
                    'limit': quota.limit,
                    'used': quota.used,
                    'reserved': quota.reserved,
                    'resets_at': quota.resets_at.isoformat() if quota.resets_at else None,
                    'unlimited': quota.unlimited
                }

            state = QuotaState(
                limits=limits_data,
                last_updated=datetime.now(timezone.utc).isoformat()
            )

            save_quota_state(state, self.persistence_path)
            logger.debug(f"Saved quota state to {self.persistence_path}")

        except Exception as e:
            logger.error(f"Failed to save quota state: {e}")

    @staticmethod
    def _platform_to_quota_key(platform: str) -> str:
        """Map platform name to quota key."""
        mapping = {
            "claude_code": "claude_code",
            "chatgpt": "chatgpt_plus",
            "gemini": "gemini_cli",  # Prefer CLI (free) by default
        }
        return mapping.get(platform, platform)

    @staticmethod
    def _next_midnight_utc() -> datetime:
        """Calculate next midnight UTC for daily quota reset."""
        now = datetime.now(timezone.utc)
        next_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # If we're past midnight, add a day
        if now >= next_day:
            next_day += timedelta(days=1)

        return next_day
