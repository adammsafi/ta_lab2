#!/usr/bin/env python3
"""Diff two ChatGPT exports to identify changes.

This script compares two ChatGPT exports (zip or directory format) and generates:
- Tree diff: Added/removed/changed files and folders
- Conversations diff: Added/removed/changed conversations with semantic analysis
- Per-conversation patches: Detailed change analysis for each conversation

The diff engine handles various ChatGPT export formats and provides semantic
comparison of conversation content, not just file-level changes.

Example usage
-------------
Command line:
  python -m ta_lab2.tools.data_tools.export.chatgpt_export_diff \\
    /path/to/old.zip \\
    /path/to/new.zip \\
    --out /path/to/diff_report

Supports:
  - zip vs zip
  - zip vs folder
  - folder vs folder

Output structure
----------------
- tree_diff.json / tree_diff.txt: File system changes
- conversations_diff.json / conversations_diff.txt: Conversation changes
- conversation_patches/: Per-conversation patch files
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import logging
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Text extraction keys for various export formats
TEXT_KEYS = ("text", "content", "parts", "message", "body")


# -------------------------
# Generic helpers
# -------------------------


def sha256_bytes(b: bytes) -> str:
    """Compute SHA256 hash of bytes."""
    return hashlib.sha256(b).hexdigest()


def safe_mkdir(p: Path) -> None:
    """Create directory if it doesn't exist."""
    p.mkdir(parents=True, exist_ok=True)


def read_text_bytes(b: bytes) -> str:
    """Decode bytes to text with error handling."""
    # exports are usually utf-8; this keeps you moving even if a file has odd bytes
    return b.decode("utf-8", errors="replace")


def json_loads_bytes(b: bytes) -> Any:
    """Load JSON from bytes."""
    return json.loads(read_text_bytes(b))


def norm_text(x: Any) -> str:
    """Best-effort extraction of human text from message/content blobs across export variants."""
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        return "\n".join(norm_text(i) for i in x).strip()
    if isinstance(x, dict):
        for k in TEXT_KEYS:
            if k in x:
                return norm_text(x.get(k))
        # fallback: concatenate primitive fields
        bits: List[str] = []
        for k, v in x.items():
            if isinstance(v, (str, int, float, bool)):
                bits.append(f"{k}:{v}")
        return "\n".join(bits).strip()
    return str(x)


def is_timestampish_key(k: str) -> bool:
    """Check if key name suggests timestamp data."""
    k2 = k.lower()
    return any(s in k2 for s in ("time", "timestamp", "created", "updated", "date"))


def strip_volatile(obj: Any) -> Any:
    """Remove fields that often change between exports but aren't semantically meaningful.

    Removes timestamps, model versions, request IDs, etc.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if is_timestampish_key(k):
                continue
            if k.lower() in (
                "model",
                "request_id",
                "response_id",
                "metadata",
                "status",
            ):
                continue
            out[k] = strip_volatile(v)
        return out
    if isinstance(obj, list):
        return [strip_volatile(x) for x in obj]
    return obj


def shorten(s: str, n: int = 240) -> str:
    """Shorten text for display."""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


# -------------------------
# Export sources (zip or dir)
# -------------------------


@dataclass(frozen=True)
class EntryMeta:
    """Metadata for a file or directory in an export."""

    path: str  # normalized posix-like path
    is_dir: bool
    size: int
    mtime_iso: str
    sha256: str


class ExportSource:
    """Abstraction over ChatGPT export (zip file or directory)."""

    def __init__(self, root: str):
        self.root = root
        self.kind = "zip" if root.lower().endswith(".zip") else "dir"
        if self.kind == "zip":
            if not zipfile.is_zipfile(root):
                raise ValueError(f"Not a valid zip file: {root}")
        else:
            if not os.path.isdir(root):
                raise ValueError(f"Not a folder: {root}")

    def list_entries(self) -> Dict[str, EntryMeta]:
        """List all files and directories in the export."""
        return (
            self._list_zip_entries() if self.kind == "zip" else self._list_dir_entries()
        )

    def read_bytes(self, relpath: str) -> bytes:
        """Read file contents as bytes."""
        relpath = relpath.replace("\\", "/")
        return (
            self._read_zip_bytes(relpath)
            if self.kind == "zip"
            else self._read_dir_bytes(relpath)
        )

    def exists(self, relpath: str) -> bool:
        """Check if a relative path exists in the export."""
        relpath = relpath.replace("\\", "/")
        if self.kind == "zip":
            with zipfile.ZipFile(self.root, "r") as z:
                return relpath in set(z.namelist())
        else:
            return os.path.exists(os.path.join(self.root, relpath.replace("/", os.sep)))

    def find_member(self, candidates: List[str]) -> Optional[str]:
        """Find a file by exact name or suffix match.

        Useful because exports may place conversations.json at root or within a subfolder.
        """
        cands = [c.replace("\\", "/") for c in candidates]
        if self.kind == "zip":
            with zipfile.ZipFile(self.root, "r") as z:
                names = list(z.namelist())
        else:
            names = list(self.list_entries().keys())

        name_set = set(names)

        # exact match first
        for c in cands:
            if c in name_set:
                return c

        # suffix match
        for n in names:
            for c in cands:
                if n.endswith("/" + c) or n.endswith(c):
                    if not n.endswith("/"):
                        return n
        return None

    # ----- ZIP -----
    def _list_zip_entries(self) -> Dict[str, EntryMeta]:
        out: Dict[str, EntryMeta] = {}
        with zipfile.ZipFile(self.root, "r") as z:
            for info in z.infolist():
                p = info.filename.replace("\\", "/")
                is_dir = p.endswith("/")
                dt = datetime(*info.date_time).isoformat()

                if is_dir:
                    out[p] = EntryMeta(
                        path=p, is_dir=True, size=0, mtime_iso=dt, sha256=""
                    )
                    continue

                b = z.read(info.filename)
                out[p] = EntryMeta(
                    path=p,
                    is_dir=False,
                    size=info.file_size,
                    mtime_iso=dt,
                    sha256=sha256_bytes(b),
                )
        return out

    def _read_zip_bytes(self, relpath: str) -> bytes:
        with zipfile.ZipFile(self.root, "r") as z:
            return z.read(relpath)

    # ----- DIR -----
    def _list_dir_entries(self) -> Dict[str, EntryMeta]:
        out: Dict[str, EntryMeta] = {}
        root = Path(self.root)

        # include folders in output (derived) for nicer reporting
        for dirpath, dirnames, filenames in os.walk(root):
            drel = Path(dirpath).relative_to(root)
            if str(drel) != ".":
                p = str(drel).replace("\\", "/") + "/"
                st = os.stat(Path(dirpath))
                out[p] = EntryMeta(
                    path=p,
                    is_dir=True,
                    size=0,
                    mtime_iso=datetime.fromtimestamp(st.st_mtime).isoformat(),
                    sha256="",
                )

            for fn in filenames:
                full = Path(dirpath) / fn
                rel = full.relative_to(root)
                p = str(rel).replace("\\", "/")
                st = os.stat(full)
                b = full.read_bytes()
                out[p] = EntryMeta(
                    path=p,
                    is_dir=False,
                    size=st.st_size,
                    mtime_iso=datetime.fromtimestamp(st.st_mtime).isoformat(),
                    sha256=sha256_bytes(b),
                )
        return out

    def _read_dir_bytes(self, relpath: str) -> bytes:
        full = Path(self.root) / Path(relpath.replace("/", os.sep))
        return full.read_bytes()


# -------------------------
# Tree diff (files + folders)
# -------------------------


def diff_entries(a: Dict[str, EntryMeta], b: Dict[str, EntryMeta]) -> Dict[str, Any]:
    """Compare two export directory trees."""
    a_paths = set(a.keys())
    b_paths = set(b.keys())

    added = sorted(b_paths - a_paths)
    removed = sorted(a_paths - b_paths)
    common = sorted(a_paths & b_paths)

    def is_dir(p: str, m: Dict[str, EntryMeta]) -> bool:
        # prefer meta if present
        em = m.get(p)
        if em:
            return em.is_dir
        return p.endswith("/")

    changed_files: List[Dict[str, Any]] = []
    for p in common:
        if is_dir(p, a) or is_dir(p, b):
            continue
        if a[p].sha256 != b[p].sha256 or a[p].size != b[p].size:
            changed_files.append(
                {
                    "path": p,
                    "a_size": a[p].size,
                    "b_size": b[p].size,
                    "a_sha256": a[p].sha256,
                    "b_sha256": b[p].sha256,
                    "a_mtime": a[p].mtime_iso,
                    "b_mtime": b[p].mtime_iso,
                }
            )

    added_files = [p for p in added if not is_dir(p, b)]
    removed_files = [p for p in removed if not is_dir(p, a)]

    added_folders = sorted(
        {p for p in added if is_dir(p, b)} | derive_folders(added_files)
    )
    removed_folders = sorted(
        {p for p in removed if is_dir(p, a)} | derive_folders(removed_files)
    )

    return {
        "added_files": added_files,
        "removed_files": removed_files,
        "changed_files": changed_files,
        "added_folders": added_folders,
        "removed_folders": removed_folders,
    }


def derive_folders(paths: List[str]) -> set:
    """Derive parent folder paths from file paths."""
    s = set()
    for p in paths:
        parts = p.split("/")
        for i in range(1, len(parts)):
            s.add("/".join(parts[:i]) + "/")
    return s


# -------------------------
# conversations.json diffing
# -------------------------


def index_conversations(data: Any) -> Dict[str, Dict[str, Any]]:
    """Index conversations by ID.

    Exports vary:
    - list at top level
    - dict with "conversations" list
    - dict with "items" list
    """
    convs: List[Any]
    if isinstance(data, dict):
        if isinstance(data.get("conversations"), list):
            convs = data["conversations"]
        elif isinstance(data.get("items"), list):
            convs = data["items"]
        else:
            convs = [v for v in data.values() if isinstance(v, dict)]
    elif isinstance(data, list):
        convs = data
    else:
        raise ValueError("Unknown conversations.json shape")

    idx: Dict[str, Dict[str, Any]] = {}
    for c in convs:
        if not isinstance(c, dict):
            continue
        cid = c.get("id") or c.get("conversation_id") or c.get("uuid")
        if cid is None:
            cid = sha256_bytes(
                json.dumps(c, sort_keys=True, ensure_ascii=False).encode("utf-8")
            )[:16]
        idx[str(cid)] = c
    return idx


def extract_messages(conv: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract messages from conversation in various formats."""
    # Common layout: "mapping"
    if isinstance(conv.get("mapping"), dict):
        msgs = []
        for node in conv["mapping"].values():
            if not isinstance(node, dict):
                continue
            msg = node.get("message")
            if isinstance(msg, dict):
                msgs.append(msg)

        def keyfn(m: Dict[str, Any]) -> float:
            ct = m.get("create_time")
            try:
                return float(ct) if ct is not None else 0.0
            except Exception:
                return 0.0

        msgs.sort(key=keyfn)
        return msgs

    if isinstance(conv.get("messages"), list):
        return [m for m in conv["messages"] if isinstance(m, dict)]

    for k in ("chat_messages", "turns"):
        if isinstance(conv.get(k), list):
            return [m for m in conv[k] if isinstance(m, dict)]

    return []


def message_signature(m: Dict[str, Any]) -> Dict[str, str]:
    """Extract semantic signature of a message (role + text)."""
    role = None
    if isinstance(m.get("author"), dict):
        role = m.get("author", {}).get("role")
    if role is None:
        role = m.get("role")

    text = norm_text(m.get("content"))
    return {"role": str(role) if role is not None else "", "text": text}


def convo_sig_list(conv: Dict[str, Any]) -> List[Dict[str, str]]:
    """Get list of message signatures for a conversation."""
    msgs = extract_messages(conv)
    sigs = []
    for m in msgs:
        sig = message_signature(m)
        if sig["role"] or sig["text"]:
            sigs.append(sig)
    return sigs


def convo_content_hash(conv: Dict[str, Any]) -> str:
    """Compute content hash of conversation (semantic messages only)."""
    sig = convo_sig_list(conv)
    payload = json.dumps(sig, ensure_ascii=False, sort_keys=True)
    return sha256_bytes(payload.encode("utf-8"))


def convo_meta_hash(conv: Dict[str, Any]) -> str:
    """Compute hash of conversation metadata."""
    meta = {}
    for k in ("title", "id", "conversation_id", "uuid"):
        if k in conv:
            meta[k] = conv.get(k)
    for k in ("create_time", "update_time"):
        if k in conv:
            meta[k] = conv.get(k)
    payload = json.dumps(strip_volatile(meta), ensure_ascii=False, sort_keys=True)
    return sha256_bytes(payload.encode("utf-8"))


def is_prefix(a: List[Dict[str, str]], b: List[Dict[str, str]]) -> bool:
    """Check if list a is a prefix of list b."""
    if len(a) > len(b):
        return False
    return a == b[: len(a)]


def unified_message_lines(sig: List[Dict[str, str]]) -> List[str]:
    """Format message signatures for unified diff."""
    lines: List[str] = []
    for i, s in enumerate(sig, start=1):
        role = s.get("role", "")
        txt = s.get("text", "")
        txt = re.sub(r"\s+", " ", txt).strip()
        lines.append(f"{i:05d} {role}: {shorten(txt, 500)}")
    return lines


def diff_one_conversation(
    a_conv: Dict[str, Any], b_conv: Dict[str, Any], last_n: int
) -> Dict[str, Any]:
    """Diff a single conversation between old and new versions."""
    a_sig = convo_sig_list(a_conv)
    b_sig = convo_sig_list(b_conv)

    change_type = "unknown"
    added_msgs: List[Dict[str, str]] = []
    removed_msgs: List[Dict[str, str]] = []
    unified_diff: List[str] = []

    if is_prefix(a_sig, b_sig) and len(b_sig) > len(a_sig):
        change_type = "append_only"
        added_msgs = b_sig[len(a_sig) :]
    elif is_prefix(b_sig, a_sig) and len(a_sig) > len(b_sig):
        change_type = "truncation"
        removed_msgs = a_sig[len(b_sig) :]
    elif a_sig == b_sig:
        change_type = "meta_only"
    else:
        change_type = "internal_edit"
        a_lines = unified_message_lines(a_sig)
        b_lines = unified_message_lines(b_sig)
        ud = difflib.unified_diff(
            a_lines, b_lines, fromfile="old", tofile="new", lineterm=""
        )
        unified_diff = list(ud)

    patch = {
        "change_type": change_type,
        "title_old": a_conv.get("title"),
        "title_new": b_conv.get("title"),
        "n_messages_old": len(a_sig),
        "n_messages_new": len(b_sig),
        "content_hash_old": convo_content_hash(a_conv),
        "content_hash_new": convo_content_hash(b_conv),
        "meta_hash_old": convo_meta_hash(a_conv),
        "meta_hash_new": convo_meta_hash(b_conv),
        "added_messages": added_msgs,
        "removed_messages": removed_msgs,
        "last_n_old": a_sig[-last_n:] if last_n > 0 else [],
        "last_n_new": b_sig[-last_n:] if last_n > 0 else [],
        # unified diff can be large; caller may also write it to a text file
        "unified_diff": unified_diff,
    }
    return patch


def diff_conversations(
    a_idx: Dict[str, Dict[str, Any]], b_idx: Dict[str, Dict[str, Any]], last_n: int
) -> Dict[str, Any]:
    """Diff conversations between two exports."""
    a_ids = set(a_idx.keys())
    b_ids = set(b_idx.keys())

    added = sorted(b_ids - a_ids)
    removed = sorted(a_ids - b_ids)
    common = sorted(a_ids & b_ids)

    changed: List[Dict[str, Any]] = []
    unchanged_count = 0

    for cid in common:
        a_conv = a_idx[cid]
        b_conv = b_idx[cid]
        ch_content = convo_content_hash(a_conv) != convo_content_hash(b_conv)
        ch_meta = convo_meta_hash(a_conv) != convo_meta_hash(b_conv)
        if ch_content or ch_meta:
            patch = diff_one_conversation(a_conv, b_conv, last_n=last_n)
            changed.append(
                {
                    "id": cid,
                    "change_type": patch["change_type"],
                    "title_old": patch["title_old"],
                    "title_new": patch["title_new"],
                    "n_messages_old": patch["n_messages_old"],
                    "n_messages_new": patch["n_messages_new"],
                    "content_hash_changed": patch["content_hash_old"]
                    != patch["content_hash_new"],
                    "meta_hash_changed": patch["meta_hash_old"]
                    != patch["meta_hash_new"],
                }
            )
        else:
            unchanged_count += 1

    # Summarize change types
    ct_counts: Dict[str, int] = {}
    for c in changed:
        ct = c["change_type"]
        ct_counts[ct] = ct_counts.get(ct, 0) + 1

    return {
        "total_old": len(a_ids),
        "total_new": len(b_ids),
        "added_conversation_ids": added,
        "removed_conversation_ids": removed,
        "changed_conversations": changed,
        "changed_by_type": ct_counts,
        "unchanged_count": unchanged_count,
    }


# -------------------------
# Reporting
# -------------------------


def write_json(path: Path, obj: Any) -> None:
    """Write object as JSON."""
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")


def write_text(path: Path, s: str) -> None:
    """Write text file."""
    path.write_text(s, encoding="utf-8")


def render_tree_txt(
    tree: Dict[str, Any], a_label: str, b_label: str, limit: int
) -> str:
    """Render tree diff as human-readable text."""

    def take(xs: List[Any]) -> List[Any]:
        return xs[:limit]

    out: List[str] = []
    out.append("=== EXPORT TREE DIFF ===\n")
    out.append(f"OLD: {a_label}\nNEW: {b_label}\n\n")

    out.append(f"Added folders: {len(tree['added_folders'])}\n")
    for p in take(tree["added_folders"]):
        out.append(f"  + {p}\n")
    if len(tree["added_folders"]) > limit:
        out.append("  ... (truncated)\n")

    out.append(f"\nRemoved folders: {len(tree['removed_folders'])}\n")
    for p in take(tree["removed_folders"]):
        out.append(f"  - {p}\n")
    if len(tree["removed_folders"]) > limit:
        out.append("  ... (truncated)\n")

    out.append(f"\nAdded files: {len(tree['added_files'])}\n")
    for p in take(tree["added_files"]):
        out.append(f"  + {p}\n")
    if len(tree["added_files"]) > limit:
        out.append("  ... (truncated)\n")

    out.append(f"\nRemoved files: {len(tree['removed_files'])}\n")
    for p in take(tree["removed_files"]):
        out.append(f"  - {p}\n")
    if len(tree["removed_files"]) > limit:
        out.append("  ... (truncated)\n")

    out.append(f"\nChanged files: {len(tree['changed_files'])}\n")
    for ch in take(tree["changed_files"]):
        out.append(f"  * {ch['path']}\n")
        out.append(f"      size: {ch['a_size']} -> {ch['b_size']}\n")
        out.append(f"      sha256(old): {ch['a_sha256']}\n")
        out.append(f"      sha256(new): {ch['b_sha256']}\n")
    if len(tree["changed_files"]) > limit:
        out.append("  ... (truncated)\n")

    return "".join(out)


def render_conversations_txt(report: Dict[str, Any], limit: int) -> str:
    """Render conversations diff as human-readable text."""
    out: List[str] = []
    out.append("=== CONVERSATIONS.JSON DIFF ===\n\n")

    if "note" in report:
        out.append(report["note"] + "\n")
        return "".join(out)

    out.append(f"Old total: {report['total_old']}\n")
    out.append(f"New total: {report['total_new']}\n")
    out.append(f"Unchanged: {report['unchanged_count']}\n\n")

    out.append("Changed by type:\n")
    for k, v in sorted(
        report.get("changed_by_type", {}).items(), key=lambda kv: (-kv[1], kv[0])
    ):
        out.append(f"  {k}: {v}\n")

    out.append(f"\nAdded conversations: {len(report['added_conversation_ids'])}\n")
    for cid in report["added_conversation_ids"][:limit]:
        out.append(f"  + {cid}\n")
    if len(report["added_conversation_ids"]) > limit:
        out.append("  ... (truncated)\n")

    out.append(f"\nRemoved conversations: {len(report['removed_conversation_ids'])}\n")
    for cid in report["removed_conversation_ids"][:limit]:
        out.append(f"  - {cid}\n")
    if len(report["removed_conversation_ids"]) > limit:
        out.append("  ... (truncated)\n")

    out.append(f"\nChanged conversations: {len(report['changed_conversations'])}\n")
    for ch in report["changed_conversations"][:limit]:
        out.append(f"  * {ch['id']}\n")
        if ch.get("title_old") != ch.get("title_new"):
            out.append(f"      title: {ch.get('title_old')} -> {ch.get('title_new')}\n")
        out.append(f"      type: {ch['change_type']}\n")
        out.append(
            f"      messages: {ch['n_messages_old']} -> {ch['n_messages_new']}\n"
        )
        out.append(
            f"      content_changed={ch['content_hash_changed']} meta_changed={ch['meta_hash_changed']}\n"
        )
    if len(report["changed_conversations"]) > limit:
        out.append("  ... (truncated)\n")

    return "".join(out)


def diff_exports(
    old_path: str,
    new_path: str,
    out_dir: Path,
    last_n: int = 8,
    limit: int = 200,
    max_patches: int = 500,
) -> Dict[str, Any]:
    """Diff two ChatGPT exports.

    Args:
        old_path: Old export (.zip) or unzipped export folder
        new_path: New export (.zip) or unzipped export folder
        out_dir: Output directory for diff reports
        last_n: Include last N messages before/after in per-conversation patches
        limit: Max items printed in text reports
        max_patches: Max per-conversation patch files to write

    Returns:
        Dict with diff statistics
    """
    src_a = ExportSource(old_path)
    src_b = ExportSource(new_path)

    safe_mkdir(out_dir)

    # ---- Tree diff ----
    logger.info("Computing tree diff...")
    a_entries = src_a.list_entries()
    b_entries = src_b.list_entries()
    tree = diff_entries(a_entries, b_entries)

    write_json(out_dir / "tree_diff.json", tree)
    write_text(
        out_dir / "tree_diff.txt", render_tree_txt(tree, old_path, new_path, limit)
    )

    # ---- conversations.json diff ----
    logger.info("Computing conversations diff...")
    conv_member_a = src_a.find_member(["conversations.json"])
    conv_member_b = src_b.find_member(["conversations.json"])

    conv_report: Dict[str, Any]
    patches_written = 0

    patches_dir = out_dir / "conversation_patches"
    safe_mkdir(patches_dir)

    if not conv_member_a or not conv_member_b:
        conv_report = {"note": "conversations.json not found in one or both exports."}
    else:
        a_data = json_loads_bytes(src_a.read_bytes(conv_member_a))
        b_data = json_loads_bytes(src_b.read_bytes(conv_member_b))

        a_idx = index_conversations(a_data)
        b_idx = index_conversations(b_data)

        conv_report = diff_conversations(a_idx, b_idx, last_n=last_n)

        # Write per-conversation patches for changed convos
        for ch in conv_report.get("changed_conversations", [])[:max_patches]:
            cid = ch["id"]
            patch = diff_one_conversation(a_idx[cid], b_idx[cid], last_n=last_n)

            # Save patch JSON
            write_json(patches_dir / f"{cid}.patch.json", patch)
            patches_written += 1

            # Also save unified diff as .diff.txt if it exists and is non-trivial
            ud = patch.get("unified_diff") or []
            if ud:
                write_text(patches_dir / f"{cid}.diff.txt", "\n".join(ud) + "\n")

        conv_report["patches_written"] = patches_written
        conv_report["conversations_json_old_path"] = conv_member_a
        conv_report["conversations_json_new_path"] = conv_member_b

    write_json(out_dir / "conversations_diff.json", conv_report)
    write_text(
        out_dir / "conversations_diff.txt", render_conversations_txt(conv_report, limit)
    )

    logger.info(f"Wrote outputs to: {out_dir.resolve()}")

    return {
        "tree": tree,
        "conversations": conv_report,
        "patches_written": patches_written,
    }


# -------------------------
# Main
# -------------------------


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    ap = argparse.ArgumentParser(
        description="Diff two ChatGPT exports: zip vs zip, zip vs folder, or folder vs folder."
    )
    ap.add_argument("old", help="Old export (.zip) or unzipped export folder")
    ap.add_argument("new", help="New export (.zip) or unzipped export folder")
    ap.add_argument(
        "--out", default="diff_report", help="Output directory (will be created)"
    )
    ap.add_argument(
        "--last-n",
        type=int,
        default=8,
        help="Include last N messages before/after in per-conversation patches",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max items printed in text reports (files/convos)",
    )
    ap.add_argument(
        "--max-patches",
        type=int,
        default=500,
        help="Max per-conversation patch files to write",
    )
    args = ap.parse_args()

    out_root = Path(args.out)

    diff_exports(
        args.old,
        args.new,
        out_root,
        last_n=args.last_n,
        limit=args.limit,
        max_patches=args.max_patches,
    )

    print("Wrote outputs to:", out_root.resolve())
    print("  - tree_diff.json / tree_diff.txt")
    print("  - conversations_diff.json / conversations_diff.txt")
    print(
        "  - conversation_patches/ (per-conversation patch json + optional unified diffs)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
