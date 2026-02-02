"""Claude Code conversation transcript extraction and phase boundary detection.

Provides JSONL parsing for Claude Code transcripts, phase boundary extraction
from git commit history, and conversation-to-phase linking for v0.4.0 context.
"""
import json
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Optional
from git import Repo

logger = logging.getLogger(__name__)


def extract_conversation(jsonl_path: Path) -> list[dict]:
    """Parse Claude Code JSONL transcript to extract conversation history.

    Reads line-by-line JSONL format, handling multiple message types
    (user-message, assistant-message, tool-use). Skips malformed entries.

    Args:
        jsonl_path: Path to Claude Code .jsonl transcript file

    Returns:
        List of message dicts with role, content, timestamp, message_id

    Example:
        >>> from pathlib import Path
        >>> messages = extract_conversation(Path("~/.claude/projects/session.jsonl"))
        >>> print(f"Found {len(messages)} messages")
        >>> for msg in messages[:3]:
        ...     print(f"{msg['role']}: {msg['content'][:50]}")
    """
    if not jsonl_path.exists():
        logger.warning(f"JSONL file not found: {jsonl_path}")
        return []

    messages = []
    line_num = 0

    try:
        with open(jsonl_path, 'r', encoding='utf-8') as f:
            for line in f:
                line_num += 1

                if not line.strip():
                    continue

                try:
                    entry = json.loads(line)

                    # Extract user messages
                    if entry.get("type") == "user-message":
                        messages.append({
                            "role": "user",
                            "content": entry.get("text", ""),
                            "timestamp": entry.get("timestamp"),
                            "message_id": entry.get("messageId")
                        })

                    # Extract assistant messages
                    elif entry.get("type") == "assistant-message":
                        messages.append({
                            "role": "assistant",
                            "content": entry.get("text", ""),
                            "timestamp": entry.get("timestamp"),
                            "message_id": entry.get("messageId")
                        })

                    # Extract tool usage
                    elif entry.get("type") == "tool-use":
                        messages.append({
                            "role": "tool",
                            "tool": entry.get("name"),
                            "input": entry.get("input", {}),
                            "timestamp": entry.get("timestamp")
                        })

                except json.JSONDecodeError as e:
                    logger.warning(f"Skipping malformed JSON at line {line_num} in {jsonl_path}: {e}")
                    continue
                except Exception as e:
                    logger.warning(f"Error parsing line {line_num} in {jsonl_path}: {e}")
                    continue

    except UnicodeDecodeError:
        # Try with fallback encoding
        logger.warning(f"UTF-8 decode failed for {jsonl_path}, trying latin-1")
        try:
            with open(jsonl_path, 'r', encoding='latin-1') as f:
                for line in f:
                    line_num += 1

                    if not line.strip():
                        continue

                    try:
                        entry = json.loads(line)

                        if entry.get("type") == "user-message":
                            messages.append({
                                "role": "user",
                                "content": entry.get("text", ""),
                                "timestamp": entry.get("timestamp"),
                                "message_id": entry.get("messageId")
                            })
                        elif entry.get("type") == "assistant-message":
                            messages.append({
                                "role": "assistant",
                                "content": entry.get("text", ""),
                                "timestamp": entry.get("timestamp"),
                                "message_id": entry.get("messageId")
                            })
                    except json.JSONDecodeError:
                        continue

        except Exception as e:
            logger.error(f"Failed to read {jsonl_path} with fallback encoding: {e}")
            return messages

    logger.info(f"Extracted {len(messages)} messages from {jsonl_path}")
    return messages


def extract_phase_boundaries(planning_dir: Path, repo: Optional[Repo] = None) -> dict[int, dict]:
    """Map phases to time ranges using SUMMARY.md files and git commits.

    Scans .planning/phases/ directories to find SUMMARY.md files, then uses
    git commit dates to determine phase start and end times.

    Args:
        planning_dir: Path to .planning directory
        repo: Optional git Repo instance (will auto-detect if None)

    Returns:
        Dict mapping phase_num -> {"name": str, "start": ISO, "end": ISO, "summary_file": str}

    Example:
        >>> from pathlib import Path
        >>> from git import Repo
        >>> repo = Repo(".")
        >>> boundaries = extract_phase_boundaries(Path(".planning"), repo)
        >>> for phase_num, info in boundaries.items():
        ...     print(f"Phase {phase_num}: {info['name']} ({info['start']} to {info['end']})")
    """
    phases_dir = planning_dir / "phases"

    if not phases_dir.exists():
        logger.warning(f"Phases directory not found: {phases_dir}")
        return {}

    # Auto-detect repo if not provided
    if repo is None:
        try:
            repo = Repo(planning_dir.parent)
        except Exception as e:
            logger.error(f"Failed to detect git repository: {e}")
            return {}

    phases = {}

    # Get all phase directories (format: NN-name)
    phase_dirs = sorted([
        d for d in phases_dir.iterdir()
        if d.is_dir() and d.name[0].isdigit()
    ])

    for phase_dir in phase_dirs:
        # Extract phase number and name
        phase_match = re.match(r'(\d+)-(.+)', phase_dir.name)
        if not phase_match:
            logger.warning(f"Skipping directory with unexpected name: {phase_dir.name}")
            continue

        phase_num = int(phase_match.group(1))
        phase_name = phase_match.group(2)

        # Find SUMMARY.md files (format: NN-NN-SUMMARY.md)
        summary_files = list(phase_dir.glob("*-SUMMARY.md"))

        if not summary_files:
            logger.debug(f"No SUMMARY.md found for phase {phase_num}, skipping")
            continue

        # Use first SUMMARY.md file
        summary_path = summary_files[0]

        try:
            # Get git commits for this summary file
            commits = list(repo.iter_commits(paths=str(summary_path), all=True))

            if not commits:
                logger.warning(f"No git commits found for {summary_path}")
                continue

            # Start date = first commit (oldest)
            start_date = commits[-1].committed_datetime

            # End date = last commit (newest)
            end_date = commits[0].committed_datetime

            phases[phase_num] = {
                "name": phase_name,
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "summary_file": str(summary_path),
                "commits": len(commits)
            }

        except Exception as e:
            logger.error(f"Failed to extract git metadata for {summary_path}: {e}")
            continue

    logger.info(f"Extracted {len(phases)} phase boundaries from {phases_dir}")
    return phases


def link_conversations_to_phases(
    messages: list[dict],
    phase_boundaries: dict[int, dict]
) -> dict[int, list[dict]]:
    """Group messages by phase using timestamp comparison.

    Assigns each message to a phase based on its timestamp falling within
    the phase's start/end dates. Messages outside all phases are assigned
    to "untracked" key.

    Args:
        messages: List of message dicts with timestamp field
        phase_boundaries: Dict from extract_phase_boundaries()

    Returns:
        Dict mapping phase_num -> [messages], with "untracked" key for unmatched messages

    Example:
        >>> messages = extract_conversation(Path("session.jsonl"))
        >>> boundaries = extract_phase_boundaries(Path(".planning"))
        >>> by_phase = link_conversations_to_phases(messages, boundaries)
        >>> print(f"Phase 1: {len(by_phase.get(1, []))} messages")
    """
    conversations_by_phase = {phase_num: [] for phase_num in phase_boundaries.keys()}
    conversations_by_phase["untracked"] = []

    for message in messages:
        timestamp = message.get("timestamp")

        if not timestamp:
            conversations_by_phase["untracked"].append(message)
            continue

        # Parse timestamp (ISO format expected)
        try:
            msg_datetime = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        except (ValueError, AttributeError) as e:
            logger.warning(f"Invalid timestamp format: {timestamp}, error: {e}")
            conversations_by_phase["untracked"].append(message)
            continue

        # Find matching phase
        matched = False
        for phase_num, phase_info in phase_boundaries.items():
            try:
                phase_start = datetime.fromisoformat(phase_info["start"].replace('Z', '+00:00'))
                phase_end = datetime.fromisoformat(phase_info["end"].replace('Z', '+00:00'))

                if phase_start <= msg_datetime <= phase_end:
                    conversations_by_phase[phase_num].append(message)
                    matched = True
                    break
            except (ValueError, KeyError) as e:
                logger.warning(f"Invalid phase boundary for phase {phase_num}: {e}")
                continue

        if not matched:
            conversations_by_phase["untracked"].append(message)

    # Log summary
    for phase_num, messages_list in conversations_by_phase.items():
        if messages_list:
            logger.info(f"Phase {phase_num}: {len(messages_list)} messages")

    return conversations_by_phase


def find_conversation_files(
    claude_projects_dir: Path,
    project_name: str
) -> list[Path]:
    """Find Claude Code conversation JSONL files for a project.

    Searches for project folder matching pattern (e.g., "C--Users-asafi-Downloads-ta-lab2")
    and returns all .jsonl files in that folder.

    Args:
        claude_projects_dir: Path to ~/.claude/projects/ directory
        project_name: Project name pattern to match (e.g., "ta-lab2" or full hash)

    Returns:
        List of Path objects to .jsonl files (empty list if not found)

    Example:
        >>> from pathlib import Path
        >>> files = find_conversation_files(
        ...     Path.home() / ".claude" / "projects",
        ...     "ta-lab2"
        ... )
        >>> print(f"Found {len(files)} conversation files")
    """
    if not claude_projects_dir.exists():
        logger.warning(f"Claude projects directory not found: {claude_projects_dir}")
        return []

    jsonl_files = []

    # Search for project directories containing the project name
    for project_dir in claude_projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        # Check if directory name contains project name pattern
        if project_name.lower() in project_dir.name.lower():
            # Find all .jsonl files in this directory
            jsonl_files.extend(project_dir.glob("*.jsonl"))

    if not jsonl_files:
        logger.warning(f"No .jsonl files found for project '{project_name}' in {claude_projects_dir}")
    else:
        logger.info(f"Found {len(jsonl_files)} conversation files for '{project_name}'")

    return sorted(jsonl_files)


__all__ = [
    "extract_conversation",
    "extract_phase_boundaries",
    "link_conversations_to_phases",
    "find_conversation_files"
]
