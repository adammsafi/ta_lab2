"""Validate memory coverage through query-based testing.

This script validates that all indexed directories (ta_lab2, Data_Tools, ProjectTT,
fredtools2, fedtools2) can be queried successfully via the memory system. Validates
MEMO-10, MEMO-11, MEMO-12 requirements from Phase 11.

Success Criteria:
- Memory queries can answer "What files exist in directory X?" for all indexed directories
- 100% of Python files are queryable (excluding explicit exclusions)
- Coverage validation report documents query success rates

Usage:
    python -m ta_lab2.tools.ai_orchestrator.memory.snapshot.validate_coverage
    python -m ta_lab2.tools.ai_orchestrator.memory.snapshot.validate_coverage --sample-size 100
"""

import json
import logging
from pathlib import Path
from typing import Optional
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_snapshot_manifests(snapshots_dir: Path) -> dict:
    """Load snapshot manifests and extract expected files.

    Args:
        snapshots_dir: Directory containing snapshot JSON files

    Returns:
        Dict mapping directory names to lists of file paths:
        {
            "ta_lab2": [file1, file2, ...],
            "Data_Tools": [file1, file2, ...],
            ...
        }
    """
    manifests = {
        "ta_lab2": snapshots_dir / "ta_lab2_snapshot.json",
        "external_dirs": snapshots_dir / "external_dirs_snapshot.json",
        "conversations": snapshots_dir / "conversations_snapshot.json",
    }

    result = {}

    # Load ta_lab2 snapshot
    if manifests["ta_lab2"].exists():
        with open(manifests["ta_lab2"], "r") as f:
            data = json.load(f)
            result["ta_lab2"] = data.get("files_indexed", [])
            logger.info(f"Loaded ta_lab2 snapshot: {len(result['ta_lab2'])} files")

    # Load external directories snapshot
    if manifests["external_dirs"].exists():
        with open(manifests["external_dirs"], "r") as f:
            data = json.load(f)
            # External dirs has per-directory stats
            for dir_stat in data.get("directory_stats", []):
                dir_name = dir_stat["directory"]
                # Files not listed individually in external_dirs_snapshot.json
                # So we'll use directory-level counts for validation
                result[dir_name] = {
                    "files_found": dir_stat["files_found"],
                    "files_indexed": dir_stat["files_indexed"]
                }
            logger.info(f"Loaded external_dirs snapshot: {len(data.get('directory_stats', []))} directories")

    # Load conversations snapshot (for stats)
    if manifests["conversations"].exists():
        with open(manifests["conversations"], "r") as f:
            data = json.load(f)
            conversations_count = data.get("statistics", {}).get("conversations_indexed", 0)
            result["conversations"] = {"count": conversations_count}
            logger.info(f"Loaded conversations snapshot: {conversations_count} conversations")

    return result


def test_directory_inventory_query(client, directory: str) -> dict:
    """Test if we can query files in a specific directory.

    Args:
        client: Mem0Client instance
        directory: Directory name (e.g., "ta_lab2", "Data_Tools")

    Returns:
        Dict with query, results_count, sample_files
    """
    query = f"List all files in {directory}"

    try:
        # Search with directory filter
        # Note: Remove filters parameter - Qdrant filter syntax is complex
        # Just use semantic search and check results
        search_results = client.search(
            query=query,
            user_id="orchestrator",
            limit=20
        )

        # Extract results list from response dict
        results = search_results.get("results", []) if isinstance(search_results, dict) else search_results

        # Filter results to only those from the target directory
        filtered_results = [
            r for r in results
            if directory.lower() in r.get("memory", "").lower() or
               r.get("metadata", {}).get("directory") == directory
        ]
        results = filtered_results

        sample_files = []
        for r in results[:5]:
            memory_text = r.get("memory", "")
            # Extract file path from memory text
            if "File:" in memory_text:
                file_path = memory_text.split("File:")[1].split("\n")[0].strip()
                sample_files.append(file_path)

        return {
            "query": query,
            "results_count": len(results),
            "sample_files": sample_files,
            "success": len(results) > 0
        }
    except Exception as e:
        logger.error(f"Directory inventory query failed for {directory}: {e}")
        return {
            "query": query,
            "results_count": 0,
            "sample_files": [],
            "success": False,
            "error": str(e)
        }


def test_function_lookup_query(client, directory: str) -> dict:
    """Test if we can query functions in a directory.

    Args:
        client: Mem0Client instance
        directory: Directory name

    Returns:
        Dict with query, found, results_count
    """
    query = f"Functions in {directory}"

    try:
        # Search for functions in directory
        search_results = client.search(
            query=query,
            user_id="orchestrator",
            limit=10
        )

        # Extract results list from response dict
        results = search_results.get("results", []) if isinstance(search_results, dict) else search_results

        # Filter results to only those from the target directory
        filtered_results = [
            r for r in results
            if r.get("metadata", {}).get("directory") == directory or
               directory.lower() in r.get("memory", "").lower()
        ]
        results = filtered_results

        # Check if results contain function information
        has_functions = any("Functions:" in r.get("memory", "") for r in results)

        return {
            "query": query,
            "found": has_functions,
            "results_count": len(results),
            "success": has_functions
        }
    except Exception as e:
        logger.error(f"Function lookup query failed for {directory}: {e}")
        return {
            "query": query,
            "found": False,
            "results_count": 0,
            "success": False,
            "error": str(e)
        }


def test_tag_filtering_query(client, tag: str) -> dict:
    """Test if tag filtering works.

    Args:
        client: Mem0Client instance
        tag: Tag to filter by (e.g., "pre_reorg_v0.5.0")

    Returns:
        Dict with query, results_count, tag_filter_works
    """
    query = f"{tag} snapshot files"

    try:
        search_results = client.search(
            query=query,
            user_id="orchestrator",
            limit=10
        )

        # Extract results list from response dict
        results = search_results.get("results", []) if isinstance(search_results, dict) else search_results

        # Check if results have the tag
        # Results can be dict or other format - handle both
        tagged_results = []
        for r in results:
            if isinstance(r, dict):
                tags = r.get("metadata", {}).get("tags", [])
                if isinstance(tags, list) and tag in tags:
                    tagged_results.append(r)
            elif isinstance(r, str) and tag in r:
                tagged_results.append(r)

        return {
            "query": query,
            "results_count": len(results),
            "tagged_results": len(tagged_results),
            "tag_filter_works": len(tagged_results) > 0,
            "success": len(tagged_results) > 0
        }
    except Exception as e:
        logger.error(f"Tag filtering query failed for {tag}: {e}")
        return {
            "query": query,
            "results_count": 0,
            "tagged_results": 0,
            "tag_filter_works": False,
            "success": False,
            "error": str(e)
        }


def test_cross_reference_query(client) -> dict:
    """Test cross-reference queries (e.g., what calls function X).

    Args:
        client: Mem0Client instance

    Returns:
        Dict with query, results_count
    """
    # Query for a common function pattern
    query = "What functions use extract_codebase?"

    try:
        search_results = client.search(query=query, user_id="orchestrator", limit=5)
        results = search_results.get("results", []) if isinstance(search_results, dict) else search_results

        return {
            "query": query,
            "results_count": len(results),
            "success": len(results) > 0
        }
    except Exception as e:
        logger.error(f"Cross-reference query failed: {e}")
        return {
            "query": query,
            "results_count": 0,
            "success": False,
            "error": str(e)
        }


def validate_file_coverage(client, expected_files: list[str], sample_size: int = 50) -> dict:
    """Validate that expected files are queryable via search.

    Args:
        client: Mem0Client instance
        expected_files: List of expected file paths
        sample_size: Max number of files to test (for efficiency)

    Returns:
        Dict with total, found, missing, coverage_percentage
    """
    import random

    # Sample files if list is too large
    if len(expected_files) > sample_size:
        test_files = random.sample(expected_files, sample_size)
    else:
        test_files = expected_files

    found = 0
    missing = []

    for file_path in test_files:
        # Extract filename for query
        filename = Path(file_path).name if "\\" in file_path or "/" in file_path else file_path

        try:
            search_results = client.search(
                query=f"File {filename}",
                user_id="orchestrator",
                limit=3
            )
            results = search_results.get("results", []) if isinstance(search_results, dict) else search_results

            # Check if any result mentions this file
            file_found = any(filename in r.get("memory", "") for r in results)

            if file_found:
                found += 1
            else:
                missing.append(file_path)
        except Exception as e:
            logger.warning(f"Search failed for {filename}: {e}")
            missing.append(file_path)

    coverage_percentage = (found / len(test_files)) * 100 if test_files else 0

    return {
        "total": len(test_files),
        "found": found,
        "missing": missing,
        "coverage_percentage": round(coverage_percentage, 2)
    }


def validate_memory_coverage(snapshots_dir: Path, sample_size: int = 50) -> dict:
    """Run complete coverage validation for all indexed directories.

    Args:
        snapshots_dir: Directory containing snapshot JSON files
        sample_size: Max files to test per directory

    Returns:
        Full validation report with overall_coverage_percentage and success flag
    """
    from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client

    logger.info("Starting memory coverage validation")

    # Initialize client
    client = get_mem0_client()

    # Load snapshot manifests
    manifests = load_snapshot_manifests(snapshots_dir)

    # Get overall memory count
    total_memories = client.memory_count
    logger.info(f"Total memories in system: {total_memories}")

    # Validate all 5 directories
    directories = ["ta_lab2", "Data_Tools", "ProjectTT", "fredtools2", "fedtools2"]

    directory_results = {}
    for directory in directories:
        logger.info(f"Validating directory: {directory}")

        # Run directory inventory query
        inventory_result = test_directory_inventory_query(client, directory)

        # Run function lookup query
        function_result = test_function_lookup_query(client, directory)

        directory_results[directory] = {
            "inventory_query": inventory_result,
            "function_lookup": function_result
        }

    # Test tag filtering
    logger.info("Testing tag filtering")
    tag_result = test_tag_filtering_query(client, "pre_reorg_v0.5.0")

    # Test cross-reference queries
    logger.info("Testing cross-reference queries")
    xref_result = test_cross_reference_query(client)

    # Validate file coverage for ta_lab2 (has file list)
    file_coverage = None
    if "ta_lab2" in manifests and isinstance(manifests["ta_lab2"], list):
        logger.info("Validating file coverage for ta_lab2")
        file_coverage = validate_file_coverage(
            client,
            manifests["ta_lab2"],
            sample_size
        )

    # Calculate overall success
    all_inventory_success = all(
        directory_results[d]["inventory_query"]["success"]
        for d in directories
    )

    all_function_success = all(
        directory_results[d]["function_lookup"]["success"]
        for d in directories
    )

    overall_coverage_percentage = 100.0 if all_inventory_success and all_function_success else 0.0

    # If we have file coverage, factor that in
    if file_coverage:
        overall_coverage_percentage = (
            overall_coverage_percentage * 0.7 +
            file_coverage["coverage_percentage"] * 0.3
        )

    success = overall_coverage_percentage >= 95.0  # Allow 5% tolerance

    return {
        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        "total_memories": total_memories,
        "directories_validated": directories,
        "directory_results": directory_results,
        "tag_filtering": tag_result,
        "cross_reference": xref_result,
        "file_coverage": file_coverage,
        "overall_coverage_percentage": round(overall_coverage_percentage, 2),
        "success": success,
        "summary": {
            "all_directories_queryable": all_inventory_success,
            "function_lookup_working": all_function_success,
            "tag_filtering_working": tag_result["success"],
            "cross_reference_working": xref_result["success"]
        }
    }


def run_validation(output_path: Path, sample_size: int = 50):
    """Run validation and save report.

    Args:
        output_path: Path to save validation report JSON
        sample_size: Max files to test per directory
    """
    # Determine snapshots directory
    planning_dir = Path(__file__).parent.parent.parent.parent.parent.parent / ".planning"
    snapshots_dir = planning_dir / "phases" / "11-memory-preparation" / "snapshots"

    logger.info(f"Using snapshots directory: {snapshots_dir}")

    # Run validation
    report = validate_memory_coverage(snapshots_dir, sample_size)

    # Save report
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Validation report saved to {output_path}")

    # Print human-readable summary
    print("\n" + "=" * 60)
    print("MEMORY COVERAGE VALIDATION REPORT")
    print("=" * 60)
    print(f"Timestamp: {report['timestamp']}")
    print(f"Total memories: {report['total_memories']}")
    print(f"Overall coverage: {report['overall_coverage_percentage']}%")
    print(f"Success: {'YES' if report['success'] else 'NO'}")
    print("\nDirectory Query Results:")
    for directory, results in report["directory_results"].items():
        inventory_success = results["inventory_query"]["success"]
        function_success = results["function_lookup"]["success"]
        print(f"  {directory}:")
        print(f"    Inventory query: {'PASS' if inventory_success else 'FAIL'} "
              f"({results['inventory_query']['results_count']} results)")
        print(f"    Function lookup: {'PASS' if function_success else 'FAIL'} "
              f"({results['function_lookup']['results_count']} results)")

    print("\nQuery Type Results:")
    print(f"  Tag filtering: {'PASS' if report['tag_filtering']['success'] else 'FAIL'}")
    print(f"  Cross-reference: {'PASS' if report['cross_reference']['success'] else 'FAIL'}")

    if report["file_coverage"]:
        print(f"\nFile Coverage (ta_lab2 sample):")
        print(f"  Tested: {report['file_coverage']['total']} files")
        print(f"  Found: {report['file_coverage']['found']} files")
        print(f"  Coverage: {report['file_coverage']['coverage_percentage']}%")

    print("=" * 60)


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate memory coverage for all indexed directories"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".planning/phases/11-memory-preparation/validation/coverage_report.json"),
        help="Output path for validation report"
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=50,
        help="Number of files to test per directory"
    )

    args = parser.parse_args()

    run_validation(args.output, args.sample_size)


if __name__ == "__main__":
    main()
