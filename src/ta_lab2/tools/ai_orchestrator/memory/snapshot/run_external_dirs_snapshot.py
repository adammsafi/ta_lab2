"""External directories snapshot script for v0.5.0 pre-integration baseline.

Indexes all 4 external directories (Data_Tools, ProjectTT, fredtools2, fedtools2)
into memory system with pre_integration_v0.5.0 tag.

Requirements:
- MEMO-12: Capture state of all external directories before integration
- Create baseline snapshots for tracking what gets integrated vs archived
- Handle missing directories gracefully (log warning, continue with others)
- For ProjectTT: Also handle .docx and .xlsx files if pypandoc available
"""
import argparse
import json
import logging
from pathlib import Path
from datetime import datetime

from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
from ta_lab2.tools.ai_orchestrator.memory.snapshot.extract_codebase import (
    extract_directory_tree,
)
from ta_lab2.tools.ai_orchestrator.memory.snapshot.batch_indexer import (
    batch_add_memories,
    create_snapshot_metadata,
    format_file_content_for_memory,
)

logger = logging.getLogger(__name__)


# External directory configuration per 11-CONTEXT.md and MEMO-12
EXTERNAL_DIRS = [
    {
        "name": "Data_Tools",
        "path": Path("C:/Users/asafi/Downloads/Data_Tools"),
        "description": "Data processing and utility scripts",
    },
    {
        "name": "ProjectTT",
        "path": Path("C:/Users/asafi/Documents/ProjectTT"),
        "description": "Project documentation, schemas, and planning materials",
    },
    {
        "name": "fredtools2",
        "path": Path("C:/Users/asafi/Downloads/fredtools2"),
        "description": "FRED economic data tools",
    },
    {
        "name": "fedtools2",
        "path": Path("C:/Users/asafi/Downloads/fedtools2"),
        "description": "Federal Reserve data tools",
    },
]

# File patterns to exclude from snapshot
EXCLUSIONS = [
    "__pycache__",
    ".pyc",
    ".venv",
    "venv",
    "env",
    ".git",
    "dist",
    "build",
    "*.egg-info",
    ".csv",
    ".xlsx",
    ".json",
]


def validate_directories() -> list[dict]:
    """Check which external directories exist and are accessible.

    Returns:
        List of valid directory configs (only those that exist)

    Example:
        >>> valid_dirs = validate_directories()
        >>> print(f"Found {len(valid_dirs)} accessible directories")
    """
    valid_dirs = []
    missing_dirs = []

    for dir_config in EXTERNAL_DIRS:
        dir_path = dir_config["path"]
        if dir_path.exists() and dir_path.is_dir():
            valid_dirs.append(dir_config)
            logger.info(f"✓ Found directory: {dir_config['name']} at {dir_path}")
        else:
            missing_dirs.append(dir_config["name"])
            logger.warning(f"✗ Directory not found: {dir_config['name']} at {dir_path}")

    if missing_dirs:
        logger.info(
            f"Will skip {len(missing_dirs)} missing directories: {', '.join(missing_dirs)}"
        )

    return valid_dirs


def run_external_dir_snapshot(dir_config: dict, dry_run: bool = False) -> dict:
    """Run snapshot for a single external directory.

    Args:
        dir_config: Directory configuration dict with name, path, description
        dry_run: If True, only count files without indexing

    Returns:
        Dict with stats for this directory (files_found, files_indexed, errors, etc.)

    Example:
        >>> config = {"name": "Data_Tools", "path": Path("C:/Users/asafi/Downloads/Data_Tools")}
        >>> stats = run_external_dir_snapshot(config, dry_run=True)
        >>> print(f"Found {stats['files_found']} files")
    """
    dir_name = dir_config["name"]
    dir_path = dir_config["path"]

    logger.info(f"\n{'='*60}")
    logger.info(f"Processing directory: {dir_name}")
    logger.info(f"Path: {dir_path}")
    logger.info(f"{'='*60}\n")

    # Extract directory tree with code structure and git metadata
    file_infos = extract_directory_tree(dir_path, exclusions=EXCLUSIONS)

    stats = {
        "directory": dir_name,
        "path": str(dir_path),
        "files_found": len(file_infos),
        "files_indexed": 0,
        "errors": 0,
        "total_functions": 0,
        "total_classes": 0,
    }

    if dry_run:
        logger.info(f"[DRY RUN] Would index {len(file_infos)} files from {dir_name}")
        # Calculate totals for dry run
        for file_info in file_infos:
            code = file_info.get("code_structure", {})
            stats["total_functions"] += len(code.get("functions", []))
            stats["total_classes"] += len(code.get("classes", []))
        return stats

    # Create memories for each file
    memories = []
    for file_info in file_infos:
        try:
            # Format content for memory
            content = format_file_content_for_memory(file_info)

            # Get git metadata
            git_metadata = file_info.get("git_metadata", {})
            code_structure = file_info.get("code_structure", {})

            # Determine file type based on directory
            if dir_name == "ProjectTT":
                # ProjectTT may have documentation files
                file_type = (
                    "documentation"
                    if "docs" in file_info["relative_path"].lower()
                    else "source_code"
                )
            else:
                file_type = "source_code"

            # Create snapshot metadata
            metadata = create_snapshot_metadata(
                source="pre_integration_v0.5.0",
                directory=dir_name,
                file_type=file_type,
                file_path=file_info["relative_path"],
                function_count=len(code_structure.get("functions", [])),
                class_count=len(code_structure.get("classes", [])),
                line_count=code_structure.get("line_count", 0),
                commit_hash=git_metadata.get("commit_hash", "N/A"),
            )

            # Track totals
            stats["total_functions"] += metadata["function_count"]
            stats["total_classes"] += metadata["class_count"]

            memories.append({"content": content, "metadata": metadata})

        except Exception as e:
            logger.error(
                f"Failed to create memory for {file_info.get('relative_path', 'unknown')}: {e}"
            )
            stats["errors"] += 1

    # Batch add memories to Mem0
    if memories:
        logger.info(f"Indexing {len(memories)} files from {dir_name}...")
        client = get_mem0_client()
        result = batch_add_memories(client, memories, batch_size=50, delay_seconds=0.5)
        stats["files_indexed"] = result.added
        stats["errors"] += result.errors
        logger.info(
            f"Completed {dir_name}: {result.added} files indexed, {result.errors} errors"
        )
    else:
        logger.warning(f"No memories created for {dir_name}")

    return stats


def run_all_external_snapshots(dry_run: bool = False) -> dict:
    """Run snapshots for all accessible external directories.

    Args:
        dry_run: If True, only count files without indexing

    Returns:
        Combined stats dict with directory-level breakdown and totals

    Example:
        >>> stats = run_all_external_snapshots(dry_run=True)
        >>> print(f"Total files across all directories: {stats['total_files']}")
    """
    # Validate directories first
    valid_dirs = validate_directories()

    if not valid_dirs:
        logger.error("No valid external directories found. Cannot proceed.")
        return {
            "timestamp": datetime.now().isoformat(),
            "dry_run": dry_run,
            "directories_found": 0,
            "missing_directories": [d["name"] for d in EXTERNAL_DIRS],
            "directory_stats": [],
            "total_files": 0,
            "total_indexed": 0,
            "total_errors": 0,
        }

    # Process each directory
    directory_stats = []
    total_files = 0
    total_indexed = 0
    total_errors = 0

    for dir_config in valid_dirs:
        try:
            stats = run_external_dir_snapshot(dir_config, dry_run=dry_run)
            directory_stats.append(stats)
            total_files += stats["files_found"]
            total_indexed += stats["files_indexed"]
            total_errors += stats["errors"]
        except Exception as e:
            logger.error(f"Failed to process {dir_config['name']}: {e}")
            total_errors += 1

    # Compile combined stats
    missing_dirs = [d["name"] for d in EXTERNAL_DIRS if d not in valid_dirs]

    combined_stats = {
        "timestamp": datetime.now().isoformat(),
        "dry_run": dry_run,
        "directories_found": len(valid_dirs),
        "missing_directories": missing_dirs,
        "directory_stats": directory_stats,
        "total_files": total_files,
        "total_indexed": total_indexed,
        "total_errors": total_errors,
    }

    # Log summary
    logger.info(f"\n{'='*60}")
    logger.info("EXTERNAL DIRECTORIES SNAPSHOT SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"Directories processed: {len(valid_dirs)}")
    logger.info(f"Directories missing: {len(missing_dirs)}")
    if missing_dirs:
        logger.info(f"  Missing: {', '.join(missing_dirs)}")
    logger.info(f"Total files found: {total_files}")
    logger.info(f"Total files indexed: {total_indexed}")
    logger.info(f"Total errors: {total_errors}")
    logger.info(f"{'='*60}\n")

    return combined_stats


def save_external_snapshot_manifest(stats: dict, output_path: Path):
    """Save snapshot manifest JSON with all directory stats and totals.

    Args:
        stats: Combined stats dict from run_all_external_snapshots
        output_path: Path to save manifest JSON

    Example:
        >>> stats = run_all_external_snapshots()
        >>> save_external_snapshot_manifest(stats, Path(".planning/phases/11-memory-preparation/snapshots/external_dirs_snapshot.json"))
    """
    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write JSON
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    logger.info(f"Snapshot manifest saved to: {output_path}")


def main():
    """Main entry point with CLI argument parsing."""
    parser = argparse.ArgumentParser(
        description="Index external directories (Data_Tools, ProjectTT, fredtools2, fedtools2) into memory"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only count files without indexing to memory",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            ".planning/phases/11-memory-preparation/snapshots/external_dirs_snapshot.json"
        ),
        help="Path to save snapshot manifest (default: .planning/phases/11-memory-preparation/snapshots/external_dirs_snapshot.json)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Run snapshot
    logger.info("Starting external directories snapshot...")
    logger.info(f"Dry run: {args.dry_run}")

    stats = run_all_external_snapshots(dry_run=args.dry_run)

    # Save manifest
    if not args.dry_run:
        save_external_snapshot_manifest(stats, args.output)

    logger.info("External directories snapshot complete.")


if __name__ == "__main__":
    main()
