"""Conversation history snapshot with code change linking.

Extracts conversation history from Claude Code transcripts and indexes
in memory system with links to resulting code changes for full traceability.

This script:
1. Finds Claude Code JSONL transcripts
2. Extracts conversation messages
3. Links conversations to phases via timestamps
4. Links conversations to code changes via git commit correlation
5. Indexes key conversations in Mem0 with commit links
6. Saves manifest documenting phase boundaries and linkage stats
"""
import json
import logging
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from git import Repo

# Import snapshot infrastructure
from ta_lab2.tools.ai_orchestrator.memory.snapshot.extract_conversations import (
    extract_conversation,
    extract_phase_boundaries,
    link_conversations_to_phases,
    find_conversation_files,
)
from ta_lab2.tools.ai_orchestrator.memory.snapshot.batch_indexer import (
    batch_add_memories,
)
from ta_lab2.tools.ai_orchestrator.memory.mem0_client import get_mem0_client
from ta_lab2.tools.ai_orchestrator.memory.metadata import create_metadata

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Configuration
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
PROJECT_FOLDER = "C--Users-asafi-Downloads-ta-lab2"
PLANNING_DIR = Path("C:/Users/asafi/Downloads/ta_lab2/.planning")
REPO_PATH = Path("C:/Users/asafi/Downloads/ta_lab2")

# Phase-to-milestone mapping
PHASE_MILESTONE_MAP = {
    range(1, 11): "v0.4.0",
    range(11, 20): "v0.5.0",
    range(20, 27): "v0.6.0",
}


def get_milestone_for_phase(phase_num: int) -> str:
    """Return the milestone version for a given phase number."""
    for phase_range, milestone in PHASE_MILESTONE_MAP.items():
        if phase_num in phase_range:
            return milestone
    return "unknown"


def get_commits_in_timerange(repo: Repo, start: datetime, end: datetime) -> list[dict]:
    """Get commits within a time range with file change details.

    Uses GitPython to iterate commits between timestamps, extracting
    commit metadata and files changed for conversation-to-code linking.

    Args:
        repo: GitPython Repo instance
        start: Start datetime (inclusive)
        end: End datetime (inclusive)

    Returns:
        List of dicts with: hash, message, author, timestamp, files_changed

    Example:
        >>> from git import Repo
        >>> from datetime import datetime
        >>> repo = Repo(".")
        >>> start = datetime(2026, 1, 1)
        >>> end = datetime(2026, 1, 31)
        >>> commits = get_commits_in_timerange(repo, start, end)
        >>> print(f"Found {len(commits)} commits in January")
    """
    commits = []

    try:
        # Get all commits in the timerange
        all_commits = repo.iter_commits(since=start, until=end, all=True)

        for commit in all_commits:
            # Get files changed in this commit
            files_changed = []
            try:
                # Get diff with parent (or empty tree for first commit)
                if commit.parents:
                    diffs = commit.parents[0].diff(commit)
                else:
                    # First commit has no parent, use empty tree
                    diffs = commit.diff(None)

                files_changed = [d.a_path for d in diffs if d.a_path]
            except Exception as e:
                logger.warning(
                    f"Failed to get diff for commit {commit.hexsha[:7]}: {e}"
                )

            commits.append(
                {
                    "hash": commit.hexsha[:7],
                    "hash_full": commit.hexsha,
                    "message": commit.message.strip(),
                    "author": commit.author.name,
                    "timestamp": commit.committed_datetime,
                    "files_changed": files_changed,
                }
            )

    except Exception as e:
        logger.error(f"Failed to iterate commits: {e}")
        return []

    return commits


def link_conversation_to_commits(
    conversation_timestamp: datetime, phase_commits: list[dict], window_hours: int = 24
) -> list[str]:
    """Link conversation to resulting commits using temporal proximity.

    Heuristic: commits made 0-24 hours AFTER a conversation are likely
    related to that conversation (implementing discussed changes).

    Args:
        conversation_timestamp: When the conversation occurred
        phase_commits: All commits in the phase (from get_commits_in_timerange)
        window_hours: Time window after conversation to search (default: 24)

    Returns:
        List of commit hashes linked to this conversation

    Example:
        >>> from datetime import datetime
        >>> conv_time = datetime(2026, 1, 15, 10, 0, 0)
        >>> phase_commits = [{"hash": "abc1234", "timestamp": datetime(2026, 1, 15, 12, 0, 0)}]
        >>> linked = link_conversation_to_commits(conv_time, phase_commits, window_hours=24)
        >>> print(linked)
        ['abc1234']
    """
    linked_commits = []

    # Define time window
    window_start = conversation_timestamp
    window_end = conversation_timestamp + timedelta(hours=window_hours)

    for commit in phase_commits:
        commit_time = commit["timestamp"]

        # Check if commit is within window AFTER conversation
        if window_start <= commit_time <= window_end:
            linked_commits.append(commit["hash"])

    return linked_commits


def extract_conversation_summaries(
    messages: list[dict], max_per_phase: int = 10
) -> list[dict]:
    """Extract most significant conversations from message list.

    Filters to key conversations (not every message) by prioritizing:
    - User messages with questions or requests
    - Assistant messages with decisions or conclusions
    - Skip tool-use messages unless they show important operations

    Args:
        messages: All messages in phase
        max_per_phase: Maximum conversations to extract per phase (default: 10)

    Returns:
        List of conversation summary dicts with: role, content, timestamp, phase

    Example:
        >>> messages = [
        ...     {"role": "user", "content": "How should we implement EMA?", "timestamp": "2026-01-15T10:00:00Z"},
        ...     {"role": "assistant", "content": "We'll use...", "timestamp": "2026-01-15T10:01:00Z"}
        ... ]
        >>> summaries = extract_conversation_summaries(messages, max_per_phase=10)
        >>> print(len(summaries))
    """
    significant_messages = []

    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")

        # Skip empty content
        if not content or len(content.strip()) < 20:
            continue

        # Skip tool messages unless they show important operations
        if role == "tool":
            tool_name = msg.get("tool", "")
            # Include only important tool operations
            if tool_name not in ["Bash", "Write", "Edit"]:
                continue
            # For tool messages, create summary of operation
            content = f"Tool: {tool_name} - {str(msg.get('input', ''))[:200]}"

        # Include user messages (questions, requests)
        if role == "user":
            significant_messages.append(
                {
                    "role": role,
                    "content": content[:500],  # Truncate to 500 chars
                    "timestamp": msg.get("timestamp"),
                    "message_id": msg.get("message_id"),
                }
            )

        # Include assistant messages (responses, decisions)
        elif role == "assistant":
            significant_messages.append(
                {
                    "role": role,
                    "content": content[:500],  # Truncate to 500 chars
                    "timestamp": msg.get("timestamp"),
                    "message_id": msg.get("message_id"),
                }
            )

    # Limit to max_per_phase most recent
    if len(significant_messages) > max_per_phase:
        # Sort by timestamp (newest first)
        significant_messages.sort(key=lambda m: m.get("timestamp", ""), reverse=True)
        significant_messages = significant_messages[:max_per_phase]

    return significant_messages


def format_conversation_for_memory(
    conversation: dict, phase: int, linked_commits: list[str]
) -> str:
    """Format conversation into memory-suitable content with code links.

    Creates concise, searchable text (under 1000 chars) including:
    - Phase context
    - Conversation role and content
    - Linked commits (code changes resulting from this discussion)

    Args:
        conversation: Message dict with role, content, timestamp
        phase: Phase number
        linked_commits: List of commit hashes linked to this conversation

    Returns:
        Formatted string for memory content

    Example:
        >>> conv = {"role": "user", "content": "Implement EMA", "timestamp": "2026-01-15T10:00:00Z"}
        >>> content = format_conversation_for_memory(conv, phase=1, linked_commits=["abc1234"])
        >>> print(content)
    """
    role = conversation.get("role", "unknown")
    content = conversation.get("content", "")
    timestamp = conversation.get("timestamp", "")

    # Parse timestamp for readable date
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        date_str = dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        date_str = timestamp

    # Format content
    lines = [
        f"Phase {phase} Conversation - {date_str}",
        f"Role: {role}",
        "",
        f"Content: {content}",
    ]

    # Add linked commits if any
    if linked_commits:
        lines.append("")
        lines.append(f"Resulting commits: {', '.join(linked_commits)}")
        lines.append("(Code changes made after this conversation)")

    return "\n".join(lines)


def run_conversation_snapshot(
    repo_path: Path,
    dry_run: bool = False,
    max_per_phase: int = 10,
    skip_phases: Optional[set] = None,
) -> dict:
    """Execute conversation snapshot with code change linking.

    Main workflow:
    1. Find Claude Code JSONL transcripts
    2. Extract all messages
    3. Get phase boundaries from git
    4. Link conversations to phases
    5. Get commits per phase
    6. Link conversations to commits
    7. Extract conversation summaries
    8. Index in memory with commit links
    9. Save manifest

    Args:
        repo_path: Path to git repository
        dry_run: If True, show stats without indexing (default: False)
        max_per_phase: Max conversations per phase (default: 10)
        skip_phases: Set of phase numbers to skip (already indexed)

    Returns:
        Stats dict with: phases_processed, conversations_indexed,
                        conversations_with_code_links, phase_breakdown

    Example:
        >>> from pathlib import Path
        >>> stats = run_conversation_snapshot(Path("."), dry_run=True)
        >>> print(f"Would index {stats['conversations_indexed']} conversations")
    """
    if skip_phases is None:
        skip_phases = set()
    logger.info("Starting conversation snapshot extraction")
    logger.info(f"Dry run: {dry_run}, Max per phase: {max_per_phase}")

    # Initialize repo
    try:
        repo = Repo(repo_path)
        logger.info(f"Repository: {repo_path}")
    except Exception as e:
        logger.error(f"Failed to open repository: {e}")
        return {"error": str(e)}

    # Find conversation files
    logger.info(f"Searching for conversation files in {CLAUDE_PROJECTS_DIR}")
    conversation_files = find_conversation_files(CLAUDE_PROJECTS_DIR, PROJECT_FOLDER)

    if not conversation_files:
        logger.error("No conversation files found")
        return {"error": "No conversation files found"}

    logger.info(f"Found {len(conversation_files)} conversation files")

    # Extract all messages from all files
    all_messages = []
    for jsonl_file in conversation_files:
        logger.info(f"Extracting from: {jsonl_file.name}")
        messages = extract_conversation(jsonl_file)
        all_messages.extend(messages)
        logger.info(f"  Extracted {len(messages)} messages")

    logger.info(f"Total messages extracted: {len(all_messages)}")

    # Get phase boundaries
    logger.info("Extracting phase boundaries from git history")
    phase_boundaries = extract_phase_boundaries(PLANNING_DIR, repo)

    if not phase_boundaries:
        logger.error("No phase boundaries found")
        return {"error": "No phase boundaries found"}

    logger.info(f"Found {len(phase_boundaries)} phases")

    # Link conversations to phases
    logger.info("Linking conversations to phases")
    conversations_by_phase = link_conversations_to_phases(
        all_messages, phase_boundaries
    )

    # Process each phase
    stats = {
        "phases_processed": 0,
        "conversations_indexed": 0,
        "conversations_with_code_links": 0,
        "phase_breakdown": {},
    }

    memories_to_add = []

    for phase_num, phase_info in sorted(phase_boundaries.items()):
        if phase_num in skip_phases:
            logger.info(f"Phase {phase_num}: Skipping (already indexed)")
            continue

        phase_messages = conversations_by_phase.get(phase_num, [])

        if not phase_messages:
            logger.info(f"Phase {phase_num}: No conversations found")
            continue

        logger.info(
            f"Phase {phase_num} ({phase_info['name']}): {len(phase_messages)} messages"
        )

        # Get commits for this phase
        try:
            phase_start = datetime.fromisoformat(
                phase_info["start"].replace("Z", "+00:00")
            )
            phase_end = datetime.fromisoformat(phase_info["end"].replace("Z", "+00:00"))
            phase_commits = get_commits_in_timerange(repo, phase_start, phase_end)
            logger.info(f"  Found {len(phase_commits)} commits in phase timerange")
        except Exception as e:
            logger.error(f"  Failed to get commits for phase {phase_num}: {e}")
            phase_commits = []

        # Extract conversation summaries
        summaries = extract_conversation_summaries(
            phase_messages, max_per_phase=max_per_phase
        )
        logger.info(f"  Extracted {len(summaries)} significant conversations")

        # Link each conversation to commits
        conversations_with_links = 0

        for conv in summaries:
            timestamp_str = conv.get("timestamp")
            if not timestamp_str:
                linked_commits = []
            else:
                try:
                    conv_time = datetime.fromisoformat(
                        timestamp_str.replace("Z", "+00:00")
                    )
                    linked_commits = link_conversation_to_commits(
                        conv_time, phase_commits
                    )
                except (ValueError, AttributeError) as e:
                    logger.warning(f"  Invalid timestamp: {timestamp_str}, error: {e}")
                    linked_commits = []

            if linked_commits:
                conversations_with_links += 1

            # Format for memory
            content = format_conversation_for_memory(conv, phase_num, linked_commits)

            # Create metadata with dynamic milestone
            milestone = get_milestone_for_phase(phase_num)
            metadata = create_metadata(
                source=f"conversation_history_{milestone}",
                category="development_context",
            )
            metadata.update(
                {
                    "milestone": milestone,
                    "phase": f"phase_{phase_num}",
                    "phase_name": phase_info["name"],
                    "role": conv.get("role"),
                    "timestamp": timestamp_str,
                    "linked_commits": linked_commits,
                    "has_code_links": len(linked_commits) > 0,
                }
            )

            # Add tags
            if "tags" not in metadata:
                metadata["tags"] = []
            metadata["tags"].extend(["conversation", f"phase_{phase_num}", milestone])

            memories_to_add.append({"content": content, "metadata": metadata})

        # Update stats
        stats["phases_processed"] += 1
        stats["conversations_indexed"] += len(summaries)
        stats["conversations_with_code_links"] += conversations_with_links
        stats["phase_breakdown"][phase_num] = {
            "name": phase_info["name"],
            "conversations": len(summaries),
            "with_code_links": conversations_with_links,
            "commits_in_phase": len(phase_commits),
        }

        logger.info(
            f"  {conversations_with_links}/{len(summaries)} conversations linked to commits"
        )

    # Index memories
    if not dry_run and memories_to_add:
        logger.info(f"Indexing {len(memories_to_add)} conversation memories")
        client = get_mem0_client()
        result = batch_add_memories(
            client, memories_to_add, batch_size=50, delay_seconds=0.5
        )
        logger.info(str(result))
    else:
        logger.info(f"Dry run: would index {len(memories_to_add)} memories")

    return stats


def save_conversation_manifest(
    stats: dict, phase_boundaries: dict, output_path: Path
) -> None:
    """Save conversation snapshot manifest with phase boundaries and stats.

    Creates JSON manifest documenting:
    - Snapshot metadata (type, timestamp)
    - Phase boundaries with dates
    - Statistics (conversations indexed, code links)
    - Per-phase breakdown

    Args:
        stats: Stats dict from run_conversation_snapshot()
        phase_boundaries: Phase boundaries dict from extract_phase_boundaries()
        output_path: Where to save manifest JSON

    Example:
        >>> from pathlib import Path
        >>> stats = {"conversations_indexed": 50}
        >>> save_conversation_manifest(stats, {}, Path(".planning/snapshots/conv.json"))
    """
    manifest = {
        "snapshot_type": "conversation_history",
        "timestamp": datetime.now().isoformat(),
        "phases": [
            {
                "phase": phase_num,
                "name": info["name"],
                "start": info["start"],
                "end": info["end"],
                "summary_file": info["summary_file"],
            }
            for phase_num, info in sorted(phase_boundaries.items())
        ],
        "statistics": {
            "phases_processed": stats.get("phases_processed", 0),
            "conversations_indexed": stats.get("conversations_indexed", 0),
            "conversations_with_code_links": stats.get(
                "conversations_with_code_links", 0
            ),
            "code_link_percentage": (
                stats.get("conversations_with_code_links", 0)
                / stats.get("conversations_indexed", 1)
                * 100
                if stats.get("conversations_indexed", 0) > 0
                else 0
            ),
        },
        "phase_breakdown": stats.get("phase_breakdown", {}),
    }

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write manifest
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, default=str)

    logger.info(f"Manifest saved to: {output_path}")


def main():
    """CLI for conversation snapshot extraction."""
    parser = argparse.ArgumentParser(
        description="Extract conversation history with code change linking"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show stats without indexing memories"
    )
    parser.add_argument(
        "--max-per-phase",
        type=int,
        default=10,
        help="Maximum conversations to extract per phase (default: 10)",
    )
    parser.add_argument(
        "--skip-phases",
        type=str,
        default="",
        help="Comma-separated phase numbers to skip (e.g., '1,2,3,4,5,6,7,8,9,10')",
    )

    args = parser.parse_args()

    # Parse skip phases
    skip_phases = set()
    if args.skip_phases:
        skip_phases = {int(x.strip()) for x in args.skip_phases.split(",") if x.strip()}

    # Run snapshot
    stats = run_conversation_snapshot(
        repo_path=REPO_PATH,
        dry_run=args.dry_run,
        max_per_phase=args.max_per_phase,
        skip_phases=skip_phases,
    )

    # Check for errors
    if "error" in stats:
        logger.error(f"Snapshot failed: {stats['error']}")
        return 1

    # Print summary
    print("\n" + "=" * 60)
    print("CONVERSATION SNAPSHOT SUMMARY")
    print("=" * 60)
    print(f"Phases processed: {stats.get('phases_processed', 0)}")
    print(f"Conversations indexed: {stats.get('conversations_indexed', 0)}")
    print(
        f"Conversations with code links: {stats.get('conversations_with_code_links', 0)}"
    )

    link_pct = (
        stats.get("conversations_with_code_links", 0)
        / stats.get("conversations_indexed", 1)
        * 100
        if stats.get("conversations_indexed", 0) > 0
        else 0
    )
    print(f"Code link percentage: {link_pct:.1f}%")

    print("\nPhase breakdown:")
    for phase_num, breakdown in sorted(stats.get("phase_breakdown", {}).items()):
        print(
            f"  Phase {phase_num} ({breakdown['name']}): "
            f"{breakdown['conversations']} conversations, "
            f"{breakdown['with_code_links']} with code links"
        )

    # Save manifest (unless dry run)
    if not args.dry_run:
        manifest_path = (
            PLANNING_DIR
            / "phases"
            / "11-memory-preparation"
            / "snapshots"
            / "conversations_snapshot.json"
        )

        # Need phase boundaries for manifest
        try:
            repo = Repo(REPO_PATH)
            phase_boundaries = extract_phase_boundaries(PLANNING_DIR, repo)
            save_conversation_manifest(stats, phase_boundaries, manifest_path)
            print(f"\nManifest saved: {manifest_path}")
        except Exception as e:
            logger.error(f"Failed to save manifest: {e}")

    print("=" * 60)

    return 0


if __name__ == "__main__":
    exit(main())
