"""Shared AST helper functions for code analysis tools.

Provides common utilities for AST parsing, function signature extraction,
file iteration, and code analysis used across the analysis module.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple


# Default directories/patterns to exclude from scans
DEFAULT_EXCLUDE_GLOBS: List[str] = [
    ".git/**",
    "**/.git/**",
    ".archive/**",
    "**/.archive/**",
    "old/**",
    "**/old/**",
    ".venv/**",
    ".venv311/**",
    "venv/**",
    "env/**",
    "build/**",
    "dist/**",
    ".eggs/**",
    "**/site-packages/**",
    ".mypy_cache/**",
    "**/.mypy_cache/**",
    "tests/**",
]

# Directories to ignore in tree traversal
IGNORE_DIRS = {".venv", ".venv311", ".git", "old", ".archive", ".mypy_cache"}


# ---------- AST node utilities ----------


def _safe_unparse(node: Optional[ast.AST]) -> str:
    """Safely unparse an AST node to string, returning empty string on failure."""
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _ann_to_str(node: Optional[ast.expr]) -> str:
    """Convert type annotation AST node to string."""
    return _safe_unparse(node) if node is not None else ""


def _get_dec_name(d: ast.expr) -> str:
    """Extract decorator name from AST expression.

    Handles Name, Attribute, and Call decorator forms.
    """
    if isinstance(d, ast.Name):
        return d.id
    if isinstance(d, ast.Attribute):
        parts: list[str] = []
        cur: ast.expr = d
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    if isinstance(d, ast.Call):
        base = _get_dec_name(d.func)
        return f"{base}(...)"
    return _safe_unparse(d)


def _arglist_sig(args: ast.arguments) -> Tuple[str, str, str, str, str]:
    """Extract function argument signature components.

    Returns:
        (positional, kwonly, vararg, kwarg, defaults) as CSV-friendly strings.
    """

    def arg_str(a: ast.arg) -> str:
        ann = _ann_to_str(a.annotation)
        return f"{a.arg}: {ann}" if ann else a.arg

    pos = [arg_str(a) for a in args.posonlyargs + args.args]
    kwonly = [arg_str(a) for a in args.kwonlyargs]
    vararg = arg_str(args.vararg) if args.vararg else ""
    kwarg = arg_str(args.kwarg) if args.kwarg else ""

    defaults: list[str] = []
    all_pos = args.posonlyargs + args.args
    pad = len(all_pos) - len(args.defaults)
    pos_defaults = [""] * pad + [_safe_unparse(d) for d in args.defaults]
    for name, val in zip([a.arg for a in all_pos], pos_defaults):
        if val != "":
            defaults.append(f"{name}={val}")

    kw_defaults = [
        (_safe_unparse(d) if d is not None else "") for d in args.kw_defaults
    ]
    for name, val in zip([a.arg for a in args.kwonlyargs], kw_defaults):
        if val != "":
            defaults.append(f"{name}={val}")

    return (", ".join(pos), ", ".join(kwonly), vararg, kwarg, ", ".join(defaults))


def _param_list_from_funcdef(fn: ast.FunctionDef) -> str:
    """Build a simple parameter list string from AST (names only).

    Returns signature like ``(arg1, arg2, *args, **kwargs)``.
    """
    a = fn.args
    parts: list[str] = []

    if getattr(a, "posonlyargs", []):
        parts += [p.arg for p in a.posonlyargs]
        parts.append("/")

    parts += [p.arg for p in a.args]

    if a.vararg:
        parts.append("*" + a.vararg.arg)
    elif a.kwonlyargs:
        parts.append("*")

    parts += [p.arg for p in a.kwonlyargs]

    if a.kwarg:
        parts.append("**" + a.kwarg.arg)

    while parts and parts[-1] in {"/", "*"}:
        parts.pop()

    return "(" + ", ".join(parts) + ")"


def _qualname(stack: List[str], name: str) -> str:
    """Build qualified name from class stack and function name."""
    return ".".join([*stack, name]) if stack else name


def _method_kind(decorators: List[str]) -> str:
    """Determine method type from decorators."""
    if "staticmethod" in decorators:
        return "staticmethod"
    if "classmethod" in decorators:
        return "classmethod"
    if "property" in decorators:
        return "property"
    return "method"


def _first_line(doc: Optional[str], max_chars: int = 300) -> str:
    """Extract first line of docstring, truncated to max_chars."""
    if not doc:
        return ""
    s = doc.strip().splitlines()[0].strip()
    return s[:max_chars]


def _first_sentence(text: str, max_chars: int = 280) -> str:
    """Extract first sentence from text, up to max_chars."""
    s = " ".join(text.strip().split())
    for sep in [". ", ".\n", "! ", "? "]:
        idx = s.find(sep)
        if 0 <= idx <= max_chars:
            return s[: idx + len(sep)].strip()
    return s[:max_chars].strip()


# ---------- AST tree annotation ----------


def attach_parents(tree: ast.AST) -> None:
    """Attach parent_chain attribute to all nodes in AST."""

    def _walk(node: ast.AST, parents: List[ast.AST]) -> None:
        for child in ast.iter_child_nodes(node):
            child.parent_chain = parents[:]  # type: ignore[attr-defined]
            _walk(child, parents + [node])

    tree.parent_chain = []  # type: ignore[attr-defined]
    _walk(tree, [])


# ---------- Call collector ----------


class CallCollector(ast.NodeVisitor):
    """AST visitor to collect all function/method calls within a node."""

    def __init__(self) -> None:
        self.calls: Set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        try:
            name = _safe_unparse(node.func)
            if name:
                self.calls.add(name)
        except Exception:
            pass
        self.generic_visit(node)


# ---------- File iteration ----------


def _glob_to_regex(pattern: str) -> str:
    """Convert a glob pattern to a regex, handling ``**`` correctly.

    ``**`` matches any number of path segments (including zero).
    ``*`` matches anything except ``/``.
    ``?`` matches any single character except ``/``.
    """
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if i + 1 < len(pattern) and pattern[i + 1] == "*":
                # ** — match any path segments
                parts.append(".*")
                i += 2
                # Skip trailing /
                if i < len(pattern) and pattern[i] == "/":
                    i += 1
            else:
                # * — match within a single segment
                parts.append("[^/]*")
                i += 1
        elif c == "?":
            parts.append("[^/]")
            i += 1
        elif c == ".":
            parts.append(re.escape(c))
            i += 1
        else:
            parts.append(re.escape(c))
            i += 1
    return "^" + "".join(parts) + "$"


def iter_py_files(
    root: Path,
    include_globs: List[str],
    exclude_globs: List[str],
) -> Iterable[Path]:
    """Walk all ``*.py`` files under *root*, applying include/exclude globs.

    Handles ``**`` patterns correctly on both Windows and Unix by converting
    globs to regexes.
    """
    import re

    include_posix = [g.replace("\\", "/") for g in include_globs]
    exclude_posix = [g.replace("\\", "/") for g in exclude_globs]

    include_res = [re.compile(_glob_to_regex(g)) for g in include_posix]
    exclude_res = [re.compile(_glob_to_regex(g)) for g in exclude_posix]

    for p in root.rglob("*.py"):
        rel = p.relative_to(root)
        rel_posix = str(rel).replace(os.sep, "/")

        if any(r.match(rel_posix) for r in exclude_res):
            continue

        if include_res and not any(r.match(rel_posix) for r in include_res):
            continue

        yield p


def clip_text(body: str, max_chars: int = 12000) -> str:
    """Truncate text to *max_chars* with an ellipsis marker."""
    if len(body) <= max_chars:
        return body
    return body[:max_chars] + "\n... [truncated]"
