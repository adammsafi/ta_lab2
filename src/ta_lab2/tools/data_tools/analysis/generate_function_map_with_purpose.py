"""Enhanced function/method mapper with purpose inference.

Generate a CSV of all functions/methods across a repo, including a 'Purpose' column.
- Uses docstring first (full, trimmed).
- Falls back to a static heuristic based on function name and called APIs.
- Also captures a compact code snippet (first ~20 lines) for later review or LLM enrichment.

This is an enhanced version of generate_function_map.py that adds:
- Purpose inference from docstrings and heuristics
- Code snippet extraction (first ~20 lines of each function)
- Called symbols tracking for API usage analysis

Usage examples:
    # Scan everything under src/, skip tests/ and common build dirs
    python -m ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose \\
        --root . --include "src/ta_lab2/**/*.py" \\
        --output artifacts/function_map_ta_lab2.csv

    # Whole repo (still skips tests by default)
    python -m ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose \\
        --root . --output artifacts/function_map_full_repo.csv

    # Use as a library
    from ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose import generate_function_map_with_purpose
    generate_function_map_with_purpose(
        root=".",
        output="function_map.csv",
        include_globs=["src/**/*.py"],
        exclude_globs=["tests/**"]
    )
"""

from __future__ import annotations
import ast
import csv
import sys
import os
import argparse
import logging
from pathlib import Path
from typing import Iterable, Optional, List, Tuple, Set
import fnmatch

logger = logging.getLogger(__name__)

# --------------------------- AST helpers ---------------------------

def _safe_unparse(node: Optional[ast.AST]) -> str:
    """Safely unparse an AST node to string, returning empty string on failure."""
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""

def _ann_to_str(node: Optional[ast.expr]) -> str:
    """Convert type annotation to string."""
    return _safe_unparse(node) if node is not None else ""

def _get_dec_name(d: ast.expr) -> str:
    """Extract decorator name from AST expression."""
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
        base = _get_dec_name(d.func)
        return f"{base}(…)"
    return _safe_unparse(d)

def _arglist_sig(args: ast.arguments) -> Tuple[str, str, str, str, str]:
    """Extract function argument signature components."""
    def arg_str(a: ast.arg) -> str:
        ann = _ann_to_str(a.annotation)
        return f"{a.arg}: {ann}" if ann else a.arg

    pos = [arg_str(a) for a in args.posonlyargs + args.args]
    kwonly = [arg_str(a) for a in args.kwonlyargs]
    vararg = arg_str(args.vararg) if args.vararg else ""
    kwarg = arg_str(args.kwarg) if args.kwarg else ""

    defaults = []
    all_pos = args.posonlyargs + args.args
    pad = len(all_pos) - len(args.defaults)
    pos_defaults = [""] * pad + [_safe_unparse(d) for d in args.defaults]
    for name, val in zip([a.arg for a in all_pos], pos_defaults):
        if val != "":
            defaults.append(f"{name}={val}")

    kw_defaults = [(_safe_unparse(d) if d is not None else "") for d in args.kw_defaults]
    for name, val in zip([a.arg for a in args.kwonlyargs], kw_defaults):
        if val != "":
            defaults.append(f"{name}={val}")

    return (", ".join(pos), ", ".join(kwonly), vararg, kwarg, ", ".join(defaults))

def _method_kind(decorators: List[str]) -> str:
    """Determine method type from decorators."""
    if "staticmethod" in decorators:
        return "staticmethod"
    if "classmethod" in decorators:
        return "classmethod"
    if "property" in decorators:
        return "property"
    return "method"

def _qualname(stack: List[str], name: str) -> str:
    """Build qualified name from class stack and function name."""
    return ".".join([*stack, name]) if stack else name

def _first_sentence(text: str, max_chars: int = 280) -> str:
    """Extract first sentence from text, up to max_chars."""
    s = " ".join(text.strip().split())
    # try to end at a sentence boundary for the first sentence
    for sep in [". ", "。", "؟ ", "! ", "… "]:
        idx = s.find(sep)
        if 0 <= idx <= max_chars:
            return s[: idx + len(sep)].strip()
    return s[:max_chars].strip()

# --------------------------- Heuristic purpose ---------------------------

KEYWORD_PURPOSES = [
    # name-based
    ("ema",              "Compute or attach exponential moving averages."),
    ("bollinger",        "Compute Bollinger Bands or related statistics."),
    ("rsi",              "Compute Relative Strength Index."),
    ("macd",             "Compute Moving Average Convergence Divergence."),
    ("atr",              "Compute Average True Range or volatility."),
    ("vol",              "Compute or aggregate volatility statistics."),
    ("resample",         "Resample time series to new bar frequencies."),
    ("season",           "Compute seasonal/periodic summary metrics."),
    ("trend",            "Detect or label trend regimes."),
    ("regime",           "Classify market regimes or state labels."),
    ("segment",          "Build or analyze contiguous market segments."),
    ("calendar",         "Expand datetime/calendar features (Y/M/W/D, holidays)."),
    ("plot",             "Plot charts or visualizations."),
    ("dashboard",        "Provide interactive dashboard or app layout."),
    ("load",             "Load data from disk or external sources."),
    ("read_",            "Read data from file-like sources."),
    ("write_",           "Write data to disk or external sinks."),
    ("predict",          "Run model inference or predictions."),
    ("train",            "Train or evaluate models."),
    ("config",           "Load or validate configuration."),
    ("feature",          "Attach or compute engineered features."),
]

CALL_HINTS = [
    ("np.",              "Use NumPy operations; numeric transforms or statistics."),
    ("pd.",              "Use pandas for tabular/time-series operations."),
    (".ewm(",            "Compute exponentially-weighted statistics."),
    (".rolling(",        "Compute rolling-window statistics."),
    ("plt.",             "Create or alter Matplotlib plots."),
    ("matplotlib",       "Create or alter Matplotlib plots."),
    ("read_csv(",        "Read CSV data."),
    ("read_parquet(",    "Read Parquet data."),
    ("to_csv(",          "Write CSV outputs."),
    ("to_parquet(",      "Write Parquet outputs."),
    ("yaml",             "Parse or emit YAML configurations."),
]

def infer_purpose(name: str, called_symbols: Set[str]) -> str:
    """Infer function purpose from name and called symbols using heuristics."""
    base = []
    lname = name.lower()

    # name keyword passes
    for kw, purpose in KEYWORD_PURPOSES:
        if kw in lname:
            base.append(purpose)

    # API call hints
    hints = set()
    for sym in called_symbols:
        for needle, msg in CALL_HINTS:
            if needle in sym:
                hints.add(msg)

    parts = []
    if base:
        parts.append(" ".join(sorted(set(base))))
    if hints:
        parts.append(" ".join(sorted(hints)))

    msg = " ".join(parts).strip()
    return msg if msg else "Define a function/method; purpose not documented (no docstring)."

class CallCollector(ast.NodeVisitor):
    """AST visitor to collect all function/method calls."""

    def __init__(self):
        self.calls: Set[str] = set()

    def visit_Call(self, node: ast.Call):
        try:
            name = _safe_unparse(node.func)
            if name:
                self.calls.add(name)
        except Exception:
            pass
        self.generic_visit(node)

# --------------------------- Collector ---------------------------

def attach_parents(tree: ast.AST):
    """Attach parent_chain attribute to all nodes in AST."""
    def _walk(node: ast.AST, parents: List[ast.AST]):
        for child in ast.iter_child_nodes(node):
            child.parent_chain = parents[:]  # type: ignore
            _walk(child, parents + [node])
    tree.parent_chain = []  # type: ignore
    _walk(tree, [])

class FunctionCollector(ast.NodeVisitor):
    """AST visitor to collect all functions/methods with metadata."""

    def __init__(self, module_path: str, file_text: str):
        self.module_path = module_path
        self.stack: List[str] = []
        self.rows: List[dict] = []
        self.file_text = file_text
        self.lines = self.file_text.splitlines()

    def visit_ClassDef(self, node: ast.ClassDef):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._record(node, is_async=True)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._record(node, is_async=False)

    def _record(self, node: ast.AST, is_async: bool):
        assert isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        decorators = [_get_dec_name(d) for d in node.decorator_list]
        pos, kwonly, vararg, kwarg, defaults = _arglist_sig(node.args)
        returns = _ann_to_str(node.returns)
        doc = ast.get_docstring(node)
        qname = _qualname(self.stack, node.name)
        obj_type = _method_kind(decorators) if self.stack else ("async_function" if is_async else "function")
        start, end = getattr(node, "lineno", None), getattr(node, "end_lineno", None)

        # collect called symbols inside body
        calls = CallCollector()
        for child in ast.walk(node):
            calls.visit(child)

        # code snippet (first <= 20 lines of the function for review)
        snippet = ""
        if isinstance(start, int) and isinstance(end, int) and 1 <= start <= end <= len(self.lines):
            block = self.lines[start - 1:end]
            snippet = "\n".join(block[:20]).strip()

        # Purpose: prefer docstring; else heuristic
        if doc and doc.strip():
            purpose = _first_sentence(doc, max_chars=400)
        else:
            purpose = infer_purpose(node.name, calls.calls)

        self.rows.append({
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
            "Purpose": purpose,
            "Docstring_FirstSentence": _first_sentence(doc) if doc else "",
            "LineStart": start or "",
            "LineEnd": end or "",
            "Called_Symbols": ", ".join(sorted(calls.calls))[:1000],
            "Code_Snippet": snippet,
        })

# --------------------------- File iteration ---------------------------

def iter_py_files(root: Path, include_globs: List[str], exclude_globs: List[str]) -> Iterable[Path]:
    """Walk all *.py files under root, applying include/exclude globs.

    We normalize both the path and patterns to posix-style ("/") so that
    patterns like "src/ta_lab2/**/*.py" work on Windows and Unix.
    """
    # Normalize patterns to POSIX style
    include_posix = [g.replace("\\", "/") for g in include_globs]
    exclude_posix = [g.replace("\\", "/") for g in exclude_globs]

    for p in root.rglob("*.py"):
        rel = p.relative_to(root)
        rel_posix = str(rel).replace(os.sep, "/")

        # Exclude first
        if any(fnmatch.fnmatch(rel_posix, pat) for pat in exclude_posix):
            continue

        # If includes are specified, require a match
        if include_posix and not any(fnmatch.fnmatch(rel_posix, pat) for pat in include_posix):
            continue

        yield p

# --------------------------- Public API ---------------------------

def generate_function_map_with_purpose(
    root: str = ".",
    output: str = "artifacts/function_map.csv",
    include_globs: Optional[List[str]] = None,
    exclude_globs: Optional[List[str]] = None
) -> int:
    """Generate function map CSV with purpose inference.

    Args:
        root: Repository root directory
        output: Output CSV path
        include_globs: Glob patterns to include (relative to root)
        exclude_globs: Glob patterns to exclude

    Returns:
        Number of functions/methods found
    """
    if include_globs is None:
        include_globs = []

    if exclude_globs is None:
        exclude_globs = [
            ".git/**",
            "**/.git/**",
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
            "tests/**",
        ]

    root_path = Path(root).resolve()
    files = list(iter_py_files(root_path, include_globs, exclude_globs))

    out_rows = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(text, filename=str(f))
            attach_parents(tree)
            collector = FunctionCollector(str(f.relative_to(root_path)).replace(os.sep, "/"), text)
            collector.visit(tree)
            out_rows.extend(collector.rows)
        except SyntaxError as e:
            logger.error(f"[SyntaxError] {f}: {e}")
        except Exception as e:
            logger.error(f"[Error] {f}: {e}")

    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
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
                "Purpose",
                "Docstring_FirstSentence",
                "LineStart",
                "LineEnd",
                "Called_Symbols",
                "Code_Snippet",
            ],
        )
        writer.writeheader()
        writer.writerows(out_rows)

    logger.info(f"Wrote {len(out_rows)} rows to {out}")
    return len(out_rows)

# --------------------------- Main ---------------------------

def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    ap = argparse.ArgumentParser(description="Generate a CSV map of all functions/methods with inferred Purpose.")
    ap.add_argument("--root", type=str, default=".", help="Repository root directory")
    ap.add_argument("--output", type=str, default="artifacts/function_map.csv", help="Output CSV path")
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
            ".git/**",
            "**/.git/**",
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
            "tests/**",
        ],
        help="Glob(s) to exclude",
    )
    args = ap.parse_args()

    count = generate_function_map_with_purpose(
        root=args.root,
        output=args.output,
        include_globs=args.include,
        exclude_globs=args.exclude
    )

    print(f"Wrote {count} rows to {args.output}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
