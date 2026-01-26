"""Quota state persistence for AI orchestrator."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class QuotaState:
    """Represents persisted quota state."""
    limits: Dict[str, Dict[str, Any]]  # Serialized QuotaLimit data
    last_updated: str  # ISO format datetime
    version: str = "1.0"


class QuotaPersistence:
    """Handles quota state storage to JSON file."""

    def __init__(self, storage_path: str = "./.memory/quota_state.json"):
        """
        Initialize quota persistence.

        Args:
            storage_path: Path to JSON storage file
        """
        self.storage_path = Path(storage_path)

    def load(self) -> Optional[QuotaState]:
        """
        Load quota state from JSON file.

        Returns:
            QuotaState if file exists and is valid, None otherwise
        """
        if not self.storage_path.exists():
            logger.debug(f"Quota state file does not exist: {self.storage_path}")
            return None

        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Validate required fields
            if not all(key in data for key in ['limits', 'last_updated', 'version']):
                logger.warning(f"Quota state file missing required fields: {self.storage_path}")
                return None

            return QuotaState(
                limits=data['limits'],
                last_updated=data['last_updated'],
                version=data['version']
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Corrupted quota state file (invalid JSON): {self.storage_path} - {e}")
            return None
        except Exception as e:
            logger.error(f"Error loading quota state: {e}")
            return None

    def save(self, state: QuotaState) -> None:
        """
        Save quota state to JSON file atomically.

        Args:
            state: QuotaState to persist

        Raises:
            PermissionError: If file cannot be written
            IOError: If write operation fails
        """
        # Ensure parent directory exists
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to temp file, then rename
        temp_path = self.storage_path.with_suffix('.tmp')

        try:
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(asdict(state), f, indent=2, ensure_ascii=False)

            # Atomic rename
            temp_path.replace(self.storage_path)
            logger.debug(f"Quota state saved to {self.storage_path}")

        except PermissionError as e:
            raise PermissionError(f"Cannot write quota state to {self.storage_path}: {e}")
        except Exception as e:
            # Clean up temp file if it exists
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise IOError(f"Failed to save quota state: {e}")

    def clear(self) -> None:
        """
        Delete quota state file.

        Used primarily for testing to reset state.
        """
        if self.storage_path.exists():
            try:
                self.storage_path.unlink()
                logger.debug(f"Quota state cleared: {self.storage_path}")
            except Exception as e:
                logger.error(f"Failed to clear quota state: {e}")


# Module-level convenience functions

def load_quota_state(path: Optional[str] = None) -> Optional[QuotaState]:
    """
    Load quota state from JSON file.

    Args:
        path: Optional custom path (defaults to ./.memory/quota_state.json)

    Returns:
        QuotaState if file exists and is valid, None otherwise
    """
    persistence = QuotaPersistence(path) if path else QuotaPersistence()
    return persistence.load()


def save_quota_state(state: QuotaState, path: Optional[str] = None) -> None:
    """
    Save quota state to JSON file.

    Args:
        state: QuotaState to persist
        path: Optional custom path (defaults to ./.memory/quota_state.json)

    Raises:
        PermissionError: If file cannot be written
        IOError: If write operation fails
    """
    persistence = QuotaPersistence(path) if path else QuotaPersistence()
    persistence.save(state)
