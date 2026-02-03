"""Update memory with Phase 15 archive, extraction, and alternatives relationships.

Creates comprehensive memory graph with relationship types:
- archived_for: Why packages were archived
- replaced_by: What ecosystem packages replace archived ones
- extracted_from: Where utils.economic functions came from
- equivalent_to: Function-level mappings
- implements: What new modules implement

Usage:
    python scripts/update_phase15_memory.py

Prerequisites:
    - Qdrant running on localhost:6333
    - openai_config.env with OPENAI_API_KEY
"""
from datetime import datetime

# Load API key
from dotenv import load_dotenv

load_dotenv("openai_config.env")

from mem0 import Memory

# Initialize Mem0 client
config = {
    "llm": {"provider": "openai", "config": {"model": "gpt-4o-mini"}},
    "embedder": {"provider": "openai"},
    "vector_store": {
        "provider": "qdrant",
        "config": {
            "host": "localhost",
            "port": 6333,
            "collection_name": "ta_lab2_memories",
        },
    },
}
client = Memory.from_config(config)
user_id = "ta_lab2_codebase"

memories_added = 0

# ============================================
# 1. Archive Relationships (archived_for)
# ============================================
archive_memories = [
    {
        "text": (
            "Package fredtools2 was archived in Phase 15 (Economic Data Strategy) on 2026-02-03. "
            "Archive location: .archive/external-packages/2026-02-03/fredtools2/. "
            "Original location: C:/Users/asafi/Downloads/fredtools2. "
            "Archive reason: Zero usage in ta_lab2 codebase, ecosystem alternatives superior. "
            "fredtools2 was a 167-line PostgreSQL-backed FRED data ingestion tool with CLI (fred init/releases/series). "
            "Relationship: archived_for"
        ),
        "metadata": {
            "type": "archive_relationship",
            "relationship": "archived_for",
            "package_name": "fredtools2",
            "source_path": "C:/Users/asafi/Downloads/fredtools2",
            "archive_path": ".archive/external-packages/2026-02-03/fredtools2/",
            "phase": "15-economic-data-strategy",
            "action": "archived",
            "reason": "Zero usage, ecosystem alternatives superior",
        },
    },
    {
        "text": (
            "Package fedtools2 was archived in Phase 15 (Economic Data Strategy) on 2026-02-03. "
            "Archive location: .archive/external-packages/2026-02-03/fedtools2/. "
            "Original location: C:/Users/asafi/Downloads/fedtools2. "
            "Archive reason: Zero usage in ta_lab2 codebase, ecosystem alternatives superior. "
            "fedtools2 was a 659-line ETL tool for consolidating Federal Reserve policy target datasets "
            "(FEDFUNDS, DFEDTAR, DFEDTARL, DFEDTARU) with TARGET_MID, TARGET_SPREAD, and regime labels. "
            "Relationship: archived_for"
        ),
        "metadata": {
            "type": "archive_relationship",
            "relationship": "archived_for",
            "package_name": "fedtools2",
            "source_path": "C:/Users/asafi/Downloads/fedtools2",
            "archive_path": ".archive/external-packages/2026-02-03/fedtools2/",
            "phase": "15-economic-data-strategy",
            "action": "archived",
            "reason": "Zero usage, ecosystem alternatives superior",
        },
    },
]

# ============================================
# 2. Replacement Relationships (replaced_by)
# ============================================
replacement_memories = [
    {
        "text": (
            "fredtools2 is replaced by fredapi (ecosystem package). "
            "fredapi provides: FRED API client with pandas integration, data revision handling (ALFRED), "
            "full FRED API coverage (series, releases, categories, tags), active maintenance since 2014. "
            "Install: pip install fredapi>=0.5.2 or pip install ta_lab2[fred]. "
            "Relationship: replaced_by"
        ),
        "metadata": {
            "type": "replacement_relationship",
            "relationship": "replaced_by",
            "old_package": "fredtools2",
            "new_package": "fredapi",
            "new_version": ">=0.5.2",
            "install_command": "pip install ta_lab2[fred]",
            "phase": "15-economic-data-strategy",
        },
    },
    {
        "text": (
            "fredtools2 can also be replaced by fedfred (modern async alternative). "
            "fedfred provides: async support for high-volume workflows, built-in rate limiting (120 calls/min), "
            "automatic caching with TTL, Pandas/Polars/Dask support. "
            "Install: pip install fedfred>=1.0. "
            "Relationship: replaced_by"
        ),
        "metadata": {
            "type": "replacement_relationship",
            "relationship": "replaced_by",
            "old_package": "fredtools2",
            "new_package": "fedfred",
            "new_version": ">=1.0",
            "phase": "15-economic-data-strategy",
        },
    },
    {
        "text": (
            "fedtools2 unique logic (TARGET_MID, TARGET_SPREAD, regime labels) extracted to ta_lab2.utils.economic. "
            "For basic FRED data access, use fredapi or ta_lab2.integrations.economic.FredProvider. "
            "The combine_timeframes and missing_ranges utilities are now in ta_lab2.utils.economic. "
            "Relationship: replaced_by"
        ),
        "metadata": {
            "type": "replacement_relationship",
            "relationship": "replaced_by",
            "old_package": "fedtools2",
            "new_package": "ta_lab2.utils.economic + ta_lab2.integrations.economic",
            "phase": "15-economic-data-strategy",
        },
    },
]

# ============================================
# 3. Extraction Relationships (extracted_from)
# ============================================
extraction_memories = [
    {
        "text": (
            "Function combine_timeframes in ta_lab2.utils.economic.consolidation was extracted from fedtools2. "
            "Original source: fedtools2.utils.consolidation.combine_timeframes. "
            "Purpose: Merge multiple time series DataFrames with coverage tracking (has_{name} flags). "
            "Cleaned up with full type hints, comprehensive docstrings, removed S#/V# comment style. "
            "Relationship: extracted_from"
        ),
        "metadata": {
            "type": "extraction_relationship",
            "relationship": "extracted_from",
            "function_name": "combine_timeframes",
            "target_module": "ta_lab2.utils.economic.consolidation",
            "source_module": "fedtools2.utils.consolidation",
            "source_package": "fedtools2",
            "phase": "15-economic-data-strategy",
        },
    },
    {
        "text": (
            "Function missing_ranges in ta_lab2.utils.economic.consolidation was extracted from fedtools2. "
            "Original source: fedtools2.utils.consolidation.missing_ranges. "
            "Purpose: Detect contiguous ranges where a boolean mask is True (gap detection). "
            "Cleaned up with full type hints and comprehensive docstrings. "
            "Relationship: extracted_from"
        ),
        "metadata": {
            "type": "extraction_relationship",
            "relationship": "extracted_from",
            "function_name": "missing_ranges",
            "target_module": "ta_lab2.utils.economic.consolidation",
            "source_module": "fedtools2.utils.consolidation",
            "source_package": "fedtools2",
            "phase": "15-economic-data-strategy",
        },
    },
    {
        "text": (
            "Functions read_csv and ensure_dir in ta_lab2.utils.economic.io_helpers were extracted from fedtools2. "
            "Original source: fedtools2.utils.io. "
            "Purpose: Simple I/O utilities for loading economic data. "
            "Cleaned up with type hints, removed environment-specific paths. "
            "Relationship: extracted_from"
        ),
        "metadata": {
            "type": "extraction_relationship",
            "relationship": "extracted_from",
            "function_name": "read_csv, ensure_dir",
            "target_module": "ta_lab2.utils.economic.io_helpers",
            "source_module": "fedtools2.utils.io",
            "source_package": "fedtools2",
            "phase": "15-economic-data-strategy",
        },
    },
]

# ============================================
# 4. Equivalence Relationships (equivalent_to)
# ============================================
equivalence_memories = [
    {
        "text": (
            "fredtools2.fred_api.get_series_observations is equivalent to fredapi.Fred.get_series. "
            "Both fetch FRED series data by series_id. "
            "fredapi returns pandas Series directly; fredtools2 returned list of dicts. "
            "Relationship: equivalent_to"
        ),
        "metadata": {
            "type": "equivalence_relationship",
            "relationship": "equivalent_to",
            "old_function": "fredtools2.fred_api.get_series_observations",
            "new_function": "fredapi.Fred.get_series",
            "phase": "15-economic-data-strategy",
        },
    },
    {
        "text": (
            "fredtools2.jobs.releases.pull_releases is equivalent to ta_lab2.integrations.economic.FredProvider.get_releases. "
            "Both fetch FRED release metadata. "
            "FredProvider also supports search and series info. "
            "Relationship: equivalent_to"
        ),
        "metadata": {
            "type": "equivalence_relationship",
            "relationship": "equivalent_to",
            "old_function": "fredtools2.jobs.releases.pull_releases",
            "new_function": "ta_lab2.integrations.economic.FredProvider.get_releases",
            "phase": "15-economic-data-strategy",
        },
    },
]

# ============================================
# 5. Implementation Relationships (implements)
# ============================================
implementation_memories = [
    {
        "text": (
            "ta_lab2.integrations.economic.FredProvider implements EconomicDataProvider protocol. "
            "FredProvider wraps fredapi to provide FRED data access with rate limiting, caching, and circuit breaker. "
            "Methods: get_series, get_series_info, search, get_releases, validate_api_key. "
            "Install: pip install ta_lab2[fred]. "
            "Relationship: implements"
        ),
        "metadata": {
            "type": "implementation_relationship",
            "relationship": "implements",
            "class_name": "FredProvider",
            "module": "ta_lab2.integrations.economic.fred_provider",
            "protocol": "EconomicDataProvider",
            "phase": "15-economic-data-strategy",
        },
    },
    {
        "text": (
            "ta_lab2.integrations.economic module implements production-ready economic data integration. "
            "Features: rate limiting (120 calls/min), TTL caching, circuit breaker, data quality validation. "
            "Types: EconomicSeries, FetchResult, SeriesInfo. "
            "Providers: FredProvider (working), Fed provider (future). "
            "Relationship: implements"
        ),
        "metadata": {
            "type": "implementation_relationship",
            "relationship": "implements",
            "module": "ta_lab2.integrations.economic",
            "features": [
                "rate_limiting",
                "caching",
                "circuit_breaker",
                "quality_validation",
            ],
            "phase": "15-economic-data-strategy",
        },
    },
]

# Add all memories with infer=False for batch performance
all_memories = (
    archive_memories
    + replacement_memories
    + extraction_memories
    + equivalence_memories
    + implementation_memories
)

print(f"Adding {len(all_memories)} memory records...")

for mem in all_memories:
    mem["metadata"]["timestamp"] = datetime.now().isoformat()
    result = client.add(
        mem["text"], user_id=user_id, metadata=mem["metadata"], infer=False
    )
    memories_added += 1
    print(
        f"  Added: {mem['metadata'].get('relationship', 'unknown')} - {mem['metadata'].get('package_name', mem['metadata'].get('function_name', 'unknown'))}"
    )

print(f"\nTotal memories added: {memories_added}")

# ============================================
# 6. Phase Completion Snapshot
# ============================================
phase_snapshot = {
    "text": (
        "Phase 15 (Economic Data Strategy) completed on 2026-02-03. "
        "Decision: Archive fredtools2 and fedtools2 packages, extract valuable utilities, create integration skeleton. "
        "Archive: Both packages archived to .archive/external-packages/2026-02-03/ with manifest, ALTERNATIVES.md, and dependency snapshot. "
        "Extraction: combine_timeframes, missing_ranges, read_csv, ensure_dir extracted to ta_lab2.utils.economic. "
        "Integration: ta_lab2.integrations.economic created with FredProvider (working fredapi passthrough), "
        "rate limiting, caching, circuit breaker, and data quality validation. "
        "Configuration: pyproject.toml updated with [fred], [fed], [economic] extras; economic_data.env.example created. "
        "Migration: docs/migration/ECONOMIC_DATA.md guide and migration_tool.py scanner created. "
        "Requirements satisfied: ECON-01 (function inventory), ECON-02 (decision documented), ECON-03 (archive/integration), "
        "MEMO-13 (moved_to/archived_to relationships), MEMO-14 (phase snapshot). "
        "Archive totals: 2 packages, ~826 lines. New code: ~1500 lines across integrations.economic and utils.economic."
    ),
    "metadata": {
        "type": "phase_snapshot",
        "phase": "15-economic-data-strategy",
        "phase_name": "Economic Data Strategy",
        "status": "complete",
        "decision": "archive + extract + integrate",
        "packages_archived": 2,
        "packages_archived_names": ["fredtools2", "fedtools2"],
        "modules_created": ["ta_lab2.utils.economic", "ta_lab2.integrations.economic"],
        "features_added": [
            "FredProvider (fredapi passthrough)",
            "rate_limiting",
            "caching",
            "circuit_breaker",
            "quality_validation",
            "migration_tool",
        ],
        "requirements_satisfied": [
            "ECON-01",
            "ECON-02",
            "ECON-03",
            "MEMO-13",
            "MEMO-14",
        ],
        "archive_path": ".archive/external-packages/2026-02-03/",
        "ecosystem_alternatives": ["fredapi", "fedfred"],
        "timestamp": datetime.now().isoformat(),
    },
}

result = client.add(
    phase_snapshot["text"],
    user_id=user_id,
    metadata=phase_snapshot["metadata"],
    infer=False,
)
print(f"\nPhase snapshot added: {result}")

# ============================================
# 7. Verification Queries
# ============================================
print("\n" + "=" * 60)
print("MEMORY QUERY VERIFICATION")
print("=" * 60)

verification_queries = [
    # Archive queries
    ("Where is fredtools2 now?", "Should return archive path"),
    ("What happened to fedtools2?", "Should return archive decision"),
    # Replacement queries (context requirement: "what replaced fredtools2?")
    ("What replaced fredtools2?", "Should return fredapi"),
    ("What should I use instead of fedtools2?", "Should return ta_lab2.utils.economic"),
    # Extraction queries
    ("Where did combine_timeframes come from?", "Should return fedtools2"),
    ("What was extracted from fedtools2?", "Should list functions"),
    # Equivalence queries
    ("What is equivalent to get_series_observations?", "Should return Fred.get_series"),
    # Phase queries
    ("Phase 15 economic data strategy", "Should return phase snapshot"),
    (
        "What modules were created in phase 15?",
        "Should list utils.economic, integrations.economic",
    ),
]

for query, expected in verification_queries:
    results = client.search(query, user_id=user_id, limit=3)

    # Handle dict vs list response format
    if isinstance(results, dict):
        results = results.get("results", [])

    print(f"\nQuery: {query}")
    print(f"Expected: {expected}")
    print(f"Results: {len(results)} found")

    if results:
        for r in results[:2]:
            memory = r.get("memory", r.get("text", "No text"))
            # Truncate long memories
            memory_preview = memory[:150] + "..." if len(memory) > 150 else memory
            print(f"  -> {memory_preview}")
    else:
        print("  -> NO RESULTS (may need to verify memory addition)")

print("\n" + "=" * 60)
print("Verification complete. Key queries should return relevant results.")
print("=" * 60)
