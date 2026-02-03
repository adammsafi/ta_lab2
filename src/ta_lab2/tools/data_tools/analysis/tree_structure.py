"""Directory tree structure generator.

Generates multiple output formats for repository structure analysis:
- structure.txt: Text tree representation
- structure.md: Markdown tree representation
- structure.json: Hierarchical JSON with metadata (name, type, path, size, mtime, children)
- structure.csv: Flat CSV with file info (path, name, type, size_bytes, mtime_iso)
- API_MAP.md: Classes and functions per file (AST-based, no imports required)

Usage:
    # Generate all structure files for current directory
    python -m ta_lab2.tools.data_tools.analysis.tree_structure

    # Generate for specific directory
    python -m ta_lab2.tools.data_tools.analysis.tree_structure /path/to/repo

    # Use as library
    from ta_lab2.tools.data_tools.analysis.tree_structure import (
        print_tree,
        build_structure_json,
        save_structure_csv,
        emit_hybrid_markdown,
    )
"""

from __future__ import annotations

import argparse
import ast
import csv
import importlib.util
import io
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

logger = logging.getLogger(__name__)

# Directories to ignore at the repo root level (and below)
IGNORE_DIRS = {".venv", ".venv311", ".git", "old"}


# ---------- Filesystem tree ----------


def print_tree(root_dir: str, prefix: str = "", file=None) -> None:
    """Print directory tree in text format.

    Args:
        root_dir: Root directory to scan
        prefix: Prefix for indentation (used recursively)
        file: Optional file-like object to write to
    """
    entries = sorted(e for e in os.listdir(root_dir) if e not in IGNORE_DIRS)
    for i, entry in enumerate(entries):
        path = os.path.join(root_dir, entry)
        connector = "└── " if i == len(entries) - 1 else "├── "
        line = f"{prefix}{connector}{entry}"
        print(line)
        if file:
            file.write(line + "\n")
        if os.path.isdir(path):
            extension = "    " if i == len(entries) - 1 else "│   "
            print_tree(path, prefix + extension, file)


def save_tree_markdown(root_dir: str, out_file: str) -> None:
    """Save directory tree in Markdown format with text code block.

    Args:
        root_dir: Root directory to scan
        out_file: Output markdown file path
    """
    buf = io.StringIO()
    print_tree(root_dir, file=buf)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("```text\n")
        f.write(buf.getvalue())
        f.write("```\n")
    logger.info(f"Saved Markdown tree to {out_file}")


# ---------- Exportable structure (JSON + CSV) ----------


def _iso_utc(ts: float) -> str:
    """Convert POSIX timestamp to ISO 8601 in UTC with seconds precision."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")


def _dir_entry(path: str, root: str) -> Dict[str, Any]:
    """Build a single entry for JSON tree structure.

    Args:
        path: Absolute path to file or directory
        root: Root directory for relative path calculation

    Returns:
        Dict with keys: name, type, path, size, mtime, children
    """
    st = os.stat(path)
    is_dir = os.path.isdir(path)
    rel = os.path.relpath(path, root)
    # Windows relpath can be ".", normalize to "" for root display
    rel = "" if rel == "." else rel.replace(os.sep, "/")
    return {
        "name": os.path.basename(path) if rel else os.path.basename(root.rstrip(os.sep)),
        "type": "dir" if is_dir else "file",
        "path": rel,
        "size": (0 if is_dir else st.st_size),
        "mtime": _iso_utc(st.st_mtime),
        "children": [] if is_dir else None,
    }


def build_structure_json(root_dir: str) -> Dict[str, Any]:
    """Build hierarchical JSON-like dict for directory tree.

    Fields: name, type, path (relative to root), size (files), mtime (UTC ISO), children (dirs).

    Args:
        root_dir: Root directory to scan

    Returns:
        Hierarchical dict representing directory tree
    """
    root_abs = os.path.abspath(root_dir)
    root_node = _dir_entry(root_abs, root_abs)

    # DFS using a stack to avoid recursion limits for huge trees
    stack: List[Dict[str, Any]] = [root_node]
    path_stack: List[str] = [root_abs]

    while stack:
        node = stack.pop()
        current_path = path_stack.pop()

        if node["type"] != "dir":
            continue

        try:
            entries = sorted(
                e for e in os.listdir(current_path) if e not in IGNORE_DIRS
            )
        except PermissionError:
            # Leave directory empty if we can't read it
            logger.warning(f"Permission denied: {current_path}")
            continue

        for name in entries:
            child_path = os.path.join(current_path, name)
            child_node = _dir_entry(child_path, root_abs)
            node["children"].append(child_node)
            if child_node["type"] == "dir":
                stack.append(child_node)
                path_stack.append(child_path)

    return root_node


def save_structure_json(root_dir: str, out_file: str) -> None:
    """Save directory tree as hierarchical JSON.

    Args:
        root_dir: Root directory to scan
        out_file: Output JSON file path
    """
    data = build_structure_json(root_dir)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    logger.info(f"Saved JSON structure to {out_file}")


def save_structure_csv(root_dir: str, out_file: str) -> None:
    """Save directory tree as flat CSV.

    Columns: path, name, type, size_bytes, mtime_iso
    Path is relative to root ("" for root itself).

    Args:
        root_dir: Root directory to scan
        out_file: Output CSV file path
    """
    rows: List[List[Any]] = []
    root_abs = os.path.abspath(root_dir)

    for cur, dirs, files in os.walk(root_abs):
        # Sort for deterministic output, skip ignored dirs
        dirs[:] = sorted(d for d in dirs if d not in IGNORE_DIRS)
        files = sorted(files)
        # Current directory row
        rel = os.path.relpath(cur, root_abs)
        rel = "" if rel == "." else rel.replace(os.sep, "/")
        st = os.stat(cur)
        rows.append(
            [
                rel,
                os.path.basename(cur) if rel else os.path.basename(root_abs),
                "dir",
                0,
                _iso_utc(st.st_mtime),
            ]
        )

        # File rows
        for fname in files:
            fpath = os.path.join(cur, fname)
            stf = os.stat(fpath)
            rel_f = os.path.relpath(fpath, root_abs).replace(os.sep, "/")
            rows.append([rel_f, fname, "file", stf.st_size, _iso_utc(stf.st_mtime)])

    with open(out_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["path", "name", "type", "size_bytes", "mtime_iso"])
        writer.writerows(rows)
    logger.info(f"Saved CSV structure to {out_file}")


# ---------- AST utilities (no imports of your package modules) ----------


def _find_pkg_dir(pkg_name: str) -> str:
    """Find package directory using importlib.

    Args:
        pkg_name: Package name (e.g., "ta_lab2")

    Returns:
        Absolute path to package directory

    Raises:
        ImportError: If package cannot be found
    """
    spec = importlib.util.find_spec(pkg_name)
    if spec is None or not spec.submodule_search_locations:
        raise ImportError(f"Cannot find package {pkg_name!r}")
    return spec.submodule_search_locations[0]


def _param_list_from_funcdef(fn: ast.FunctionDef) -> str:
    """Build a simple parameter list string from AST (names only).

    Args:
        fn: AST FunctionDef node

    Returns:
        Parameter signature string like "(arg1, arg2, *args, **kwargs)"
    """
    a = fn.args
    parts: list[str] = []

    # Positional-only (Py3.8+)
    if getattr(a, "posonlyargs", []):
        parts += [p.arg for p in a.posonlyargs]
        parts.append("/")  # indicates end of pos-only

    # Positional / normal args
    parts += [p.arg for p in a.args]

    # Varargs
    if a.vararg:
        parts.append("*" + a.vararg.arg)
    else:
        # If there are keyword-only args but no vararg, add bare "*" marker
        if a.kwonlyargs:
            parts.append("*")

    # Keyword-only args
    parts += [p.arg for p in a.kwonlyargs]

    # Kwargs
    if a.kwarg:
        parts.append("**" + a.kwarg.arg)

    # Remove trailing "/" or "*" if they ended up last
    while parts and parts[-1] in {"/", "*"}:
        parts.pop()

    return "(" + ", ".join(parts) + ")"


def describe_package_ast(pkg_name: str) -> dict:
    """Extract package structure using AST (no imports).

    Args:
        pkg_name: Package name (e.g., "ta_lab2")

    Returns:
        Dict with package, root, and modules list (each with module, classes, functions)
    """
    pkg_dir = _find_pkg_dir(pkg_name)
    result = {"package": pkg_name, "root": pkg_dir, "modules": []}

    for root, _, files in os.walk(pkg_dir):
        for fname in files:
            if not fname.endswith(".py"):
                continue
            path = os.path.join(root, fname)
            rel = os.path.relpath(path, pkg_dir)[:-3]  # strip ".py"
            mod_name = pkg_name + "." + rel.replace(os.sep, ".")
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=path)
            except Exception as e:
                logger.warning(f"Error parsing {mod_name}: {e}")
                result["modules"].append({"module": mod_name, "error": str(e)})
                continue

            classes, functions = [], []
            for node in tree.body:  # top-level only
                if isinstance(node, ast.ClassDef):
                    classes.append(node.name)
                elif isinstance(node, ast.FunctionDef):
                    functions.append(node.name)

            result["modules"].append(
                {"module": mod_name, "classes": classes, "functions": functions}
            )
    return result


def emit_hybrid_markdown(
    pkg_name: str,
    out_file: str,
    ignore_dirs: Iterable[str] = (
        "__pycache__",
        "tests",
        "ta_lab2.egg-info",
        "out",
        "data",
        ".venv",
        ".venv311",
    ),
    include_inits: bool = True,
) -> None:
    """Generate hybrid markdown with file paths and symbols (classes/functions).

    Args:
        pkg_name: Package name (e.g., "ta_lab2")
        out_file: Output markdown file path
        ignore_dirs: Directory names to ignore
        include_inits: Whether to include __init__.py files
    """
    pkg_dir = _find_pkg_dir(pkg_name)
    lines: list[str] = []
    lines.append(f"# {pkg_name} – File & Symbol Map")
    lines.append(
        f"_Generated: {datetime.now().isoformat(timespec='seconds')}_\n"
    )

    for root, dirs, files in os.walk(pkg_dir):
        # prune ignored dirs in-place
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        py_files = sorted(f for f in files if f.endswith(".py"))
        if not include_inits:
            py_files = [f for f in py_files if f != "__init__.py"]

        rel_root = os.path.relpath(root, pkg_dir)
        if rel_root != ".":
            lines.append(f"## `{pkg_name}/{rel_root.replace(os.sep, '/')}`\n")

        for fname in py_files:
            path = os.path.join(root, fname)
            rel_path = os.path.relpath(path, pkg_dir).replace(os.sep, "/")

            try:
                with open(path, "r", encoding="utf-8") as fh:
                    tree = ast.parse(fh.read(), filename=path)
            except Exception as e:
                logger.warning(f"Error parsing {rel_path}: {e}")
                lines.append(f"### `{rel_path}`\n- ⚠️ Parse error: `{e}`\n")
                continue

            classes, functions = [], []
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    doc = (ast.get_docstring(node) or "").split("\n")[0]
                    classes.append((node.name, doc))
                elif isinstance(node, ast.FunctionDef):
                    doc = (ast.get_docstring(node) or "").split("\n")[0]
                    sig = _param_list_from_funcdef(node)
                    functions.append((node.name + sig, doc))

            lines.append(f"### `{rel_path}`")
            if not classes and not functions:
                lines.append("_(no top-level classes or functions)_\n")
                continue

            if classes:
                lines.append("**Classes**")
                for name, doc in classes:
                    suffix = f" — {doc}" if doc else ""
                    lines.append(f"- `{name}`{suffix}")
                lines.append("")

            if functions:
                lines.append("**Functions**")
                for name_sig, doc in functions:
                    suffix = f" — {doc}" if doc else ""
                    lines.append(f"- `{name_sig}`{suffix}")
                lines.append("")

    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"Saved hybrid API map to {out_file}")


def generate_tree_structure(
    root_dir: str,
    output_prefix: str = "structure",
    pkg_name: str = None,
    generate_api_map: bool = False,
) -> None:
    """Generate all tree structure outputs.

    Args:
        root_dir: Root directory to scan
        output_prefix: Prefix for output files (default: "structure")
        pkg_name: Package name for API map generation (optional)
        generate_api_map: Whether to generate API_MAP.md (requires pkg_name)
    """
    root_path = Path(root_dir).resolve()

    # Text tree
    structure_txt = root_path / f"{output_prefix}.txt"
    with open(structure_txt, "w", encoding="utf-8") as f:
        print_tree(str(root_path), file=f)
    logger.info(f"Generated {structure_txt}")

    # Markdown tree
    structure_md = root_path / f"{output_prefix}.md"
    save_tree_markdown(str(root_path), str(structure_md))

    # JSON tree
    structure_json = root_path / f"{output_prefix}.json"
    save_structure_json(str(root_path), str(structure_json))

    # CSV tree
    structure_csv = root_path / f"{output_prefix}.csv"
    save_structure_csv(str(root_path), str(structure_csv))

    # API map (if requested)
    if generate_api_map and pkg_name:
        api_md = root_path / "API_MAP.md"
        emit_hybrid_markdown(pkg_name, str(api_md), include_inits=True)

        src_json = root_path / "src_structure.json"
        info = describe_package_ast(pkg_name)
        with open(src_json, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)
        logger.info(f"Generated {src_json}")


# ---------- Main (CLI entry point) ----------


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Generate directory tree structure in multiple formats"
    )
    parser.add_argument(
        "root_dir",
        nargs="?",
        default=".",
        help="Root directory to scan (default: current directory)",
    )
    parser.add_argument(
        "--output-prefix",
        default="structure",
        help="Prefix for output files (default: structure)",
    )
    parser.add_argument(
        "--package",
        help="Package name for API map generation (e.g., ta_lab2)",
    )
    parser.add_argument(
        "--api-map",
        action="store_true",
        help="Generate API map (requires --package)",
    )
    args = parser.parse_args()

    if args.api_map and not args.package:
        parser.error("--api-map requires --package")

    generate_tree_structure(
        args.root_dir,
        args.output_prefix,
        args.package,
        args.api_map,
    )

    print(f"✅ Structure files generated in {Path(args.root_dir).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
