"""Generate commits.txt file from git history.

Creates a commit target list file ("commits.txt") with useful descriptors:
- commit hash
- author date (ISO-ish)
- subject
- changed files count
- insertions, deletions (from --shortstat)

Default Output format (TSV, comment header):
  <hash>\t<date>\t<files>\t<ins>\t<del>\t<subject>

Hash-only Output format (for scripts that expect one hash per line):
  <hash>

Usage examples:
    # TSV format (default) - full commit metadata
    python -m ta_lab2.tools.data_tools.generators.generate_commits_txt \\
        --repo "C:\\Users\\asafi\\Downloads\\ta_lab2" \\
        --out "commits.txt" \\
        --max 500

    # Hash-only format (recommended for generate_memories_from_diffs.py)
    python -m ta_lab2.tools.data_tools.generators.generate_commits_txt \\
        --repo "C:\\Users\\asafi\\Downloads\\ta_lab2" \\
        --out "commits.txt" \\
        --max 500 \\
        --hash-only

    # Filter by date range
    python -m ta_lab2.tools.data_tools.generators.generate_commits_txt \\
        --repo . \\
        --out commits.txt \\
        --since "2025-01-01" \\
        --until "2026-01-01"

    # Filter by path
    python -m ta_lab2.tools.data_tools.generators.generate_commits_txt \\
        --repo . \\
        --out commits.txt \\
        --path "src/ta_lab2"

    # Use as a library
    from ta_lab2.tools.data_tools.generators.generate_commits_txt import generate_commits_txt
    generate_commits_txt(
        repo=".",
        out_path="commits.txt",
        max_count=500,
        hash_only=False
    )

Notes:
- "size" of a commit isn't directly a git primitive, but insertions+deletions is the best proxy.
- Merge commits sometimes lack stats depending on repo settings; we handle missing as 0.
"""

from __future__ import annotations
import argparse
import datetime as dt
import os
import re
import subprocess
import logging
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Regex to parse git --shortstat output
SHORTSTAT_RE = re.compile(
    r"(?:(\d+)\s+files?\s+changed)?"
    r"(?:,\s+(\d+)\s+insertions?\(\+\))?"
    r"(?:,\s+(\d+)\s+deletions?\(-\))?",
    re.IGNORECASE,
)


def run_git(args: List[str], repo: str) -> str:
    """Run git command in specified repo directory.

    Args:
        args: Git command arguments (without 'git' prefix)
        repo: Repository path

    Returns:
        Git command stdout

    Raises:
        RuntimeError: If git command fails
    """
    p = subprocess.run(
        ["git"] + args,
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed:\n{p.stderr.strip()}")
    return p.stdout


def parse_shortstat(shortstat_line: str) -> Tuple[int, int, int]:
    """Parse git --shortstat output line.

    Parse: ' 3 files changed, 120 insertions(+), 55 deletions(-)'
    Return (files, insertions, deletions). Missing parts -> 0.

    Args:
        shortstat_line: Output from git log --shortstat

    Returns:
        Tuple of (files_changed, insertions, deletions)
    """
    m = SHORTSTAT_RE.search(shortstat_line.strip())
    if not m:
        return 0, 0, 0
    files = int(m.group(1) or 0)
    ins = int(m.group(2) or 0)
    dele = int(m.group(3) or 0)
    return files, ins, dele


def build_git_log_cmd(
    max_count: int,
    since: Optional[str],
    until: Optional[str],
    path: Optional[str],
    include_merges: bool,
) -> List[str]:
    """Build git log command with filters.

    We use a record separator (\\x1e) between commits and field separator (\\x1f) within a record.
    Then append --shortstat lines after each commit.

    Args:
        max_count: Maximum number of commits to fetch
        since: Git date filter (e.g. "2025-01-01" or "2 weeks ago")
        until: Git date filter (e.g. "2026-01-21" or "now")
        path: Limit to commits touching this path
        include_merges: Whether to include merge commits

    Returns:
        Git command arguments list
    """
    fmt = "%H%x1f%aI%x1f%s%x1e"
    cmd = ["log", f"--max-count={max_count}", f"--pretty=format:{fmt}", "--shortstat"]
    if not include_merges:
        cmd.append("--no-merges")
    if since:
        cmd.append(f"--since={since}")
    if until:
        cmd.append(f"--until={until}")
    if path:
        cmd += ["--", path]
    return cmd


def _extract_shortstat_from_lines(lines: List[str]) -> Tuple[int, int, int]:
    """Extract shortstat from git log output lines.

    Look through git log --shortstat lines and pick the first line that yields any signal.
    Some commits (merges) may not have stats; returns (0,0,0).

    Args:
        lines: Lines from git log output

    Returns:
        Tuple of (files_changed, insertions, deletions)
    """
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        # Try parsing regardless of whether "files changed" literal appears.
        files_changed, insertions, deletions = parse_shortstat(s)
        if files_changed or insertions or deletions:
            return files_changed, insertions, deletions

        # If regex matches but all groups are empty (rare), ignore.
        # If a repo emits variants, you can expand here.
    return 0, 0, 0


def generate_commits_txt(
    repo: str,
    out_path: str,
    max_count: int = 2000,
    since: Optional[str] = None,
    until: Optional[str] = None,
    path: Optional[str] = None,
    include_merges: bool = False,
    hash_only: bool = False,
) -> int:
    """Generate commits.txt file from git history.

    Args:
        repo: Path to git repository
        out_path: Output commits.txt path
        max_count: Maximum number of commits to include
        since: Git date filter (e.g. "2025-01-01" or "2 weeks ago")
        until: Git date filter (e.g. "2026-01-21" or "now")
        path: Limit to commits touching this path (e.g. "src/ta_lab2")
        include_merges: Include merge commits (default: false)
        hash_only: Write only commit hashes (one per line), recommended for read_lines() consumers

    Returns:
        Number of commits written
    """
    cmd = build_git_log_cmd(max_count, since, until, path, include_merges)
    raw = run_git(cmd, repo)

    records = [r for r in raw.split("\x1e") if r.strip()]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if hash_only:
        header = [
            "# commits.txt (hash-only)",
            f"# generated_at_utc: {dt.datetime.now(dt.timezone.utc).isoformat()}",
            f"# repo: {os.path.abspath(repo)}",
            f"# filters: max={max_count}"
            + (f", since={since}" if since else "")
            + (f", until={until}" if until else "")
            + (f", path={path}" if path else "")
            + (", include_merges=true" if include_merges else ", include_merges=false"),
            "# columns: hash",
            "",
        ]
    else:
        header = [
            "# commits.txt (TSV)",
            f"# generated_at_utc: {dt.datetime.now(dt.timezone.utc).isoformat()}",
            f"# repo: {os.path.abspath(repo)}",
            f"# filters: max={max_count}"
            + (f", since={since}" if since else "")
            + (f", until={until}" if until else "")
            + (f", path={path}" if path else "")
            + (", include_merges=true" if include_merges else ", include_merges=false"),
            "# columns: hash\tdate\tfiles_changed\tinsertions\tdeletions\tsubject",
            "",
        ]

    lines_out: List[str] = []
    for rec in records:
        parts = rec.splitlines()
        if not parts:
            continue

        meta = parts[0].split("\x1f")
        if len(meta) < 3:
            continue
        commit_hash, author_date, subject = meta[0].strip(), meta[1].strip(), meta[2].strip()

        if hash_only:
            lines_out.append(commit_hash)
            continue

        files_changed, insertions, deletions = _extract_shortstat_from_lines(parts[1:])

        lines_out.append(
            f"{commit_hash}\t{author_date}\t{files_changed}\t{insertions}\t{deletions}\t{subject}"
        )

    with out.open("w", encoding="utf-8") as f:
        f.write("\n".join(header))
        f.write("\n".join(lines_out))
        f.write("\n")

    logger.info(f"Wrote {len(lines_out)} commits to: {out}")
    return len(lines_out)


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    ap = argparse.ArgumentParser(description="Generate commits.txt with commit descriptors.")
    ap.add_argument("--repo", required=True, help="Path to git repo")
    ap.add_argument("--out", required=True, help="Output commits.txt path")
    ap.add_argument("--max", type=int, default=2000, help="Max commits to include")
    ap.add_argument("--since", default=None, help='Git date, e.g. "2025-01-01" or "2 weeks ago"')
    ap.add_argument("--until", default=None, help='Git date, e.g. "2026-01-21" or "now"')
    ap.add_argument("--path", default=None, help="Limit to commits touching this path (e.g. src/ta_lab2)")
    ap.add_argument("--include-merges", action="store_true", help="Include merge commits (default: false)")
    ap.add_argument(
        "--hash-only",
        action="store_true",
        help="Write only commit hashes (one per line). Recommended for read_lines()-style consumers.",
    )
    args = ap.parse_args()

    count = generate_commits_txt(
        repo=args.repo,
        out_path=args.out,
        max_count=args.max,
        since=args.since,
        until=args.until,
        path=args.path,
        include_merges=args.include_merges,
        hash_only=args.hash_only,
    )

    print(f"Wrote {count} commits to: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
