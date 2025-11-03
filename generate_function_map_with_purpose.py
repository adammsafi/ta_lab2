from __future__ import annotations
import ast, csv, sys, os, argparse, textwrap
from pathlib import Path
from typing import Iterable, Optional, List, Tuple, Set

# -*- coding: utf-8 -*-
"""
Created on Sun Nov  2 22:41:20 2025

@author: asafi
"""


"""
Generate a CSV of all functions/methods across a repo, including a 'Purpose' column.
- Uses docstring first (full, trimmed).
- Falls back to a static heuristic based on function name and called APIs.
- Also captures a compact code snippet (first ~20 lines) for later review or LLM enrichment.

Usage examples:
  # scan everything under src/, skip tests/ and common build dirs
  python generate_function_map_with_purpose.py --root . --include "src/**/*.py" --output artifacts/function_map.csv

  # whole repo (still skips tests by default)
  python generate_function_map_with_purpose.py --root . --output artifacts/function_map.csv
"""

# --------------------------- AST helpers ---------------------------

def _safe_unparse(node: Optional[ast.AST]) -> str:
    if node is None: return ""
    try:
        return ast.unparse(node)
    except Exception:
        return ""

def _ann_to_str(node: Optional[ast.expr]) -> str:
    return _safe_unparse(node) if node is not None else ""

def _get_dec_name(d: ast.expr) -> str:
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
    if "staticmethod" in decorators:
        return "staticmethod"
    if "classmethod" in decorators:
        return "classmethod"
    if "property" in decorators:
        return "property"
    return "method"

def _qualname(stack: List[str], name: str) -> str:
    return ".".join([*stack, name]) if stack else name

def _first_sentence(text: str, max_chars: int = 280) -> str:
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
    def _walk(node: ast.AST, parents: List[ast.AST]):
        for child in ast.iter_child_nodes(node):
            child.parent_chain = parents[:]  # type: ignore
            _walk(child, parents + [node])
    tree.parent_chain = []  # type: ignore
    _walk(tree, [])

class FunctionCollector(ast.NodeVisitor):
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
            block = self.lines[start-1:end]
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
    for p in root.rglob("*.py"):
        rel = p.relative_to(root)
        srel = str(rel)
        if any(Path(srel).match(g) for g in exclude_globs):
            continue
        if include_globs and not any(Path(srel).match(g) for g in include_globs):
            continue
        yield p

# --------------------------- Main ---------------------------

def main():
    ap = argparse.ArgumentParser(description="Generate a CSV map of all functions/methods with inferred Purpose.")
    ap.add_argument("--root", type=str, default=".", help="Repository root directory")
    ap.add_argument("--output", type=str, default="artifacts/function_map.csv", help="Output CSV path")
    ap.add_argument("--include", type=str, nargs="*", default=[],
                    help="Glob(s) to include (relative to root), e.g. 'src/**/*.py'")
    ap.add_argument("--exclude", type=str, nargs="*", default=[
        ".venv/**", "venv/**", "env/**", "build/**", "dist/**", ".eggs/**",
        "**/site-packages/**", "tests/**"
    ], help="Glob(s) to exclude")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    files = list(iter_py_files(root, args.include, args.exclude))

    out_rows = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(text, filename=str(f))
            attach_parents(tree)
            collector = FunctionCollector(str(f.relative_to(root)).replace(os.sep, "/"), text)
            collector.visit(tree)
            out_rows.extend(collector.rows)
        except SyntaxError as e:
            sys.stderr.write(f"[SyntaxError] {f}: {e}\n")
        except Exception as e:
            sys.stderr.write(f"[Error] {f}: {e}\n")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "ModulePath","QualifiedName","Name","ObjectType","IsAsync",
            "Decorators","Args_Positional","Args_KeywordOnly","Arg_Vararg","Arg_Kwarg",
            "Defaults","Returns","Purpose","Docstring_FirstSentence",
            "LineStart","LineEnd","Called_Symbols","Code_Snippet"
        ])
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"Wrote {len(out_rows)} rows to {out}")

if __name__ == "__main__":
    main()
