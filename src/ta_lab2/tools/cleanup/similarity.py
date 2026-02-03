"""Function similarity detection via AST comparison.

Provides tools for finding similar Python functions across the codebase
using AST parsing and text-based similarity scoring.

Example:
    >>> from ta_lab2.tools.cleanup import find_similar_functions
    >>> similar = find_similar_functions(Path("src"), threshold=0.85)
    >>> print(f"Found {len(similar)} similar function pairs")
"""
import ast
from pathlib import Path
from difflib import SequenceMatcher
from dataclasses import dataclass, field
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Directories to exclude from scanning
EXCLUDE_DIRS = {".git", ".venv", ".venv311", "__pycache__", ".pytest_cache", ".archive"}


@dataclass
class FunctionInfo:
    """Information about a parsed function."""
    file: Path
    name: str
    lineno: int
    code: str  # Unparsed AST (normalized)
    docstring: Optional[str] = None
    arg_count: int = 0

    @property
    def location(self) -> str:
        return f"{self.file}:{self.name}:{self.lineno}"


@dataclass
class SimilarityMatch:
    """A pair of similar functions."""
    func1: FunctionInfo
    func2: FunctionInfo
    similarity: float
    tier: str  # "near_exact", "similar", "related"

    def __str__(self) -> str:
        return f"{self.func1.location} <-> {self.func2.location} ({self.similarity:.1%} {self.tier})"

    def to_dict(self) -> dict:
        return {
            "func1": {
                "file": str(self.func1.file),
                "name": self.func1.name,
                "lineno": self.func1.lineno,
                "arg_count": self.func1.arg_count,
            },
            "func2": {
                "file": str(self.func2.file),
                "name": self.func2.name,
                "lineno": self.func2.lineno,
                "arg_count": self.func2.arg_count,
            },
            "similarity": self.similarity,
            "tier": self.tier,
        }


def extract_functions(file_path: Path) -> list[FunctionInfo]:
    """Extract all function definitions from a Python file.

    Args:
        file_path: Path to Python file

    Returns:
        List of FunctionInfo for each function in the file
    """
    functions = []

    try:
        code = file_path.read_text(encoding="utf-8")
        tree = ast.parse(code, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError) as e:
        logger.debug(f"Skipping {file_path}: {e}")
        return []

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            try:
                # Save metadata
                name = node.name
                lineno = node.lineno
                arg_count = len(node.args.args)
                docstring = ast.get_docstring(node)

                # Unparse to code string (no normalization needed - unparsed code is already normalized)
                unparsed = ast.unparse(node)

                functions.append(FunctionInfo(
                    file=file_path,
                    name=name,
                    lineno=lineno,
                    code=unparsed,
                    docstring=docstring,
                    arg_count=arg_count
                ))
            except Exception as e:
                logger.debug(f"Error processing {node.name} in {file_path}: {e}")
                continue

    return functions


def normalize_ast(node: ast.AST) -> ast.AST:
    """Normalize AST by removing location information.

    This allows comparing functions regardless of where they appear in files.

    Note: This function is kept for potential future use but is not currently used
    since ast.unparse() already produces normalized output.
    """
    for child in ast.walk(node):
        for attr in ("lineno", "col_offset", "end_lineno", "end_col_offset"):
            if hasattr(child, attr):
                delattr(child, attr)
    return node


def compare_functions(func1: FunctionInfo, func2: FunctionInfo) -> float:
    """Compare two functions and return similarity score 0.0-1.0."""
    # Use SequenceMatcher on normalized code
    return SequenceMatcher(None, func1.code, func2.code).ratio()


def classify_similarity(score: float) -> str:
    """Classify similarity score into tier."""
    if score >= 0.95:
        return "near_exact"
    elif score >= 0.85:
        return "similar"
    elif score >= 0.70:
        return "related"
    else:
        return "different"


def find_similar_functions(
    root: Path,
    pattern: str = "**/*.py",
    threshold: float = 0.70,
    exclude_dirs: set[str] | None = None,
    min_lines: int = 5,
) -> list[SimilarityMatch]:
    """Find similar functions across Python files.

    Args:
        root: Root directory to scan
        pattern: Glob pattern for Python files
        threshold: Minimum similarity score (0.0-1.0)
        exclude_dirs: Directory names to exclude
        min_lines: Minimum function lines to consider (skip trivial functions)

    Returns:
        List of SimilarityMatch objects for similar function pairs
    """
    exclude = exclude_dirs or EXCLUDE_DIRS
    all_functions: list[FunctionInfo] = []

    # Collect all functions
    for file_path in root.glob(pattern):
        if not file_path.is_file():
            continue
        if any(part in exclude for part in file_path.parts):
            continue

        functions = extract_functions(file_path)

        # Filter by minimum lines
        for func in functions:
            if func.code.count("\n") >= min_lines - 1:  # -1 because single line has 0 newlines
                all_functions.append(func)

    logger.info(f"Extracted {len(all_functions)} functions from {root}")

    # Compare all pairs (O(n^2) but acceptable for typical codebase size)
    matches: list[SimilarityMatch] = []

    for i, func1 in enumerate(all_functions):
        for func2 in all_functions[i + 1:]:
            # Skip same file same name (likely same function)
            if func1.file == func2.file and func1.name == func2.name:
                continue

            # Quick filter: skip if arg counts differ significantly
            if abs(func1.arg_count - func2.arg_count) > 3:
                continue

            similarity = compare_functions(func1, func2)

            if similarity >= threshold:
                tier = classify_similarity(similarity)
                matches.append(SimilarityMatch(
                    func1=func1,
                    func2=func2,
                    similarity=similarity,
                    tier=tier
                ))

    # Sort by similarity (highest first)
    matches.sort(key=lambda m: m.similarity, reverse=True)

    return matches


def generate_similarity_report(matches: list[SimilarityMatch]) -> dict:
    """Generate JSON-serializable similarity report.

    Returns:
        Report dict with summary and matches categorized by tier
    """
    report = {
        "$schema": "https://ta_lab2.local/schemas/similarity-report/v1.0.0",
        "version": "1.0.0",
        "summary": {
            "total_matches": len(matches),
            "near_exact": len([m for m in matches if m.tier == "near_exact"]),
            "similar": len([m for m in matches if m.tier == "similar"]),
            "related": len([m for m in matches if m.tier == "related"]),
        },
        "near_exact": [],  # 95%+ similarity
        "similar": [],     # 85-95% similarity
        "related": [],     # 70-85% similarity
    }

    for match in matches:
        report[match.tier].append(match.to_dict())

    return report
