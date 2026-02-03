from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from openai import OpenAI
except ImportError:
    print("Error: openai library not found. Install with: pip install openai")
    raise SystemExit(1)


FM_START = "---\n"
FM_END = "\n---\n"


# ---------------------------
# YAML front-matter helpers
# ---------------------------

def has_front_matter(text: str) -> bool:
    t = text.lstrip("\ufeff\r\n\t ")
    return t.startswith(FM_START) and (FM_END in t[len(FM_START):])


def split_front_matter(text: str) -> Tuple[Optional[str], str]:
    t = text.lstrip("\ufeff\r\n\t ")
    if not has_front_matter(text):
        return None, text
    end_idx = t.find(FM_END, len(FM_START))
    if end_idx == -1:
        return None, text
    fm = t[len(FM_START):end_idx]
    rest = t[end_idx + len(FM_END):]
    return fm, rest


def parse_front_matter_minimal(fm: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    lines = fm.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line or line.lstrip().startswith("#"):
            i += 1
            continue

        m_list = re.match(r"^([A-Za-z0-9_]+):\s*$", line)
        if m_list:
            key = m_list.group(1)
            i += 1
            if i < len(lines) and lines[i].strip() == "[]":
                out[key] = []
                i += 1
                continue
            items: List[str] = []
            while i < len(lines) and lines[i].lstrip().startswith("- "):
                items.append(lines[i].lstrip()[2:].strip().strip('"'))
                i += 1
            out[key] = items
            continue

        m = re.match(r"^([A-Za-z0-9_]+):\s*(.*)$", line)
        if m:
            key = m.group(1)
            val = m.group(2).strip()
            if val.startswith('"') and val.endswith('"'):
                val = val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
            if val == "null":
                out[key] = None
            elif val in ("true", "false"):
                out[key] = (val == "true")
            else:
                if re.fullmatch(r"-?\d+", val):
                    out[key] = int(val)
                else:
                    out[key] = val
        i += 1
    return out


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def clip_text(body: str, max_chars: int) -> str:
    if len(body) <= max_chars:
        return body
    half = max_chars // 2
    return body[:half] + "\n\n[...CLIPPED...]\n\n" + body[-half:]


# ---------------------------
# OpenAI schema (child memories)
# ---------------------------

CHILD_SCHEMA_NAME = "child_memories_v1"
CHILD_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "memories": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["decision", "procedure", "invariant", "definition", "bug", "fix", "todo", "insight", "meta"],
                    },
                    "title": {"type": "string", "maxLength": 120},
                    "content": {"type": "string", "maxLength": 900},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "conflict_key": {
                        "type": "string",
                        "maxLength": 80,
                        "description": (
                            "Optional normalized key for conflict grouping, e.g., "
                            "'model_selection', 'cli_structure', 'time_model_invariant'"
                        ),
                    },
                    "decision_status": {
                        "type": "string",
                        "enum": ["", "proposed", "accepted", "implemented", "deprecated"],
                        "description": "Only for type=decision, else empty string.",
                    },
                    "evidence_hint": {
                        "type": "string",
                        "maxLength": 200,
                        "description": "Optional hint about what could verify this in code/tests/docs, e.g. 'pyproject.toml [project.scripts]'",
                    },
                },
                "required": ["type", "title", "content", "confidence", "conflict_key", "decision_status", "evidence_hint"],
            },
        }
    },
    "required": ["memories"],
}


def extract_child_memories(
    client: OpenAI,
    model: str,
    reasoning_effort: str,
    parent_title: str,
    parent_projects: List[str],
    parent_tags: List[str],
    chunk_text: str,
) -> Dict[str, Any]:
    system_prompt = (
        "You are extracting atomic 'memories' from a ChatGPT conversation chunk.\n"
        "Return ONLY JSON matching the schema.\n"
        "Prefer specific, actionable items.\n"
        "Decisions: mark status (proposed/accepted/implemented/deprecated) when clearly implied by language.\n"
        "If a decision is uncertain, use proposed.\n"
        "Use conflict_key only when it helps group potentially conflicting decisions across time.\n"
        "Do not invent file paths; use evidence_hint as a suggestion only.\n"
    )
    user_prompt = (
        f"Conversation title: {parent_title}\n"
        f"Projects: {parent_projects}\n"
        f"Tags: {parent_tags}\n\n"
        f"Chunk:\n{chunk_text}\n"
    )

    resp = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        reasoning={"effort": reasoning_effort},
        text={
            "format": {
                "type": "json_schema",
                "name": CHILD_SCHEMA_NAME,
                "schema": CHILD_SCHEMA,
                "strict": True,
            }
        },
    )

    # Best-effort parsed extraction
    data = None
    for item in getattr(resp, "output", []) or []:
        for c in getattr(item, "content", []) or []:
            parsed = getattr(c, "parsed", None)
            if parsed:
                data = parsed
                break
        if data:
            break
    if data is not None:
        return data

    raw_text = getattr(resp, "output_text", "") or ""
    if not raw_text:
        for item in getattr(resp, "output", []) or []:
            for c in getattr(item, "content", []) or []:
                t = getattr(c, "text", None)
                if t:
                    raw_text = t
                    break
            if raw_text:
                break
    if not raw_text:
        raise ValueError("No JSON text returned by model.")

    # Robust parse: allow extra trailing data by decoding only the first JSON object
    dec = json.JSONDecoder()
    raw_text_stripped = raw_text.lstrip()
    obj, _idx = dec.raw_decode(raw_text_stripped)

    # Safety: ensure it's a dict and has expected key
    if not isinstance(obj, dict) or "memories" not in obj:
        raise ValueError(
            f"Parsed JSON did not match expected shape. type={type(obj)} keys={list(obj)[:10] if isinstance(obj, dict) else 'n/a'}"
        )

    return obj


# ---------------------------
# Chunking logic
# ---------------------------

USER_BLOCK_RE = re.compile(r"^##\s+USER\s+\(", re.MULTILINE)
ASSISTANT_BLOCK_RE = re.compile(r"^##\s+ASSISTANT\s+\(", re.MULTILINE)


def chunk_by_sections(body: str, max_chars: int) -> List[str]:
    """
    Simple chunking: split on "## USER (" boundaries, then pack into <= max_chars.
    Works well for your exported markdown format.
    """
    parts = re.split(r"(?=^##\s+USER\s+\()", body, flags=re.MULTILINE)
    parts = [p for p in parts if p.strip()]

    chunks: List[str] = []
    cur = ""
    for p in parts:
        if not cur:
            cur = p
        elif len(cur) + len(p) + 2 <= max_chars:
            cur += "\n\n" + p
        else:
            chunks.append(cur)
            cur = p
    if cur.strip():
        chunks.append(cur)

    # If a single chunk is still too big, hard clip
    out: List[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            out.append(c)
        else:
            out.append(clip_text(c, max_chars))
    return out


# ---------------------------
# Conflict grouping + review queue
# ---------------------------

def norm_key(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:80]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Instantiate child memories (Strategy 2) with auditable provenance + conflict grouping."
    )
    ap.add_argument("--kept-manifest", required=True, help="Path to kept conversations manifest CSV")
    ap.add_argument("--out-dir", required=True, help="Output directory for memory_children.jsonl")
    ap.add_argument("--model", default="gpt-5.2", help="Default gpt-5.2")
    ap.add_argument("--reasoning-effort", default="high", choices=["none", "medium", "high", "xhigh"])
    ap.add_argument("--max-chars-per-chunk", type=int, default=12000)
    ap.add_argument("--max-chunks-per-convo", type=int, default=6)
    ap.add_argument("--max-memories-per-chunk", type=int, default=10, help="Soft cap enforced via prompt/schema maxItems")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run-manifest-out", default="memory_children_run_manifest.json")
    args = ap.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY env var is not set.")

    out_dir = Path(args.out_dir)
    ensure_dir(out_dir)

    client = OpenAI()
    kept_rows = read_csv(Path(args.kept_manifest))

    children_jsonl = out_dir / "memory_children.jsonl"
    conflicts_json = out_dir / "memory_conflicts.json"
    review_csv = out_dir / "review_queue.csv"
    run_manifest = out_dir / args.run_manifest_out

    run_utc = datetime.now(timezone.utc).isoformat()

    processed_convos = 0
    total_child_memories = 0
    errors: List[Dict[str, Any]] = []

    done_parents: set[str] = set()

    if children_jsonl.exists():
        with children_jsonl.open("r", encoding="utf-8") as rf:
            for line in rf:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    mid = str(obj.get("memory_id") or "")
                    pmid = str(obj.get("parent_memory_id") or "").strip()
                    if pmid and mid.endswith("::DONE"):
                        done_parents.add(pmid)
                except Exception:
                    continue

    print(f"[resume] found {len(done_parents)} completed parents (DONE markers)", flush=True)

    # conflict_key -> list[child_memory]
    conflicts: Dict[str, List[Dict[str, Any]]] = {}

    # write jsonl streaming (unless dry-run)
    out_f = None
    if not args.dry_run:
        out_f = children_jsonl.open("a", encoding="utf-8")

    def emit(obj: Dict[str, Any]) -> None:
        nonlocal total_child_memories
        total_child_memories += 1
        ck = norm_key(obj.get("conflict_key", ""))
        if ck:
            conflicts.setdefault(ck, []).append(obj)
        if out_f is not None:
            out_f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            out_f.flush()

    for kr in kept_rows:
        cid = (kr.get("id") or "").strip()
        md_path_s = (kr.get("dest_path") or kr.get("resolved_path") or kr.get("src_path") or "").strip()
        if not cid or not md_path_s:
            continue

        md_path = Path(md_path_s)
        if not md_path.exists():
            continue

        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
            fm_raw, body = split_front_matter(text)
            if fm_raw is None:
                continue
            fm = parse_front_matter_minimal(fm_raw)

            parent_memory_id = str(fm.get("memory_id") or "").strip()
            if not parent_memory_id:
                errors.append({"conversation_id": cid, "path": str(md_path), "error": "missing memory_id in front matter"})
                continue

            if parent_memory_id in done_parents:
                print(f"[resume] skipping already done convo={cid} parent={parent_memory_id}", flush=True)
                continue

            parent_title = str(fm.get("title") or "").strip()
            parent_projects = fm.get("projects") or []
            parent_tags = fm.get("tags") or []

            chunks = chunk_by_sections(body, args.max_chars_per_chunk)[: args.max_chunks_per_convo]
            print(f"[progress] convo={cid} file={md_path.name} chunks={len(chunks)}", flush=True)

            start_marker = {
                "memory_id": f"{parent_memory_id}::START",
                "parent_memory_id": parent_memory_id,
                "conversation_id": cid,
                "type": "meta",
                "title": "START",
                "content": f"chunks={len(chunks)} max_chars_per_chunk={args.max_chars_per_chunk}",
                "confidence": "high",
                "conflict_key": "",
                "decision_status": "",
                "evidence_hint": "",
                "source_path": str(md_path),
                "chunk_index": -1,
                "chunk_char_start": None,
                "chunk_char_end": None,
                "run_utc": run_utc,
                "model": args.model,
                "reasoning_effort": args.reasoning_effort,
            }
            emit(start_marker)

            # Extract per chunk
            for chunk_idx, chunk in enumerate(chunks):
                print(f"[progress] convo={cid} chunk={chunk_idx+1}/{len(chunks)} calling OpenAI...", flush=True)
                data = extract_child_memories(
                    client=client,
                    model=args.model,
                    reasoning_effort=args.reasoning_effort,
                    parent_title=parent_title,
                    parent_projects=parent_projects,
                    parent_tags=parent_tags,
                    chunk_text=chunk,
                )

                memories = data.get("memories", []) or []
                print(f"[progress] convo={cid} chunk={chunk_idx+1}/{len(chunks)} returned memories={len(memories)}", flush=True)
                for mem_i, m in enumerate(memories):
                    child_id = f"{parent_memory_id}::c{chunk_idx:02d}m{mem_i:02d}"

                    child = {
                        "memory_id": child_id,
                        "parent_memory_id": parent_memory_id,
                        "conversation_id": cid,
                        "type": m["type"],
                        "title": m["title"],
                        "content": m["content"],
                        "confidence": m["confidence"],
                        "conflict_key": m.get("conflict_key", "") or "",
                        "decision_status": m.get("decision_status", "") or "",
                        "evidence_hint": m.get("evidence_hint", "") or "",
                        # provenance
                        "source_chunk": chunk,
                        "source_path": str(md_path),
                        "chunk_index": chunk_idx,
                        "chunk_char_start": None,
                        "chunk_char_end": None,
                        "run_utc": run_utc,
                        "model": args.model,
                        "reasoning_effort": args.reasoning_effort,
                    }
                    emit(child)
                    if (mem_i + 1) % 5 == 0:
                        print(f"[progress] convo={cid} chunk={chunk_idx+1}/{len(chunks)} emitted={mem_i+1}", flush=True)

            # Mark parent as fully processed (resume-safe)
            done_marker = {
                "memory_id": f"{parent_memory_id}::DONE",
                "parent_memory_id": parent_memory_id,
                "conversation_id": cid,
                "type": "meta",
                "title": "DONE",
                "content": "",
                "confidence": "high",
                "conflict_key": "",
                "decision_status": "",
                "evidence_hint": "",
                # provenance
                "source_path": str(md_path),
                "chunk_index": -1,
                "chunk_char_start": None,
                "chunk_char_end": None,
                "run_utc": run_utc,
                "model": args.model,
                "reasoning_effort": args.reasoning_effort,
            }
            emit(done_marker)
            done_parents.add(parent_memory_id)
            processed_convos += 1

        except Exception as e:
            errors.append({"conversation_id": cid, "path": str(md_path), "error": repr(e)})

    if out_f is not None:
        out_f.close()

    # Build conflicts + review queue (only decisions with same conflict_key)
    conflict_report: Dict[str, Any] = {}
    review_rows: List[Dict[str, Any]] = []

    for ck, items in conflicts.items():
        decision_items = [x for x in items if x.get("type") == "decision"]
        if len(decision_items) < 2:
            continue

        statuses = sorted(set((x.get("decision_status") or "").strip() for x in decision_items))
        contents = sorted(set((x.get("content") or "").strip() for x in decision_items))

        is_conflict = (len(statuses) > 1) or (len(contents) > 1)
        if not is_conflict:
            continue

        conflict_report[ck] = {
            "count": len(decision_items),
            "statuses": statuses,
            "examples": decision_items[:5],
        }

        review_rows.append(
            {
                "conflict_key": ck,
                "decision_count": len(decision_items),
                "statuses": "|".join(statuses),
                "needs_review": "yes",
                "notes": "Conflicting decision memories; prefer code-state verification or manual resolve.",
            }
        )

    conflicts_json.write_text(json.dumps(conflict_report, indent=2, ensure_ascii=False), encoding="utf-8")

    with review_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["conflict_key", "decision_count", "statuses", "needs_review", "notes"])
        w.writeheader()
        for r in sorted(review_rows, key=lambda x: (-int(x["decision_count"]), x["conflict_key"])):
            w.writerow(r)

    manifest = {
        "run_utc": run_utc,
        "kept_manifest": str(Path(args.kept_manifest)),
        "out_dir": str(out_dir),
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "processed_conversations": processed_convos,
        "child_memories": total_child_memories,
        "conflict_keys": len(conflict_report),
        "errors": errors,
    }
    run_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print("\n=== Summary ===")
    print(
        json.dumps(
            {
                "processed_conversations": processed_convos,
                "child_memories": total_child_memories,
                "conflict_keys": len(conflict_report),
                "errors": len(errors),
                "out_dir": str(out_dir),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
