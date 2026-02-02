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

                    # Extract user messages (format: type="user", message.content)
                    if entry.get("type") == "user":
                        message_obj = entry.get("message", {})
                        content = message_obj.get("content", "")
                        # Handle string content or list content
                        if isinstance(content, list):
                            # Extract text from content blocks
                            content = " ".join([
                                block.get("text", "") if isinstance(block, dict) else str(block)
                                for block in content
                            ])
                        messages.append({
                            "role": "user",
                            "content": content,
                            "timestamp": entry.get("timestamp"),
                            "message_id": entry.get("uuid")
                        })

                    # Extract assistant messages (format: type="assistant", message.content)
                    elif entry.get("type") == "assistant":
                        message_obj = entry.get("message", {})
                        content = message_obj.get("content", [])
                        # Extract text from content blocks (skip thinking blocks)
                        text_parts = []
                        if isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict):
                                    if block.get("type") == "text":
                                        text_parts.append(block.get("text", ""))
                                    elif block.get("type") == "thinking":
                                        # Skip thinking blocks for now
                                        pass
                                else:
                                    text_parts.append(str(block))
                        else:
                            text_parts.append(str(content))

                        content_str = " ".join(text_parts)
                        if content_str:
                            messages.append({
                                "role": "assistant",
                                "content": content_str,
                                "timestamp": entry.get("timestamp"),
                                "message_id": entry.get("uuid")
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

                        # Same extraction logic as above
                        if entry.get("type") == "user":
                            message_obj = entry.get("message", {})
                            content = message_obj.get("content", "")
                            if isinstance(content, list):
                                content = " ".join([
                                    block.get("text", "") if isinstance(block, dict) else str(block)
                                    for block in content
                                ])
                            messages.append({
                                "role": "user",
                                "content": content,
                                "timestamp": entry.get("timestamp"),
                                "message_id": entry.get("uuid")
                            })
                        elif entry.get("type") == "assistant":
                            message_obj = entry.get("message", {})
                            content = message_obj.get("content", [])
                            text_parts = []
                            if isinstance(content, list):
                                for block in content:
                                    if isinstance(block, dict) and block.get("type") == "text":
                                        text_parts.append(block.get("text", ""))
                            content_str = " ".join(text_parts)
                            if content_str:
                                messages.append({
                                    "role": "assistant",
                                    "content": content_str,
                                    "timestamp": entry.get("timestamp"),
                                    "message_id": entry.get("uuid")
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

        # Find ALL SUMMARY.md files (format: NN-NN-SUMMARY.md)
        summary_files = sorted(phase_dir.glob("*-SUMMARY.md"))

        if not summary_files:
            logger.debug(f"No SUMMARY.md found for phase {phase_num}, skipping")
            continue

        # Get commits for ALL summary files to find phase start/end
        all_commit_times = []
        summary_file_list = []

        for summary_path in summary_files:
            try:
                # Get git commits for this summary file
                commits = list(repo.iter_commits(paths=str(summary_path), all=True))

                if commits:
                    # Add all commit times from this file
                    all_commit_times.extend([c.committed_datetime for c in commits])
                    summary_file_list.append(str(summary_path))

            except Exception as e:
                logger.warning(f"Failed to extract git metadata for {summary_path}: {e}")
                continue

        if not all_commit_times:
            logger.warning(f"No git commits found for any SUMMARY files in phase {phase_num}")
            continue

        # Phase start = earliest commit across all SUMMARY files
        start_date = min(all_commit_times)

        # Phase end = latest commit across all SUMMARY files
        end_date = max(all_commit_times)

        phases[phase_num] = {
            "name": phase_name,
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "summary_file": summary_file_list[0] if summary_file_list else "unknown",
            "summary_files": summary_file_list,
            "commits": len(all_commit_times)
        }

        logger.debug(
            f"Phase {phase_num}: {len(summary_file_list)} SUMMARY files, "
            f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        )

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
