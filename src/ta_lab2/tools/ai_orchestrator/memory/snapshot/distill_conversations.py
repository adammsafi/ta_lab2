"""Distill AI coding assistant conversations into structured memories via GPT-4o-mini.

Supports three sources: Claude Code, Gemini CLI, and OpenAI Codex CLI.
Replaces the raw 500-char excerpt pipeline with LLM-distilled decisions, facts,
and procedures. Processes ALL messages, uses Mem0 with infer=True for dedup.

Pipeline per session:
  1. Extract messages (source-specific parser)
  2. format_for_distillation(messages) -> conversation text
  3. chunk_conversation(text) -> chunks (80K chars, split at message boundaries)
  4. distill_with_gpt(chunk) -> [{title, content, type}, ...]
  5. store_distilled_memories(memories) -> Mem0 add(infer=True)

Usage:
    # Claude Code (default)
    python -m ta_lab2.tools.ai_orchestrator.memory.snapshot.distill_conversations

    # Gemini CLI
    python -m ta_lab2.tools.ai_orchestrator.memory.snapshot.distill_conversations \
        --source gemini

    # OpenAI Codex CLI
    python -m ta_lab2.tools.ai_orchestrator.memory.snapshot.distill_conversations \
        --source codex

    # Purge old raw excerpts
    python -m ta_lab2.tools.ai_orchestrator.memory.snapshot.distill_conversations \
        --purge-only --confirm-purge

    # Dry-run with file limit
    python -m ta_lab2.tools.ai_orchestrator.memory.snapshot.distill_conversations \
        --source gemini --dry-run --max-files 2
"""

import argparse
import json
import logging
import os
import re
import time
import urllib.request
from pathlib import Path

from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
from ta_lab2.tools.ai_orchestrator.memory.metadata import create_metadata
from ta_lab2.tools.ai_orchestrator.memory.snapshot.extract_conversations import (
    extract_conversation,
    find_conversation_files,
)
from ta_lab2.tools.data_tools.memory.generate_memories_from_conversations import (
    MEMORY_EXTRACTION_PROMPT,
)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# --- Constants ---

QDRANT_URL = "http://localhost:6333"
COLLECTION = "project_memories"
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
PROJECT_FOLDER = "C--Users-asafi-Downloads-ta-lab2"
MAX_CHUNK_CHARS = 80_000
DEFAULT_MODEL = "gpt-4o-mini"

# Sources used by the old run_conversation_snapshot.py pipeline
RAW_EXCERPT_SOURCES = [
    "conversation_history_v0.4.0",
    "conversation_history_v0.5.0",
    "conversation_history_v0.6.0",
    "conversation_history_v0.7.0",
    "conversation_history_v0.8.0",
    "conversation_history_v0.9.0",
    "conversation_history_v1.0.0",
    "conversation_history_v1.0.1",
]

# Gemini and Codex paths
GEMINI_CHATS_DIR = Path.home() / ".gemini" / "tmp" / "ta-lab2" / "chats"
CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"

# Progress file for resumability (per-source)
PROGRESS_DIR = CLAUDE_PROJECTS_DIR / PROJECT_FOLDER


def _progress_file(source: str) -> Path:
    """Return source-specific progress file path."""
    suffix = "" if source == "claude" else f"_{source}"
    return PROGRESS_DIR / f".distill_progress{suffix}.json"


# --- Source-specific extractors ---


def extract_gemini_conversation(json_path: Path) -> list[dict]:
    """Parse Gemini CLI session JSON to extract conversation messages.

    Gemini sessions are single JSON files with a top-level ``messages`` array.
    Each message has ``type`` ("user" or "gemini") and ``content``.

    Args:
        json_path: Path to Gemini session .json file

    Returns:
        List of message dicts with role, content, timestamp
    """
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to read Gemini session {json_path}: {e}")
        return []

    messages = []
    for msg in data.get("messages", []):
        msg_type = msg.get("type", "")
        raw = msg.get("content", "")
        # Content can be a string or a list of {"text": ...} dicts
        if isinstance(raw, list):
            content = " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in raw
            ).strip()
        else:
            content = str(raw).strip()
        if not content:
            continue
        # Normalize role: "gemini" -> "assistant"
        role = "assistant" if msg_type == "gemini" else msg_type
        messages.append(
            {
                "role": role,
                "content": content,
                "timestamp": msg.get("timestamp"),
            }
        )

    logger.info(
        f"Extracted {len(messages)} messages from Gemini session {json_path.name}"
    )
    return messages


def find_gemini_files() -> list[Path]:
    """Find Gemini CLI session JSON files for the ta-lab2 project."""
    if not GEMINI_CHATS_DIR.exists():
        logger.warning(f"Gemini chats directory not found: {GEMINI_CHATS_DIR}")
        return []
    files = sorted(GEMINI_CHATS_DIR.glob("session-*.json"))
    logger.info(f"Found {len(files)} Gemini session files")
    return files


def extract_codex_conversation(jsonl_path: Path) -> list[dict]:
    """Parse OpenAI Codex CLI session JSONL to extract conversation messages.

    Codex sessions use JSONL with ``response_item`` entries containing
    ``payload.type="message"`` and ``payload.role`` ("user"/"assistant").
    Content is in ``payload.content[].text``.

    Args:
        jsonl_path: Path to Codex session .jsonl file

    Returns:
        List of message dicts with role, content, timestamp
    """
    messages = []
    try:
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get("type") != "response_item":
                    continue

                payload = entry.get("payload", {})
                if payload.get("type") != "message":
                    continue

                role = payload.get("role", "")
                if role not in ("user", "assistant"):
                    continue

                # Extract text from content blocks
                content_blocks = payload.get("content", [])
                text_parts = []
                for block in content_blocks:
                    if isinstance(block, dict) and block.get("type") in (
                        "input_text",
                        "output_text",
                    ):
                        text_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        text_parts.append(block)

                content = "\n".join(text_parts).strip()
                if not content:
                    continue

                # Skip system injection messages (AGENTS.md, environment_context)
                if content.startswith("# AGENTS.md") or content.startswith(
                    "<environment_context>"
                ):
                    continue

                messages.append(
                    {
                        "role": role,
                        "content": content,
                        "timestamp": entry.get("timestamp"),
                    }
                )
    except (OSError, UnicodeDecodeError) as e:
        logger.warning(f"Failed to read Codex session {jsonl_path}: {e}")
        return []

    logger.info(
        f"Extracted {len(messages)} messages from Codex session {jsonl_path.name}"
    )
    return messages


def find_codex_files() -> list[Path]:
    """Find OpenAI Codex CLI session JSONL files."""
    if not CODEX_SESSIONS_DIR.exists():
        logger.warning(f"Codex sessions directory not found: {CODEX_SESSIONS_DIR}")
        return []
    files = sorted(CODEX_SESSIONS_DIR.rglob("rollout-*.jsonl"))
    logger.info(f"Found {len(files)} Codex session files")
    return files


# --- Qdrant helpers (urllib pattern from report_memory_map.py) ---


def _qdrant_post(endpoint: str, body: dict) -> dict:
    """POST JSON to Qdrant REST API."""
    url = f"{QDRANT_URL}/collections/{COLLECTION}/{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read().decode("utf-8"))


def _qdrant_count(filt: dict) -> int:
    """Count points matching a Qdrant filter."""
    result = _qdrant_post("points/count", {"filter": filt, "exact": True})
    return result["result"]["count"]


def purge_raw_excerpts(dry_run: bool = True) -> int:
    """Delete raw conversation excerpts from Qdrant.

    Targets points with category=development_context AND source matching
    any of the old conversation_history_v* sources.

    Args:
        dry_run: If True, count but do not delete.

    Returns:
        Number of points deleted (or that would be deleted in dry-run).
    """
    # Build filter: category=development_context AND source IN raw sources
    filt = {
        "must": [
            {"key": "category", "match": {"value": "development_context"}},
            {"key": "source", "match": {"any": RAW_EXCERPT_SOURCES}},
        ]
    }

    count = _qdrant_count(filt)
    logger.info(f"Found {count} raw excerpt points matching purge filter")

    if dry_run:
        logger.info("Dry run -- no points deleted")
        return count

    if count == 0:
        logger.info("Nothing to purge")
        return 0

    # Delete via Qdrant REST API
    result = _qdrant_post("points/delete", {"filter": filt})
    status = result.get("status", "unknown")
    logger.info(f"Purge result: status={status}, deleted ~{count} points")
    return count


# --- Conversation formatting ---


def format_for_distillation(messages: list[dict]) -> str:
    """Convert extracted messages to 'ROLE: content' text for GPT.

    Processes ALL messages (no phase filtering). Skips empty content.

    Args:
        messages: List of message dicts from extract_conversation().

    Returns:
        Formatted conversation text.
    """
    parts = []
    for msg in messages:
        role = (msg.get("role") or "unknown").upper()
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        parts.append(f"{role}: {content}")
    return "\n\n".join(parts)


def chunk_conversation(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split conversation text at message boundaries.

    Splits on double-newline (message separator) to avoid cutting mid-message.

    Args:
        text: Full conversation text from format_for_distillation().
        max_chars: Maximum characters per chunk.

    Returns:
        List of text chunks, each under max_chars.
    """
    if len(text) <= max_chars:
        return [text]

    messages = text.split("\n\n")
    chunks = []
    current = []
    current_len = 0

    for msg in messages:
        msg_len = len(msg) + 2  # +2 for \n\n separator
        if current_len + msg_len > max_chars and current:
            chunks.append("\n\n".join(current))
            current = []
            current_len = 0
        current.append(msg)
        current_len += msg_len

    if current:
        chunks.append("\n\n".join(current))

    return chunks


# --- GPT distillation ---


def distill_with_gpt(
    text: str,
    client: "OpenAI",  # noqa: F821
    model: str = DEFAULT_MODEL,
    max_retries: int = 3,
) -> list[dict]:
    """Call GPT to extract structured memories from conversation text.

    Uses the MEMORY_EXTRACTION_PROMPT from generate_memories_from_conversations.

    Args:
        text: Conversation chunk text.
        client: OpenAI client instance.
        model: Model to use.
        max_retries: Retries on rate limit errors.

    Returns:
        List of dicts with keys: title, content, type.
    """
    if len(text.strip()) < 100:
        return []

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a memory extraction assistant. Extract key "
                            "technical memories from Claude Code conversations about "
                            "the ta_lab2 quantitative trading system."
                        ),
                    },
                    {"role": "user", "content": MEMORY_EXTRACTION_PROMPT + text},
                ],
                temperature=0.3,
            )

            result_text = response.choices[0].message.content or ""

            # Extract JSON array from response
            json_match = re.search(r"\[\s*\{.*\}\s*\]", result_text, re.DOTALL)
            if json_match:
                memories = json.loads(json_match.group())
                # Validate structure
                valid = []
                for m in memories:
                    if isinstance(m, dict) and "content" in m:
                        m.setdefault("title", m["content"][:60])
                        m.setdefault("type", "other")
                        valid.append(m)
                return valid

            logger.warning("No valid JSON array in GPT response, skipping chunk")
            return []

        except Exception as e:
            err_str = str(e).lower()
            if "rate_limit" in err_str or "429" in err_str:
                wait = 2 ** (attempt + 1)
                logger.warning(
                    f"Rate limited, retrying in {wait}s (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(wait)
                continue
            logger.error(f"GPT distillation error: {e}")
            return []

    logger.error(f"Exhausted {max_retries} retries for GPT call")
    return []


# --- Memory storage ---


def store_distilled_memories(
    memories: list[dict],
    mem0_client,
    session_id: str,
    model: str = DEFAULT_MODEL,
    source_tag: str = "distilled_conversations",
    dry_run: bool = False,
) -> tuple[int, int]:
    """Store distilled memories in Mem0 with infer=True.

    Args:
        memories: List of {title, content, type} dicts from GPT.
        mem0_client: Mem0Client instance.
        session_id: Session file stem for metadata.
        model: Distillation model name for metadata.
        source_tag: Source identifier for metadata (e.g. distilled_gemini).
        dry_run: If True, log but do not store.

    Returns:
        (stored_count, error_count)
    """
    stored = 0
    errors = 0

    for mem in memories:
        metadata = create_metadata(
            source=source_tag,
            category=mem.get("type", "other"),
        )
        metadata.update(
            {
                "title": mem.get("title", ""),
                "session_id": session_id,
                "distillation_model": model,
                "pipeline_version": "v2",
            }
        )
        metadata["tags"] = [
            "distilled",
            "conversation",
            f"type_{mem.get('type', 'other')}",
        ]

        content = mem["content"]
        title = mem.get("title", "")
        if title:
            content = f"{title}: {content}"

        if dry_run:
            logger.info(f"  [dry-run] Would store: {title[:80]}")
            stored += 1
            continue

        try:
            mem0_client.add(
                messages=[{"role": "user", "content": content}],
                user_id="orchestrator",
                metadata=metadata,
                infer=True,
            )
            stored += 1
        except Exception as e:
            err_str = str(e).lower()
            if "timeout" in err_str:
                logger.warning(
                    f"Mem0 infer timeout for '{title[:50]}', retrying with infer=False"
                )
                try:
                    mem0_client.add(
                        messages=[{"role": "user", "content": content}],
                        user_id="orchestrator",
                        metadata=metadata,
                        infer=False,
                    )
                    stored += 1
                except Exception as e2:
                    logger.error(f"Mem0 fallback also failed for '{title[:50]}': {e2}")
                    errors += 1
            else:
                logger.error(f"Failed to store memory '{title[:50]}': {e}")
                errors += 1

    return stored, errors


# --- Progress tracking ---


def _load_progress(source: str = "claude") -> dict:
    """Load progress file (completed/failed sessions)."""
    pf = _progress_file(source)
    if pf.exists():
        with open(pf, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed": [], "failed": [], "total_stored": 0}


def _save_progress(progress: dict, source: str = "claude") -> None:
    """Save progress file."""
    pf = _progress_file(source)
    pf.parent.mkdir(parents=True, exist_ok=True)
    with open(pf, "w", encoding="utf-8") as f:
        json.dump(progress, f, indent=2)


# --- Main pipeline ---


def main() -> int:
    """CLI entry point for conversation distillation pipeline."""
    parser = argparse.ArgumentParser(
        description="Distill AI assistant conversations into structured memories"
    )
    parser.add_argument(
        "--source",
        choices=["claude", "gemini", "codex"],
        default="claude",
        help="Conversation source (default: claude)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview operations without writing",
    )
    parser.add_argument(
        "--purge-only",
        action="store_true",
        help="Only purge raw excerpts, do not distill",
    )
    parser.add_argument(
        "--confirm-purge",
        action="store_true",
        help="Actually execute purge (required with --purge-only)",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Process a single session file (path or stem)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip already-completed sessions from progress file",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=0,
        help="Limit number of session files to process (0=all)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"OpenAI model for distillation (default: {DEFAULT_MODEL})",
    )

    args = parser.parse_args()
    source: str = args.source

    # --- Purge mode (Claude only) ---
    if args.purge_only:
        if args.dry_run or not args.confirm_purge:
            count = purge_raw_excerpts(dry_run=True)
            print(f"\nWould purge {count} raw excerpt points from Qdrant")
            if not args.confirm_purge:
                print("Add --confirm-purge to execute")
            return 0
        count = purge_raw_excerpts(dry_run=False)
        print(f"\nPurged {count} raw excerpt points from Qdrant")
        return 0

    # --- Distillation mode ---

    # Check OpenAI key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error(
            "OPENAI_API_KEY not set. Export it:\n"
            "  export $(grep OPENAI_API_KEY docker/.env)"
        )
        return 1

    try:
        from openai import OpenAI
    except ImportError:
        logger.error("openai package required: pip install openai")
        return 1

    client = OpenAI(api_key=api_key)

    # Source-specific: extractor function and file finder
    extractor_map = {
        "claude": extract_conversation,
        "gemini": extract_gemini_conversation,
        "codex": extract_codex_conversation,
    }
    extract_fn = extractor_map[source]
    source_tag = f"distilled_{source}"

    # Find session files
    if args.file:
        file_path = Path(args.file)
        if not file_path.exists():
            logger.error(f"File not found: {args.file}")
            return 1
        session_files = [file_path]
    elif source == "claude":
        session_files = find_conversation_files(CLAUDE_PROJECTS_DIR, PROJECT_FOLDER)
    elif source == "gemini":
        session_files = find_gemini_files()
    elif source == "codex":
        session_files = find_codex_files()
    else:
        session_files = []

    if not session_files:
        logger.error(f"No {source} session files found")
        return 1

    logger.info(f"Found {len(session_files)} {source} session files")

    # Load progress for resume
    progress = (
        _load_progress(source)
        if args.resume
        else {"completed": [], "failed": [], "total_stored": 0}
    )

    # Filter out already-completed sessions BEFORE applying --max-files
    if args.resume:
        completed_stems = set(progress["completed"])
        session_files = [f for f in session_files if f.stem not in completed_stems]
        logger.info(
            f"Resuming: {len(completed_stems)} already completed, "
            f"{len(session_files)} remaining"
        )

    # Apply --max-files limit
    if args.max_files > 0:
        session_files = session_files[: args.max_files]
        logger.info(f"Processing {len(session_files)} files (--max-files)")

    # Get Mem0 client (only when actually writing)
    mem0 = None
    if not args.dry_run:
        mem0 = get_mem0_client()

    # Process sessions
    total_stored = progress.get("total_stored", 0)
    total_distilled = 0
    total_errors = 0
    sessions_processed = 0

    for i, session_file in enumerate(session_files, 1):
        stem = session_file.stem
        logger.info(f"\n[{i}/{len(session_files)}] Processing {stem[:12]}...")

        # 1. Extract messages (source-specific)
        messages = extract_fn(session_file)
        if not messages:
            logger.info("  Empty session, skipping")
            progress["completed"].append(stem)
            _save_progress(progress, source)
            continue

        # 2. Format for distillation
        text = format_for_distillation(messages)
        if len(text.strip()) < 100:
            logger.info(f"  Too short ({len(text)} chars), skipping")
            progress["completed"].append(stem)
            _save_progress(progress, source)
            continue

        logger.info(f"  {len(messages)} messages, {len(text):,} chars")

        # 3. Chunk at message boundaries
        chunks = chunk_conversation(text)
        logger.info(f"  Split into {len(chunks)} chunk(s)")

        # 4. Distill each chunk via GPT
        session_memories: list[dict] = []
        for ci, chunk in enumerate(chunks, 1):
            logger.info(
                f"  Distilling chunk {ci}/{len(chunks)} ({len(chunk):,} chars)..."
            )
            memories = distill_with_gpt(chunk, client, model=args.model)
            logger.info(f"  -> {len(memories)} memories extracted")
            session_memories.extend(memories)

        total_distilled += len(session_memories)

        if not session_memories:
            logger.info("  No memories distilled")
            progress["completed"].append(stem)
            _save_progress(progress, source)
            continue

        # 5. Store via Mem0 with infer=True
        stored, errs = store_distilled_memories(
            session_memories,
            mem0,
            session_id=stem,
            model=args.model,
            source_tag=source_tag,
            dry_run=args.dry_run,
        )
        total_stored += stored
        total_errors += errs
        sessions_processed += 1

        logger.info(f"  Stored: {stored}, Errors: {errs}")

        # Update progress
        if errs == 0:
            progress["completed"].append(stem)
        else:
            progress["failed"].append(stem)
        progress["total_stored"] = total_stored
        _save_progress(progress, source)

    # Summary
    pf = _progress_file(source)
    print(f"\n{'=' * 60}")
    print(f"DISTILLATION SUMMARY ({source.upper()})")
    print(f"{'=' * 60}")
    print(f"Sessions processed: {sessions_processed}/{len(session_files)}")
    print(f"Total memories distilled: {total_distilled}")
    print(f"Total memories stored: {total_stored}")
    print(f"Total errors: {total_errors}")
    if args.dry_run:
        print("(dry-run mode -- nothing was written)")
    print(f"Progress file: {pf}")
    print(f"{'=' * 60}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
