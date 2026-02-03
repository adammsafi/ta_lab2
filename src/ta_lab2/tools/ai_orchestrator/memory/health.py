"""Memory health monitoring for detecting stale and deprecated memories.

Provides MemoryHealthMonitor for scanning memory stores, detecting stale
memories (not verified in 90+ days), generating health reports, and managing
deprecation workflows (MEMO-06).

Health monitoring is non-destructive by default (dry_run=True).
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from ta_lab2.tools.ai_orchestrator.memory.mem0_client import Mem0Client, get_mem0_client
from ta_lab2.tools.ai_orchestrator.memory.metadata import mark_deprecated

logger = logging.getLogger(__name__)


@dataclass
class HealthReport:
    """Memory health report with comprehensive statistics.

    Attributes:
        total_memories: Total number of memories scanned
        healthy: Memories verified within staleness threshold
        stale: Memories not verified in staleness_days
        deprecated: Memories marked with deprecated_since
        missing_metadata: Memories without created_at or last_verified
        age_distribution: Age distribution dict (e.g., {"0-30d": 100, "30-60d": 50})
        stale_memories: List of stale memory details for review
        scan_timestamp: ISO 8601 timestamp when scan ran

    Example:
        >>> report = HealthReport(
        ...     total_memories=100,
        ...     healthy=80,
        ...     stale=15,
        ...     deprecated=5,
        ...     missing_metadata=0,
        ...     age_distribution={'0-30d': 50, '30-60d': 30},
        ...     stale_memories=[],
        ...     scan_timestamp='2026-01-28T15:00:00'
        ... )
    """

    total_memories: int
    healthy: int
    stale: int
    deprecated: int
    missing_metadata: int
    age_distribution: dict[str, int]
    stale_memories: list[dict]
    scan_timestamp: str


class MemoryHealthMonitor:
    """Monitor memory health by detecting stale and deprecated memories.

    Scans memories for staleness (based on last_verified timestamp),
    generates comprehensive health reports, and provides deprecation workflows.

    Non-destructive by default (dry_run=True). Only flags/deprecates when
    explicitly requested.

    Example:
        >>> monitor = MemoryHealthMonitor(staleness_days=90)
        >>> report = monitor.generate_health_report()
        >>> print(f"Stale: {report.stale}/{report.total_memories}")

        >>> # Flag stale memories (dry run by default)
        >>> count = monitor.flag_stale_memories(dry_run=True)
        >>> print(f"Would flag {count} stale memories")

        >>> # Refresh verification for confirmed accurate memories
        >>> monitor.refresh_verification(["mem_123", "mem_456"])
    """

    def __init__(self, client: Optional[Mem0Client] = None, staleness_days: int = 90):
        """Initialize MemoryHealthMonitor.

        Args:
            client: Optional Mem0Client instance. If None, uses get_mem0_client()
            staleness_days: Threshold for marking as stale (default: 90)
        """
        self.client = client if client is not None else get_mem0_client()
        self.staleness_days = staleness_days
        logger.info(
            f"MemoryHealthMonitor initialized with staleness_days={staleness_days}"
        )

    def scan_stale_memories(self) -> list[dict]:
        """Scan all memories and find stale ones (not verified within threshold).

        Returns:
            List of stale memory dicts with:
            - id: Memory ID
            - content: First 100 chars of memory content
            - last_verified: Last verification timestamp (or "never")
            - age_days: Days since last verification

        Example:
            >>> stale = monitor.scan_stale_memories()
            >>> for mem in stale:
            ...     print(f"{mem['id']}: {mem['age_days']} days old")
        """
        stale_memories = []
        threshold_date = datetime.now(timezone.utc) - timedelta(
            days=self.staleness_days
        )

        try:
            # Get all memories
            all_memories = self.client.get_all(user_id="orchestrator")
            logger.info(f"Scanning {len(all_memories)} memories for staleness")

            for memory in all_memories:
                metadata = memory.get("metadata", {})
                last_verified = metadata.get("last_verified")

                # Check if memory is stale
                is_stale = False
                age_days = None

                if last_verified:
                    try:
                        verified_date = datetime.fromisoformat(last_verified)
                        if verified_date < threshold_date:
                            is_stale = True
                            age_days = (datetime.now(timezone.utc) - verified_date).days
                    except (ValueError, TypeError) as e:
                        logger.warning(
                            f"Invalid last_verified timestamp for {memory.get('id')}: {e}"
                        )
                        is_stale = True
                        age_days = None
                else:
                    # Missing last_verified is considered stale
                    is_stale = True
                    age_days = None

                if is_stale:
                    content = memory.get("memory", "")
                    stale_memories.append(
                        {
                            "id": memory.get("id"),
                            "content": content[:100] if content else "",
                            "last_verified": last_verified
                            if last_verified
                            else "never",
                            "age_days": age_days,
                        }
                    )

            logger.info(
                f"Found {len(stale_memories)} stale memories (threshold: {self.staleness_days} days)"
            )
            return stale_memories

        except Exception as e:
            logger.error(f"Failed to scan stale memories: {e}")
            raise

    def generate_health_report(self) -> HealthReport:
        """Generate comprehensive health report for all memories.

        Scans all memories and categorizes by age, status, and metadata completeness.

        Returns:
            HealthReport with full statistics and stale memory details

        Example:
            >>> report = monitor.generate_health_report()
            >>> print(f"Health: {report.healthy}/{report.total_memories} healthy")
            >>> print(f"Age distribution: {report.age_distribution}")
        """
        try:
            all_memories = self.client.get_all(user_id="orchestrator")
            total = len(all_memories)

            healthy = 0
            stale = 0
            deprecated = 0
            missing_metadata = 0

            # Age distribution buckets
            age_buckets = {"0-30d": 0, "30-60d": 0, "60-90d": 0, "90+d": 0}

            stale_memories = []
            threshold_date = datetime.now(timezone.utc) - timedelta(
                days=self.staleness_days
            )

            for memory in all_memories:
                metadata = memory.get("metadata", {})

                # Check for missing metadata
                if not metadata.get("created_at") or not metadata.get("last_verified"):
                    missing_metadata += 1

                # Check if deprecated
                if metadata.get("deprecated_since"):
                    deprecated += 1

                # Calculate age and categorize
                last_verified = metadata.get("last_verified")
                if last_verified:
                    try:
                        verified_date = datetime.fromisoformat(last_verified)
                        age_days = (datetime.now(timezone.utc) - verified_date).days

                        # Age distribution
                        if age_days < 30:
                            age_buckets["0-30d"] += 1
                        elif age_days < 60:
                            age_buckets["30-60d"] += 1
                        elif age_days < 90:
                            age_buckets["60-90d"] += 1
                        else:
                            age_buckets["90+d"] += 1

                        # Health status
                        if verified_date >= threshold_date:
                            healthy += 1
                        else:
                            stale += 1
                            content = memory.get("memory", "")
                            stale_memories.append(
                                {
                                    "id": memory.get("id"),
                                    "content": content[:100] if content else "",
                                    "last_verified": last_verified,
                                    "age_days": age_days,
                                }
                            )
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Invalid timestamp for {memory.get('id')}: {e}")
                        stale += 1
                        age_buckets["90+d"] += 1
                else:
                    # Missing last_verified considered stale
                    stale += 1
                    age_buckets["90+d"] += 1
                    content = memory.get("memory", "")
                    stale_memories.append(
                        {
                            "id": memory.get("id"),
                            "content": content[:100] if content else "",
                            "last_verified": "never",
                            "age_days": None,
                        }
                    )

            report = HealthReport(
                total_memories=total,
                healthy=healthy,
                stale=stale,
                deprecated=deprecated,
                missing_metadata=missing_metadata,
                age_distribution=age_buckets,
                stale_memories=stale_memories,
                scan_timestamp=datetime.now(timezone.utc).isoformat(),
            )

            logger.info(
                f"Health report generated: {healthy}/{total} healthy, {stale} stale, {deprecated} deprecated"
            )
            return report

        except Exception as e:
            logger.error(f"Failed to generate health report: {e}")
            raise

    def flag_stale_memories(self, dry_run: bool = True) -> int:
        """Flag stale memories as deprecated with reason.

        Non-destructive by default (dry_run=True). Only updates when explicitly
        requested with dry_run=False.

        Args:
            dry_run: If True, only report what would be flagged (default: True)

        Returns:
            Count of flagged (or would-be-flagged) memories

        Example:
            >>> # Preview what would be flagged
            >>> count = monitor.flag_stale_memories(dry_run=True)
            >>> print(f"Would flag {count} memories")

            >>> # Actually flag stale memories
            >>> count = monitor.flag_stale_memories(dry_run=False)
            >>> print(f"Flagged {count} stale memories")
        """
        try:
            stale_memories = self.scan_stale_memories()
            count = len(stale_memories)

            if dry_run:
                logger.info(f"DRY RUN: Would flag {count} stale memories as deprecated")
                return count

            # Actually flag memories
            for mem in stale_memories:
                memory_id = mem["id"]
                age_days = mem["age_days"]

                # Build deprecation reason
                if age_days is not None:
                    reason = f"Not verified in {age_days} days (threshold: {self.staleness_days} days)"
                else:
                    reason = f"Never verified (threshold: {self.staleness_days} days)"

                try:
                    # Get current memory to update metadata
                    all_memories = self.client.get_all(user_id="orchestrator")
                    current_memory = next(
                        (m for m in all_memories if m.get("id") == memory_id), None
                    )

                    if current_memory:
                        current_metadata = current_memory.get("metadata", {})
                        updated_metadata = mark_deprecated(
                            current_metadata, reason=reason
                        )

                        # Update memory with deprecated metadata
                        self.client.update(
                            memory_id=memory_id,
                            data=current_memory.get("memory", ""),
                            metadata=updated_metadata,
                        )
                        logger.info(
                            f"Flagged memory {memory_id} as deprecated: {reason}"
                        )
                except Exception as e:
                    logger.error(f"Failed to flag memory {memory_id}: {e}")
                    # Continue flagging other memories

            logger.info(f"Flagged {count} stale memories as deprecated")
            return count

        except Exception as e:
            logger.error(f"Failed to flag stale memories: {e}")
            raise

    def refresh_verification(self, memory_ids: list[str]) -> int:
        """Refresh last_verified timestamp for confirmed accurate memories.

        Use this when human confirms a memory is still accurate. Updates
        last_verified to current UTC time, keeping memory healthy.

        Args:
            memory_ids: List of memory IDs to refresh

        Returns:
            Count of successfully refreshed memories

        Example:
            >>> # Human confirms these memories are still accurate
            >>> count = monitor.refresh_verification(["mem_123", "mem_456"])
            >>> print(f"Refreshed {count} memories")
        """
        refreshed = 0

        try:
            all_memories = self.client.get_all(user_id="orchestrator")

            for memory_id in memory_ids:
                try:
                    # Find memory
                    memory = next(
                        (m for m in all_memories if m.get("id") == memory_id), None
                    )

                    if not memory:
                        logger.warning(f"Memory {memory_id} not found")
                        continue

                    # Update last_verified
                    current_metadata = memory.get("metadata", {})
                    updated_metadata = current_metadata.copy()
                    updated_metadata["last_verified"] = datetime.now(
                        timezone.utc
                    ).isoformat()

                    # Update memory
                    self.client.update(
                        memory_id=memory_id,
                        data=memory.get("memory", ""),
                        metadata=updated_metadata,
                    )

                    refreshed += 1
                    logger.info(f"Refreshed verification for memory {memory_id}")

                except Exception as e:
                    logger.error(f"Failed to refresh memory {memory_id}: {e}")
                    # Continue refreshing other memories

            logger.info(
                f"Refreshed verification for {refreshed}/{len(memory_ids)} memories"
            )
            return refreshed

        except Exception as e:
            logger.error(f"Failed to refresh verification: {e}")
            raise


def scan_stale_memories(
    staleness_days: int = 90, client: Optional[Mem0Client] = None
) -> list[dict]:
    """Convenience function to scan for stale memories.

    Creates MemoryHealthMonitor and scans for stale memories in one call.

    Args:
        staleness_days: Threshold for marking as stale (default: 90)
        client: Optional Mem0Client instance. If None, uses get_mem0_client()

    Returns:
        List of stale memory dicts with id, content, last_verified, age_days

    Example:
        >>> stale = scan_stale_memories(staleness_days=60)
        >>> print(f"Found {len(stale)} stale memories")
    """
    monitor = MemoryHealthMonitor(client=client, staleness_days=staleness_days)
    return monitor.scan_stale_memories()


if __name__ == "__main__":
    import sys
    import json

    # Parse args
    staleness_days = 90
    dry_run = True
    for arg in sys.argv[1:]:
        if arg.startswith("--staleness="):
            staleness_days = int(arg.split("=")[1])
        if arg == "--flag":
            dry_run = False

    # Run health check
    monitor = MemoryHealthMonitor(staleness_days=staleness_days)
    report = monitor.generate_health_report()

    print("Memory Health Report")
    print("====================")
    print(f"Total: {report.total_memories}")
    print(f"Healthy: {report.healthy}")
    print(f"Stale: {report.stale}")
    print(f"Deprecated: {report.deprecated}")
    print(f"Missing metadata: {report.missing_metadata}")
    print(f"\nAge distribution: {json.dumps(report.age_distribution, indent=2)}")

    if report.stale > 0 and not dry_run:
        count = monitor.flag_stale_memories(dry_run=False)
        print(f"\nFlagged {count} stale memories as deprecated")


__all__ = ["MemoryHealthMonitor", "HealthReport", "scan_stale_memories"]
