"""Build rich chronological project timeline from Qdrant + git."""
import json
import sys
import io
import subprocess
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO_PATH = Path(__file__).resolve().parents[6]  # ta_lab2 root
QDRANT_URL = "http://localhost:6333"
COLLECTION = "project_memories"


def scroll_all(filt, fields=None, max_points=500):
    """Scroll through filtered points."""
    all_pts = []
    offset = None
    body_base = {
        "limit": 100,
        "with_payload": fields if fields else True,
        "with_vector": False,
        "filter": filt,
    }
    while len(all_pts) < max_points:
        body = dict(body_base)
        if offset:
            body["offset"] = offset
        req = urllib.request.Request(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll",
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


# Fetch all conversation memories from Qdrant
points = scroll_all(
    {"must": [{"key": "category", "match": {"value": "development_context"}}]},
    max_points=500,
)

# Group by phase
by_phase = defaultdict(list)
for p in points:
    pl = p["payload"]
    phase = pl.get("phase", "unknown")
    by_phase[phase].append(pl)

# Get git commit log for context
git_log = (
    subprocess.run(
        ["git", "log", "--format=%h|%ai|%s", "--reverse"],
        capture_output=True,
        text=True,
        cwd=str(REPO_PATH),
    )
    .stdout.strip()
    .split("\n")
)

commits_by_date = defaultdict(list)
for line in git_log:
    parts = line.split("|", 2)
    if len(parts) == 3:
        date = parts[1][:10]
        commits_by_date[date].append(
            {"hash": parts[0], "date": parts[1][:19], "msg": parts[2]}
        )


def phase_sort_key(phase_str):
    try:
        return int(phase_str.split("_")[1])
    except Exception:
        return 999


# Phase descriptions from roadmap knowledge
phase_descriptions = {
    1: "Set up orchestrator foundation, quota tracking, task-to-model routing",
    2: "Integrate existing 3,763 ChromaDB memories with orchestrator for semantic search",
    3: "Migrate ChromaDB to Mem0+Qdrant for conflict detection, dedup, health monitoring",
    4: "Build AI adapter layer (ChatGPT, Gemini, Claude Code) with fallback routing",
    5: "Orchestrator coordination - tier-based routing, cost tracking, workflow state",
    6: "Formalize time model - dim_timeframe, dim_sessions, calendar systems",
    7: "Feature pipeline - EMA multi-TF, calendar anchors, vectorized computation",
    8: "Signal generation - returns features, volatility features, daily views",
    9: "Integration + observability - E2E workflows, correlation IDs, health monitoring",
    10: "Release validation - v0.4.0 test suite, requirements verification, changelog",
    11: "Memory preparation - snapshot 299 ta_lab2 files + 73 external files + 70 conversations",
    12: "Placeholder - skipped",
    13: "Documentation consolidation - merge external docs into ta_lab2",
    14: "Tools integration - migrate Data_Tools, fredtools2, fedtools2 into ta_lab2",
    15: "Economic data strategy - FRED, Fed data integration planning",
    16: "Repository cleanup - archive old code, flatten structure",
    17: "Verification & validation - comprehensive testing of migrated code",
    18: "Structure & documentation - standardize module layout, update docs",
    19: "Memory validation & release - function-level indexing, graph validation, v0.5.0 release",
    20: "Historical context - establish pre-v0.6.0 baseline, identify gaps",
    21: "Comprehensive review - audit all bar builders, EMA refreshers, returns scripts",
    22: "Critical data quality fixes - OHLC correctness, bar integrity, gap handling",
    23: "Reliable incremental refresh - coverage tracking, idempotent builders",
    24: "Pattern consistency - BaseBarBuilder, standardize all builders",
    25: "Baseline capture - SQL snapshots, comparison infrastructure",
}

print("=" * 90)
print("  ta_lab2 PROJECT DEVELOPMENT TIMELINE")
print(f"  Reconstructed from {len(points)} Qdrant conversation memories + git history")
print("=" * 90)

prev_milestone = None
total_commits_linked = 0

for phase_key in sorted(by_phase.keys(), key=phase_sort_key):
    convos = by_phase[phase_key]
    convos.sort(key=lambda c: c.get("timestamp", ""))

    phase_num = phase_sort_key(phase_key)
    milestone = convos[0].get("milestone", "?")
    phase_name = convos[0].get("phase_name", "?")

    # Milestone header
    if milestone != prev_milestone:
        print()
        print("=" * 90)
        if milestone == "v0.4.0":
            print(
                f"  MILESTONE: {milestone} - AI Orchestration + Memory + ta_lab2 Core"
            )
            print("  Period: Jan 22 - Feb 2, 2026 | Phases 1-10")
        elif milestone == "v0.5.0":
            print(
                f"  MILESTONE: {milestone} - Repository Consolidation + Memory Enrichment"
            )
            print("  Period: Feb 2 - Feb 4, 2026 | Phases 11-19")
        elif milestone == "v0.6.0":
            print(f"  MILESTONE: {milestone} - Data Quality + Pattern Standardization")
            print("  Period: Feb 5 - Feb 6, 2026 | Phases 20-26")
        print("=" * 90)
        prev_milestone = milestone

    # Date range
    timestamps = [c.get("timestamp", "") for c in convos if c.get("timestamp")]
    if timestamps:
        first_ts = timestamps[0]
        last_ts = timestamps[-1]
        first_date = first_ts[:10]
        last_date = last_ts[:10]
        date_range = (
            f"{first_date} to {last_date}" if first_date != last_date else first_date
        )
    else:
        date_range = "unknown"

    # Commits linked
    all_commits = set()
    for c in convos:
        for commit in c.get("linked_commits", []):
            all_commits.add(commit)
    total_commits_linked += len(all_commits)

    desc = phase_descriptions.get(phase_num, "")

    print()
    print(f"  Phase {phase_num}: {phase_name}")
    print(f"  {'-' * (len(str(phase_num)) + len(phase_name) + 9)}")
    print(
        f"  Date: {date_range} | Conversations: {len(convos)} | Commits: {len(all_commits)}"
    )
    if desc:
        print(f"  What: {desc}")

    # Key conversations (extract actual content, not metadata)
    shown = 0
    for c in convos:
        if shown >= 2:
            break
        content = c.get("data", "")
        lines = content.split("\n")
        # Find content line
        for line in lines:
            if line.startswith("Content:"):
                text = line[8:].strip()
                # Skip if it's just XML tags or very short
                if len(text) > 30 and not text.startswith("<"):
                    ts = c.get("timestamp", "")[:16]
                    role = c.get("role", "?")
                    # Truncate to fit
                    if len(text) > 85:
                        text = text[:82] + "..."
                    print(f"    > {text}")
                    shown += 1
                break

    if len(all_commits) > 0:
        commit_sample = list(all_commits)[:5]
        print(
            f"  Commits: {', '.join(commit_sample)}{'...' if len(all_commits) > 5 else ''}"
        )

print()
print("=" * 90)
print("  SUMMARY")
print("=" * 90)
print(f"  Total conversation memories: {len(points)}")
print(f"  Phases with conversations: {len(by_phase)}")
print(f"  Total linked commits: {total_commits_linked}")
print()

# Milestone breakdown
milestones = defaultdict(lambda: {"count": 0, "phases": set()})
for p in points:
    pl = p["payload"]
    m = pl.get("milestone", "?")
    milestones[m]["count"] += 1
    milestones[m]["phases"].add(pl.get("phase", "?"))

for m in sorted(milestones.keys()):
    info = milestones[m]
    print(f"  {m}: {info['count']} memories across {len(info['phases'])} phases")

# Date range of entire project
all_ts = [
    p["payload"].get("timestamp", "") for p in points if p["payload"].get("timestamp")
]
all_ts.sort()
if all_ts:
    print()
    print(f"  Project span: {all_ts[0][:10]} to {all_ts[-1][:10]}")
    try:
        d1 = datetime.fromisoformat(all_ts[0].replace("Z", "+00:00"))
        d2 = datetime.fromisoformat(all_ts[-1].replace("Z", "+00:00"))
        days = (d2 - d1).days
        print(f"  Duration: {days} days")
    except Exception:
        pass

print("=" * 90)
