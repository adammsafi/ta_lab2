"""Run full memory validation suite.

Executes:
1. Function extraction and indexing (if not already done)
2. Relationship linking (if not already done)
3. Duplicate detection
4. Memory graph validation
5. Query capability tests
6. Report generation

Usage:
    # Run from command line
    python -m ta_lab2.tools.ai_orchestrator.memory.run_validation

    # Or import and run
    from ta_lab2.tools.ai_orchestrator.memory.run_validation import run_full_validation
    report = run_full_validation()
"""
import argparse
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .graph_validation import MemoryGraphValidation, validate_memory_graph
from .indexing import IndexingResult, extract_functions, index_codebase_functions
from .mem0_client import get_mem0_client
from .query_validation import QueryValidation, validate_queries
from .relationships import LinkingResult, link_codebase_relationships
from .similarity import DuplicateReport, detect_duplicates

logger = logging.getLogger(__name__)


@dataclass
class ValidationReport:
    """Complete validation report for v0.5.0 release.

    Attributes:
        timestamp: When validation was run
        phase: Phase identifier
        milestone: Milestone identifier
        indexing_result: Result from function indexing (None if skipped)
        linking_result: Result from relationship linking (None if skipped)
        duplicate_report: Duplicate detection results
        graph_validation: Memory graph validation results
        query_validation: Query capability validation results
        overall_status: "PASS" or "FAIL"
        blocking_issues: List of release-blocking issues
        warnings: List of non-blocking warnings
        duration_seconds: Total validation duration
    """

    timestamp: datetime
    phase: str = "19-memory-validation-release"
    milestone: str = "v0.5.0"

    indexing_result: Optional[IndexingResult] = None
    linking_result: Optional[LinkingResult] = None
    duplicate_report: Optional[DuplicateReport] = None
    graph_validation: Optional[MemoryGraphValidation] = None
    query_validation: Optional[QueryValidation] = None

    overall_status: str = "FAIL"
    blocking_issues: List[str] = None
    warnings: List[str] = None
    duration_seconds: float = 0.0

    def __post_init__(self):
        if self.blocking_issues is None:
            self.blocking_issues = []
        if self.warnings is None:
            self.warnings = []


def run_full_validation(
    index_if_needed: bool = True,
    output_path: Optional[Path] = None,
    verbose: bool = False,
) -> ValidationReport:
    """Run full memory validation suite.

    Args:
        index_if_needed: Whether to index functions if not already done
        output_path: Path to write VALIDATION.md (None = don't write)
        verbose: Enable verbose logging

    Returns:
        ValidationReport with overall status and detailed results
    """
    start_time = time.time()

    # Configure logging
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    logger.info("Starting full memory validation suite")
    logger.info("Phase: 19-memory-validation-release, Milestone: v0.5.0")

    # Initialize report
    report = ValidationReport(timestamp=datetime.now())

    try:
        # Step 1: Initialize Mem0Client
        logger.info("Initializing Mem0 client")
        client = get_mem0_client()

        # Step 2: Check if indexing needed
        logger.info("Checking if function indexing needed")
        function_count = 0
        try:
            # Try to get function count
            results = client.search(
                query="function definition",
                filters={"category": "function_definition"},
                limit=1,
            )
            # If we got results, try to estimate total count
            # by fetching in batches
            if results:
                logger.info("Functions already indexed, counting total")
                batch_size = 1000
                total = 0
                while True:
                    batch = client.search(
                        query="function definition",
                        filters={"category": "function_definition"},
                        limit=batch_size,
                    )
                    if not batch:
                        break
                    total += len(batch)
                    if len(batch) < batch_size:
                        break
                function_count = total
                logger.info(f"Found {function_count} indexed functions")
        except Exception as e:
            logger.warning(f"Error checking function count: {e}")
            function_count = 0

        # Step 3: Index if needed (threshold: at least 100 functions expected)
        indexing_threshold = 100
        if index_if_needed and function_count < indexing_threshold:
            logger.info(
                f"Function count ({function_count}) below threshold ({indexing_threshold}), indexing codebase"
            )
            src_path = Path(__file__).parent.parent.parent.parent
            logger.info(f"Indexing from: {src_path}")

            indexing_result = index_codebase_functions(src_path)
            report.indexing_result = indexing_result

            logger.info(
                f"Indexed {indexing_result.indexed_count} functions "
                f"({indexing_result.skipped_count} skipped, "
                f"{indexing_result.error_count} errors)"
            )

            if indexing_result.error_count > 0:
                report.warnings.append(
                    f"{indexing_result.error_count} errors during indexing"
                )
        else:
            logger.info("Skipping indexing (already done or not requested)")

        # Step 4: Link relationships if indexing was done
        if report.indexing_result and index_if_needed:
            logger.info("Linking function relationships")
            src_path = Path(__file__).parent.parent.parent.parent
            linking_result = link_codebase_relationships(src_path)
            report.linking_result = linking_result

            logger.info(
                f"Created {linking_result.relationship_count} relationships "
                f"({linking_result.contains_count} contains, "
                f"{linking_result.calls_count} calls, "
                f"{linking_result.imports_count} imports)"
            )
        else:
            logger.info("Skipping relationship linking (not needed)")

        # Step 5: Detect duplicates
        logger.info("Detecting duplicate functions")
        # Extract functions for duplicate detection
        src_path = Path(__file__).parent.parent.parent.parent
        all_functions = []
        for py_file in src_path.rglob("*.py"):
            # Skip test files and hidden files
            if "__pycache__" in str(py_file) or "/.venv/" in str(py_file):
                continue
            try:
                functions = extract_functions(py_file)
                all_functions.extend(functions)
            except Exception as e:
                logger.debug(f"Skipping {py_file}: {e}")

        logger.info(f"Analyzing {len(all_functions)} functions for duplicates")
        duplicate_report = detect_duplicates(all_functions)
        report.duplicate_report = duplicate_report

        logger.info(
            f"Found {len(duplicate_report.exact_duplicates)} exact duplicates, "
            f"{len(duplicate_report.very_similar)} very similar, "
            f"{len(duplicate_report.related)} related"
        )

        # Step 6: Validate memory graph
        logger.info("Validating memory graph integrity")
        graph_validation = validate_memory_graph(client=client)
        report.graph_validation = graph_validation

        if graph_validation.is_valid:
            logger.info("Memory graph validation PASSED")
        else:
            logger.error(
                f"Memory graph validation FAILED: {graph_validation.failure_reasons}"
            )
            report.blocking_issues.extend(graph_validation.failure_reasons)

        # Step 7: Test query capabilities
        logger.info("Testing query capabilities")
        query_validation = validate_queries(client=client)
        report.query_validation = query_validation

        if query_validation.is_valid:
            logger.info(
                f"Query validation PASSED ({query_validation.passed_count}/{query_validation.total_count})"
            )
        else:
            logger.error(f"Query validation FAILED: {query_validation.failure_reasons}")
            report.blocking_issues.extend(query_validation.failure_reasons)

        # Step 8: Determine overall status
        if graph_validation.is_valid and query_validation.is_valid:
            report.overall_status = "PASS"
            logger.info("Overall validation: PASS")
        else:
            report.overall_status = "FAIL"
            logger.error("Overall validation: FAIL")

        # Step 9: Calculate duration
        report.duration_seconds = time.time() - start_time

        # Step 10: Write VALIDATION.md if requested
        if output_path:
            logger.info(f"Writing validation report to {output_path}")
            md_content = generate_validation_md(report)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(md_content, encoding="utf-8")
            logger.info(f"Validation report written to {output_path}")

    except Exception as e:
        logger.exception(f"Validation failed with error: {e}")
        report.overall_status = "FAIL"
        report.blocking_issues.append(f"Validation error: {e}")
        report.duration_seconds = time.time() - start_time

    return report


def generate_validation_md(report: ValidationReport) -> str:
    """Generate markdown validation report.

    Args:
        report: ValidationReport to format

    Returns:
        Formatted markdown string
    """
    lines = [
        "# Memory Validation Report",
        "",
        f"**Status:** {report.overall_status}",
        f"**Timestamp:** {report.timestamp.strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Phase:** {report.phase}",
        f"**Milestone:** {report.milestone}",
        f"**Duration:** {report.duration_seconds:.2f} seconds",
        "",
    ]

    # Summary table
    lines.extend(["## Summary", ""])

    indexing_status = "Skipped"
    indexing_detail = "Already indexed"
    if report.indexing_result:
        indexing_status = "OK" if report.indexing_result.error_count == 0 else "WARN"
        indexing_detail = f"{report.indexing_result.indexed_count} functions indexed"

    linking_status = "Skipped"
    linking_detail = "Already linked"
    if report.linking_result:
        linking_status = "OK"
        linking_detail = f"{report.linking_result.relationship_count} relationships"

    graph_status = "PASS" if report.graph_validation.is_valid else "FAIL"
    graph_detail = (
        f"{report.graph_validation.orphan_rate:.1%} orphan rate"
        if report.graph_validation
        else "N/A"
    )

    query_status = "PASS" if report.query_validation.is_valid else "FAIL"
    query_detail = (
        f"{report.query_validation.passed_count}/{report.query_validation.total_count} tests passed"
        if report.query_validation
        else "N/A"
    )

    duplicate_detail = "N/A"
    if report.duplicate_report:
        duplicate_detail = (
            f"{len(report.duplicate_report.exact_duplicates)} exact, "
            f"{len(report.duplicate_report.very_similar)} similar"
        )

    lines.extend(
        [
            "| Check | Status | Details |",
            "|-------|--------|---------|",
            f"| Function Indexing | {indexing_status} | {indexing_detail} |",
            f"| Relationship Linking | {linking_status} | {linking_detail} |",
            f"| Graph Validation | {graph_status} | {graph_detail} |",
            f"| Query Validation | {query_status} | {query_detail} |",
            f"| Duplicate Detection | INFO | {duplicate_detail} |",
            "",
        ]
    )

    # Blocking issues
    if report.blocking_issues:
        lines.extend(["## Blocking Issues", ""])
        for issue in report.blocking_issues:
            lines.append(f"- {issue}")
        lines.append("")
    else:
        lines.extend(["## Blocking Issues", "", "None - all validations passed.", ""])

    # Graph validation details
    if report.graph_validation:
        lines.extend([report.graph_validation.markdown_report(), ""])

    # Query validation details
    if report.query_validation:
        lines.extend([report.query_validation.markdown_report(), ""])

    # Duplicate detection details
    if report.duplicate_report:
        lines.extend([report.duplicate_report.markdown_summary(), ""])

    # Warnings
    if report.warnings:
        lines.extend(["## Warnings", ""])
        for warning in report.warnings:
            lines.append(f"- {warning}")
        lines.append("")

    # Footer
    lines.extend(["---", "*Generated by run_validation.py*", ""])

    return "\n".join(lines)


def main():
    """Command-line entry point for validation."""
    parser = argparse.ArgumentParser(
        description="Run full memory validation suite for v0.5.0 release"
    )
    parser.add_argument(
        "--index",
        action="store_true",
        help="Index functions if not already done (default: True)",
    )
    parser.add_argument(
        "--no-index",
        action="store_true",
        help="Skip indexing even if needed",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Path to write VALIDATION.md",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Determine indexing behavior
    index_if_needed = not args.no_index

    # Run validation
    report = run_full_validation(
        index_if_needed=index_if_needed,
        output_path=args.output,
        verbose=args.verbose,
    )

    # Print summary
    print("\n" + "=" * 80)
    print("MEMORY VALIDATION REPORT")
    print("=" * 80)
    print(f"Status: {report.overall_status}")
    print(f"Duration: {report.duration_seconds:.2f}s")

    if report.graph_validation:
        print(
            f"\nGraph Validation: {'PASS' if report.graph_validation.is_valid else 'FAIL'}"
        )
        print(f"  Functions: {report.graph_validation.total_functions:,}")
        print(f"  Relationships: {report.graph_validation.total_relationships:,}")
        print(f"  Orphan Rate: {report.graph_validation.orphan_rate:.1%}")

    if report.query_validation:
        print(
            f"\nQuery Validation: {'PASS' if report.query_validation.is_valid else 'FAIL'}"
        )
        print(
            f"  Tests Passed: {report.query_validation.passed_count}/{report.query_validation.total_count}"
        )

    if report.duplicate_report:
        print("\nDuplicate Detection:")
        print(f"  Exact: {len(report.duplicate_report.exact_duplicates)}")
        print(f"  Very Similar: {len(report.duplicate_report.very_similar)}")
        print(f"  Related: {len(report.duplicate_report.related)}")

    if report.blocking_issues:
        print(f"\nBlocking Issues: {len(report.blocking_issues)}")
        for issue in report.blocking_issues:
            print(f"  - {issue}")

    if report.warnings:
        print(f"\nWarnings: {len(report.warnings)}")
        for warning in report.warnings:
            print(f"  - {warning}")

    print("\n" + "=" * 80)

    # Exit with appropriate code
    sys.exit(0 if report.overall_status == "PASS" else 1)


if __name__ == "__main__":
    main()
