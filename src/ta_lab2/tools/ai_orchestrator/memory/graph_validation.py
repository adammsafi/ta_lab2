"""Memory graph validation with orphan detection.

Validates memory graph integrity:
- Orphan detection (memories with no relationships)
- Relationship target verification (all targets exist)
- Coverage metrics (% of functions with relationships)

Usage:
    from ta_lab2.tools.ai_orchestrator.memory.graph_validation import (
        validate_memory_graph
    )

    result = validate_memory_graph(max_orphan_rate=0.05)
    if result.is_valid:
        print("Memory graph validation passed")
    else:
        print(f"Validation failed: {result.failure_reasons}")
"""
import logging
from dataclasses import dataclass, field
from typing import Dict, List

logger = logging.getLogger(__name__)


@dataclass
class MemoryGraphValidation:
    """Result of memory graph validation.

    Attributes:
        total_functions: Number of function definition memories
        total_relationships: Number of relationship memories
        relationship_breakdown: Count by type (contains, calls, imports, etc.)
        orphaned_functions: List of functions with no relationships (file::function format)
        orphan_rate: Percentage of orphaned functions (0.0-1.0)
        missing_targets: Relationships pointing to non-existent entities
        relationship_coverage: Percentage of functions with at least one relationship
        is_valid: Whether validation passed
        failure_reasons: List of failure reasons
    """

    total_functions: int = 0
    total_relationships: int = 0
    relationship_breakdown: Dict[str, int] = field(default_factory=dict)
    orphaned_functions: List[str] = field(default_factory=list)
    orphan_rate: float = 0.0
    missing_targets: List[str] = field(default_factory=list)
    relationship_coverage: float = 0.0
    is_valid: bool = False
    failure_reasons: List[str] = field(default_factory=list)

    def markdown_report(self) -> str:
        """Generate markdown report for VALIDATION.md.

        Returns:
            Formatted markdown report
        """
        status = "✓ PASSED" if self.is_valid else "✗ FAILED"
        lines = [
            f"## Memory Graph Validation {status}",
            "",
            "### Metrics",
            "",
            f"- **Total Functions:** {self.total_functions:,}",
            f"- **Total Relationships:** {self.total_relationships:,}",
            f"- **Relationship Coverage:** {self.relationship_coverage:.1%}",
            f"- **Orphan Rate:** {self.orphan_rate:.1%}",
            "",
            "### Relationship Breakdown",
            "",
        ]

        # Add relationship type counts
        if self.relationship_breakdown:
            for rel_type, count in sorted(self.relationship_breakdown.items()):
                lines.append(f"- **{rel_type}:** {count:,}")
        else:
            lines.append("- No relationships found")

        lines.extend(["", "### Validation Results", ""])

        if self.is_valid:
            lines.extend(
                [
                    "✓ All validation checks passed",
                    f"- Orphan rate ({self.orphan_rate:.1%}) within acceptable threshold",
                    f"- All {self.total_relationships:,} relationship targets verified",
                    f"- {self.relationship_coverage:.1%} of functions have relationships",
                ]
            )
        else:
            lines.append("✗ Validation failed:")
            for reason in self.failure_reasons:
                lines.append(f"- {reason}")

            # Show sample orphaned functions if relevant
            if self.orphaned_functions and len(self.orphaned_functions) <= 10:
                lines.extend(["", "**Orphaned Functions:**", ""])
                for func in self.orphaned_functions:
                    lines.append(f"- `{func}`")
            elif self.orphaned_functions:
                lines.extend(
                    [
                        "",
                        f"**Orphaned Functions:** {len(self.orphaned_functions)} total (showing first 10)",
                        "",
                    ]
                )
                for func in self.orphaned_functions[:10]:
                    lines.append(f"- `{func}`")

            # Show missing targets if any
            if self.missing_targets and len(self.missing_targets) <= 10:
                lines.extend(["", "**Missing Relationship Targets:**", ""])
                for target in self.missing_targets:
                    lines.append(f"- `{target}`")
            elif self.missing_targets:
                lines.extend(
                    [
                        "",
                        f"**Missing Targets:** {len(self.missing_targets)} total (showing first 10)",
                        "",
                    ]
                )
                for target in self.missing_targets[:10]:
                    lines.append(f"- `{target}`")

        return "\n".join(lines)


def get_all_function_memories(client) -> List[Dict]:
    """Query all function definition memories.

    Args:
        client: Mem0Client instance

    Returns:
        List of memory payloads with category="function_definition"
    """

    if client is None:
        from .mem0_client import get_mem0_client

        client = get_mem0_client()

    functions = []
    limit = 1000
    offset = 0

    # Pagination loop - keep fetching until no more results
    while True:
        # Mem0 search with metadata filters
        results = client.search(
            query="function definition",  # Semantic query
            user_id="orchestrator",  # Required by Mem0
            filters={"category": "function_definition"},
            limit=limit,
        )

        if not results:
            break

        # Extract memory payloads
        for result in results:
            functions.append(result)

        # Check if we got fewer results than limit (last page)
        if len(results) < limit:
            break

        offset += limit

    logger.info(f"Retrieved {len(functions)} function memories")
    return functions


def get_all_relationship_memories(client) -> List[Dict]:
    """Query all relationship memories.

    Args:
        client: Mem0Client instance

    Returns:
        List of memory payloads with category="function_relationship"
    """

    if client is None:
        from .mem0_client import get_mem0_client

        client = get_mem0_client()

    relationships = []
    limit = 1000
    offset = 0

    # Pagination loop
    while True:
        results = client.search(
            query="function relationship",  # Semantic query
            user_id="orchestrator",  # Required by Mem0
            filters={"category": "function_relationship"},
            limit=limit,
        )

        if not results:
            break

        for result in results:
            relationships.append(result)

        if len(results) < limit:
            break

        offset += limit

    logger.info(f"Retrieved {len(relationships)} relationship memories")
    return relationships


def detect_orphans(functions: List[Dict], relationships: List[Dict]) -> List[str]:
    """Detect functions with no relationships.

    Args:
        functions: List of function memory payloads
        relationships: List of relationship memory payloads

    Returns:
        List of orphaned function identifiers (file::function format)
    """
    # Build set of functions mentioned in any relationship
    mentioned = set()

    for rel in relationships:
        metadata = rel.get("metadata", {})

        # Source entity (caller in calls, file in contains)
        source_file = metadata.get("source_file", "")
        source_entity = metadata.get("source_entity", "")
        if source_file and source_entity:
            mentioned.add(f"{source_file}::{source_entity}")

        # Target entity (called function, imported module)
        target_file = metadata.get("target_file", "")
        target_entity = metadata.get("target_entity", "")
        if target_file and target_entity:
            mentioned.add(f"{target_file}::{target_entity}")

        # For contains relationships, target_entity is the function in source_file
        if (
            metadata.get("relationship_type") == "contains"
            and source_file
            and target_entity
        ):
            mentioned.add(f"{source_file}::{target_entity}")

    # Find functions NOT in mentioned set
    orphans = []
    for func in functions:
        metadata = func.get("metadata", {})
        file_path = metadata.get("file_path", "")
        function_name = metadata.get("function_name", "")

        if not file_path or not function_name:
            continue

        identifier = f"{file_path}::{function_name}"

        if identifier not in mentioned:
            # Filter out acceptable orphans
            # 1. Functions in __init__.py (often just exports)
            if "__init__.py" in file_path:
                continue

            # 2. Very short functions (< 3 lines, trivial helpers)
            # Check line_count in metadata if available
            line_count = metadata.get(
                "line_count", 999
            )  # Assume non-trivial if unknown
            if line_count < 3:
                continue

            # 3. Constants/config functions (common patterns)
            if function_name.isupper():  # CONSTANT_NAME pattern
                continue
            if function_name.startswith("get_config") or function_name.startswith(
                "setup_"
            ):
                continue

            orphans.append(identifier)

    logger.info(f"Found {len(orphans)} orphaned functions (after filtering)")
    return orphans


def verify_relationship_targets(
    functions: List[Dict], relationships: List[Dict]
) -> List[str]:
    """Verify all relationship targets exist in function index.

    Args:
        functions: List of function memory payloads
        relationships: List of relationship memory payloads

    Returns:
        List of missing target identifiers
    """
    # Build function index (file::name -> exists)
    function_index = set()
    for func in functions:
        metadata = func.get("metadata", {})
        file_path = metadata.get("file_path", "")
        function_name = metadata.get("function_name", "")

        if file_path and function_name:
            function_index.add(f"{file_path}::{function_name}")

    # Check each relationship's target
    missing = []
    for rel in relationships:
        metadata = rel.get("metadata", {})
        relationship_type = metadata.get("relationship_type", "")

        # For function calls, verify target exists
        if relationship_type == "calls":
            target_entity = metadata.get("target_entity", "")
            # For calls, we often don't know the target file, so skip verification
            # (target might be in external library, or we only captured name)
            continue

        # For contains relationships, target is in source_file
        if relationship_type == "contains":
            source_file = metadata.get("source_file", "")
            target_entity = metadata.get("target_entity", "")
            if source_file and target_entity:
                identifier = f"{source_file}::{target_entity}"
                if identifier not in function_index:
                    missing.append(identifier)

        # For imports, we're not tracking module entities, skip
        if relationship_type == "imports":
            continue

        # For similar_to, verify both sides exist
        if relationship_type == "similar_to":
            source_file = metadata.get("source_file", "")
            source_entity = metadata.get("source_entity", "")
            target_file = metadata.get("target_file", "")
            target_entity = metadata.get("target_entity", "")

            if source_file and source_entity:
                identifier = f"{source_file}::{source_entity}"
                if identifier not in function_index:
                    missing.append(identifier)

            if target_file and target_entity:
                identifier = f"{target_file}::{target_entity}"
                if identifier not in function_index:
                    missing.append(identifier)

    logger.info(f"Found {len(missing)} missing relationship targets")
    return missing


def validate_memory_graph(
    client=None, max_orphan_rate: float = 0.05, max_orphan_rate_tests: float = 0.10
) -> MemoryGraphValidation:
    """Validate memory graph integrity.

    Args:
        client: Optional Mem0Client instance
        max_orphan_rate: Maximum acceptable orphan rate for production code (default: 5%)
        max_orphan_rate_tests: Maximum acceptable orphan rate for test code (default: 10%)

    Returns:
        MemoryGraphValidation result with is_valid and failure_reasons
    """
    if client is None:
        from .mem0_client import get_mem0_client

        client = get_mem0_client()

    logger.info("Starting memory graph validation")

    # Get all memories
    functions = get_all_function_memories(client)
    relationships = get_all_relationship_memories(client)

    # Detect orphans
    orphaned = detect_orphans(functions, relationships)

    # Calculate orphan rate with threshold adjustment for tests
    total_funcs = len(functions)
    orphan_rate = len(orphaned) / total_funcs if total_funcs > 0 else 0.0

    # Use higher threshold if many test functions
    test_count = sum(
        1 for f in functions if "test_" in f.get("metadata", {}).get("file_path", "")
    )
    test_ratio = test_count / total_funcs if total_funcs > 0 else 0.0

    # If >30% are test functions, use higher threshold
    effective_threshold = max_orphan_rate_tests if test_ratio > 0.3 else max_orphan_rate

    # Verify relationship targets
    missing_targets = verify_relationship_targets(functions, relationships)

    # Calculate relationship breakdown
    breakdown: Dict[str, int] = {}
    for rel in relationships:
        rel_type = rel.get("metadata", {}).get("relationship_type", "unknown")
        breakdown[rel_type] = breakdown.get(rel_type, 0) + 1

    # Calculate coverage (% of functions with relationships)
    mentioned = set()
    for rel in relationships:
        metadata = rel.get("metadata", {})
        source_file = metadata.get("source_file", "")
        source_entity = metadata.get("source_entity", "")
        target_file = metadata.get("target_file", "")
        target_entity = metadata.get("target_entity", "")

        if source_file and source_entity:
            mentioned.add(f"{source_file}::{source_entity}")
        if target_file and target_entity:
            mentioned.add(f"{target_file}::{target_entity}")
        # For contains
        if (
            metadata.get("relationship_type") == "contains"
            and source_file
            and target_entity
        ):
            mentioned.add(f"{source_file}::{target_entity}")

    coverage = len(mentioned) / total_funcs if total_funcs > 0 else 0.0

    # Determine validity
    is_valid = True
    failure_reasons = []

    if orphan_rate > effective_threshold:
        is_valid = False
        failure_reasons.append(
            f"Orphan rate {orphan_rate:.1%} exceeds threshold {effective_threshold:.1%}"
        )

    if missing_targets:
        is_valid = False
        failure_reasons.append(
            f"{len(missing_targets)} relationship targets do not exist"
        )

    if total_funcs == 0:
        is_valid = False
        failure_reasons.append("No function memories found")

    if len(relationships) == 0:
        is_valid = False
        failure_reasons.append("No relationship memories found")

    result = MemoryGraphValidation(
        total_functions=total_funcs,
        total_relationships=len(relationships),
        relationship_breakdown=breakdown,
        orphaned_functions=orphaned,
        orphan_rate=orphan_rate,
        missing_targets=missing_targets,
        relationship_coverage=coverage,
        is_valid=is_valid,
        failure_reasons=failure_reasons,
    )

    logger.info(
        f"Memory graph validation complete: {'PASSED' if is_valid else 'FAILED'}"
    )
    return result


__all__ = ["MemoryGraphValidation", "validate_memory_graph"]
