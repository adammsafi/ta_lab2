"""Execute full migration: ChromaDB -> Mem0 -> Metadata enrichment.

This script performs the complete Phase 3 migration:
1. Migrate all memories from ChromaDB (Phase 2) to Mem0/Qdrant (Phase 3)
2. Enrich all memories with enhanced metadata (created_at, last_verified)
3. Validate migration success
"""
import os
import sys
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Ensure OPENAI_API_KEY is set
if not os.environ.get('OPENAI_API_KEY'):
    print("ERROR: OPENAI_API_KEY environment variable not set")
    print("Please set it: export OPENAI_API_KEY=your-key-here")
    sys.exit(1)

from ta_lab2.tools.ai_orchestrator.memory.migration import (
    migrate_chromadb_to_mem0,
    migrate_metadata,
    validate_migration
)

def main():
    """Execute full migration pipeline."""
    print("=" * 80)
    print("PHASE 3 FULL MIGRATION")
    print("=" * 80)
    print()

    # Step 1: ChromaDB -> Mem0 migration (dry run first)
    print("STEP 1: ChromaDB -> Mem0 Migration (Dry Run)")
    print("-" * 80)

    result1_dry = migrate_chromadb_to_mem0(dry_run=True, batch_size=100)
    print(result1_dry)
    print()

    if result1_dry.total == 0:
        print("WARNING: No memories found in ChromaDB to migrate")
        print("Skipping ChromaDB -> Mem0 migration")
    else:
        # Ask for confirmation
        print(f"Will migrate {result1_dry.total} memories from ChromaDB to Mem0")
        response = input("Proceed with ChromaDB -> Mem0 migration? (yes/no): ")

        if response.lower() != 'yes':
            print("Migration cancelled by user")
            return

        print()
        print("Executing ChromaDB -> Mem0 migration...")
        result1 = migrate_chromadb_to_mem0(dry_run=False, batch_size=100)
        print()
        print(result1)
        print()

        if result1.errors > 0:
            print(f"WARNING: {result1.errors} errors occurred during ChromaDB -> Mem0 migration")
            print(f"Error IDs: {result1.error_ids[:10]}")
            response = input("Continue with metadata migration? (yes/no): ")
            if response.lower() != 'yes':
                print("Migration stopped by user")
                return

    # Step 2: Metadata enrichment (dry run first)
    print()
    print("STEP 2: Metadata Enrichment (Dry Run)")
    print("-" * 80)

    result2_dry = migrate_metadata(dry_run=True, batch_size=100)
    print(result2_dry)
    print()

    if result2_dry.total == 0:
        print("WARNING: No memories found in Mem0 to enrich")
        print("Migration incomplete")
        return

    # Ask for confirmation
    print(f"Will enrich metadata for {result2_dry.updated} memories")
    response = input("Proceed with metadata enrichment? (yes/no): ")

    if response.lower() != 'yes':
        print("Migration cancelled by user")
        return

    print()
    print("Executing metadata enrichment...")
    result2 = migrate_metadata(dry_run=False, batch_size=100)
    print()
    print(result2)
    print()

    if result2.errors > 0:
        print(f"WARNING: {result2.errors} errors occurred during metadata enrichment")
        print(f"Error IDs: {result2.error_ids[:10]}")

    # Step 3: Validation
    print()
    print("STEP 3: Migration Validation")
    print("-" * 80)

    success, message = validate_migration(sample_size=100)
    print(message)
    print()

    if success:
        print("=" * 80)
        print("MIGRATION COMPLETE")
        print("=" * 80)
        print()
        print(f"Total memories migrated: {result2.total}")
        print(f"Metadata enrichment success rate: {(result2.updated + result2.skipped) / result2.total * 100:.1f}%")
        print()
        print("Phase 3 migration successful!")
    else:
        print("=" * 80)
        print("MIGRATION VALIDATION FAILED")
        print("=" * 80)
        print()
        print("Please review the errors above and re-run migration if needed")
        sys.exit(1)

if __name__ == "__main__":
    main()
