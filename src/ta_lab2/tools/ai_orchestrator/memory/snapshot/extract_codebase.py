"""AST-based Python file analysis and git metadata extraction.

Provides code structure extraction using Python's built-in AST module,
combined with GitPython for git metadata (commit hash, author, timestamps).
Supports full directory tree analysis with configurable exclusions.
"""
import ast
import logging
from pathlib import Path
from typing import Optional
from git import Repo, GitCommandError

logger = logging.getLogger(__name__)


def extract_code_structure(file_path: Path) -> dict:
    """Parse Python file using AST module to extract code structure.

    Extracts functions, classes, imports, and file metadata from a Python file.
    Uses Python's built-in ast module for reliable parsing.

    Args:
        file_path: Path to Python file to analyze

    Returns:
        Dict with file path, functions, classes, imports, line_count, size_bytes

    Example:
        >>> from pathlib import Path
        >>> result = extract_code_structure(Path("src/mymodule.py"))
        >>> print(f"Found {len(result['functions'])} functions")

    Raises:
        FileNotFoundError: If file doesn't exist
        SyntaxError: If file contains invalid Python syntax
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    try:
        # Read source code
        with open(file_path, 'r', encoding='utf-8') as f:
            source = f.read()
    except UnicodeDecodeError:
        # Try with fallback encoding
        logger.warning(f"UTF-8 decode failed for {file_path}, trying latin-1")
        with open(file_path, 'r', encoding='latin-1') as f:
            source = f.read()

    # Parse with AST
    try:
        tree = ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        logger.error(f"Syntax error parsing {file_path}: {e}")
        raise

    # Extract functions
    functions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            functions.append({
                "name": node.name,
                "line_start": node.lineno,
                "line_end": node.end_lineno if hasattr(node, 'end_lineno') else node.lineno,
                "args": [arg.arg for arg in node.args.args],
                "docstring": ast.get_docstring(node) or ""
            })

    # Extract classes
    classes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            methods = [m.name for m in node.body if isinstance(m, ast.FunctionDef)]
            classes.append({
                "name": node.name,
                "line_start": node.lineno,
                "methods": methods
            })

    # Extract imports
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.append({
                "module": None,
                "names": [alias.name for alias in node.names]
            })
        elif isinstance(node, ast.ImportFrom):
            imports.append({
                "module": node.module,
                "names": [alias.name for alias in node.names]
            })

    return {
        "file": str(file_path),
        "functions": functions,
        "classes": classes,
        "imports": imports,
        "line_count": len(source.splitlines()),
        "size_bytes": len(source.encode('utf-8'))
    }


def get_file_git_metadata(repo_path: Path, file_path: Path) -> dict:
    """Get git metadata for a file using GitPython.

    Extracts the latest commit affecting the file, including commit hash,
    author, timestamp, and message. Handles untracked files gracefully.

    Args:
        repo_path: Path to git repository root
        file_path: Path to file (can be absolute or relative to repo)

    Returns:
        Dict with commit_hash, author_name, author_email, committed_datetime, message.
        For untracked files, returns {"tracked": False, "commit_hash": "untracked"}

    Example:
        >>> from pathlib import Path
        >>> metadata = get_file_git_metadata(Path("."), Path("src/myfile.py"))
        >>> print(metadata["commit_hash"])
    """
    try:
        repo = Repo(repo_path)

        # Make file_path relative to repo if it's absolute
        if file_path.is_absolute():
            try:
                file_path = file_path.relative_to(repo_path)
            except ValueError:
                logger.warning(f"File {file_path} is outside repo {repo_path}")
                return {"tracked": False, "commit_hash": "untracked"}

        # Get latest commit affecting this file
        try:
            commits = list(repo.iter_commits(paths=str(file_path), max_count=1))
        except GitCommandError as e:
            logger.warning(f"Git error for {file_path}: {e}")
            return {"tracked": False, "commit_hash": "untracked"}

        if not commits:
            # File is not tracked or has no commits
            return {"tracked": False, "commit_hash": "untracked"}

        commit = commits[0]

        return {
            "tracked": True,
            "commit_hash": commit.hexsha[:7],  # 7-char short hash
            "commit_hash_full": commit.hexsha,
            "author_name": commit.author.name,
            "author_email": commit.author.email,
            "committed_datetime": commit.committed_datetime.isoformat(),
            "message": commit.message.strip()
        }

    except Exception as e:
        logger.error(f"Failed to get git metadata for {file_path}: {e}")
        return {"tracked": False, "commit_hash": "untracked", "error": str(e)}


def extract_directory_tree(
    root_path: Path,
    exclusions: Optional[list[str]] = None
) -> list[dict]:
    """Walk directory and extract code structure + git metadata for all Python files.

    Recursively processes all .py files in directory tree, skipping exclusions.
    For each file, combines AST analysis with git metadata.

    Args:
        root_path: Root directory to scan
        exclusions: List of directory/file patterns to skip (default: __pycache__, .venv, .git, .pyc)

    Returns:
        List of dicts, each containing file_info, code_structure, and git_metadata

    Example:
        >>> from pathlib import Path
        >>> results = extract_directory_tree(Path("src/ta_lab2"))
        >>> print(f"Analyzed {len(results)} Python files")
        >>> for result in results[:5]:
        ...     print(result["file"])
    """
    if exclusions is None:
        exclusions = [
            "__pycache__",
            ".venv",
            "venv",
            "env",
            ".git",
            ".pyc",
            "node_modules",
            ".pytest_cache",
            ".tox",
            "dist",
            "build",
            ".egg-info"
        ]

    results = []
    processed_count = 0
    skipped_count = 0

    logger.info(f"Scanning directory: {root_path}")

    # Determine repo root (walk up to find .git)
    repo_path = root_path
    while not (repo_path / ".git").exists():
        if repo_path.parent == repo_path:
            # Reached filesystem root without finding .git
            logger.warning(f"No git repository found for {root_path}")
            repo_path = None
            break
        repo_path = repo_path.parent

    # Walk directory tree
    for py_file in root_path.rglob("*.py"):
        # Check exclusions
        skip = False
        for exclusion in exclusions:
            if exclusion in py_file.parts or py_file.name.endswith(exclusion):
                skip = True
                break

        if skip:
            skipped_count += 1
            continue

        try:
            # Extract code structure
            code_structure = extract_code_structure(py_file)

            # Extract git metadata if repo found
            git_metadata = {}
            if repo_path:
                git_metadata = get_file_git_metadata(repo_path, py_file)

            # Combine results
            results.append({
                "file": str(py_file),
                "relative_path": str(py_file.relative_to(root_path)),
                "code_structure": code_structure,
                "git_metadata": git_metadata
            })

            processed_count += 1

            # Log progress
            if processed_count % 50 == 0:
                logger.info(f"Progress: {processed_count} files processed, {skipped_count} skipped")

        except SyntaxError as e:
            logger.warning(f"Skipping {py_file} due to syntax error: {e}")
            skipped_count += 1
        except UnicodeDecodeError as e:
            logger.warning(f"Skipping {py_file} due to encoding error: {e}")
            skipped_count += 1
        except Exception as e:
            logger.error(f"Failed to process {py_file}: {e}")
            skipped_count += 1

    logger.info(
        f"Directory scan complete: {processed_count} files processed, "
        f"{skipped_count} skipped"
    )

    return results


__all__ = [
    "extract_code_structure",
    "get_file_git_metadata",
    "extract_directory_tree"
]
