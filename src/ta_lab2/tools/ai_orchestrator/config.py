"""Configuration management for AI orchestrator.

Loads configuration from environment variables and provides validation.
"""
import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorConfig:
    """Configuration for AI orchestrator adapters and quota management."""

    # API Keys
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    google_credentials_path: Optional[str] = None

    # Quota Settings
    gemini_daily_quota: int = 1500
    quota_alert_thresholds: list[int] = field(default_factory=lambda: [50, 80, 90])

    # Memory Configuration
    mem0_storage_path: str = "./.memory/mem0"
    vertex_ai_project: Optional[str] = None
    vertex_ai_location: str = "us-central1"


def load_config() -> OrchestratorConfig:
    """Load configuration from environment variables.

    Attempts to load .env file if python-dotenv is available.
    Logs warnings for missing optional keys but does not fail.

    Returns:
        OrchestratorConfig instance populated from environment variables
    """
    # Try to load .env file if dotenv is available
    if load_dotenv is not None:
        env_path = Path(".env")
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)
            logger.info("Loaded configuration from .env file")
        else:
            logger.debug(".env file not found, using system environment variables")

    # Parse quota alert thresholds
    thresholds_str = os.environ.get("QUOTA_ALERT_THRESHOLDS", "50,80,90")
    try:
        quota_alert_thresholds = [int(x.strip()) for x in thresholds_str.split(",")]
    except ValueError:
        logger.warning(f"Invalid QUOTA_ALERT_THRESHOLDS format: {thresholds_str}, using defaults")
        quota_alert_thresholds = [50, 80, 90]

    # Build config
    config = OrchestratorConfig(
        openai_api_key=os.environ.get("OPENAI_API_KEY"),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
        google_credentials_path=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"),
        gemini_daily_quota=int(os.environ.get("GEMINI_DAILY_QUOTA", "1500")),
        quota_alert_thresholds=quota_alert_thresholds,
        mem0_storage_path=os.environ.get("MEM0_STORAGE_PATH", "./.memory/mem0"),
        vertex_ai_project=os.environ.get("VERTEX_AI_PROJECT"),
        vertex_ai_location=os.environ.get("VERTEX_AI_LOCATION", "us-central1"),
    )

    # Log warnings for missing optional keys
    if not config.openai_api_key:
        logger.warning("OPENAI_API_KEY not set - OpenAI adapter will not be available")
    if not config.anthropic_api_key:
        logger.debug("ANTHROPIC_API_KEY not set - Claude API mode not configured")
    if not config.google_credentials_path:
        logger.warning("GOOGLE_APPLICATION_CREDENTIALS not set - Gemini adapter may not work")
    if not config.vertex_ai_project:
        logger.debug("VERTEX_AI_PROJECT not set - Memory Bank cloud storage not configured")

    return config


def validate_config(config: OrchestratorConfig) -> dict[str, bool]:
    """Validate configuration and report which SDKs are properly configured.

    Does not fail on missing keys - just reports status.

    Args:
        config: OrchestratorConfig instance to validate

    Returns:
        Dictionary mapping SDK names to configuration status:
        - 'openai': True if OpenAI API key is set
        - 'anthropic': True if Anthropic API key is set
        - 'google': True if Google credentials path is set
        - 'vertex_memory': True if Vertex AI project is configured
    """
    status = {
        'openai': bool(config.openai_api_key),
        'anthropic': bool(config.anthropic_api_key),
        'google': bool(config.google_credentials_path),
        'vertex_memory': bool(config.vertex_ai_project),
    }

    logger.info(f"SDK configuration status: {status}")
    return status


__all__ = ['OrchestratorConfig', 'load_config', 'validate_config']
