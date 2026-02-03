"""Update memory with Phase 14 Data_Tools migration relationships."""
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

# Load OpenAI API key from environment file
load_dotenv('openai_config.env')

from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def load_migration_data():
    """Load migration data from discovery.json."""
    discovery_path = Path('.planning/phases/14-tools-integration/14-01-discovery.json')
    with open(discovery_path) as f:
        data = json.load(f)

    scripts = data['scripts']['root'] + data['scripts']['chatgpt']
    migrated = [s for s in scripts if s['decision'] == 'migrate']
    archived = [s for s in scripts if s['decision'] == 'archive']

    return migrated, archived, data


def create_migration_memories(migrated, dry_run=False):
    """Create migration memories for all migrated scripts."""
    client = get_mem0_client()
    memories_created = 0

    logger.info(f"Creating migration memories for {len(migrated)} scripts (dry_run={dry_run})")

    for script in migrated:
        # Build source path
        if 'chatgpt/' in script['path']:
            source = f"C:/Users/asafi/Downloads/Data_Tools/{script['path']}"
        else:
            source = f"C:/Users/asafi/Downloads/Data_Tools/{script['filename']}"

        target = script['target_dir'] + script['filename']
        category = script['category']

        memory_text = f"""Script migration: {script['filename']}
Moved from: {source}
Moved to: {target}
Category: {category}
Phase: 14 (Tools Integration)
Relationship: moved_to"""

        metadata = {
            "type": "script_migration",
            "source_path": source,
            "target_path": target,
            "category": category,
            "phase": "14",
            "phase_name": "tools-integration",
            "relationship": "moved_to",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if dry_run:
            logger.info(f"[DRY RUN] Would create: {script['filename']} -> {category}/")
        else:
            client.add(
                messages=[{"role": "user", "content": memory_text}],
                user_id="ta_lab2_system",
                metadata=metadata,
                infer=False,  # Batch mode following Phase 11/13 patterns
            )
            memories_created += 1

            if memories_created % 10 == 0:
                logger.info(f"Progress: {memories_created}/{len(migrated)} migration memories created")

    logger.info(f"Created {memories_created} migration memories")
    return memories_created


def create_archive_memories(archived, dry_run=False):
    """Create archive memories for all archived scripts."""
    client = get_mem0_client()
    memories_created = 0

    logger.info(f"Creating archive memories for {len(archived)} scripts (dry_run={dry_run})")

    for script in archived:
        # Build source path
        if 'chatgpt/' in script['path']:
            source = f"C:/Users/asafi/Downloads/Data_Tools/{script['path']}"
        else:
            source = f"C:/Users/asafi/Downloads/Data_Tools/{script['filename']}"

        target = script['target_dir'] + script['filename']

        memory_text = f"""Script archived: {script['filename']}
Original location: {source}
Archived to: {target}
Reason: {script['rationale']}
Phase: 14 (Tools Integration)
Relationship: archived_to"""

        metadata = {
            "type": "script_archive",
            "source_path": source,
            "archive_path": target,
            "reason": script['rationale'][:100],  # Truncate for metadata
            "phase": "14",
            "phase_name": "tools-integration",
            "relationship": "archived_to",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if dry_run:
            logger.info(f"[DRY RUN] Would archive: {script['filename']}")
        else:
            client.add(
                messages=[{"role": "user", "content": memory_text}],
                user_id="ta_lab2_system",
                metadata=metadata,
                infer=False,
            )
            memories_created += 1

    logger.info(f"Created {memories_created} archive memories")
    return memories_created


def create_phase_snapshot(discovery_data, migrated_count, archived_count, dry_run=False):
    """Create Phase 14 completion snapshot."""
    client = get_mem0_client()

    # Count scripts by category
    categories = {}
    for script in [s for s in discovery_data['scripts']['root'] + discovery_data['scripts']['chatgpt'] if s['decision'] == 'migrate']:
        cat = script['category']
        categories[cat] = categories.get(cat, 0) + 1

    snapshot_text = f"""Phase 14: Tools Integration - Completion Snapshot

Summary: Migrated {migrated_count} scripts from external Data_Tools directory into ta_lab2/tools/data_tools/ package. Archived {archived_count} prototype/one-off scripts.

Key Accomplishments:
- Created data_tools package with 6 functional categories
- Migrated analysis, memory, export, context, generators, processing tools
- Standardized imports to ta_lab2 patterns
- Removed hardcoded paths, added CLI arguments
- Created smoke tests and path validation tests
- Archived non-migrated scripts with manifest

Package Structure:
src/ta_lab2/tools/data_tools/
├── analysis/ ({categories.get('analysis', 0)} scripts)
├── memory/ ({categories.get('memory', 0)} scripts)
├── export/ ({categories.get('export', 0)} scripts)
├── context/ ({categories.get('context', 0)} scripts)
├── generators/ ({categories.get('generators', 0)} scripts)
└── processing/ ({categories.get('processing', 0)} scripts)

Requirements Satisfied:
- TOOL-01: Data_Tools scripts moved to src/ta_lab2/tools/data_tools/
- TOOL-02: All import paths updated (no hardcoded paths remain)
- TOOL-03: pytest smoke tests pass for migrated scripts
- MEMO-13: Memory updated with moved_to relationships
- MEMO-14: Phase-level memory snapshot created
"""

    metadata = {
        "type": "phase_snapshot",
        "phase": "14",
        "phase_name": "tools-integration",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "scripts_migrated": migrated_count,
        "scripts_archived": archived_count,
        "categories": list(categories.keys()),
        "requirements_satisfied": ["TOOL-01", "TOOL-02", "TOOL-03", "MEMO-13", "MEMO-14"],
    }

    if dry_run:
        logger.info(f"[DRY RUN] Would create phase snapshot")
        logger.info(f"Snapshot text preview:\n{snapshot_text[:300]}...")
    else:
        client.add(
            messages=[{"role": "user", "content": snapshot_text}],
            user_id="ta_lab2_system",
            metadata=metadata,
            infer=False,
        )
        logger.info("Created Phase 14 snapshot")

    return 1 if not dry_run else 0


def verify_memory_queries():
    """Test memory queries to confirm migration tracking works."""
    client = get_mem0_client()

    queries = [
        ("Where is generate_function_map.py now?", "Should show migration record"),
        ("Data_Tools memory scripts migration", "Should show memory category migrations"),
        ("Phase 14 tools integration", "Should show phase snapshot"),
    ]

    results = {}
    for query, description in queries:
        logger.info(f"\nQuery: {query}")
        logger.info(f"Expected: {description}")

        search_results = client.search(
            query=query,
            user_id="ta_lab2_system",
            limit=3
        )

        # Handle dict vs list response
        if isinstance(search_results, dict):
            search_results = search_results.get('results', [])

        logger.info(f"Results ({len(search_results)} found):")
        for i, result in enumerate(search_results[:2], 1):
            memory_text = result.get("memory", "")
            logger.info(f"  {i}. {memory_text[:150]}...")

        results[query] = search_results

    return results


if __name__ == "__main__":
    import sys

    dry_run = "--dry-run" in sys.argv
    skip_verify = "--skip-verify" in sys.argv

    # Load migration data
    migrated, archived, discovery_data = load_migration_data()

    # Task 1: Create migration memories
    logger.info("\n=== Task 1: Creating migration memories ===")
    migration_count = create_migration_memories(migrated, dry_run=dry_run)
    archive_count = create_archive_memories(archived, dry_run=dry_run)

    # Task 2: Create phase snapshot
    logger.info("\n=== Task 2: Creating phase snapshot ===")
    snapshot_count = create_phase_snapshot(discovery_data, len(migrated), len(archived), dry_run=dry_run)

    # Task 3: Verify queries
    if not skip_verify and not dry_run:
        logger.info("\n=== Task 3: Verifying memory queries ===")
        verify_memory_queries()

    # Summary
    logger.info("\n=== Summary ===")
    logger.info(f"Migration memories: {migration_count}")
    logger.info(f"Archive memories: {archive_count}")
    logger.info(f"Phase snapshot: {snapshot_count}")
    logger.info(f"Total memories created: {migration_count + archive_count + snapshot_count}")
