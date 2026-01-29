"""Fix Qdrant persistence issue and re-run migration.

Qdrant local mode requires explicit flush/close to persist data to disk.
This script properly handles Qdrant client lifecycle and re-runs migration.
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

def main():
    """Execute migration with proper Qdrant persistence."""
    print("=" * 80)
    print("QDRANT PERSISTENCE FIX + MIGRATION")
    print("=" * 80)
    print()

    # Import after env check
    from ta_lab2.tools.ai_orchestrator.memory.migration import migrate_chromadb_to_mem0
    from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
    from ta_lab2.tools.ai_orchestrator.memory.health import MemoryHealthMonitor

    # Get Mem0 client (this initializes Qdrant)
    mem0_client = get_mem0_client()

    try:
        # Step 1: Check existing Mem0 memories
        print("STEP 1: Check existing Mem0 memories")
        print("-" * 80)
        existing = mem0_client.get_all(user_id="orchestrator")
        print(f"Existing memories in Mem0: {len(existing)}")
        print()

        # Step 2: Run migration
        print("STEP 2: Execute ChromaDB -> Mem0 migration")
        print("-" * 80)
        result = migrate_chromadb_to_mem0(
            mem0_client=mem0_client,
            dry_run=False,
            batch_size=100
        )
        print()
        print(result)
        print()

        if result.errors > 0:
            print(f"WARNING: {result.errors} errors occurred")

        # Step 3: Force Qdrant to persist
        print("STEP 3: Force Qdrant persistence")
        print("-" * 80)

        # Access the underlying Qdrant client
        qdrant_client = mem0_client.memory.vector_store.client

        # Explicitly ensure data is flushed (Qdrant auto-flushes but let's be sure)
        print(f"Qdrant client type: {type(qdrant_client)}")
        print(f"Storage location: {qdrant_client.location}")

        # Give Qdrant time to flush writes
        print("Waiting 2 seconds for Qdrant to flush...")
        time.sleep(2)

        # Verify collection exists and has data
        try:
            collection_info = qdrant_client.get_collection("project_memories")
            print(f"Collection points count: {collection_info.points_count}")
            print(f"Collection vectors count: {collection_info.vectors_count}")
        except Exception as e:
            print(f"Warning: Could not get collection info: {e}")

        print()

        # Step 4: Verify persistence by closing and reopening
        print("STEP 4: Verify persistence")
        print("-" * 80)
        print("Closing current client...")

        # Close the Qdrant client properly
        qdrant_client.close()
        print("Client closed")

        # Reset singleton
        from ta_lab2.tools.ai_orchestrator.memory.mem0_client import reset_mem0_client
        reset_mem0_client()

        # Wait a moment
        time.sleep(1)

        # Create new client (should load persisted data)
        print("Creating new client...")
        mem0_client_new = get_mem0_client()

        # Check memories
        memories_after = mem0_client_new.get_all(user_id="orchestrator")
        print(f"Memories after restart: {len(memories_after)}")
        print()

        # Step 5: Health report
        print("STEP 5: Health Report")
        print("-" * 80)
        monitor = MemoryHealthMonitor()
        report = monitor.generate_health_report()

        print(f"Total memories: {report.total_memories}")
        print(f"Healthy: {report.healthy}")
        print(f"Stale: {report.stale}")
        print(f"Missing metadata: {report.missing_metadata}")
        print()

        # Final verdict
        print("=" * 80)
        if len(memories_after) >= result.updated:
            print("✓ PERSISTENCE FIX SUCCESSFUL")
            print("=" * 80)
            print(f"All {len(memories_after)} memories persisted and accessible")
        elif len(memories_after) > 0:
            print("⚠ PARTIAL SUCCESS")
            print("=" * 80)
            print(f"Expected {result.updated}, found {len(memories_after)}")
            print("Some data persisted but not all")
        else:
            print("✗ PERSISTENCE ISSUE REMAINS")
            print("=" * 80)
            print("Data not persisting across client restart")
            print("Consider switching to Qdrant server mode")

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=True)
        raise

    finally:
        # Ensure Qdrant client is properly closed
        try:
            if 'qdrant_client' in locals():
                qdrant_client.close()
        except:
            pass

if __name__ == "__main__":
    main()
