"""Generate semantic memories from git diffs with LLM analysis."""
from __future__ import annotations
# generate_memories_from_diffs.py

r"""
Analyze diffs into a manifest, then run-one (or run-batch) to generate memories.

Key upgrades in this version:
- Optional accurate token counting via tiktoken (fallback to heuristic).
- Minimal context support (git unified context + local context_keep around +/- lines).
- LLM provider abstraction (OpenAI implementation included).
- Diff caching (avoids repeated git show per entry).
- Better progress reporting.
- Optional parallel run-batch (threaded; safe within one process).
- Built-in self-test for core utilities (no network).

Examples:

ANALYZE
python -m ta_lab2.tools.data_tools.memory.generate_memories_from_diffs analyze \
  --repo-path "C:\Users\asafi\Downloads\ta_lab2" \
  --commit-hashes-file "C:\path\commits.txt" \
  --diff-files-list "C:\path\diff_files.txt" \
  --manifest-out "C:\path\manifest.ndjson" \
  --model "gpt-4o-mini" \
  --tpm-limit 30000 \
  --safety 0.70 \
  --max-output-tokens 600 \
  --unified-context 2 \
  --context-keep 1

LIST
python -m ta_lab2.tools.data_tools.memory.generate_memories_from_diffs list --manifest "C:\path\manifest.ndjson" --top 25

RUN ONE
python -m ta_lab2.tools.data_tools.memory.generate_memories_from_diffs run-one \
  --manifest "C:\path\manifest.ndjson" \
  --memories-out "C:\path\memories.ndjson" \
  --model "gpt-4o-mini"

RUN BATCH (optionally parallel)
python -m ta_lab2.tools.data_tools.memory.generate_memories_from_diffs run-batch \
  --manifest "C:\path\manifest.ndjson" \
  --memories-out "C:\path\memories.ndjson" \
  --model "gpt-4o-mini" \
  --limit 200 \
  --workers 4

PUBLISH TO MEM0 LOCAL
python -m ta_lab2.tools.data_tools.memory.generate_memories_from_diffs run-batch \
  --manifest "C:\path\manifest.ndjson" \
  --memories-out "C:\path\memories.ndjson" \
  --publish mem0 \
  --mem0-user-id "adam" \
  --publish-format raw_json

PUBLISH BOTH MEM0 + VERTEX MEMORY BANK
python -m ta_lab2.tools.data_tools.memory.generate_memories_from_diffs run-batch \
  --manifest "C:\path\manifest.ndjson" \
  --memories-out "C:\path\memories.ndjson" \
  --publish both \
  --mem0-user-id "adam" \
  --publish-format raw_json \
  --gcp-project-id "your-project" \
  --vertex-region "us-central1" \
  --vertex-memory-agent-id "REASONING_ENGINE_ID" \
  --memory-scope-json '{"app":"ta_lab2","user_id":"adam"}' \
  --memory-labels-json '{"source":"gitdiff"}'

PUBLISH AN EXISTING memories.ndjson FILE (dedup by memory_id)
python -m ta_lab2.tools.data_tools.memory.generate_memories_from_diffs publish-file \
  --memories-ndjson "C:\path\memories.ndjson" \
  --publish mem0 \
  --mem0-user-id "adam" \
  --publish-format raw_json \
  --dedup-ids-file "C:\path\published_ids.txt"

SELF TEST (no network)
python -m ta_lab2.tools.data_tools.memory.generate_memories_from_diffs self-test

Env knobs:
  OPENAI_RETRY_MAX=3
  OPENAI_RETRY_BASE_DELAY_SEC=2.0
"""

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Optional: Vertex Memory Bank publish (requires google-auth)
try:
    import google.auth
    import google.auth.transport.requests
except Exception:  # pragma: no cover
    google = None  # type: ignore

# Optional: mem0 local publish
try:
    from mem0 import Memory as Mem0Memory  # type: ignore
except Exception:  # pragma: no cover
    Mem0Memory = None  # type: ignore

# Optional: tiktoken for accurate token counts
try:
    import tiktoken  # type: ignore
except Exception:  # pragma: no cover
    tiktoken = None  # type: ignore

# Requires: pip install openai
try:
    from openai import OpenAI
except ImportError:
    print(
        "Error: openai library not found. Install with: pip install openai",
        file=sys.stderr,
    )
    sys.exit(1)


DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_TPM_LIMIT = 30000
DEFAULT_SAFETY = 0.70
DEFAULT_MAX_OUTPUT_TOKENS = 600
DEFAULT_API_DELAY_SEC = 0.0
DEFAULT_UNIFIED_CONTEXT = 2  # git show --unified=N
DEFAULT_CONTEXT_KEEP = 1  # keep +/- lines plus this many surrounding diff-context lines
DEFAULT_WORKERS = 1


# =========================
# Data Models
# =========================
@dataclass(frozen=True)
class Hunk:
    file_path: str
    new_start_line: int
    new_line_count: int
    hunk_header: str
    reduced_diff: str


@dataclass
class ManifestEntry:
    entry_id: str
    repo_path: str
    source_type: str  # commit | diff_file
    source_id: str  # commit hash or diff file path
    commit_subject: str
    file_path: str
    hunk_header: str
    new_start_line: int
    new_line_count: int

    # token budgeting (estimated, and max budgets used)
    est_input_tokens: int
    max_input_tokens: int
    max_output_tokens: int

    # context knobs used to generate/reconstruct the diff
    unified_context: int = DEFAULT_UNIFIED_CONTEXT
    context_keep: int = DEFAULT_CONTEXT_KEEP

    # status
    status: str = "pending"  # pending | done | error | skipped
    last_error: Optional[str] = None

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ManifestEntry":
        # Backward-compatible: fill missing new fields with defaults.
        d2 = dict(d)
        d2.setdefault("unified_context", DEFAULT_UNIFIED_CONTEXT)
        d2.setdefault("context_keep", DEFAULT_CONTEXT_KEEP)
        d2.setdefault("status", "pending")
        d2.setdefault("last_error", None)
        return ManifestEntry(**d2)


# =========================
# Utilities
# =========================
def sha1_text(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()


def read_lines(path: Optional[str]) -> List[str]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    out: List[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def run_git(repo_path: str, args: List[str]) -> str:
    cmd = ["git", "-C", repo_path] + args
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git failed: {cmd}\n{r.stderr}")
    return r.stdout


def _now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _short(s: str, n: int = 140) -> str:
    s2 = (s or "").replace("\n", " ").strip()
    return s2 if len(s2) <= n else s2[: n - 3] + "..."


# =========================
# Token counting (tiktoken optional)
# =========================
class TokenCounter:
    """
    TokenCounter tries tiktoken for more accurate estimates; falls back to len(text)/4 heuristic.
    We keep this as an estimator (not an exact allocator), but accuracy materially improves chunking.
    """

    def __init__(self) -> None:
        self._enc_cache: Dict[str, Any] = {}

    def _get_encoder(self, model: str) -> Any:
        if tiktoken is None:
            return None
        if model in self._enc_cache:
            return self._enc_cache[model]
        # Try per-model encoder; fallback to a reasonable base encoding.
        try:
            enc = tiktoken.encoding_for_model(model)  # type: ignore[attr-defined]
        except Exception:
            try:
                enc = tiktoken.get_encoding("o200k_base")  # type: ignore[attr-defined]
            except Exception:
                enc = None
        self._enc_cache[model] = enc
        return enc

    def estimate(self, text: str, model: str) -> int:
        if not text:
            return 0
        enc = self._get_encoder(model)
        if enc is not None:
            try:
                return int(len(enc.encode(text)))
            except Exception:
                pass
        # fallback heuristic
        return max(1, int(len(text) / 4))


TOKENS = TokenCounter()


# =========================
# Diff parsing / reduction
# =========================
HUNK_RE = re.compile(r"^@@\s+\-(\d+),?(\d*)\s+\+(\d+),?(\d*)\s+@@(.*)$")


def reduce_unified_diff(diff_text: str, context_keep: int = 0) -> List[Hunk]:
    """
    Parse unified diff and return a list of hunks with reduced lines.

    - Always keeps +/- lines.
    - If context_keep > 0, also keeps that many surrounding lines around each +/- line
      within the hunk body. This is a lightweight way to preserve minimal context.
    """
    lines = diff_text.splitlines()
    file_path = ""
    hunks: List[Hunk] = []

    i = 0
    while i < len(lines):
        line = lines[i]

        # git headers that can help track the current file
        if line.startswith("diff --git "):
            # example: diff --git a/foo.py b/foo.py
            parts = line.split()
            if len(parts) >= 4:
                bpath = parts[3]
                file_path = bpath.replace("b/", "", 1)
            i += 1
            continue

        if line.startswith("+++ "):
            fp = line[4:].strip()
            file_path = fp.replace("b/", "", 1)
            i += 1
            continue

        m = HUNK_RE.match(line)
        if not m:
            i += 1
            continue

        new_start = int(m.group(3))
        new_count = int(m.group(4) or "1")
        hunk_header = line

        i += 1
        hunk_lines: List[str] = []
        while i < len(lines) and not lines[i].startswith("@@ "):
            # stop if next file starts (defensive)
            if lines[i].startswith("diff --git "):
                break
            hunk_lines.append(lines[i])
            i += 1

        kept: List[str] = []
        if context_keep <= 0:
            for hl in hunk_lines:
                if hl.startswith("+") or hl.startswith("-"):
                    kept.append(hl)
        else:
            idxs = [
                k
                for k, hl in enumerate(hunk_lines)
                if hl.startswith("+") or hl.startswith("-")
            ]
            keep_set = set()
            for k in idxs:
                for w in range(
                    max(0, k - context_keep), min(len(hunk_lines), k + context_keep + 1)
                ):
                    keep_set.add(w)
            for k, hl in enumerate(hunk_lines):
                if k in keep_set:
                    kept.append(hl)

        reduced = "\n".join(kept).strip()
        if reduced:
            hunks.append(
                Hunk(
                    file_path=file_path or "<unknown>",
                    new_start_line=new_start,
                    new_line_count=new_count,
                    hunk_header=hunk_header,
                    reduced_diff=reduced,
                )
            )

    return hunks


def load_diff_for_commit(
    repo_path: str, commit_hash: str, unified_context: int
) -> Tuple[str, str]:
    subject = run_git(repo_path, ["show", "-s", "--format=%s", commit_hash]).strip()
    diff_text = run_git(
        repo_path, ["show", f"--unified={int(unified_context)}", commit_hash]
    )
    return subject, diff_text


def load_diff_from_file(path: str) -> Tuple[str, str]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    return f"diff_file:{p.name}", p.read_text(encoding="utf-8")


# =========================
# Diff cache (avoid repeating git show per entry)
# =========================
class DiffCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key: (source_type, source_id, unified_context, context_keep) -> (subject, diff_text, hunks)
        self._cache: Dict[Tuple[str, str, int, int], Tuple[str, str, List[Hunk]]] = {}

    def get_subject_diff_hunks(
        self,
        repo_path: str,
        source_type: str,
        source_id: str,
        unified_context: int,
        context_keep: int,
    ) -> Tuple[str, str, List[Hunk]]:
        key = (source_type, source_id, int(unified_context), int(context_keep))
        with self._lock:
            if key in self._cache:
                return self._cache[key]

        if source_type == "commit":
            subject, diff_text = load_diff_for_commit(
                repo_path, source_id, unified_context=unified_context
            )
        else:
            subject, diff_text = load_diff_from_file(source_id)

        hunks = reduce_unified_diff(diff_text, context_keep=context_keep)

        with self._lock:
            self._cache[key] = (subject, diff_text, hunks)
        return subject, diff_text, hunks


DIFFS = DiffCache()


# =========================
# Prompting (light dynamic prompt engineering)
# =========================
_ALLOWED_TYPES = "decision|invariant|pitfall|procedure|constraint|design|bugfix|refactor|performance|testing|other"


def _hint_for_file(file_path: str) -> str:
    fp = (file_path or "").lower()
    if fp.endswith(".sql"):
        return "File is SQL; prefer memories about schema, queries, invariants, and performance constraints."
    if fp.endswith(".py"):
        return "File is Python; prefer memories about behavior, invariants, tests, refactors, and performance."
    if fp.endswith(".md") or fp.endswith(".rst"):
        return "File is docs; prefer procedure/decision/design memories."
    if fp.endswith(".yml") or fp.endswith(".yaml"):
        return "File is config; prefer constraint/procedure/design memories."
    return "Prefer crisp, specific engineering memories grounded in the diff."


def build_memory_prompt(
    repo_path: str,
    source_type: str,
    source_id: str,
    commit_subject: str,
    hunk: Hunk,
    part_index: int,
    part_count: int,
    *,
    est_total_tokens: int,
) -> str:
    # Encourage specificity more strongly on small prompts; allow broader summaries on huge ones.
    if est_total_tokens <= 1200:
        specificity = (
            "Be highly specific: include function/class/module names when available."
        )
    else:
        specificity = "Be specific but concise: focus on the most important intent, invariants, and pitfalls."

    return (
        "You are extracting engineering 'memories' from git diffs.\n"
        "Return VALID JSON ONLY (no markdown, no prose).\n\n"
        "Schema (JSON object):\n"
        "{\n"
        f'  "memory_type": "{_ALLOWED_TYPES}",\n'
        '  "summary": "1-3 sentence summary, crisp and specific",\n'
        '  "tags": ["short", "tags"],\n'
        '  "confidence": 0.0-1.0,\n'
        '  "evidence_line_range": "new:START-END"  # best effort\n'
        "}\n\n"
        f"Guidance:\n- {_hint_for_file(hunk.file_path)}\n- {specificity}\n"
        "- If the diff lacks sufficient context to be confident, lower confidence.\n\n"
        f"Repo: {repo_path}\n"
        f"Source: {source_type}:{source_id}\n"
        f"Commit subject: {commit_subject}\n"
        f"File: {hunk.file_path}\n"
        f"Hunk: {hunk.hunk_header}\n"
        f"Part: {part_index}/{part_count}\n\n"
        "Reduced diff:\n"
        f"{hunk.reduced_diff}\n"
    )


def split_text_by_token_budget(text: str, max_tokens: int, model: str) -> List[str]:
    """
    Chunk text by line boundaries, aiming to keep chunks <= max_tokens (estimated).
    Uses TokenCounter (tiktoken if available).
    """
    if TOKENS.estimate(text, model) <= max_tokens:
        return [text]
    lines = text.splitlines()
    chunks: List[str] = []
    buf: List[str] = []
    buf_tokens = 0
    for ln in lines:
        t = TOKENS.estimate(ln + "\n", model)
        if buf and buf_tokens + t > max_tokens:
            chunks.append("\n".join(buf).strip())
            buf = [ln]
            buf_tokens = t
        else:
            buf.append(ln)
            buf_tokens += t
    if buf:
        chunks.append("\n".join(buf).strip())
    return [c for c in chunks if c]


def normalize_memory_type(x: Any) -> str:
    if not isinstance(x, str):
        return "other"
    v = x.strip().lower()
    allowed = {
        "decision",
        "invariant",
        "pitfall",
        "procedure",
        "constraint",
        "design",
        "bugfix",
        "refactor",
        "performance",
        "testing",
        "other",
    }
    return v if v in allowed else "other"


def coerce_confidence(x: Any) -> float:
    try:
        v = float(x)
    except Exception:
        return 0.5
    if math.isnan(v) or math.isinf(v):
        return 0.5
    return max(0.0, min(1.0, v))


# =========================
# LLM abstraction
# =========================
class LLMClient:
    def generate_json(
        self, model: str, prompt: str, max_output_tokens: int
    ) -> Dict[str, Any]:
        raise NotImplementedError


# =========================
# OpenAI call (with retries + JSON hardening)
# =========================
def _extract_json_object(text: str) -> Dict[str, Any]:
    """Best-effort JSON parse from model output text."""
    t = (text or "").strip()
    if not t:
        raise ValueError("Empty response text; expected JSON.")

    try:
        obj = json.loads(t)
        if not isinstance(obj, dict):
            raise ValueError("Expected a JSON object at top level.")
        return obj
    except Exception:
        pass

    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        sub = t[start : end + 1]
        obj2 = json.loads(sub)
        if not isinstance(obj2, dict):
            raise ValueError("Expected a JSON object at top level.")
        return obj2

    raise ValueError("Could not parse JSON from model output.")


def _call_openai_json(
    client: OpenAI, model: str, prompt: str, max_output_tokens: int
) -> Dict[str, Any]:
    """
    Try Responses API first; fallback to Chat Completions.
    Retries are exponential backoff controlled by env vars.
    """
    max_tries = int(os.getenv("OPENAI_RETRY_MAX", "3") or "3")
    base_delay = float(os.getenv("OPENAI_RETRY_BASE_DELAY_SEC", "2.0") or "2.0")

    last_err: Optional[Exception] = None

    for attempt in range(1, max_tries + 1):
        try:
            # Responses API path (newer)
            try:
                resp = client.responses.create(
                    model=model,
                    input=prompt,
                    max_output_tokens=max_output_tokens,
                )
                text_out = getattr(resp, "output_text", None)
                if not text_out:
                    parts: List[str] = []
                    for item in getattr(resp, "output", []) or []:
                        for c in getattr(item, "content", []) or []:
                            t = getattr(c, "text", None)
                            if t:
                                parts.append(t)
                    text_out = "\n".join(parts).strip()
                return _extract_json_object(text_out)
            except Exception:
                pass

            # Chat Completions fallback (older)
            # response_format json_object works on many models; if unsupported, fall back to normal text parse.
            try:
                cc = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Return valid JSON only. No markdown. No commentary.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    max_tokens=max_output_tokens,
                )
                return _extract_json_object(cc.choices[0].message.content)
            except Exception:
                cc2 = client.chat.completions.create(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Return valid JSON only. No markdown. No commentary.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=max_output_tokens,
                )
                return _extract_json_object(cc2.choices[0].message.content)

        except Exception as e:
            last_err = e
            if attempt < max_tries:
                sleep_s = base_delay * (2 ** (attempt - 1))
                time.sleep(sleep_s)
            else:
                break

    assert last_err is not None
    raise last_err


class OpenAILLMClient(LLMClient):
    def __init__(self) -> None:
        self._client = OpenAI()

    def generate_json(
        self, model: str, prompt: str, max_output_tokens: int
    ) -> Dict[str, Any]:
        return _call_openai_json(self._client, model, prompt, max_output_tokens)


# =========================
# Publish (Vertex Memory Bank)
# =========================
@dataclass(frozen=True)
class PublishConfig:
    enabled: bool
    project_id: str
    region: str
    reasoning_engine_id: str
    scope: Dict[str, str]
    labels: Dict[str, str]


class MemoryBankPublisher:
    def __init__(self, cfg: PublishConfig):
        if not cfg.enabled:
            raise ValueError("Publisher initialized with enabled=False")
        if google is None:
            raise RuntimeError(
                "google-auth is required for publishing. Install: pip install google-auth"
            )
        self.cfg = cfg
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        self.sess = google.auth.transport.requests.AuthorizedSession(creds)

    @property
    def base(self) -> str:
        return f"https://{self.cfg.region}-aiplatform.googleapis.com/v1beta1"

    @property
    def engine_name(self) -> str:
        return (
            f"projects/{self.cfg.project_id}/locations/{self.cfg.region}/"
            f"reasoningEngines/{self.cfg.reasoning_engine_id}"
        )

    def create_memory(self, text_content: str) -> Dict[str, Any]:
        url = f"{self.base}/{self.engine_name}/memories"
        body: Dict[str, Any] = {
            "memory": {"scope": self.cfg.scope, "textContent": text_content}
        }
        if self.cfg.labels:
            body["memory"]["labels"] = self.cfg.labels

        r = self.sess.post(url, json=body, timeout=120)
        if r.status_code >= 300:
            raise RuntimeError(f"publish create failed: {r.status_code} {r.text}")
        return r.json()


# =========================
# Publish (mem0 local)
# =========================
@dataclass(frozen=True)
class Mem0PublishConfig:
    enabled: bool
    user_id: str
    base_metadata: Dict[str, Any]


class Mem0Publisher:
    """
    Local mem0 publisher.
    Requires: pip install mem0
    """

    def __init__(self, cfg: Mem0PublishConfig):
        if not cfg.enabled:
            raise ValueError("Mem0Publisher initialized with enabled=False")
        if Mem0Memory is None:
            raise RuntimeError(
                "mem0 is required for publishing. Install: pip install mem0"
            )
        if not cfg.user_id:
            raise RuntimeError("mem0 user_id is required.")
        self.cfg = cfg
        self.m = Mem0Memory()

    def add_memory(self, text_content: str, metadata: Dict[str, Any]) -> Any:
        meta = dict(self.cfg.base_metadata)
        meta.update(metadata or {})
        try:
            return self.m.add(text_content, user_id=self.cfg.user_id, metadata=meta)
        except TypeError:
            # Older mem0 versions
            return self.m.add(text_content, user_id=self.cfg.user_id)


# =========================
# Publish formatting
# =========================
def build_memory_bank_text(record: Dict[str, Any]) -> str:
    mt = (record.get("memory_type") or "").strip()
    summary = (record.get("summary") or "").strip()
    tags = record.get("tags") if isinstance(record.get("tags"), list) else []
    ev = record.get("evidence") or {}

    bits = []
    if mt:
        bits.append(f"TYPE: {mt}")
    if summary:
        bits.append(f"SUMMARY: {summary}")
    if tags:
        bits.append("TAGS: " + ", ".join([str(x) for x in tags[:15]]))

    fp = ev.get("file_path")
    commit = ev.get("commit")
    subj = ev.get("commit_subject")
    if fp or commit or subj:
        bits.append(f"EVIDENCE: file={fp} commit={commit} subject={subj}")

    return "\n".join(bits).strip()


def build_publish_payload(record: Dict[str, Any], publish_format: str) -> str:
    """
    publish_format:
      - "text": compact human text (good for Memory Bank)
      - "raw_json": full record as JSON (best for mem0, keeps structure)
    """
    if publish_format == "raw_json":
        return json.dumps(record, ensure_ascii=False, sort_keys=True)
    return build_memory_bank_text(record)


# =========================
# Manifest I/O
# =========================
def write_manifest_entries(path: Path, entries: List[ManifestEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(dataclasses.asdict(e), ensure_ascii=False) + "\n")


def read_manifest(path: Path) -> List[ManifestEntry]:
    entries: List[ManifestEntry] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            d = json.loads(line)
            entries.append(ManifestEntry.from_dict(d))
    return entries


# In-process locks (safe for threads; not multi-process)
_MANIFEST_LOCK = threading.Lock()
_MEMORIES_LOCK = threading.Lock()


def update_manifest_status(
    manifest_path: Path, entry_id: str, status: str, last_error: Optional[str]
) -> None:
    # Simple & safe: rewrite file under lock. Good enough for threaded runs.
    with _MANIFEST_LOCK:
        entries = read_manifest(manifest_path)
        updated = False
        for e in entries:
            if e.entry_id == entry_id:
                e.status = status
                e.last_error = last_error
                updated = True
                break
        if not updated:
            raise RuntimeError(f"entry_id not found: {entry_id}")
        write_manifest_entries(manifest_path, entries)


# =========================
# Memory output (NDJSON)
# =========================
def write_memory_ndjson(path: Path, record: Dict[str, Any]) -> None:
    with _MEMORIES_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def iter_ndjson(path: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            out.append(json.loads(s))
    return out


def load_dedup_ids(path: Optional[str]) -> set[str]:
    if not path:
        return set()
    p = Path(path)
    if not p.exists():
        return set()
    return {
        ln.strip() for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()
    }


def append_dedup_id(path: Optional[str], memory_id: str) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(memory_id + "\n")


# =========================
# Reconstructing hunks from manifest
# =========================
def reconstruct_hunk_from_manifest(e: ManifestEntry) -> Hunk:
    _, _, hunks = DIFFS.get_subject_diff_hunks(
        repo_path=e.repo_path,
        source_type=e.source_type,
        source_id=e.source_id,
        unified_context=e.unified_context,
        context_keep=e.context_keep,
    )

    # Prefer exact match (stable if we kept the same unified/context settings)
    for h in hunks:
        if (
            h.file_path == e.file_path
            and h.hunk_header == e.hunk_header
            and h.new_start_line == e.new_start_line
            and h.new_line_count == e.new_line_count
        ):
            return h

    # Fallback: file match
    for h in hunks:
        if h.file_path == e.file_path:
            return h

    raise RuntimeError(
        "Could not reconstruct hunk from manifest entry (context parameters may differ)."
    )


# =========================
# Run processing
# =========================
def format_memory_record(
    e: ManifestEntry,
    h: Hunk,
    part_index: int,
    part_count: int,
    mem: Dict[str, Any],
    model: str,
) -> Dict[str, Any]:
    snippet_hash = sha1_text(h.reduced_diff)

    evidence_line_range = mem.get("evidence_line_range")
    if not evidence_line_range:
        start = e.new_start_line
        end = e.new_start_line + max(0, e.new_line_count - 1)
        evidence_line_range = f"new:{start}-{end}"

    record = {
        "schema_version": 2,
        "memory_id": sha1_text(f"{e.entry_id}|{part_index}|{snippet_hash}")[:20],
        "memory_type": normalize_memory_type(mem.get("memory_type")),
        "summary": (mem.get("summary") or "").strip(),
        "tags": mem.get("tags") if isinstance(mem.get("tags"), list) else [],
        "confidence": coerce_confidence(mem.get("confidence")),
        "evidence": {
            "repo_path": e.repo_path,
            "commit": e.source_id if e.source_type == "commit" else None,
            "source_type": e.source_type,
            "source_id": e.source_id,
            "commit_subject": e.commit_subject,
            "file_path": e.file_path,
            "hunk_header": e.hunk_header,
            "new_start_line": e.new_start_line,
            "new_line_count": e.new_line_count,
            "part_index": part_index,
            "part_count": part_count,
            "snippet_sha1": snippet_hash,
            "unified_context": e.unified_context,
            "context_keep": e.context_keep,
        },
        "evidence_line_range": evidence_line_range,
        "model": model,
        "created_at_utc": _now_utc_iso(),
        # Optional publishing backrefs:
        "mem0_result": None,
        "memory_bank_result": None,
    }
    return record


def publish_record(
    record: Dict[str, Any],
    *,
    publish_mode: str,
    publish_format: str,
    mem0_pub: Optional[Mem0Publisher],
    mb_pub: Optional[MemoryBankPublisher],
) -> Dict[str, Any]:
    payload = build_publish_payload(record, publish_format=publish_format)
    results: Dict[str, Any] = {}

    if publish_mode in ("mem0", "both"):
        if mem0_pub is None:
            raise RuntimeError(
                "mem0 publisher not configured but publish mode requires it."
            )
        meta = {
            "memory_id": record.get("memory_id"),
            "memory_type": record.get("memory_type"),
            "tags": record.get("tags"),
            "confidence": record.get("confidence"),
            "evidence": record.get("evidence"),
            "created_at_utc": record.get("created_at_utc"),
            "source": "gitdiff",
        }
        res = mem0_pub.add_memory(payload, metadata=meta)
        results["mem0"] = res

    if publish_mode in ("memory_bank", "both"):
        if mb_pub is None:
            raise RuntimeError(
                "memory bank publisher not configured but publish mode requires it."
            )
        res2 = mb_pub.create_memory(payload)
        results["memory_bank"] = res2

    return results


def _build_prompt_and_parts(
    e: ManifestEntry, hunk: Hunk, model: str
) -> Tuple[List[Hunk], List[str]]:
    # First pass prompt estimate on full hunk
    tmp_prompt = build_memory_prompt(
        repo_path=e.repo_path,
        source_type=e.source_type,
        source_id=e.source_id,
        commit_subject=e.commit_subject,
        hunk=hunk,
        part_index=1,
        part_count=1,
        est_total_tokens=0,
    )
    est_prompt_tokens = TOKENS.estimate(tmp_prompt, model)

    # If the full prompt is too big, chunk the reduced diff
    if est_prompt_tokens > e.max_input_tokens:
        # Conservative chunk budget: leave space for headers/instructions
        chunk_budget = max(600, int(e.max_input_tokens * 0.55))
        chunks = split_text_by_token_budget(
            hunk.reduced_diff, max_tokens=chunk_budget, model=model
        )
    else:
        chunks = [hunk.reduced_diff]

    part_count = len(chunks)
    hunks: List[Hunk] = []
    prompts: List[str] = []

    for i, diff_chunk in enumerate(chunks, start=1):
        h2 = Hunk(
            file_path=hunk.file_path,
            new_start_line=hunk.new_start_line,
            new_line_count=hunk.new_line_count,
            hunk_header=hunk.hunk_header,
            reduced_diff=diff_chunk,
        )
        # Estimate with final prompt content for dynamic knobs
        prompt_pre = build_memory_prompt(
            repo_path=e.repo_path,
            source_type=e.source_type,
            source_id=e.source_id,
            commit_subject=e.commit_subject,
            hunk=h2,
            part_index=i,
            part_count=part_count,
            est_total_tokens=0,
        )
        est_total = TOKENS.estimate(prompt_pre, model)
        prompt = build_memory_prompt(
            repo_path=e.repo_path,
            source_type=e.source_type,
            source_id=e.source_id,
            commit_subject=e.commit_subject,
            hunk=h2,
            part_index=i,
            part_count=part_count,
            est_total_tokens=est_total,
        )
        hunks.append(h2)
        prompts.append(prompt)

    return hunks, prompts


def process_one_manifest_entry(
    llm: LLMClient,
    manifest_path: Path,
    memories_out_path: Path,
    model: str,
    api_delay_sec: float,
    e: ManifestEntry,
    publish_mode: str,
    publish_format: str,
    mem0_pub: Optional[Mem0Publisher],
    mb_pub: Optional[MemoryBankPublisher],
    *,
    progress_prefix: str = "",
    verbose: bool = True,
) -> None:
    if e.status == "done":
        return

    hunk = reconstruct_hunk_from_manifest(e)
    parts_hunks, parts_prompts = _build_prompt_and_parts(e, hunk, model=model)

    try:
        for idx, (h_part, prompt) in enumerate(
            zip(parts_hunks, parts_prompts), start=1
        ):
            est_in = TOKENS.estimate(prompt, model)
            if verbose:
                print(
                    f"{progress_prefix}entry={e.entry_id} part={idx}/{len(parts_prompts)} "
                    f"est_in={est_in} max_in={e.max_input_tokens} "
                    f"file={e.file_path} subj={_short(e.commit_subject, 80)}"
                )

            # If prompt is still too large, do a second-level split (rare if budgets are conservative)
            if est_in > e.max_input_tokens:
                sub_budget = max(500, int(e.max_input_tokens * 0.40))
                subchunks = split_text_by_token_budget(
                    h_part.reduced_diff, max_tokens=sub_budget, model=model
                )
                if verbose:
                    print(
                        f"{progress_prefix}  oversize -> subchunks={len(subchunks)} budget={sub_budget}"
                    )

                for sub_i, sub in enumerate(subchunks, start=1):
                    h3 = dataclasses.replace(h_part, reduced_diff=sub)
                    prompt_pre = build_memory_prompt(
                        repo_path=e.repo_path,
                        source_type=e.source_type,
                        source_id=e.source_id,
                        commit_subject=e.commit_subject,
                        hunk=h3,
                        part_index=idx,
                        part_count=len(parts_prompts),
                        est_total_tokens=0,
                    )
                    est_total = TOKENS.estimate(prompt_pre, model)
                    prompt2 = build_memory_prompt(
                        repo_path=e.repo_path,
                        source_type=e.source_type,
                        source_id=e.source_id,
                        commit_subject=e.commit_subject,
                        hunk=h3,
                        part_index=idx,
                        part_count=len(parts_prompts),
                        est_total_tokens=est_total,
                    )

                    mem = llm.generate_json(
                        model=model,
                        prompt=prompt2,
                        max_output_tokens=e.max_output_tokens,
                    )
                    record = format_memory_record(
                        e, h3, idx, len(parts_prompts), mem, model
                    )
                    record["evidence"]["subchunk_index"] = sub_i
                    record["evidence"]["subchunk_count"] = len(subchunks)

                    # Publish first (optional), then write a single final record
                    if publish_mode != "none":
                        results = publish_record(
                            record,
                            publish_mode=publish_mode,
                            publish_format=publish_format,
                            mem0_pub=mem0_pub,
                            mb_pub=mb_pub,
                        )
                        if "mem0" in results:
                            record["mem0_result"] = results["mem0"]
                        if "memory_bank" in results:
                            record["memory_bank_result"] = results["memory_bank"]

                    write_memory_ndjson(memories_out_path, record)

                    if api_delay_sec > 0:
                        time.sleep(api_delay_sec)

                continue

            mem = llm.generate_json(
                model=model, prompt=prompt, max_output_tokens=e.max_output_tokens
            )
            record = format_memory_record(
                e, h_part, idx, len(parts_prompts), mem, model
            )

            # Publish first (optional), then write a single final record
            if publish_mode != "none":
                results = publish_record(
                    record,
                    publish_mode=publish_mode,
                    publish_format=publish_format,
                    mem0_pub=mem0_pub,
                    mb_pub=mb_pub,
                )
                if "mem0" in results:
                    record["mem0_result"] = results["mem0"]
                if "memory_bank" in results:
                    record["memory_bank_result"] = results["memory_bank"]

            write_memory_ndjson(memories_out_path, record)

            if api_delay_sec > 0:
                time.sleep(api_delay_sec)

        update_manifest_status(manifest_path, e.entry_id, "done", last_error=None)

    except Exception as ex:
        update_manifest_status(manifest_path, e.entry_id, "error", last_error=str(ex))
        raise


# =========================
# Analyze command
# =========================
def _compute_max_input_tokens(
    tpm_limit: int, safety: float, max_output_tokens: int
) -> int:
    max_input_tokens = int((int(tpm_limit) * float(safety)) - int(max_output_tokens))
    if max_input_tokens < 1000:
        max_input_tokens = 1000
    return max_input_tokens


def build_manifest_entries_from_commits(
    repo_path: str,
    commit_hashes: List[str],
    model: str,
    tpm_limit: int,
    safety: float,
    max_output_tokens: int,
    unified_context: int,
    context_keep: int,
) -> List[ManifestEntry]:
    entries: List[ManifestEntry] = []
    max_input_tokens = _compute_max_input_tokens(tpm_limit, safety, max_output_tokens)

    for ch in commit_hashes:
        subject, diff_text = load_diff_for_commit(
            repo_path, ch, unified_context=unified_context
        )
        hunks = reduce_unified_diff(diff_text, context_keep=context_keep)
        for h in hunks:
            # estimate prompt tokens using the same token counter as runtime chunking
            prompt_pre = build_memory_prompt(
                repo_path, "commit", ch, subject, h, 1, 1, est_total_tokens=0
            )
            est = TOKENS.estimate(prompt_pre, model)
            entry_id = sha1_text(
                f"{repo_path}|commit|{ch}|{h.file_path}|{h.hunk_header}|{h.new_start_line}"
            )[:16]
            entries.append(
                ManifestEntry(
                    entry_id=entry_id,
                    repo_path=repo_path,
                    source_type="commit",
                    source_id=ch,
                    commit_subject=subject,
                    file_path=h.file_path,
                    hunk_header=h.hunk_header,
                    new_start_line=h.new_start_line,
                    new_line_count=h.new_line_count,
                    est_input_tokens=est,
                    max_input_tokens=max_input_tokens,
                    max_output_tokens=max_output_tokens,
                    unified_context=int(unified_context),
                    context_keep=int(context_keep),
                    status="pending",
                    last_error=None,
                )
            )
    return entries


def build_manifest_entries_from_diff_files(
    repo_path: str,
    diff_files: List[str],
    model: str,
    tpm_limit: int,
    safety: float,
    max_output_tokens: int,
    unified_context: int,
    context_keep: int,
) -> List[ManifestEntry]:
    entries: List[ManifestEntry] = []
    max_input_tokens = _compute_max_input_tokens(tpm_limit, safety, max_output_tokens)

    for df in diff_files:
        subject, diff_text = load_diff_from_file(df)
        hunks = reduce_unified_diff(diff_text, context_keep=context_keep)
        for h in hunks:
            prompt_pre = build_memory_prompt(
                repo_path, "diff_file", df, subject, h, 1, 1, est_total_tokens=0
            )
            est = TOKENS.estimate(prompt_pre, model)
            entry_id = sha1_text(
                f"{repo_path}|diff_file|{df}|{h.file_path}|{h.hunk_header}|{h.new_start_line}"
            )[:16]
            entries.append(
                ManifestEntry(
                    entry_id=entry_id,
                    repo_path=repo_path,
                    source_type="diff_file",
                    source_id=df,
                    commit_subject=subject,
                    file_path=h.file_path,
                    hunk_header=h.hunk_header,
                    new_start_line=h.new_start_line,
                    new_line_count=h.new_line_count,
                    est_input_tokens=est,
                    max_input_tokens=max_input_tokens,
                    max_output_tokens=max_output_tokens,
                    unified_context=int(unified_context),
                    context_keep=int(context_keep),
                    status="pending",
                    last_error=None,
                )
            )
    return entries


def cmd_analyze(args: argparse.Namespace) -> None:
    repo_path = args.repo_path
    commits = read_lines(args.commit_hashes_file)
    diff_files = read_lines(args.diff_files_list)

    entries: List[ManifestEntry] = []
    if commits:
        entries.extend(
            build_manifest_entries_from_commits(
                repo_path=repo_path,
                commit_hashes=commits,
                model=args.model,
                tpm_limit=args.tpm_limit,
                safety=args.safety,
                max_output_tokens=args.max_output_tokens,
                unified_context=args.unified_context,
                context_keep=args.context_keep,
            )
        )
    if diff_files:
        entries.extend(
            build_manifest_entries_from_diff_files(
                repo_path=repo_path,
                diff_files=diff_files,
                model=args.model,
                tpm_limit=args.tpm_limit,
                safety=args.safety,
                max_output_tokens=args.max_output_tokens,
                unified_context=args.unified_context,
                context_keep=args.context_keep,
            )
        )

    write_manifest_entries(Path(args.manifest_out), entries)
    print(
        f"Wrote manifest entries: {len(entries)} -> {args.manifest_out} "
        f"(unified_context={args.unified_context}, context_keep={args.context_keep}, "
        f"token_mode={'tiktoken' if tiktoken else 'heuristic'})"
    )


# =========================
# List command
# =========================
def cmd_list(args: argparse.Namespace) -> None:
    manifest = Path(args.manifest)
    entries = read_manifest(manifest)

    pending = [e for e in entries if e.status == "pending"]
    done = [e for e in entries if e.status == "done"]
    err = [e for e in entries if e.status == "error"]
    skipped = [e for e in entries if e.status == "skipped"]

    print(f"Manifest: {manifest}")
    print(
        f"Total={len(entries)} pending={len(pending)} done={len(done)} error={len(err)} skipped={len(skipped)}"
    )

    if args.top:
        pending_sorted = sorted(
            pending, key=lambda e: e.est_input_tokens, reverse=True
        )[: int(args.top)]
        print("\nTop pending by est_input_tokens:")
        for e in pending_sorted:
            print(
                f"  {e.entry_id} est={e.est_input_tokens} max_in={e.max_input_tokens} "
                f"src={e.source_type}:{_short(e.source_id, 12)} file={_short(e.file_path, 60)} "
                f"subj={_short(e.commit_subject, 70)}"
            )

    if args.show_errors:
        if err:
            print("\nErrors:")
            for e in err[: max(25, int(args.top or 25))]:
                print(f"  {e.entry_id} last_error={_short(e.last_error or '', 240)}")


# =========================
# Publishing helpers
# =========================
def _build_publishers_from_args(
    args: argparse.Namespace,
) -> Tuple[str, str, Optional[Mem0Publisher], Optional[MemoryBankPublisher]]:
    publish_mode = getattr(args, "publish", "none")
    publish_format = getattr(args, "publish_format", "text")

    mem0_pub: Optional[Mem0Publisher] = None
    mb_pub: Optional[MemoryBankPublisher] = None

    if publish_mode in ("mem0", "both"):
        if not args.mem0_user_id:
            raise RuntimeError("--mem0-user-id is required when --publish mem0/both")
        mem0_cfg = Mem0PublishConfig(
            enabled=True,
            user_id=args.mem0_user_id,
            base_metadata={
                "pipeline": "generate_memories_from_diffs",
                "store": "mem0_local",
            },
        )
        mem0_pub = Mem0Publisher(mem0_cfg)

    if publish_mode in ("memory_bank", "both"):
        try:
            scope = json.loads(args.memory_scope_json) if args.memory_scope_json else {}
        except Exception as ex:
            raise RuntimeError("Invalid JSON for --memory-scope-json") from ex
        try:
            labels = (
                json.loads(args.memory_labels_json) if args.memory_labels_json else {}
            )
        except Exception as ex:
            raise RuntimeError("Invalid JSON for --memory-labels-json") from ex

        if (
            not args.gcp_project_id
            or not args.vertex_region
            or not args.vertex_memory_agent_id
        ):
            raise RuntimeError(
                "--gcp-project-id, --vertex-region, and --vertex-memory-agent-id are required "
                "when --publish memory_bank/both"
            )

        mb_cfg = PublishConfig(
            enabled=True,
            project_id=args.gcp_project_id,
            region=args.vertex_region,
            reasoning_engine_id=args.vertex_memory_agent_id,
            scope=scope,
            labels=labels,
        )
        mb_pub = MemoryBankPublisher(mb_cfg)

    return publish_mode, publish_format, mem0_pub, mb_pub


# =========================
# Run-one / Run-batch
# =========================
def _pick_pending_entries(
    entries: List[ManifestEntry], limit: int
) -> List[ManifestEntry]:
    pending = [e for e in entries if e.status == "pending"]
    # Heuristic: larger first to reduce long-tail stragglers
    pending_sorted = sorted(pending, key=lambda e: e.est_input_tokens, reverse=True)
    return pending_sorted[:limit]


def cmd_run_one(args: argparse.Namespace) -> None:
    manifest_path = Path(args.manifest)
    memories_out_path = Path(args.memories_out)

    entries = read_manifest(manifest_path)
    if args.entry_id:
        matches = [e for e in entries if e.entry_id == args.entry_id]
        if not matches:
            raise RuntimeError(f"--entry-id not found in manifest: {args.entry_id}")
        entry = matches[0]
    else:
        pending = _pick_pending_entries(entries, limit=1)
        if not pending:
            print("No pending entries.")
            return
        entry = pending[0]

    publish_mode, publish_format, mem0_pub, mb_pub = _build_publishers_from_args(args)
    llm = OpenAILLMClient()

    print(
        f"RUN-ONE: entry_id={entry.entry_id} file={entry.file_path} subj={_short(entry.commit_subject, 90)}"
    )
    process_one_manifest_entry(
        llm=llm,
        manifest_path=manifest_path,
        memories_out_path=memories_out_path,
        model=args.model,
        api_delay_sec=float(args.api_delay_sec),
        e=entry,
        publish_mode=publish_mode,
        publish_format=publish_format,
        mem0_pub=mem0_pub,
        mb_pub=mb_pub,
        progress_prefix="",
        verbose=not args.quiet,
    )
    print("Done.")


def cmd_run_batch(args: argparse.Namespace) -> None:
    manifest_path = Path(args.manifest)
    memories_out_path = Path(args.memories_out)

    entries = read_manifest(manifest_path)
    todo = _pick_pending_entries(entries, limit=int(args.limit))

    if not todo:
        print("No pending entries.")
        return

    publish_mode, publish_format, mem0_pub, mb_pub = _build_publishers_from_args(args)
    llm = OpenAILLMClient()

    total = len(todo)
    print(
        f"RUN-BATCH: pending_selected={total} workers={args.workers} "
        f"publish={publish_mode} token_mode={'tiktoken' if tiktoken else 'heuristic'}"
    )

    # Threaded concurrency is safe because:
    # - DiffCache is locked
    # - manifest writes are locked
    # - memories writes are locked
    # Note: OpenAI client is thread-safe enough in practice, but to be safe we create one per task.
    # For simplicity, we reuse llm here; if you observe issues, instantiate per worker.

    failures = 0
    start = time.time()

    def _run_one(ix: int, entry: ManifestEntry) -> None:
        prefix = f"[{ix}/{total}] "
        process_one_manifest_entry(
            llm=llm,
            manifest_path=manifest_path,
            memories_out_path=memories_out_path,
            model=args.model,
            api_delay_sec=float(args.api_delay_sec),
            e=entry,
            publish_mode=publish_mode,
            publish_format=publish_format,
            mem0_pub=mem0_pub,
            mb_pub=mb_pub,
            progress_prefix=prefix,
            verbose=not args.quiet,
        )

    workers = max(1, int(args.workers))
    if workers == 1:
        for ix, entry in enumerate(todo, start=1):
            try:
                _run_one(ix, entry)
            except Exception as ex:
                failures += 1
                if not args.quiet:
                    print(f"[{ix}/{total}] ERROR entry={entry.entry_id}: {ex}")
                if args.fail_fast:
                    raise
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {
                ex.submit(_run_one, ix, entry): (ix, entry)
                for ix, entry in enumerate(todo, start=1)
            }
            for fut in as_completed(futures):
                ix, entry = futures[fut]
                try:
                    fut.result()
                except Exception as e:
                    failures += 1
                    if not args.quiet:
                        print(f"[{ix}/{total}] ERROR entry={entry.entry_id}: {e}")
                    if args.fail_fast:
                        raise

    dur = time.time() - start
    print(
        f"RUN-BATCH complete: processed={total} failures={failures} elapsed_sec={dur:.1f}"
    )


# =========================
# Publish-file command
# =========================
def cmd_publish_file(args: argparse.Namespace) -> None:
    memories_path = Path(args.memories_ndjson)
    if not memories_path.exists():
        raise FileNotFoundError(str(memories_path))

    publish_mode, publish_format, mem0_pub, mb_pub = _build_publishers_from_args(args)
    if publish_mode == "none":
        raise RuntimeError("--publish must be one of: mem0, memory_bank, both")

    dedup_ids = load_dedup_ids(args.dedup_ids_file)
    records = iter_ndjson(memories_path)

    published = 0
    skipped = 0
    failed = 0

    for rec in records:
        mid = str(rec.get("memory_id") or "").strip()
        if not mid:
            skipped += 1
            continue
        if mid in dedup_ids:
            skipped += 1
            continue

        try:
            results = publish_record(
                rec,
                publish_mode=publish_mode,
                publish_format=publish_format,
                mem0_pub=mem0_pub,
                mb_pub=mb_pub,
            )
            if "mem0" in results:
                rec["mem0_result"] = results["mem0"]
            if "memory_bank" in results:
                rec["memory_bank_result"] = results["memory_bank"]

            published += 1
            dedup_ids.add(mid)
            append_dedup_id(args.dedup_ids_file, mid)

            if not args.quiet and (published % 25 == 0):
                print(f"Published {published}...")

            if args.api_delay_sec and float(args.api_delay_sec) > 0:
                time.sleep(float(args.api_delay_sec))

        except Exception as ex:
            failed += 1
            if not args.quiet:
                print(f"Publish failed memory_id={mid}: {ex}")
            if args.fail_fast:
                raise

    print(
        f"PUBLISH-FILE complete: published={published} skipped={skipped} failed={failed}"
    )


# =========================
# Self-test (no network)
# =========================
def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def cmd_self_test(_: argparse.Namespace) -> None:
    # _extract_json_object
    _assert(_extract_json_object('{"a":1}')["a"] == 1, "json parse basic failed")
    _assert(_extract_json_object('ok {"b":2} thanks')["b"] == 2, "json salvage failed")

    # normalize/coerce
    _assert(
        normalize_memory_type("REFactor") == "refactor", "normalize_memory_type failed"
    )
    _assert(coerce_confidence("0.9") == 0.9, "coerce_confidence numeric failed")
    _assert(
        0.0 <= coerce_confidence("nan") <= 1.0, "coerce_confidence nan clamp failed"
    )

    # split_text_by_token_budget (ensure never empty chunks)
    chunks = split_text_by_token_budget("a\nb\nc\n", max_tokens=2, model=DEFAULT_MODEL)
    _assert(all(ch.strip() for ch in chunks), "chunking produced empty chunk")

    # reduce_unified_diff basic
    sample = "\n".join(
        [
            "diff --git a/x.py b/x.py",
            "--- a/x.py",
            "+++ b/x.py",
            "@@ -1,2 +1,2 @@",
            "-old",
            "+new",
            " context",
        ]
    )
    hs0 = reduce_unified_diff(sample, context_keep=0)
    _assert(len(hs0) == 1, "reduce_unified_diff should produce one hunk")
    _assert(
        "+new" in hs0[0].reduced_diff and "-old" in hs0[0].reduced_diff,
        "reduce_unified_diff +/- missing",
    )
    hs1 = reduce_unified_diff(sample, context_keep=1)
    _assert(
        " context" in hs1[0].reduced_diff, "reduce_unified_diff context_keep failed"
    )

    print("SELF-TEST OK")


# =========================
# CLI wiring
# =========================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate memories from diffs into a manifest and NDJSON output."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # analyze
    pa = sub.add_parser(
        "analyze", help="Build a manifest from commit hashes and/or diff files."
    )
    pa.add_argument("--repo-path", required=True)
    pa.add_argument("--commit-hashes-file", default=None)
    pa.add_argument("--diff-files-list", default=None)
    pa.add_argument("--manifest-out", required=True)
    pa.add_argument("--model", default=DEFAULT_MODEL)
    pa.add_argument("--tpm-limit", type=int, default=DEFAULT_TPM_LIMIT)
    pa.add_argument("--safety", type=float, default=DEFAULT_SAFETY)
    pa.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    pa.add_argument("--unified-context", type=int, default=DEFAULT_UNIFIED_CONTEXT)
    pa.add_argument("--context-keep", type=int, default=DEFAULT_CONTEXT_KEEP)
    pa.set_defaults(func=cmd_analyze)

    # list
    pl = sub.add_parser("list", help="Summarize a manifest and show pending entries.")
    pl.add_argument("--manifest", required=True)
    pl.add_argument("--top", type=int, default=25)
    pl.add_argument("--show-errors", action="store_true")
    pl.set_defaults(func=cmd_list)

    # shared publish args
    def add_publish_args(px: argparse.ArgumentParser) -> None:
        px.add_argument(
            "--publish", choices=["none", "mem0", "memory_bank", "both"], default="none"
        )
        px.add_argument(
            "--publish-format", choices=["text", "raw_json"], default="text"
        )

        # mem0
        px.add_argument("--mem0-user-id", default=None)

        # memory bank
        px.add_argument("--gcp-project-id", default=None)
        px.add_argument("--vertex-region", default=None)
        px.add_argument("--vertex-memory-agent-id", default=None)
        px.add_argument("--memory-scope-json", default=None)
        px.add_argument("--memory-labels-json", default=None)

    # run-one
    po = sub.add_parser(
        "run-one",
        help="Process a single manifest entry (first pending or by --entry-id).",
    )
    po.add_argument("--manifest", required=True)
    po.add_argument("--memories-out", required=True)
    po.add_argument("--model", default=DEFAULT_MODEL)
    po.add_argument("--entry-id", default=None)
    po.add_argument("--api-delay-sec", type=float, default=DEFAULT_API_DELAY_SEC)
    po.add_argument("--quiet", action="store_true")
    add_publish_args(po)
    po.set_defaults(func=cmd_run_one)

    # run-batch
    pb = sub.add_parser(
        "run-batch", help="Process many manifest entries (optionally parallel)."
    )
    pb.add_argument("--manifest", required=True)
    pb.add_argument("--memories-out", required=True)
    pb.add_argument("--model", default=DEFAULT_MODEL)
    pb.add_argument("--limit", type=int, default=200)
    pb.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    pb.add_argument("--api-delay-sec", type=float, default=DEFAULT_API_DELAY_SEC)
    pb.add_argument("--quiet", action="store_true")
    pb.add_argument("--fail-fast", action="store_true")
    add_publish_args(pb)
    pb.set_defaults(func=cmd_run_batch)

    # publish-file
    pp = sub.add_parser(
        "publish-file", help="Publish an existing memories.ndjson (dedup by memory_id)."
    )
    pp.add_argument("--memories-ndjson", required=True)
    pp.add_argument("--dedup-ids-file", default=None)
    pp.add_argument("--api-delay-sec", type=float, default=DEFAULT_API_DELAY_SEC)
    pp.add_argument("--quiet", action="store_true")
    pp.add_argument("--fail-fast", action="store_true")
    add_publish_args(pp)
    pp.set_defaults(func=cmd_publish_file)

    # self-test
    pt = sub.add_parser(
        "self-test", help="Run local tests for core utilities (no network)."
    )
    pt.set_defaults(func=cmd_self_test)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
        return 0
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as ex:
        print(f"ERROR: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
