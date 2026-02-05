"""
Metadata capture for baseline validation reproducibility.

Captures full audit trail (git hash, timestamp, config) to enable reproduction
of baseline capture runs for debugging and investigation.

Pattern from Phase 25 RESEARCH.md:
- Git commit hash for exact code version
- ISO-8601 timestamp for unambiguous ordering
- Asset count and date range for scope validation
- Script versions for debugging
- Database connection details (redacted for logging)
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class BaselineConfig:
    """
    Configuration for baseline capture run.

    Args:
        assets: List of asset IDs to validate
        start_date: Start date for rebuild (YYYY-MM-DD)
        end_date: End date for rebuild (YYYY-MM-DD)
        bar_scripts: List of bar builder scripts to invoke
        ema_scripts: List of EMA refresher scripts to invoke
        db_url: Database connection URL
        epsilon_rtol: Relative tolerance for comparison (default: 1e-5)
        epsilon_atol: Absolute tolerance for comparison (default: 1e-6)
        sampling: Sampling strategy dict (default: empty)
    """

    assets: list[int]
    start_date: str
    end_date: str
    bar_scripts: list[str]
    ema_scripts: list[str]
    db_url: str
    epsilon_rtol: float = 1e-5
    epsilon_atol: float = 1e-6
    sampling: dict[str, Any] = field(default_factory=dict)


@dataclass
class BaselineMetadata:
    """
    Full audit trail for baseline capture reproducibility.

    Attributes:
        capture_timestamp: ISO-8601 UTC timestamp of capture
        git_commit_hash: Git commit hash for exact code version
        git_branch: Git branch name
        git_is_dirty: True if uncommitted changes present
        asset_count: Number of assets validated
        asset_ids: List of asset IDs validated
        date_range_start: Start date of validation range
        date_range_end: End date of validation range
        bar_builders_invoked: List of bar builder scripts executed
        ema_refreshers_invoked: List of EMA refresher scripts executed
        db_url: Database URL (password redacted for logging)
        snapshot_table_suffix: Timestamp suffix for snapshot tables
        epsilon_rtol: Relative tolerance used for comparison
        epsilon_atol: Absolute tolerance used for comparison
        sampling_strategy: Sampling strategy dict
    """

    capture_timestamp: str
    git_commit_hash: str
    git_branch: str
    git_is_dirty: bool
    asset_count: int
    asset_ids: list[int]
    date_range_start: str
    date_range_end: str
    bar_builders_invoked: list[str]
    ema_refreshers_invoked: list[str]
    db_url: str
    snapshot_table_suffix: str
    epsilon_rtol: float
    epsilon_atol: float
    sampling_strategy: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize to dictionary for JSON logging.

        Returns:
            Dictionary with nested structure for readability
        """
        return {
            "capture_timestamp": self.capture_timestamp,
            "git": {
                "commit_hash": self.git_commit_hash,
                "branch": self.git_branch,
                "dirty": self.git_is_dirty,
            },
            "assets": {
                "count": self.asset_count,
                "ids": self.asset_ids,
            },
            "date_range": {
                "start": self.date_range_start,
                "end": self.date_range_end,
            },
            "scripts": {
                "bar_builders": self.bar_builders_invoked,
                "ema_refreshers": self.ema_refreshers_invoked,
            },
            "database": {
                "url": self.db_url.split("@")[-1]
                if "@" in self.db_url
                else self.db_url,
                "snapshot_suffix": self.snapshot_table_suffix,
            },
            "comparison_config": {
                "epsilon_rtol": self.epsilon_rtol,
                "epsilon_atol": self.epsilon_atol,
                "sampling": self.sampling_strategy,
            },
        }


def capture_metadata(config: BaselineConfig) -> BaselineMetadata:
    """
    Capture full metadata for audit trail.

    Executes git commands to capture:
    - Commit hash (exact code version)
    - Branch name
    - Dirty status (uncommitted changes)

    Also generates timestamp and redacts password from database URL.

    Args:
        config: BaselineConfig with validation parameters

    Returns:
        BaselineMetadata with full audit trail

    Raises:
        subprocess.CalledProcessError: If git commands fail
    """
    # Get project root (where .git directory is)
    project_root = Path(__file__).parent.parent.parent.parent.parent

    # Git commit hash
    git_hash = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        text=True,
    ).strip()

    # Git branch
    git_branch = subprocess.check_output(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=project_root,
        text=True,
    ).strip()

    # Git dirty status (return code 0 = clean, non-zero = dirty)
    git_dirty_result = subprocess.run(
        ["git", "diff", "--quiet"],
        cwd=project_root,
        capture_output=True,
    )
    git_dirty = git_dirty_result.returncode != 0

    # Timestamp in ISO-8601 UTC (for snapshot table suffix)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    return BaselineMetadata(
        capture_timestamp=timestamp,
        git_commit_hash=git_hash,
        git_branch=git_branch,
        git_is_dirty=git_dirty,
        asset_count=len(config.assets),
        asset_ids=config.assets,
        date_range_start=config.start_date,
        date_range_end=config.end_date,
        bar_builders_invoked=config.bar_scripts,
        ema_refreshers_invoked=config.ema_scripts,
        db_url=config.db_url,
        snapshot_table_suffix=timestamp,
        epsilon_rtol=config.epsilon_rtol,
        epsilon_atol=config.epsilon_atol,
        sampling_strategy=config.sampling,
    )


def save_metadata(metadata: BaselineMetadata, output_path: str | Path) -> None:
    """
    Save metadata as JSON to output path.

    Creates parent directories if needed.

    Args:
        metadata: BaselineMetadata to serialize
        output_path: Path to JSON file

    Example:
        >>> metadata = capture_metadata(config)
        >>> save_metadata(metadata, ".logs/baseline-capture-20260205.json")
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metadata.to_dict(), f, indent=2, ensure_ascii=False)
