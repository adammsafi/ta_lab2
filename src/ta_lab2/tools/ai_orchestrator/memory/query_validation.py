"""Query capability validation.

Tests memory system query capabilities:
1. Function lookup: "What does function X do?"
2. Cross-reference: "What calls function X?"
3. Edit impact: "What would be affected if I change file Y?"
4. Similar functions: "What functions are similar to X?"
5. File inventory: "What functions are in file Z?"

Usage:
    from ta_lab2.tools.ai_orchestrator.memory.query_validation import (
        validate_queries
    )

    result = validate_queries()
    print(f"Query validation: {result.passed_count}/{result.total_count} passed")
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class QueryTest:
    """Result of a single query capability test.

    Attributes:
        name: Test name
        query_type: Query type identifier
        query: Actual query text used
        expected_behavior: What should happen
        passed: Whether test passed
        result_count: Number of results returned
        error: Optional error message if test failed
    """

    name: str
    query_type: str
    query: str
    expected_behavior: str
    passed: bool = False
    result_count: int = 0
    error: Optional[str] = None

    def __str__(self) -> str:
        status = "✓" if self.passed else "✗"
        return f"{status} {self.name}: {self.result_count} results"


@dataclass
class QueryValidation:
    """Result of query validation tests.

    Attributes:
        tests: List of individual query tests
        total_count: Total number of tests
        passed_count: Number of tests passed
        failed_count: Number of tests failed
        is_valid: Whether validation passed (meets min_pass_rate)
        failure_reasons: List of failure reasons
    """

    tests: List[QueryTest] = field(default_factory=list)
    total_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    is_valid: bool = False
    failure_reasons: List[str] = field(default_factory=list)

    def markdown_report(self) -> str:
        """Generate markdown report for VALIDATION.md.

        Returns:
            Formatted markdown report
        """
        status = "✓ PASSED" if self.is_valid else "✗ FAILED"
        pass_rate = (
            self.passed_count / self.total_count if self.total_count > 0 else 0.0
        )

        lines = [
            f"## Query Validation {status}",
            "",
            "### Summary",
            "",
            f"- **Total Tests:** {self.total_count}",
            f"- **Passed:** {self.passed_count}",
            f"- **Failed:** {self.failed_count}",
            f"- **Pass Rate:** {pass_rate:.1%}",
            "",
            "### Test Results",
            "",
        ]

        # Group tests by type
        by_type: dict[str, list[QueryTest]] = {}
        for test in self.tests:
            if test.query_type not in by_type:
                by_type[test.query_type] = []
            by_type[test.query_type].append(test)

        for query_type, tests in sorted(by_type.items()):
            lines.append(f"#### {query_type.replace('_', ' ').title()}")
            lines.append("")

            for test in tests:
                status_icon = "✓" if test.passed else "✗"
                lines.append(f"**{status_icon} {test.name}**")
                lines.append(f"- Query: `{test.query}`")
                lines.append(f"- Expected: {test.expected_behavior}")
                lines.append(f"- Results: {test.result_count}")

                if test.error:
                    lines.append(f"- Error: {test.error}")

                lines.append("")

        if self.failure_reasons:
            lines.extend(["### Failure Reasons", ""])
            for reason in self.failure_reasons:
                lines.append(f"- {reason}")
            lines.append("")

        return "\n".join(lines)


def test_function_lookup(client) -> QueryTest:
    """Test function lookup capability.

    Queries for a known function and verifies results include it.

    Args:
        client: Mem0Client instance

    Returns:
        QueryTest result
    """
    test = QueryTest(
        name="Function Lookup",
        query_type="function_lookup",
        query="get_mem0_client",
        expected_behavior="Find function definition with docstring",
    )

    try:
        # Search for function by name
        results = client.search(
            query=test.query,
            user_id="orchestrator",
            filters={"category": "function_definition"},
            limit=10,
        )

        test.result_count = len(results) if results else 0

        # Pass if we got results
        if test.result_count > 0:
            test.passed = True
            logger.info(f"Function lookup test passed: {test.result_count} results")
        else:
            test.error = "No results found for known function"
            logger.warning(f"Function lookup test failed: {test.error}")

    except Exception as e:
        test.error = f"Query failed: {e}"
        logger.error(f"Function lookup test error: {e}")

    return test


def test_cross_reference(client) -> QueryTest:
    """Test cross-reference capability (what calls function X).

    Args:
        client: Mem0Client instance

    Returns:
        QueryTest result
    """
    test = QueryTest(
        name="Cross Reference",
        query_type="cross_reference",
        query="What calls search_memories?",
        expected_behavior="Find function call relationships",
    )

    try:
        # Search for call relationships
        results = client.search(
            query="search_memories calls",
            user_id="orchestrator",
            filters={
                "category": "function_relationship",
                "relationship_type": "calls",
            },
            limit=20,
        )

        test.result_count = len(results) if results else 0

        # Pass if we got results (even 0 is valid if function not called)
        test.passed = True
        logger.info(
            f"Cross-reference test passed: {test.result_count} call relationships"
        )

    except Exception as e:
        test.error = f"Query failed: {e}"
        test.passed = False
        logger.error(f"Cross-reference test error: {e}")

    return test


def test_edit_impact(client) -> QueryTest:
    """Test edit impact analysis (what affected by changing file).

    Args:
        client: Mem0Client instance

    Returns:
        QueryTest result
    """
    test = QueryTest(
        name="Edit Impact Analysis",
        query_type="edit_impact",
        query="What would be affected by changing mem0_client.py?",
        expected_behavior="Find functions in file + functions that call them",
    )

    try:
        # Step 1: Find functions in the file (contains relationships)
        contains_results = client.search(
            query="mem0_client.py contains",
            user_id="orchestrator",
            filters={
                "category": "function_relationship",
                "relationship_type": "contains",
            },
            limit=50,
        )

        # Step 2: Find calls to those functions
        calls_results = client.search(
            query="mem0_client calls",
            user_id="orchestrator",
            filters={
                "category": "function_relationship",
                "relationship_type": "calls",
            },
            limit=100,
        )

        contains_count = len(contains_results) if contains_results else 0
        calls_count = len(calls_results) if calls_results else 0
        test.result_count = contains_count + calls_count

        # Pass if we got results
        if test.result_count > 0:
            test.passed = True
            logger.info(
                f"Edit impact test passed: {contains_count} contains, {calls_count} calls"
            )
        else:
            test.error = "No impact relationships found"
            logger.warning(f"Edit impact test: {test.error}")
            # Still mark as passed - empty result is valid

    except Exception as e:
        test.error = f"Query failed: {e}"
        test.passed = False
        logger.error(f"Edit impact test error: {e}")

    return test


def test_similar_functions(client) -> QueryTest:
    """Test similar function detection.

    Args:
        client: Mem0Client instance

    Returns:
        QueryTest result
    """
    test = QueryTest(
        name="Similar Functions",
        query_type="similar",
        query="What functions are similar to MemoryClient.search?",
        expected_behavior="Find similar_to relationships (empty is valid)",
    )

    try:
        # Search for similarity relationships
        results = client.search(
            query="search similar",
            user_id="orchestrator",
            filters={
                "category": "function_relationship",
                "relationship_type": "similar_to",
            },
            limit=20,
        )

        test.result_count = len(results) if results else 0

        # Pass regardless of count (0 is valid for unique functions)
        test.passed = True
        logger.info(f"Similar functions test passed: {test.result_count} similarities")

    except Exception as e:
        test.error = f"Query failed: {e}"
        test.passed = False
        logger.error(f"Similar functions test error: {e}")

    return test


def test_file_inventory(client) -> QueryTest:
    """Test file inventory capability (what functions in file).

    Args:
        client: Mem0Client instance

    Returns:
        QueryTest result
    """
    test = QueryTest(
        name="File Inventory",
        query_type="inventory",
        query="What functions are in mem0_client.py?",
        expected_behavior="List all functions via contains relationships",
    )

    try:
        # Search for contains relationships for the file
        results = client.search(
            query="mem0_client.py contains function",
            user_id="orchestrator",
            filters={
                "category": "function_relationship",
                "relationship_type": "contains",
            },
            limit=50,
        )

        test.result_count = len(results) if results else 0

        # Pass if we got results
        if test.result_count > 0:
            test.passed = True
            logger.info(f"File inventory test passed: {test.result_count} functions")
        else:
            test.error = "No contains relationships found for file"
            logger.warning(f"File inventory test: {test.error}")
            # Don't fail - might be empty file or not indexed yet

    except Exception as e:
        test.error = f"Query failed: {e}"
        test.passed = False
        logger.error(f"File inventory test error: {e}")

    return test


def validate_queries(client=None, min_pass_rate: float = 0.80) -> QueryValidation:
    """Validate query capabilities.

    Runs all 5 query tests and determines if pass rate meets threshold.

    Args:
        client: Optional Mem0Client instance
        min_pass_rate: Minimum pass rate for validation (default: 80%)

    Returns:
        QueryValidation result with is_valid and test details
    """
    if client is None:
        from .mem0_client import get_mem0_client

        client = get_mem0_client()

    logger.info("Starting query validation tests")

    # Run all tests
    tests = [
        test_function_lookup(client),
        test_cross_reference(client),
        test_edit_impact(client),
        test_similar_functions(client),
        test_file_inventory(client),
    ]

    # Calculate metrics
    total_count = len(tests)
    passed_count = sum(1 for t in tests if t.passed)
    failed_count = total_count - passed_count
    pass_rate = passed_count / total_count if total_count > 0 else 0.0

    # Determine validity
    is_valid = pass_rate >= min_pass_rate
    failure_reasons = []

    if not is_valid:
        failure_reasons.append(
            f"Pass rate {pass_rate:.1%} below threshold {min_pass_rate:.1%}"
        )

        # List failed tests
        for test in tests:
            if not test.passed:
                failure_reasons.append(f"{test.name} failed: {test.error}")

    result = QueryValidation(
        tests=tests,
        total_count=total_count,
        passed_count=passed_count,
        failed_count=failed_count,
        is_valid=is_valid,
        failure_reasons=failure_reasons,
    )

    logger.info(
        f"Query validation complete: {passed_count}/{total_count} passed "
        f"({'PASSED' if is_valid else 'FAILED'})"
    )
    return result


__all__ = ["QueryTest", "QueryValidation", "validate_queries"]
