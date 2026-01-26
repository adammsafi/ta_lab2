"""Pre-flight validation for platform adapters - implements double-check pattern."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Platform, Task
    from .adapters import BasePlatformAdapter

from .core import Platform as Plat


@dataclass
class ValidationResult:
    """
    Result from validating a platform adapter.

    Attributes:
        adapter_name: Name of the adapter
        is_valid: True if adapter can be used
        is_implemented: True if adapter has working implementation
        status: Implementation status ('working', 'partial', 'stub', 'unavailable', 'error')
        message: Human-readable validation message
        requirements_met: Dict of requirement checks
        timestamp: When validation occurred
    """
    adapter_name: str
    is_valid: bool
    is_implemented: bool
    status: str
    message: str
    requirements_met: dict[str, bool]
    timestamp: datetime


class AdapterValidator:
    """
    Validates platform adapters for routing and execution.

    Implements double-check pattern:
    1. Routing checkpoint: get_available_platforms() filters out stubs/unavailable
    2. Execution checkpoint: pre_flight_check() verifies before execution
    """

    def __init__(self, adapters: dict[Platform, BasePlatformAdapter]):
        """
        Initialize validator with platform adapters.

        Args:
            adapters: Dict mapping Platform enum to adapter instances
        """
        self.adapters = adapters

    def validate_adapter(self, platform: Platform) -> ValidationResult:
        """
        Validate a specific adapter.

        Checks:
        - is_implemented property
        - Environment variables (API keys)
        - CLI tools availability
        - Adapter-specific requirements

        Args:
            platform: Platform to validate

        Returns:
            ValidationResult with comprehensive status
        """
        adapter = self.adapters.get(platform)
        if not adapter:
            return ValidationResult(
                adapter_name=platform.value,
                is_valid=False,
                is_implemented=False,
                status="error",
                message=f"Adapter not found for {platform.value}",
                requirements_met={},
                timestamp=datetime.utcnow()
            )

        # Get adapter status
        try:
            status_info = adapter.get_adapter_status()
            is_implemented = adapter.is_implemented
            impl_status = adapter.implementation_status

            # Check environment variables based on platform
            requirements_met = self._check_requirements(platform)

            # Determine if adapter is valid (implemented AND requirements met)
            is_valid = is_implemented and all(requirements_met.values())

            # Build message
            if is_valid:
                message = f"{status_info['name']} is ready to use"
            elif not is_implemented:
                message = f"{status_info['name']} is not yet implemented (status: {impl_status})"
            else:
                missing = [k for k, v in requirements_met.items() if not v]
                message = f"{status_info['name']} missing requirements: {', '.join(missing)}"

            return ValidationResult(
                adapter_name=status_info['name'],
                is_valid=is_valid,
                is_implemented=is_implemented,
                status=impl_status,
                message=message,
                requirements_met=requirements_met,
                timestamp=datetime.utcnow()
            )

        except Exception as e:
            return ValidationResult(
                adapter_name=platform.value,
                is_valid=False,
                is_implemented=False,
                status="error",
                message=f"Validation error: {str(e)}",
                requirements_met={},
                timestamp=datetime.utcnow()
            )

    def validate_all(self) -> dict[Platform, ValidationResult]:
        """
        Validate all adapters.

        Returns:
            Dict mapping Platform to ValidationResult
        """
        return {
            platform: self.validate_adapter(platform)
            for platform in self.adapters.keys()
        }

    def get_available_platforms(self) -> list[Platform]:
        """
        Get list of available (implemented) platforms.

        FIRST VALIDATION CHECKPOINT: Used by router to filter stubs.

        Returns:
            List of platforms that are implemented (even if missing some requirements)
        """
        available = []
        for platform in self.adapters.keys():
            adapter = self.adapters[platform]
            if adapter.is_implemented:
                available.append(platform)
        return available

    def get_unavailable_platforms(self) -> list[Platform]:
        """
        Get list of unavailable platforms (stubs or broken).

        Returns:
            List of platforms that are not implemented
        """
        unavailable = []
        for platform in self.adapters.keys():
            adapter = self.adapters[platform]
            if not adapter.is_implemented:
                unavailable.append(platform)
        return unavailable

    def is_platform_available(self, platform: Platform) -> bool:
        """
        Quick check if a platform is available.

        Args:
            platform: Platform to check

        Returns:
            True if platform is implemented
        """
        adapter = self.adapters.get(platform)
        return adapter.is_implemented if adapter else False

    def _check_requirements(self, platform: Platform) -> dict[str, bool]:
        """
        Check platform-specific requirements.

        Args:
            platform: Platform to check

        Returns:
            Dict of requirement name -> met status
        """
        requirements = {}

        if platform == Plat.CHATGPT:
            requirements["OPENAI_API_KEY"] = bool(os.environ.get("OPENAI_API_KEY"))

        elif platform == Plat.GEMINI:
            # Gemini checks gcloud availability in its own _check_gcloud_available
            adapter = self.adapters[platform]
            requirements["gcloud_cli"] = adapter.is_implemented

        elif platform == Plat.CLAUDE_CODE:
            # Claude Code works if we're running in it
            requirements["claude_code_session"] = True

        return requirements


def pre_flight_check(task: Task, validator: AdapterValidator) -> tuple[bool, str]:
    """
    SECOND VALIDATION CHECKPOINT: Execution-time safety check.

    Verifies that a task can actually be executed before attempting.

    Args:
        task: Task to validate
        validator: AdapterValidator instance

    Returns:
        Tuple of (can_execute: bool, reason_if_not: str)
    """
    # Get available platforms
    available = validator.get_available_platforms()

    if not available:
        unavailable = validator.get_unavailable_platforms()
        unavailable_names = [p.value for p in unavailable]
        return (
            False,
            f"No implemented adapters available. Stubs: {', '.join(unavailable_names)}. "
            "Please implement at least one adapter to execute tasks."
        )

    # If platform_hint specified, validate it specifically
    if task.platform_hint:
        if not validator.is_platform_available(task.platform_hint):
            result = validator.validate_adapter(task.platform_hint)
            available_names = [p.value for p in available]
            return (
                False,
                f"Requested platform {task.platform_hint.value} is not available: {result.message}. "
                f"Available platforms: {', '.join(available_names)}"
            )

    # At least one platform is available
    return (True, "")


def validate_adapters(orchestrator) -> dict[Platform, ValidationResult]:
    """
    Convenience function to validate all adapters in an orchestrator.

    Args:
        orchestrator: Orchestrator instance with validator

    Returns:
        Dict mapping Platform to ValidationResult
    """
    return orchestrator.validator.validate_all()
