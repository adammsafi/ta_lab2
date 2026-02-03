"""Process and instantiate final memory records for storage."""
from __future__ import annotations

import argparse
import json
import logging
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

try:
    import chromadb
except ImportError:
    print("Error: chromadb library not found. Install with: pip install chromadb")
    raise SystemExit(1)


# -----------------------------
# Config (edit as you learn)
# -----------------------------

DEFAULT_KEY_MODE = "conflict_key_title"  # conflict_key_title | conflict_key_only | title_only | stable_hash

# If you want stronger dedupe, expand the "key_fields" below, or switch to stable_hash.
KEY_FIELDS_FOR_HASH = (
    "conflict_key",
    "title",
    "content",
    "source_path",
    "conversation_id",
    "parent_memory_id",
)

EVIDENCE_TOKEN_PATTERNS = [
    r"src[\\/].+?\.(py|sql|md|toml|yml|yaml|json)",
    r"[A-Za-z0-9_]+\.py",
    r"ta_lab2\.[A-Za-z0-9_\.]+",
    r"public\.[A-Za-z0-9_]+",
    r"pytest\s+-",
    r"python\s+-m\s+\w+",
]

CAUTION_WORDS = {
    "maybe",
    "might",
    "unsure",
    "approx",
    "approximate",
    "guess",
    "unclear",
    "tbd",
    "todo",
    "to do",
    "later",
    "eventually",
    "should",
    "would",
}

POLICY_HINT_WORDS = {
    "prefer",
    "preference",
    "always",
    "never",
    "must",
    "do not",
    "dont",
    "rule",
    "rules",
    "style",
    "tone",
    "guideline",
}

# Upstream statuses to treat as "accept" or "review".
# Adjust these if your generator uses different words.
ACCEPT_STATUSES = {
    "accept",
    "accepted",
    "approve",
    "approved",
    "keep",
    "kept",
    "done",
    "implemented",
    "ship",
    "shipped",
    "final",
    "promote",
    "promoted",
}

REVIEW_STATUSES = {
    "review",
    "needs_review",
    "conflict",
    "hold",
    "pending",
    "maybe",
    "unknown",
}


class EvidenceResult:
    def __init__(self, ok: bool, hits: int, patterns: List[str], sample: List[str]):
        self.ok = ok
        self.hits = hits
        self.patterns = patterns
        self.sample = sample


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception as e:
                raise RuntimeError(f"Invalid JSON on line {i} in {path}: {e}") from e


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for o in rows:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")


def load_overrides(path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    """
    Overrides JSONL format (one per line):
      {"registry_key":"...", "decision":"accept|review|reject", "note":"..."}
    Returns map registry_key -> override object.
    """
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"Overrides file not found: {path}")
    out: Dict[str, Dict[str, Any]] = {}
    for o in read_jsonl(path):
        rk = str(o.get("registry_key") or "").strip()
        dec = str(o.get("decision") or "").strip().lower()
        if not rk:
            continue
        if dec not in {"accept", "review", "reject"}:
            raise ValueError(f"Invalid override decision for {rk!r}: {dec!r}")
        out[rk] = o
    return out


def get_text(o: Dict[str, Any]) -> str:
    # Your file uses 'content'. Keep 'memory' as a fallback for compatibility.
    return str(o.get("content") or o.get("memory") or "")


def stable_hash_key(o: Dict[str, Any]) -> str:
    import hashlib

    parts: List[str] = []
    for k in KEY_FIELDS_FOR_HASH:
        parts.append(str(o.get(k, "") or ""))
    blob = "\n".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha256(blob).hexdigest()[:16]


def normalize_title(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def compute_registry_key(o: Dict[str, Any], key_mode: str) -> str:
    ck = str(o.get("conflict_key") or "").strip()
    title = normalize_title(str(o.get("title") or ""))

    if key_mode == "conflict_key_title":
        # If conflict_key is missing, don't collapse to "::title"
        return f"{ck}::{title}" if ck else title
    if key_mode == "conflict_key_only":
        return ck or stable_hash_key(o)
    if key_mode == "title_only":
        return title or stable_hash_key(o)
    if key_mode == "stable_hash":
        return stable_hash_key(o)
    raise ValueError(f"Unknown key_mode: {key_mode}")


def looks_cautionary(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in CAUTION_WORDS)


def looks_like_policy(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in POLICY_HINT_WORDS)


def get_query_embedding(query: str, client: OpenAI, model: str) -> List[float]:
    """Generates an embedding for a single query string."""
    if not query.strip():  # Handle empty or whitespace-only queries
        logging.warning("Attempted to generate embedding for an empty query. Skipping.")
        return []
    try:
        response = client.embeddings.create(input=[query], model=model)
        return response.data[0].embedding
    except Exception as e:
        logging.error(f"Error calling OpenAI embedding API for query: {e}")
        return []


def semantic_evidence_check(
    memory_text: str,
    collection: chromadb.Collection,
    client: OpenAI,
    model: str,
    n_results: int = 5,
    threshold: float = 1.1,
    max_tokens: int = 8000,  # Max tokens for text-embedding-3-small is 8192
) -> EvidenceResult:
    """
    Performs a semantic search for code chunks related to the memory text.
    Returns an EvidenceResult.
    """
    # Truncate memory_text if it's too long for the embedding model
    if len(memory_text) > max_tokens:  # Simple char count as a proxy for tokens
        logging.warning(
            f"Memory text too long ({len(memory_text)} chars). Truncating to {max_tokens} chars for embedding."
        )
        memory_text = memory_text[:max_tokens]

    query_embedding = get_query_embedding(memory_text, client, model)
    if not query_embedding:
        return EvidenceResult(ok=False, hits=0, patterns=[], sample=[])

    results = collection.query(query_embeddings=[query_embedding], n_results=n_results)

    hits = 0
    sample = []
    patterns = []  # Use this to store the names of the functions/classes found

    if results and results.get("documents"):
        for i, doc in enumerate(results["documents"][0]):
            distance = results["distances"][0][i]
            if distance < threshold:
                hits += 1
                metadata = results["metadatas"][0][i]
                # Create a readable sample format
                sample_line = f"Source: {metadata.get('file_path')}:{metadata.get('start_line')} | Function/Class: {metadata.get('name')}"
                sample.append(sample_line)
                patterns.append(metadata.get("name", ""))

    return EvidenceResult(ok=(hits > 0), hits=hits, patterns=patterns, sample=sample)


def normalize_status(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace(" ", "_")
    return s


def decide(o: Dict[str, Any], done_marker: bool, ev: EvidenceResult) -> Tuple[str, str]:
    """
    Returns (decision, reason)
    decision ∈ {accept, review, reject}
    """
    text = get_text(o)
    status = normalize_status(str(o.get("decision_status") or ""))

    # 1) Upstream decision_status wins
    if status:
        if status in ACCEPT_STATUSES:
            if looks_cautionary(text) and not looks_like_policy(text):
                return (
                    "review",
                    f"decision_status={status} but text looks cautionary/uncertain",
                )
            return "accept", f"decision_status={status}"
        if status in REVIEW_STATUSES:
            return "review", f"decision_status={status}"
        # Unknown status: fall through to heuristic

    # 2) DONE marker is strong
    if done_marker:
        if looks_cautionary(text) and not looks_like_policy(text):
            return "review", "DONE marker present but text looks cautionary/uncertain"
        return "accept", "DONE marker present"

    # 3) No DONE: accept only with evidence and not cautionary
    if ev.ok and not looks_cautionary(text):
        return "accept", f"repo evidence found ({ev.hits} hits)"

    return "review", "insufficient signal to auto-accept"


DECISION_RANK = {"reject": 0, "review": 1, "accept": 2}


def pick_best_candidate(cands: List[Dict[str, Any]]) -> Dict[str, Any]:
    def score(c: Dict[str, Any]) -> Tuple[int, int, int, int]:
        meta = c.get("_decision_meta", {}) or {}
        decision = str(meta.get("decision") or "review")
        done = int(bool(meta.get("done_marker")))
        hits = int(((meta.get("evidence") or {}).get("hits")) or 0)
        txt_len = len(get_text(c))
        return (DECISION_RANK.get(decision, 1), done, hits, txt_len)

    return max(cands, key=score)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    log = logging.getLogger()

    ap = argparse.ArgumentParser(
        description="Instantiate final memories from children with semantic evidence checking"
    )
    ap.add_argument("--children", required=True, help="Path to memory_children.jsonl")
    ap.add_argument(
        "--out-dir",
        required=True,
        help="Output directory for final/decision/review files",
    )
    ap.add_argument(
        "--registry",
        required=True,
        help="Path to memory_registry_root.jsonl (for parent context)",
    )
    ap.add_argument(
        "--chroma-dir",
        required=True,
        help="Path to the ChromaDB vector store directory.",
    )
    ap.add_argument(
        "--code-collection-name",
        required=True,
        help="Name of the ChromaDB collection for code.",
    )
    ap.add_argument(
        "--embedding-model",
        default="text-embedding-3-small",
        help="OpenAI model for embeddings.",
    )
    ap.add_argument(
        "--key-mode", default=DEFAULT_KEY_MODE, help="Keying mode for registry"
    )
    ap.add_argument(
        "--overrides", default=None, help="Path to decision_overrides.jsonl (optional)"
    )
    args = ap.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        log.error("Error: The OPENAI_API_KEY environment variable is not set.")
        return 1

    client = OpenAI()
    children_path = Path(args.children)
    out_dir = Path(args.out_dir)
    registry_path = Path(args.registry)
    chroma_path = Path(args.chroma_dir)
    overrides = load_overrides(Path(args.overrides) if args.overrides else None)

    # --- Initialize ChromaDB ---
    log.info(f"Connecting to ChromaDB at: {chroma_path}")
    try:
        chroma_client = chromadb.PersistentClient(path=str(chroma_path))
        code_collection = chroma_client.get_collection(name=args.code_collection_name)
        log.info(
            f"Connected to code collection '{args.code_collection_name}' with {code_collection.count()} documents."
        )
    except Exception as e:
        log.error(f"Failed to connect to ChromaDB collection: {e}")
        return 1

    # Load parent memory registry for context
    parent_memories: Dict[str, Dict[str, Any]] = {}
    if registry_path.exists():
        for p_mem in read_jsonl(registry_path):
            p_id = str(p_mem.get("memory_id") or "")
            if p_id:
                parent_memories[p_id] = p_mem

    final_path = out_dir / "final_memory.jsonl"
    decision_log_path = out_dir / "decision_log.jsonl"
    review_path = out_dir / "review_queue.jsonl"

    decisions: List[Dict[str, Any]] = []
    final: List[Dict[str, Any]] = []
    by_key: Dict[str, List[Dict[str, Any]]] = {}

    for o in read_jsonl(children_path):
        mem_id = str(o.get("memory_id") or "")
        done_marker = mem_id.endswith("::DONE")

        key = compute_registry_key(o, args.key_mode)

        text = get_text(o)
        ev = semantic_evidence_check(
            text, code_collection, client, args.embedding_model
        )

        decision, reason = decide(o, done_marker=done_marker, ev=ev)

        # ---- APPLY OVERRIDE (by registry_key) ----
        forced = None
        ov = overrides.get(key)
        if ov:
            forced = str(ov.get("decision") or "").strip().lower()
            decision = forced
            reason = f"override: {ov.get('note')}" if ov.get("note") else "override"
        # -----------------------------------------

        record: Dict[str, Any] = {
            "ts_utc": utc_now_iso(),
            "registry_key": key,
            "memory_id": mem_id,
            "title": o.get("title"),
            "conflict_key": o.get("conflict_key"),
            "source_path": o.get("source_path"),
            "decision_status": o.get("decision_status"),
            "decision": decision,
            "reason": reason,
            "done_marker": done_marker,
            "evidence": {
                "ok": ev.ok,
                "hits": ev.hits,
                "patterns": ev.patterns,
                "sample": ev.sample[:5],
            },
        }
        if forced is not None:
            record["decision_forced"] = forced
            record["decision_forced_note"] = ov.get("note")

        decisions.append(record)

        o2 = dict(o)
        o2["_decision_meta"] = record
        by_key.setdefault(key, []).append(o2)

    review_best: List[Dict[str, Any]] = []

    for key, cands in by_key.items():
        best = pick_best_candidate(cands)
        meta = best.get("_decision_meta", {}) or {}

        if meta.get("decision") == "accept":
            if not get_text(best).strip():
                # skip empty-content accepts (e.g., marker rows)
                continue

            parent_id = best.get("parent_memory_id")
            parent_info = parent_memories.get(parent_id) or {}

            final.append(
                {
                    "registry_key": key,
                    "memory_id": best.get("memory_id"),
                    "title": best.get("title"),
                    "conflict_key": best.get("conflict_key"),
                    "content": get_text(best),
                    "source_path": best.get("source_path"),
                    "conversation_id": best.get("conversation_id"),
                    "parent_memory_id": parent_id,
                    "parent_summary": parent_info.get("summary", ""),
                    "parent_tags": parent_info.get("tags", []),
                    "source_chunk": best.get("source_chunk", ""),
                    "accepted_ts_utc": utc_now_iso(),
                    "accepted_reason": meta.get("reason"),
                    "evidence": meta.get("evidence"),
                }
            )
        else:
            review_best.append(best)

    write_jsonl(final_path, final)
    write_jsonl(decision_log_path, decisions)
    write_jsonl(review_path, review_best)

    print(f"Wrote: {final_path} (accepted={len(final)})")
    print(f"Wrote: {decision_log_path} (decisions={len(decisions)})")
    print(f"Wrote: {review_path} (review={len(review_best)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
