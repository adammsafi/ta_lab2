"""Generate CSV map of all functions/methods in a repository using AST parsing.

This tool analyzes Python source files and extracts function/method signatures,
parameters, return types, and docstrings without importing the code.

Usage:
    # Scan specific directory
    python -m ta_lab2.tools.data_tools.analysis.generate_function_map --root . --include "src/ta_lab2/**/*.py" --output function_map.csv

    # Scan entire repo with default exclusions
    python -m ta_lab2.tools.data_tools.analysis.generate_function_map --root . --output function_map.csv

Output CSV columns:
    - ModulePath: Relative path to Python file
    - QualifiedName: Full qualified name (e.g., ClassName.method_name)
    - Name: Function/method name
    - ObjectType: function/method/staticmethod/classmethod/property/async_function
    - IsAsync: "yes" if async function
    - Decorators: Comma-separated decorator list
    - Args_Positional: Positional parameters with type hints
    - Args_KeywordOnly: Keyword-only parameters
    - Arg_Vararg: *args parameter
    - Arg_Kwarg: **kwargs parameter
    - Defaults: Parameter defaults
    - Returns: Return type annotation
    - Docstring_1stLine: First line of docstring
    - LineStart: Starting line number
    - LineEnd: Ending line number
"""

from __future__ import annotations

import argparse
import ast
import csv
import logging
import os
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)


# --------------------------- AST helpers ---------------------------


def _get_dec_name(d: ast.expr) -> str:
    """Extract decorator name, e.g. 'staticmethod', 'classmethod', 'property', 'lru_cache', 'app.route'."""
    if isinstance(d, ast.Name):
        return d.id
    if isinstance(d, ast.Attribute):
        parts = []
        cur = d
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    if isinstance(d, ast.Call):
        # decorator with args, like @lru_cache(maxsize=128)
        base = _get_dec_name(d.func)
        return f"{base}(…)"
    return ast.unparse(d) if hasattr(ast, "unparse") else str(d)


def _ann_to_str(node: Optional[ast.expr]) -> str:
    """Convert type annotation AST node to string."""
    if node is None:
        return ""
    try:
        return ast.unparse(node)  # Python 3.9+
    except Exception:
        return ""


def _arglist_sig(args: ast.arguments) -> Tuple[str, str, str, str, str]:
    """Return (positional, kwonly, vararg, kwarg, defaults) as CSV-friendly strings."""

    def arg_str(a: ast.arg) -> str:
        ann = _ann_to_str(a.annotation)
        return f"{a.arg}: {ann}" if ann else a.arg

    pos = [arg_str(a) for a in args.posonlyargs + args.args]
    kwonly = [arg_str(a) for a in args.kwonlyargs]
    vararg = arg_str(args.vararg) if args.vararg else ""
    kwarg = arg_str(args.kwarg) if args.kwarg else ""

    # defaults align with the rightmost positional+kwonly
    defaults = []
    all_pos = args.posonlyargs + args.args
    pos_defaults = ["" for _ in range(len(all_pos) - len(args.defaults))] + [
        _safe_unparse(d) for d in args.defaults
    ]
    for name, val in zip([a.arg for a in all_pos], pos_defaults):
        defaults.append(f"{name}={val}" if val != "" else "")

    kw_defaults = [
        (_safe_unparse(d) if d is not None else "") for d in args.kw_defaults
    ]
    for name, val in zip([a.arg for a in args.kwonlyargs], kw_defaults):
        defaults.append(f"{name}={val}" if val != "" else "")

    return (
        ", ".join(pos),
        ", ".join(kwonly),
        vararg,
        kwarg,
        ", ".join([d for d in defaults if d]),
    )


def _safe_unparse(node: Optional[ast.AST]) -> str:
    """Safely unparse AST node to string."""
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""


def _first_line(doc: Optional[str], max_chars: int = 300) -> str:
    """Extract first line of docstring."""
    if not doc:
        return ""
    s = doc.strip().splitlines()[0].strip()
    return s[:max_chars]


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


# --------------------------- Collector ---------------------------


class FunctionCollector(ast.NodeVisitor):
    """AST visitor that collects function and method signatures."""

    def __init__(self, module_path: str):
        self.module_path = module_path  # e.g. src/ta_lab2/features/ema.py
        self.stack: List[str] = []
        self.rows: List[dict] = []

    def visit_ClassDef(self, node: ast.ClassDef):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._record_func(node, is_async=True)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._record_func(node, is_async=False)

    def _record_func(self, node: ast.AST, is_async: bool):
        """Record function/method signature details."""
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        decorators = [_get_dec_name(d) for d in node.decorator_list]
        pos, kwonly, vararg, kwarg, defaults = _arglist_sig(node.args)
        returns = _ann_to_str(node.returns)
        doc = ast.get_docstring(node)

        obj_type = (
            _method_kind(decorators)
            if self.stack
            else ("async_function" if is_async else "function")
        )

        qname = _qualname(self.stack, node.name)

        self.rows.append(
            {
                "ModulePath": self.module_path,
                "QualifiedName": qname,
                "Name": node.name,
                "ObjectType": obj_type,
                "IsAsync": "yes" if is_async else "no",
                "Decorators": ", ".join(decorators),
                "Args_Positional": pos,
                "Args_KeywordOnly": kwonly,
                "Arg_Vararg": vararg,
                "Arg_Kwarg": kwarg,
                "Defaults": defaults,
                "Returns": returns,
                "Docstring_1stLine": _first_line(doc),
                "LineStart": getattr(node, "lineno", ""),
                "LineEnd": getattr(node, "end_lineno", ""),
            }
        )


def attach_parents(tree: ast.AST):
    """Annotate nodes with a 'parent_chain' for context (used to detect in-class)."""

    def _walk(node: ast.AST, parents: List[ast.AST]):
        for child in ast.iter_child_nodes(node):
            child.parent_chain = parents[:]  # type: ignore
            _walk(child, parents + [node])

    tree.parent_chain = []  # type: ignore
    _walk(tree, [])


# --------------------------- Runner ---------------------------


def iter_py_files(
    root: Path, include_globs: List[str], exclude_globs: List[str]
) -> Iterable[Path]:
    """Iterate Python files matching include/exclude patterns."""
    for p in root.rglob("*.py"):
        rel = p.relative_to(root)
        srel = str(rel)
        if any(Path(srel).match(g) for g in exclude_globs):
            continue
        if include_globs and not any(Path(srel).match(g) for g in include_globs):
            continue
        yield p


def generate_function_map(
    root: Path,
    output: Path,
    include_globs: List[str] = None,
    exclude_globs: List[str] = None,
) -> int:
    """Generate function map CSV from repository.

    Args:
        root: Repository root directory
        output: Output CSV file path
        include_globs: Glob patterns to include (e.g., ["src/ta_lab2/**/*.py"])
        exclude_globs: Glob patterns to exclude

    Returns:
        Number of functions/methods found
    """
    if include_globs is None:
        include_globs = []
    if exclude_globs is None:
        exclude_globs = [
            ".venv/**",
            "venv/**",
            "env/**",
            "build/**",
            "dist/**",
            ".eggs/**",
            "**/site-packages/**",
            "tests/**",
        ]

    files = list(iter_py_files(root, include_globs, exclude_globs))
    logger.info(f"Scanning {len(files)} Python files under {root}")

    rows = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(text, filename=str(f))
            attach_parents(tree)
            collector = FunctionCollector(str(f.relative_to(root)).replace(os.sep, "/"))
            collector.visit(tree)
            rows.extend(collector.rows)
        except SyntaxError as e:
            logger.warning(f"[SyntaxError] {f}: {e}")
        except Exception as e:
            logger.warning(f"[Error] {f}: {e}")

    # Write CSV
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "ModulePath",
                "QualifiedName",
                "Name",
                "ObjectType",
                "IsAsync",
                "Decorators",
                "Args_Positional",
                "Args_KeywordOnly",
                "Arg_Vararg",
                "Arg_Kwarg",
                "Defaults",
                "Returns",
                "Docstring_1stLine",
                "LineStart",
                "LineEnd",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Wrote {len(rows)} function/method signatures to {output}")
    return len(rows)


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    ap = argparse.ArgumentParser(
        description="Generate a CSV map of all functions/methods in a repo."
    )
    ap.add_argument("--root", type=str, default=".", help="Repository root directory")
    ap.add_argument(
        "--output", type=str, default="function_map.csv", help="Output CSV path"
    )
    ap.add_argument(
        "--include",
        type=str,
        nargs="*",
        default=[],
        help="Glob(s) to include (relative to root), e.g. 'src/ta_lab2/**/*.py'",
    )
    ap.add_argument(
        "--exclude",
        type=str,
        nargs="*",
        default=[
            ".venv/**",
            "venv/**",
            "env/**",
            "build/**",
            "dist/**",
            ".eggs/**",
            "**/site-packages/**",
            "tests/**",
        ],
        help="Glob(s) to exclude",
    )
    args = ap.parse_args()

    root = Path(args.root).resolve()
    output = Path(args.output)

    count = generate_function_map(root, output, args.include, args.exclude)
    print(f"Wrote {count} rows to {output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
