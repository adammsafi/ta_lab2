"""Build chronological project timeline from Qdrant conversation memories."""
import json
import sys
import io
import urllib.request
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

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

# Group by phase, sort by timestamp
by_phase = defaultdict(list)
for p in points:
    pl = p["payload"]
    phase = pl.get("phase", "unknown")
    by_phase[phase].append(pl)


# Sort phases
def phase_sort_key(phase_str):
    try:
        return int(phase_str.split("_")[1])
    except Exception:
        return 999


print("=" * 80)
print("CHRONOLOGICAL PROJECT DEVELOPMENT TIMELINE")
print(f"Based on {len(points)} conversation memories in Qdrant")
print("=" * 80)

for phase_key in sorted(by_phase.keys(), key=phase_sort_key):
    convos = by_phase[phase_key]
    convos.sort(key=lambda c: c.get("timestamp", ""))

    milestone = convos[0].get("milestone", "?")
    phase_name = convos[0].get("phase_name", "?")

    # Get date range
    timestamps = [c.get("timestamp", "") for c in convos if c.get("timestamp")]
    if timestamps:
        first = timestamps[0][:10]
        last = timestamps[-1][:10]
        date_range = f"{first} to {last}" if first != last else first
    else:
        date_range = "unknown"

    # Count commits linked
    all_commits = set()
    for c in convos:
        for commit in c.get("linked_commits", []):
            all_commits.add(commit)

    print()
    print(f"--- {phase_key.upper()} ({phase_name}) [{milestone}] ---")
    print(f"    Date: {date_range}")
    print(f"    Conversations: {len(convos)} | Linked commits: {len(all_commits)}")

    # Show key conversation snippets
    for c in convos[:3]:
        role = c.get("role", "?")
        content = c.get("data", "")
        # Extract first meaningful line of content
        lines = content.split("\n")
        summary = ""
        for line in lines:
            if line.startswith("Content:"):
                summary = line[8:].strip()[:120]
                break
        if not summary:
            summary = lines[0][:120] if lines else "(empty)"

        ts = c.get("timestamp", "?")[:16]
        print(f"    [{ts}] {role}: {summary}")

    if len(convos) > 3:
        print(f"    ... and {len(convos) - 3} more conversations")

print()
print("=" * 80)
print(f"Total: {len(points)} conversation memories across {len(by_phase)} phases")

# Summary stats
milestones = defaultdict(int)
for p in points:
    milestones[p["payload"].get("milestone", "?")] += 1
print("By milestone: " + ", ".join(f"{k}: {v}" for k, v in sorted(milestones.items())))
print("=" * 80)
