"""Execute ChromaDB to Mem0 migration with proper persistence.

This script performs the ChromaDB -> Mem0 migration and ensures Qdrant data is persisted.
"""
import os
import sys
import logging
import time

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Ensure OPENAI_API_KEY is set
if not os.environ.get('OPENAI_API_KEY'):
    print("ERROR: OPENAI_API_KEY environment variable not set")
    sys.exit(1)

from ta_lab2.tools.ai_orchestrator.memory.migration import migrate_chromadb_to_mem0
from ta_lab2.tools.ai_orchestrator.memory.health import MemoryHealthMonitor

def main():
    """Execute ChromaDB to Mem0 migration."""
    print("=" * 80)
    print("CHROMADB -> MEM0 MIGRATION")
    print("=" * 80)
    print()

    # Step 1: Dry run
    print("STEP 1: Dry Run")
    print("-" * 80)
    result_dry = migrate_chromadb_to_mem0(dry_run=True, batch_size=100)
    print(result_dry)
    print()

    if result_dry.total == 0:
        print("No memories found in ChromaDB")
        return

    # Step 2: Execute migration
    print("STEP 2: Execute Migration")
    print("-" * 80)
    print(f"Migrating {result_dry.total} memories...")
    print()

    result = migrate_chromadb_to_mem0(dry_run=False, batch_size=100)
    print()
    print(result)
    print()

    if result.errors > 0:
        print(f"WARNING: {result.errors} errors occurred")
        print(f"Error IDs: {result.error_ids[:10]}")

    # Step 3: Wait for Qdrant to persist
    print("Waiting 5 seconds for Qdrant to persist data...")
    time.sleep(5)

    # Step 4: Verify with health report
    print()
    print("STEP 3: Verification")
    print("-" * 80)
    monitor = MemoryHealthMonitor()
    report = monitor.generate_health_report()

    print(f"Total memories: {report.total_memories}")
    print(f"Healthy: {report.healthy}")
    print(f"Stale: {report.stale}")
    print(f"Missing metadata: {report.missing_metadata}")
    print(f"Age distribution: {report.age_distribution}")
    print()

    if report.total_memories == result.total and report.missing_metadata == 0:
        print("=" * 80)
        print("MIGRATION SUCCESSFUL")
        print("=" * 80)
        print(f"All {report.total_memories} memories migrated with complete metadata")
    else:
        print("=" * 80)
        print("MIGRATION INCOMPLETE")
        print("=" * 80)
        print(f"Expected {result.total}, found {report.total_memories}")
        print(f"Missing metadata: {report.missing_metadata}")

if __name__ == "__main__":
    main()
