# -*- coding: utf-8 -*-
"""
Created on Sat Nov  1 14:19:55 2025

@author: asafi
"""

# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import ast
import csv
import json
import importlib.util
from datetime import datetime, timezone
from typing import Iterable, Dict, Any, List



"""
Generate:
- structure.txt         : directory tree (text)
- structure.md          : directory tree in Markdown
- structure.json        : directory tree (hierarchical JSON; name/type/path/size/mtime/children)
- structure.csv         : directory tree (flat CSV; one row per item)
- API_MAP.md            : per-file classes & functions (from AST, no imports)
- src_structure.json    : module -> {classes, functions} (from AST, no imports)
"""

# ---------- Filesystem tree (existing) ----------

def print_tree(root_dir: str, prefix: str = "", file=None) -> None:
    entries = sorted(os.listdir(root_dir))
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
    import io
    buf = io.StringIO()
    print_tree(root_dir, file=buf)
    with open(out_file, "w", encoding="utf-8") as f:
        f.write("```text\n")
        f.write(buf.getvalue())
        f.write("```\n")

# ---------- NEW: exportable structure (JSON + CSV) ----------

def _iso_utc(ts: float) -> str:
    """POSIX timestamp -> ISO 8601 in UTC with seconds precision."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")

def _dir_entry(path: str, root: str) -> Dict[str, Any]:
    """Build a single entry for JSON tree."""
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
    """
    Return a hierarchical JSON-like dict for the directory tree.
    Fields: name, type, path (relative to root), size (files), mtime (UTC ISO), children (dirs).
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
            entries = sorted(os.listdir(current_path))
        except PermissionError:
            # Leave directory empty if we can't read it
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
    data = build_structure_json(root_dir)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def save_structure_csv(root_dir: str, out_file: str) -> None:
    """
    Flat export with columns:
    path,name,type,size_bytes,mtime_iso
    path is relative to root ("" for root itself).
    """
    rows: List[List[Any]] = []
    root_abs = os.path.abspath(root_dir)

    for cur, dirs, files in os.walk(root_abs):
        # Sort for deterministic output
        dirs[:] = sorted(dirs)
        files = sorted(files)
        # Current directory row
        rel = os.path.relpath(cur, root_abs)
        rel = "" if rel == "." else rel.replace(os.sep, "/")
        st = os.stat(cur)
        rows.append([rel, os.path.basename(cur) if rel else os.path.basename(root_abs), "dir", 0, _iso_utc(st.st_mtime)])

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

# ---------- AST utilities (no imports of your package modules) ----------

def _find_pkg_dir(pkg_name: str) -> str:
    spec = importlib.util.find_spec(pkg_name)
    if spec is None or not spec.submodule_search_locations:
        raise ImportError(f"Cannot find package {pkg_name!r}")
    return spec.submodule_search_locations[0]

def _param_list_from_funcdef(fn: ast.FunctionDef) -> str:
    """Build a simple parameter list string from AST (names only)."""
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
    ignore_dirs: Iterable[str] = ("__pycache__", "tests", "ta_lab2.egg-info", "out", "data"),
    include_inits: bool = True,
) -> None:
    pkg_dir = _find_pkg_dir(pkg_name)
    lines: list[str] = []
    lines.append(f"# {pkg_name} – File & Symbol Map")
    lines.append(f"_Generated: {datetime.now().isoformat(timespec='seconds')}_\n")

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

# ---------- Main (side-effects live here) ----------

if __name__ == "__main__":
    ROOT = r"C:\Users\asafi\Downloads\ta_lab2"
    PKG  = "ta_lab2"

    # 1) Tree (txt + md)
    structure_txt = os.path.join(ROOT, "structure.txt")
    structure_md  = os.path.join(ROOT, "structure.md")
    with open(structure_txt, "w", encoding="utf-8") as f:
        print_tree(ROOT, file=f)
    save_tree_markdown(ROOT, structure_md)
    print(f"✅ Structure saved to:\n- {structure_txt}\n- {structure_md}")

    # 1b) NEW: Exportable structure (JSON + CSV)
    structure_json = os.path.join(ROOT, "structure.json")
    structure_csv  = os.path.join(ROOT, "structure.csv")
    save_structure_json(ROOT, structure_json)
    save_structure_csv(ROOT, structure_csv)
    print(f"✅ Exportable structure written to:\n- {structure_json}\n- {structure_csv}")

    # 2) Hybrid API map (AST, import-safe)
    api_md = os.path.join(ROOT, "API_MAP.md")
    emit_hybrid_markdown(PKG, api_md, include_inits=True)
    print(f"✅ Hybrid API map written to: {api_md}")

    # 3) JSON API structure (AST, import-safe)
    src_json = os.path.join(ROOT, "src_structure.json")
    info = describe_package_ast(PKG)
    with open(src_json, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
    print(f"✅ JSON API structure written to: {src_json}")
