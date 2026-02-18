"""Build COMPLETE chronological project timeline from ALL Qdrant memories."""
import json
import sys
import io
import urllib.request
from collections import Counter

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def count_filter(filt):
    body = {"filter": filt}
    req = urllib.request.Request(
        "http://localhost:6333/collections/project_memories/points/count",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read().decode("utf-8"))["result"]["count"]


def scroll_all(filt, fields=None, max_points=500):
    """Scroll through filtered points."""
    all_pts = []
    offset = None
    body_base = {
        "limit": 500,
        "with_payload": fields if fields else True,
        "with_vector": False,
        "filter": filt,
    }
    while len(all_pts) < max_points:
        body = dict(body_base)
        if offset:
            body["offset"] = offset
        req = urllib.request.Request(
            "http://localhost:6333/collections/project_memories/points/scroll",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read().decode("utf-8"))
        pts = data["result"]["points"]
        all_pts.extend(pts)
        offset = data["result"].get("next_page_offset")
        if not offset:
            break
    return all_pts


# ============================================================
# Gather all memory counts
# ============================================================

total = count_filter({})

# Original ChromaDB memories
chromadb_count = count_filter(
    {"must": [{"key": "source", "match": {"value": "chromadb_phase2"}}]}
)

# Get ChromaDB memory type breakdown
chromadb_pts = scroll_all(
    {"must": [{"key": "source", "match": {"value": "chromadb_phase2"}}]},
    fields=["data", "created_at"],
    max_points=3763,
)
# Parse types from data field
chromadb_types = Counter()
for p in chromadb_pts:
    data = p["payload"].get("data", "")
    # Extract Type: line
    for line in data.split("\n"):
        if line.startswith("Type:"):
            chromadb_types[line[5:].strip()] += 1
            break
    else:
        chromadb_types["unknown"] += 1

# Phase-level counts (using all known formats)
phase_counts = {}
for phase_num in range(1, 27):
    c = 0
    for val in [phase_num, str(phase_num), f"phase_{phase_num}"]:
        c += count_filter({"must": [{"key": "phase", "match": {"value": val}}]})
    phase_counts[phase_num] = c

# Memory categories
cats_to_check = [
    "development_context",
    "codebase_snapshot",
    "function_definition",
    "function_relationship",
    "file_migration",
    "documentation",
]
cat_counts = {}
for cat in cats_to_check:
    cat_counts[cat] = count_filter(
        {"must": [{"key": "category", "match": {"value": cat}}]}
    )

# Type counts
type_counts = {}
for t in ["file_archive", "script_migration", "script_archive", "doc_reorganization"]:
    type_counts[t] = count_filter({"must": [{"key": "type", "match": {"value": t}}]})

# Source counts
source_counts = {}
for s in [
    "chromadb_phase2",
    "conversation_history_v0.4.0",
    "conversation_history_v0.5.0",
    "conversation_history_v0.6.0",
    "pre_reorg_v0.5.0",
    "pre_integration_v0.5.0",
    "doc_conversion_phase13",
    "architecture_docs_2026",
]:
    source_counts[s] = count_filter(
        {"must": [{"key": "source", "match": {"value": s}}]}
    )


# ============================================================
# Print the complete timeline
# ============================================================

print("=" * 90)
print("  ta_lab2 COMPLETE MEMORY MAP")
print(f"  {total:,} total memories in Qdrant (project_memories collection)")
print("=" * 90)

print()
print("  LAYER 1: ORIGINAL KNOWLEDGE BASE (Pre-GSD)")
print("  " + "-" * 60)
print(f"  {chromadb_count:,} memories migrated from ChatGPT/ChromaDB")
print("  These span Oct 2025 - Jan 2026 (project inception to GSD start)")
print()
print("  Memory types:")
for t, c in chromadb_types.most_common(15):
    print(f"    {t}: {c:,}")

print()
print("=" * 90)
print("  LAYER 2: GSD DEVELOPMENT HISTORY (Jan 22 - Feb 6, 2026)")
print("  " + "-" * 60)

# Phase descriptions
descs = {
    1: ("Foundation & Quota Management", "v0.4.0", "Jan 26"),
    2: ("Memory Core - ChromaDB Integration", "v0.4.0", "Jan 28"),
    3: ("Memory Advanced - Mem0 Migration", "v0.4.0", "Jan 28"),
    4: ("Orchestrator Adapters", "v0.4.0", "Jan 29"),
    5: ("Orchestrator Coordination", "v0.4.0", "Jan 29"),
    6: ("ta_lab2 Time Model", "v0.4.0", "Jan 30"),
    7: ("ta_lab2 Feature Pipeline", "v0.4.0", "Jan 30"),
    8: ("ta_lab2 Signals", "v0.4.0", "Jan 30"),
    9: ("Integration & Observability", "v0.4.0", "Jan 30-31"),
    10: ("Release Validation", "v0.4.0", "Feb 1-2"),
    11: ("Memory Preparation", "v0.5.0", "Feb 2"),
    12: ("(Skipped)", "v0.5.0", "-"),
    13: ("Documentation Consolidation", "v0.5.0", "Feb 2-3"),
    14: ("Tools Integration", "v0.5.0", "Feb 3"),
    15: ("Economic Data Strategy", "v0.5.0", "Feb 3"),
    16: ("Repository Cleanup", "v0.5.0", "Feb 3"),
    17: ("Verification & Validation", "v0.5.0", "Feb 3"),
    18: ("Structure & Documentation", "v0.5.0", "Feb 4"),
    19: ("Memory Validation & Release", "v0.5.0", "Feb 4"),
    20: ("Historical Context", "v0.6.0", "Feb 5"),
    21: ("Comprehensive Review", "v0.6.0", "Feb 5"),
    22: ("Critical Data Quality Fixes", "v0.6.0", "Feb 5"),
    23: ("Reliable Incremental Refresh", "v0.6.0", "Feb 5"),
    24: ("Pattern Consistency", "v0.6.0", "Feb 5"),
    25: ("Baseline Capture", "v0.6.0", "Feb 5"),
    26: ("(Planned)", "v0.6.0", "-"),
}

prev_ms = None
for phase_num in range(1, 27):
    desc, ms, date = descs.get(phase_num, ("?", "?", "?"))
    count = phase_counts[phase_num]

    if ms != prev_ms:
        print()
        print(f"  --- {ms} ---")
        prev_ms = ms

    indicator = " " if count > 0 else "!"
    bar = "#" * min(count // 2, 40) if count else ""
    print(
        f"  {indicator} Phase {phase_num:>2}: {desc:<42} {date:<10} {count:>5} mems  {bar}"
    )

print()
print("=" * 90)
print("  LAYER 3: MEMORY COMPOSITION")
print("  " + "-" * 60)

print()
print("  By source:")
for s, c in sorted(source_counts.items(), key=lambda x: -x[1]):
    print(f"    {s}: {c:,}")
unsourced = total - sum(source_counts.values())
print(f"    (unsourced/phase-tagged): {unsourced:,}")

print()
print("  By category:")
for cat, c in sorted(cat_counts.items(), key=lambda x: -x[1]):
    print(f"    {cat}: {c:,}")

print()
print("  By type (file operations):")
for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
    print(f"    {t}: {c:,}")

print()
print("=" * 90)
print("  GAPS & ISSUES")
print("  " + "-" * 60)

gaps = []
for phase_num in range(1, 26):
    if phase_counts[phase_num] == 0 and phase_num != 12:
        gaps.append(phase_num)

if gaps:
    print(f"  Phases with ZERO memories: {gaps}")
else:
    print("  No phase gaps (all phases have memories)")

# Check conversation coverage
conv_phases = set()
for src in [
    "conversation_history_v0.4.0",
    "conversation_history_v0.5.0",
    "conversation_history_v0.6.0",
]:
    pts = scroll_all(
        {"must": [{"key": "source", "match": {"value": src}}]}, ["phase"], 200
    )
    for p in pts:
        conv_phases.add(p["payload"].get("phase", ""))

conv_phase_nums = set()
for cp in conv_phases:
    if cp.startswith("phase_"):
        try:
            conv_phase_nums.add(int(cp.split("_")[1]))
        except ValueError:
            pass

missing_convos = []
for phase_num in range(1, 26):
    if phase_num not in conv_phase_nums and phase_num != 12:
        missing_convos.append(phase_num)

if missing_convos:
    print(f"  Phases missing CONVERSATION memories: {missing_convos}")
    print("    (These phases have code/file memories but no Claude Code conversations)")
    print(
        "    Fix: Run conversation snapshot for these phases or check if sessions exist"
    )

print()
print("  ChatGPT conversation coverage:")
print(f"    Original ChatGPT memories in Qdrant: {chromadb_count:,}")
print("    These predate the GSD workflow and cover Oct-Jan project discussions")
print("    They have Title/Type/Content format but no phase tagging")

print()
print("=" * 90)
