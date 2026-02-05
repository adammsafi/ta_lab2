"""
Configuration dataclass for bar builders.

Mirrors EMARefresherConfig pattern from base_ema_refresher.py.
Provides type-safe configuration for all bar builder variants.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BarBuilderConfig:
    """
    Configuration for bar builders - mirrors EMARefresherConfig pattern.

    Attributes:
        db_url: SQLAlchemy database URL
        ids: List of cryptocurrency IDs to process
        daily_table: Source daily price table name
        bars_table: Output bars table name
        state_table: State tracking table name
        full_rebuild: If True, delete and rebuild all bars
        keep_rejects: If True, log OHLC violations to rejects table
        rejects_table: Table name for OHLC violations
        num_processes: Number of parallel worker processes
        log_level: Logging level (INFO, DEBUG, etc.)
        log_file: Optional log file path
        tz: Timezone for calendar builders (None for non-calendar)
        extra_config: Variant-specific configuration (alignment_type, etc.)
    """

    db_url: str
    ids: list[int]
    daily_table: str
    bars_table: str
    state_table: str
    full_rebuild: bool = False
    keep_rejects: bool = False
    rejects_table: str | None = None
    num_processes: int = 6
    log_level: str = "INFO"
    log_file: str | None = None
    tz: str | None = None
    extra_config: dict[str, Any] | None = None

    def __post_init__(self):
        """Ensure extra_config is a dict (not None)."""
        if self.extra_config is None:
            object.__setattr__(self, "extra_config", {})
