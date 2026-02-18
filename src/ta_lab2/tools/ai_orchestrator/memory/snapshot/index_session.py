"""Index a single Claude Code session transcript into Qdrant via Mem0.

Designed to be called from a Claude Code SessionEnd hook to stream
conversations into memory automatically after each session.

Usage:
    python -m ta_lab2.tools.ai_orchestrator.memory.snapshot.index_session \
        --session-file <path-to-session.jsonl>

    Or via hook (reads session_id from stdin JSON):
    echo '{"session_id":"abc123","transcript_path":"/path/to/session.jsonl"}' | \
        python -m ta_lab2.tools.ai_orchestrator.memory.snapshot.index_session --from-hook
"""
import json
import sys
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from git import Repo

from ta_lab2.tools.ai_orchestrator.memory.snapshot.extract_conversations import (
    extract_conversation,
    extract_phase_boundaries,
    link_conversations_to_phases,
)
from ta_lab2.tools.ai_orchestrator.memory.snapshot.batch_indexer import (
    batch_add_memories,
)
from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
from ta_lab2.tools.ai_orchestrator.memory.metadata import create_metadata

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

PLANNING_DIR = Path("C:/Users/asafi/Downloads/ta_lab2/.planning")
REPO_PATH = Path("C:/Users/asafi/Downloads/ta_lab2")

# Phase-to-milestone mapping
PHASE_MILESTONE_MAP = {
    range(1, 11): "v0.4.0",
    range(11, 20): "v0.5.0",
    range(20, 27): "v0.6.0",
    range(27, 100): "v0.7.0",
}


def get_milestone_for_phase(phase_num: int) -> str:
    """Return the milestone version for a given phase number."""
    for phase_range, milestone in PHASE_MILESTONE_MAP.items():
        if phase_num in phase_range:
            return milestone
    return "unknown"


def index_session(session_file: Path, dry_run: bool = False) -> dict:
    """Index a single session transcript into Qdrant.

    Args:
        session_file: Path to .jsonl transcript file
        dry_run: If True, show what would be indexed without writing

    Returns:
        Stats dict with indexed count and errors
    """
    if not session_file.exists():
        logger.error(f"Session file not found: {session_file}")
        return {"error": "file not found"}

    logger.info(f"Indexing session: {session_file.name}")

    # Extract messages
    messages = extract_conversation(session_file)
    if not messages:
        logger.info("No messages found in session")
        return {"indexed": 0, "errors": 0}

    logger.info(f"Extracted {len(messages)} messages")

    # Get phase boundaries
    try:
        repo = Repo(REPO_PATH)
        phase_boundaries = extract_phase_boundaries(PLANNING_DIR, repo)
    except Exception as e:
        logger.error(f"Failed to get phase boundaries: {e}")
        phase_boundaries = {}

    # Link conversations to phases
    conversations_by_phase = link_conversations_to_phases(messages, phase_boundaries)

    # Get commits for linking
    def get_commits_in_window(timestamp_str: str, window_hours: int = 24) -> list[str]:
        """Get commit hashes within window after a timestamp."""
        try:
            ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            commits = []
            for c in repo.iter_commits(
                since=ts, until=ts + timedelta(hours=window_hours), all=True
            ):
                commits.append(c.hexsha[:7])
            return commits
        except Exception:
            return []

    memories_to_add = []

    for phase_num, phase_msgs in conversations_by_phase.items():
        if phase_num == "untracked" or not phase_msgs:
            continue

        phase_info = phase_boundaries.get(phase_num, {})
        milestone = get_milestone_for_phase(phase_num)

        # Filter to significant messages (skip short ones)
        significant = [
            m
            for m in phase_msgs
            if m.get("content")
            and len(m["content"].strip()) >= 20
            and m.get("role") in ("user", "assistant")
        ]

        # Limit per phase
        if len(significant) > 10:
            significant.sort(key=lambda m: m.get("timestamp", ""), reverse=True)
            significant = significant[:10]

        for msg in significant:
            timestamp_str = msg.get("timestamp", "")
            linked_commits = (
                get_commits_in_window(timestamp_str) if timestamp_str else []
            )

            # Format content
            try:
                dt = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except (ValueError, AttributeError):
                date_str = timestamp_str

            content_lines = [
                f"Phase {phase_num} Conversation - {date_str}",
                f"Role: {msg['role']}",
                "",
                f"Content: {msg['content'][:500]}",
            ]
            if linked_commits:
                content_lines.append("")
                content_lines.append(f"Resulting commits: {', '.join(linked_commits)}")

            content = "\n".join(content_lines)

            metadata = create_metadata(
                source=f"conversation_history_{milestone}",
                category="development_context",
            )
            metadata.update(
                {
                    "milestone": milestone,
                    "phase": f"phase_{phase_num}",
                    "phase_name": phase_info.get("name", "unknown"),
                    "role": msg["role"],
                    "timestamp": timestamp_str,
                    "linked_commits": linked_commits,
                    "has_code_links": len(linked_commits) > 0,
                    "session_file": session_file.name,
                }
            )
            if "tags" not in metadata:
                metadata["tags"] = []
            metadata["tags"].extend(["conversation", f"phase_{phase_num}", milestone])

            memories_to_add.append({"content": content, "metadata": metadata})

    if not memories_to_add:
        logger.info("No significant conversations to index")
        return {"indexed": 0, "errors": 0}

    if dry_run:
        logger.info(f"Dry run: would index {len(memories_to_add)} memories")
        return {"indexed": 0, "would_index": len(memories_to_add), "errors": 0}

    # Index via Mem0
    client = get_mem0_client()
    result = batch_add_memories(
        client, memories_to_add, batch_size=50, delay_seconds=0.5
    )
    logger.info(str(result))

    return {"indexed": len(memories_to_add), "errors": 0}


def main():
    parser = argparse.ArgumentParser(
        description="Index a Claude Code session into Qdrant"
    )
    parser.add_argument("--session-file", type=str, help="Path to session .jsonl file")
    parser.add_argument(
        "--from-hook",
        action="store_true",
        help="Read session info from stdin (Claude Code hook mode)",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be indexed"
    )
    args = parser.parse_args()

    session_file = None

    if args.from_hook:
        # Read hook input from stdin
        try:
            hook_input = json.loads(sys.stdin.read())
            transcript_path = hook_input.get("transcript_path")
            if transcript_path:
                session_file = Path(transcript_path)
            else:
                logger.error("No transcript_path in hook input")
                return 1
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Failed to parse hook input: {e}")
            return 1
    elif args.session_file:
        session_file = Path(args.session_file)
    else:
        parser.error("Either --session-file or --from-hook is required")

    stats = index_session(session_file, dry_run=args.dry_run)

    if "error" in stats:
        logger.error(f"Failed: {stats['error']}")
        return 1

    print(f"Indexed: {stats.get('indexed', 0)} memories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
