"""Run ta_lab2 directory snapshot for pre-reorganization baseline.

Creates complete memory index of ta_lab2 codebase with pre_reorg_v0.5.0 tag
as baseline before file reorganization. Uses AST-based code extraction and
batch memory indexing with rate limiting.

Usage:
    # Dry run (discover files without indexing)
    python run_ta_lab2_snapshot.py --dry-run

    # Execute snapshot (index to memory)
    python run_ta_lab2_snapshot.py
"""
import argparse
import json
import logging
from datetime import datetime
from pathlib import Path
from git import Repo
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

# Exclusions per 11-CONTEXT.md
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
    ".json",  # data files
    "node_modules",
    ".pytest_cache",
    ".tox",
]


def run_ta_lab2_snapshot(repo_path: Path, dry_run: bool = False) -> dict:
    """Execute ta_lab2 directory snapshot.

    Extracts code structure from all Python files in src/ta_lab2/ directory,
    creates formatted memories with pre_reorg_v0.5.0 tag, and optionally
    indexes them to Mem0+Qdrant memory system.

    Args:
        repo_path: Path to repository root (ta_lab2 directory)
        dry_run: If True, discover files but don't add to memory

    Returns:
        Stats dict with:
        - total_files: Number of Python files processed
        - total_functions: Sum of all functions discovered
        - total_classes: Sum of all classes discovered
        - memories_added: Number of memories successfully indexed
        - errors: List of error messages
        - files_indexed: List of file paths indexed
        - commit_hash: Current git HEAD commit

    Example:
        >>> from pathlib import Path
        >>> stats = run_ta_lab2_snapshot(Path("."), dry_run=True)
        >>> print(f"Found {stats['total_files']} files")
    """
    logger.info(f"Starting ta_lab2 snapshot: repo_path={repo_path}, dry_run={dry_run}")

    # Get current git commit hash for versioning
    try:
        repo = Repo(repo_path)
        commit_hash = repo.head.commit.hexsha[:7]
        logger.info(f"Current git commit: {commit_hash}")
    except Exception as e:
        logger.warning(f"Failed to get git commit: {e}")
        commit_hash = "unknown"

    # Define ta_lab2 source directory
    ta_lab2_dir = repo_path / "src" / "ta_lab2"
    if not ta_lab2_dir.exists():
        raise FileNotFoundError(f"ta_lab2 directory not found: {ta_lab2_dir}")

    logger.info(f"Extracting directory tree: {ta_lab2_dir}")

    # Extract directory tree with code structure
    file_infos = extract_directory_tree(ta_lab2_dir, exclusions=EXCLUSIONS)

    logger.info(f"Extracted {len(file_infos)} Python files")

    # Calculate statistics
    total_functions = sum(
        len(info["code_structure"].get("functions", [])) for info in file_infos
    )
    total_classes = sum(
        len(info["code_structure"].get("classes", [])) for info in file_infos
    )

    logger.info(f"Total functions: {total_functions}, Total classes: {total_classes}")

    stats = {
        "total_files": len(file_infos),
        "total_functions": total_functions,
        "total_classes": total_classes,
        "memories_added": 0,
        "errors": [],
        "files_indexed": [],
        "commit_hash": commit_hash,
    }

    if dry_run:
        logger.info("Dry run mode - skipping memory indexing")
        stats["files_indexed"] = [info["relative_path"] for info in file_infos]
        return stats

    # Create memories for each file
    memories = []
    for file_info in file_infos:
        try:
            # Determine file type
            relative_path = file_info["relative_path"]
            if "test" in relative_path.lower():
                file_type = "test"
            elif "config" in relative_path.lower():
                file_type = "config"
            else:
                file_type = "source_code"

            # Format content
            content = format_file_content_for_memory(file_info)

            # Create metadata
            code_structure = file_info["code_structure"]
            git_metadata = file_info["git_metadata"]

            metadata = create_snapshot_metadata(
                source="pre_reorg_v0.5.0",
                directory="ta_lab2",
                file_type=file_type,
                file_path=relative_path,
                function_count=len(code_structure.get("functions", [])),
                class_count=len(code_structure.get("classes", [])),
                line_count=code_structure.get("line_count", 0),
                commit_hash=git_metadata.get("commit_hash", commit_hash),
            )

            memories.append(
                {
                    "content": content,
                    "metadata": metadata,
                    "id": relative_path,  # For error tracking
                }
            )

            stats["files_indexed"].append(relative_path)

        except Exception as e:
            logger.error(
                f"Failed to create memory for {file_info.get('relative_path', 'unknown')}: {e}"
            )
            stats["errors"].append(str(e))

    logger.info(f"Created {len(memories)} memories, starting batch indexing")

    # Batch add to memory with rate limiting
    try:
        client = get_mem0_client()
        result = batch_add_memories(client, memories, batch_size=50, delay_seconds=0.5)

        stats["memories_added"] = result.added
        stats["errors"].extend([f"Memory error: {eid}" for eid in result.error_ids])

        logger.info(f"Batch indexing complete: {result}")

    except Exception as e:
        logger.error(f"Failed to batch add memories: {e}")
        stats["errors"].append(f"Batch add failed: {e}")

    return stats


def save_snapshot_manifest(stats: dict, output_path: Path) -> None:
    """Save snapshot metadata to JSON manifest file.

    Creates a JSON file with complete snapshot metadata including:
    - snapshot_type: "ta_lab2_pre_reorg"
    - timestamp: ISO format snapshot time
    - commit_hash: Git commit at snapshot time
    - directory_stats: File/function/class counts
    - files_indexed: List of all indexed file paths

    Args:
        stats: Statistics dict from run_ta_lab2_snapshot()
        output_path: Path to save manifest JSON file

    Example:
        >>> from pathlib import Path
        >>> stats = {"total_files": 100, "commit_hash": "49499eb"}
        >>> save_snapshot_manifest(stats, Path(".planning/phases/11-memory-preparation/snapshots/ta_lab2_snapshot.json"))
    """
    # Create parent directories if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "snapshot_type": "ta_lab2_pre_reorg",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "commit_hash": stats.get("commit_hash", "unknown"),
        "directory_stats": {
            "total_files": stats.get("total_files", 0),
            "total_functions": stats.get("total_functions", 0),
            "total_classes": stats.get("total_classes", 0),
            "memories_added": stats.get("memories_added", 0),
            "errors": len(stats.get("errors", [])),
        },
        "files_indexed": stats.get("files_indexed", []),
        "errors": stats.get("errors", []),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    logger.info(f"Snapshot manifest saved to: {output_path}")


def main():
    """CLI entry point for ta_lab2 snapshot script.

    Parses command-line arguments, configures logging, executes snapshot,
    and saves manifest file.

    Usage:
        python run_ta_lab2_snapshot.py [--dry-run]
    """
    parser = argparse.ArgumentParser(
        description="Run ta_lab2 directory snapshot for pre-reorganization baseline"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover files without indexing to memory",
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Get repository path (script location -> src/ta_lab2/tools/ai_orchestrator/memory/snapshot)
    script_path = Path(__file__).resolve()
    repo_path = script_path.parents[6]  # Go up 6 levels to repo root

    logger.info(f"Repository path: {repo_path}")
    logger.info(f"Dry run mode: {args.dry_run}")

    try:
        # Run snapshot
        stats = run_ta_lab2_snapshot(repo_path, dry_run=args.dry_run)

        # Save manifest
        manifest_path = (
            repo_path
            / ".planning"
            / "phases"
            / "11-memory-preparation"
            / "snapshots"
            / "ta_lab2_snapshot.json"
        )
        save_snapshot_manifest(stats, manifest_path)

        # Print summary
        print("\n" + "=" * 60)
        print("TA_LAB2 SNAPSHOT COMPLETE")
        print("=" * 60)
        print(f"Total files: {stats['total_files']}")
        print(f"Total functions: {stats['total_functions']}")
        print(f"Total classes: {stats['total_classes']}")
        print(f"Memories added: {stats['memories_added']}")
        print(f"Errors: {len(stats['errors'])}")
        print(f"Commit hash: {stats['commit_hash']}")
        print(f"\nManifest: {manifest_path}")
        print("=" * 60 + "\n")

        if stats["errors"]:
            print("Errors encountered:")
            for error in stats["errors"][:10]:  # Show first 10
                print(f"  - {error}")
            if len(stats["errors"]) > 10:
                print(f"  ... and {len(stats['errors']) - 10} more")

    except Exception as e:
        logger.error(f"Snapshot failed: {e}", exc_info=True)
        print(f"\nERROR: Snapshot failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
