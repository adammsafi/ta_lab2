"""Consolidated function/method mapper with purpose inference, LLM enrichment, and diff.

Generates a CSV of all functions/methods/classes across a repo with:
- Signature details (args, returns, decorators, line numbers)
- Purpose inference (docstring → heuristic → optional LLM enrichment)
- Code snippet extraction (first ~20 lines of each function)
- Called-symbols tracking for API usage analysis
- Class-level summaries (base classes, method/property counts)
- Script-level summaries (module docstring, counts)
- Diff mode to compare two function map CSVs

Usage examples:
    # Full function map with purpose inference
    python -m ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose \\
        --root . --include "src/ta_lab2/**/*.py" \\
        --output artifacts/function_map.csv

    # Simple mode (backward-compatible with generate_function_map.py output)
    python -m ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose \\
        --root . --simple --output function_map.csv

    # With LLM enrichment for undocumented functions
    python -m ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose \\
        --root . --enrich --output artifacts/function_map.csv

    # Diff two function maps
    python -m ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose \\
        --root . --output new.csv --diff old.csv

    # Generate script-level summaries
    python -m ta_lab2.tools.data_tools.analysis.generate_function_map_with_purpose \\
        --root . --script-summary --script-summary-output artifacts/script_summary
"""

from __future__ import annotations

import argparse
import ast
import csv
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ta_lab2.tools.data_tools.analysis._ast_helpers import (
    DEFAULT_EXCLUDE_GLOBS,
    CallCollector,
    _ann_to_str,
    _arglist_sig,
    _first_line,
    _first_sentence,
    _get_dec_name,
    _method_kind,
    _qualname,
    _safe_unparse,
    attach_parents,
    clip_text,
    iter_py_files,
)

logger = logging.getLogger(__name__)

# ---------- Column definitions ----------

SIMPLE_FIELDNAMES = [
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
]

FULL_FIELDNAMES = [
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
    "BaseClasses",
    "MethodCount",
    "PropertyCount",
]

# ---------- Heuristic purpose inference ----------

KEYWORD_PURPOSES = [
    ("ema", "Compute or attach exponential moving averages."),
    ("bollinger", "Compute Bollinger Bands or related statistics."),
    ("rsi", "Compute Relative Strength Index."),
    ("macd", "Compute Moving Average Convergence Divergence."),
    ("atr", "Compute Average True Range or volatility."),
    ("vol", "Compute or aggregate volatility statistics."),
    ("resample", "Resample time series to new bar frequencies."),
    ("season", "Compute seasonal/periodic summary metrics."),
    ("trend", "Detect or label trend regimes."),
    ("regime", "Classify market regimes or state labels."),
    ("segment", "Build or analyze contiguous market segments."),
    ("calendar", "Expand datetime/calendar features (Y/M/W/D, holidays)."),
    ("plot", "Plot charts or visualizations."),
    ("dashboard", "Provide interactive dashboard or app layout."),
    ("load", "Load data from disk or external sources."),
    ("read_", "Read data from file-like sources."),
    ("write_", "Write data to disk or external sinks."),
    ("predict", "Run model inference or predictions."),
    ("train", "Train or evaluate models."),
    ("config", "Load or validate configuration."),
    ("feature", "Attach or compute engineered features."),
]

CALL_HINTS = [
    ("np.", "Use NumPy operations; numeric transforms or statistics."),
    ("pd.", "Use pandas for tabular/time-series operations."),
    (".ewm(", "Compute exponentially-weighted statistics."),
    (".rolling(", "Compute rolling-window statistics."),
    ("plt.", "Create or alter Matplotlib plots."),
    ("matplotlib", "Create or alter Matplotlib plots."),
    ("read_csv(", "Read CSV data."),
    ("read_parquet(", "Read Parquet data."),
    ("to_csv(", "Write CSV outputs."),
    ("to_parquet(", "Write Parquet outputs."),
    ("yaml", "Parse or emit YAML configurations."),
]


def infer_purpose(name: str, called_symbols: Set[str]) -> str:
    """Infer function purpose from name and called symbols using heuristics."""
    base: list[str] = []
    lname = name.lower()

    for kw, purpose in KEYWORD_PURPOSES:
        if kw in lname:
            base.append(purpose)

    hints: set[str] = set()
    for sym in called_symbols:
        for needle, msg in CALL_HINTS:
            if needle in sym:
                hints.add(msg)

    parts: list[str] = []
    if base:
        parts.append(" ".join(sorted(set(base))))
    if hints:
        parts.append(" ".join(sorted(hints)))

    msg = " ".join(parts).strip()
    return msg if msg else "Purpose not documented (no docstring)."


# ---------- Collector ----------


class FunctionCollector(ast.NodeVisitor):
    """AST visitor that collects function, method, and class signatures."""

    def __init__(self, module_path: str, file_text: str) -> None:
        self.module_path = module_path
        self.stack: List[str] = []
        self.rows: List[dict] = []
        self.file_text = file_text
        self.lines = self.file_text.splitlines()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # Emit a class-level summary row
        doc = ast.get_docstring(node)
        bases = [_safe_unparse(b) for b in node.bases]

        method_count = sum(
            1
            for child in ast.iter_child_nodes(node)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        property_count = sum(
            1
            for child in ast.iter_child_nodes(node)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(_get_dec_name(d) == "property" for d in child.decorator_list)
        )

        if doc and doc.strip():
            purpose = _first_sentence(doc, 400)
        else:
            purpose = f"Class with {method_count} methods, {property_count} properties."

        self.rows.append(
            {
                "ModulePath": self.module_path,
                "QualifiedName": _qualname(self.stack, node.name),
                "Name": node.name,
                "ObjectType": "class",
                "IsAsync": "no",
                "Decorators": ", ".join(_get_dec_name(d) for d in node.decorator_list),
                "Args_Positional": ", ".join(bases),
                "Args_KeywordOnly": "",
                "Arg_Vararg": "",
                "Arg_Kwarg": "",
                "Defaults": "",
                "Returns": "",
                "Purpose": purpose,
                "Docstring_FirstSentence": _first_sentence(doc) if doc else "",
                "Docstring_1stLine": _first_line(doc) if doc else "",
                "LineStart": getattr(node, "lineno", ""),
                "LineEnd": getattr(node, "end_lineno", ""),
                "Called_Symbols": "",
                "Code_Snippet": "",
                "BaseClasses": ", ".join(bases),
                "MethodCount": str(method_count),
                "PropertyCount": str(property_count),
            }
        )

        # Recurse into class body
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record(node, is_async=True)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node, is_async=False)

    def _record(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool
    ) -> None:
        decorators = [_get_dec_name(d) for d in node.decorator_list]
        pos, kwonly, vararg, kwarg, defaults = _arglist_sig(node.args)
        returns = _ann_to_str(node.returns)
        doc = ast.get_docstring(node)
        qname = _qualname(self.stack, node.name)
        obj_type = (
            _method_kind(decorators)
            if self.stack
            else ("async_function" if is_async else "function")
        )
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)

        # Collect called symbols
        calls = CallCollector()
        for child in ast.walk(node):
            calls.visit(child)

        # Code snippet (first <= 20 lines)
        snippet = ""
        if (
            isinstance(start, int)
            and isinstance(end, int)
            and 1 <= start <= end <= len(self.lines)
        ):
            block = self.lines[start - 1 : end]
            snippet = "\n".join(block[:20]).strip()

        # Purpose: prefer docstring, then heuristic
        if doc and doc.strip():
            purpose = _first_sentence(doc, max_chars=400)
        else:
            purpose = infer_purpose(node.name, calls.calls)

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
                "Purpose": purpose,
                "Docstring_FirstSentence": _first_sentence(doc) if doc else "",
                "Docstring_1stLine": _first_line(doc) if doc else "",
                "LineStart": start or "",
                "LineEnd": end or "",
                "Called_Symbols": ", ".join(sorted(calls.calls))[:1000],
                "Code_Snippet": snippet,
                "BaseClasses": "",
                "MethodCount": "",
                "PropertyCount": "",
            }
        )


# ---------- LLM Enrichment ----------


def _enrich_with_llm(
    rows: List[dict],
    model: str = "gpt-4o-mini",
    batch_size: int = 15,
    max_snippet_chars: int = 800,
    dry_run: bool = False,
) -> Tuple[List[dict], dict]:
    """Enrich rows lacking docstrings with LLM-generated purpose summaries.

    Args:
        rows: Function/class rows from FunctionCollector.
        model: OpenAI model name.
        batch_size: Functions per API call.
        max_snippet_chars: Max chars per code snippet sent to LLM.
        dry_run: If True, log what would be enriched without calling API.

    Returns:
        (enriched_rows, manifest) where manifest tracks tokens/cost/errors.
    """
    manifest: Dict = {
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": model,
        "total_rows": len(rows),
        "enriched": 0,
        "skipped_has_docstring": 0,
        "batches_sent": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "errors": [],
    }

    # Find rows needing enrichment (no docstring)
    needs_enrichment: list[int] = []
    for i, row in enumerate(rows):
        if row.get("Docstring_FirstSentence", "").strip():
            manifest["skipped_has_docstring"] += 1
        elif row.get("Code_Snippet", "").strip():
            needs_enrichment.append(i)
        else:
            manifest["skipped_has_docstring"] += 1

    logger.info(
        f"LLM enrichment: {len(needs_enrichment)} functions need enrichment, "
        f"{manifest['skipped_has_docstring']} already documented"
    )

    if dry_run:
        logger.info(
            f"[DRY RUN] Would enrich {len(needs_enrichment)} functions in "
            f"{(len(needs_enrichment) + batch_size - 1) // batch_size} batches"
        )
        for idx in needs_enrichment[:10]:
            logger.info(
                f"  Would enrich: {rows[idx]['QualifiedName']} "
                f"({rows[idx]['ModulePath']})"
            )
        if len(needs_enrichment) > 10:
            logger.info(f"  ... and {len(needs_enrichment) - 10} more")
        return rows, manifest

    if not needs_enrichment:
        logger.info("All functions already have docstrings. Nothing to enrich.")
        return rows, manifest

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning(
            "openai not installed. Install with: pip install ta_lab2[orchestrator]"
        )
        logger.warning("Skipping LLM enrichment. Heuristic purposes will be used.")
        return rows, manifest

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("OPENAI_API_KEY not set. Skipping LLM enrichment.")
        return rows, manifest

    client = OpenAI()

    system_prompt = (
        "You are a Python code documentation assistant. For each function/method "
        "below, write a one-line purpose summary (under 200 characters). Focus on "
        "WHAT the function does and WHY, not HOW. If the function is a test helper, "
        "say so. If it is a CLI entry point, mention what command it serves. "
        'Return JSON: {"functions": [{"qualified_name": "...", "purpose": "..."}]}.'
    )

    # Process in batches
    for batch_start in range(0, len(needs_enrichment), batch_size):
        batch_indices = needs_enrichment[batch_start : batch_start + batch_size]

        # Build user prompt
        entries: list[str] = []
        for idx in batch_indices:
            row = rows[idx]
            snippet = clip_text(row.get("Code_Snippet", ""), max_snippet_chars)
            entries.append(
                f"### {row['QualifiedName']} ({row['ModulePath']})\n```python\n{snippet}\n```"
            )
        user_prompt = (
            "Generate one-line purpose summaries for these Python functions:\n\n"
            + "\n\n".join(entries)
        )

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )

            manifest["batches_sent"] += 1
            if response.usage:
                manifest["total_input_tokens"] += response.usage.prompt_tokens
                manifest["total_output_tokens"] += response.usage.completion_tokens

            # Parse response
            content = response.choices[0].message.content or "{}"
            data = json.loads(content)
            functions = data.get("functions", [])

            # Match by position — we sent batch_indices in order, LLM returns
            # in the same order. This is more reliable than name matching.
            for i, idx in enumerate(batch_indices):
                if i < len(functions):
                    func = functions[i]
                    # LLM may use "purpose", "summary", or "description"
                    purpose = (
                        func.get("purpose")
                        or func.get("summary")
                        or func.get("description")
                        or ""
                    )
                    if purpose:
                        rows[idx]["Purpose"] = purpose
                        manifest["enriched"] += 1

        except Exception as e:
            logger.error(f"LLM enrichment batch error: {e}")
            manifest["errors"].append(
                {
                    "batch_start": batch_start,
                    "error": repr(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                }
            )

    logger.info(
        f"LLM enrichment complete: {manifest['enriched']} enriched, "
        f"{manifest['batches_sent']} batches, "
        f"{manifest['total_input_tokens'] + manifest['total_output_tokens']} tokens"
    )

    return rows, manifest


# ---------- Diff Report ----------


def generate_diff_report(
    current_csv: Path,
    previous_csv: Path,
    output: Path,
) -> dict:
    """Compare two function map CSVs and produce a markdown diff report.

    Args:
        current_csv: Path to current function map CSV.
        previous_csv: Path to previous function map CSV.
        output: Path for markdown diff report output.

    Returns:
        Summary dict with counts of added/removed/changed.
    """

    def _load_csv(path: Path) -> Dict[Tuple[str, str], dict]:
        result: Dict[Tuple[str, str], dict] = {}
        with path.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                key = (row.get("ModulePath", ""), row.get("QualifiedName", ""))
                result[key] = row
        return result

    current = _load_csv(current_csv)
    previous = _load_csv(previous_csv)

    current_keys = set(current.keys())
    previous_keys = set(previous.keys())

    added_keys = sorted(current_keys - previous_keys)
    removed_keys = sorted(previous_keys - current_keys)

    # Check for signature changes in shared keys
    compare_fields = ["Args_Positional", "Args_KeywordOnly", "Returns", "Decorators"]
    changed: list[
        Tuple[Tuple[str, str], str, str, str]
    ] = []  # key, field, before, after
    for key in sorted(current_keys & previous_keys):
        for field in compare_fields:
            old_val = previous[key].get(field, "")
            new_val = current[key].get(field, "")
            if old_val != new_val:
                changed.append((key, field, old_val, new_val))

    summary = {
        "added": len(added_keys),
        "removed": len(removed_keys),
        "changed": len(changed),
    }

    lines: list[str] = [
        "# Function Map Diff Report",
        f"_Compared: `{previous_csv}` vs `{current_csv}`_",
        f"_Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}_\n",
        "## Summary",
        f"- **Added**: {summary['added']} functions/classes",
        f"- **Removed**: {summary['removed']} functions/classes",
        f"- **Changed signatures**: {summary['changed']}\n",
    ]

    if added_keys:
        lines.append("## Added\n")
        lines.append("| Module | QualifiedName | ObjectType |")
        lines.append("|--------|--------------|------------|")
        for key in added_keys:
            row = current[key]
            lines.append(f"| `{key[0]}` | `{key[1]}` | {row.get('ObjectType', '')} |")
        lines.append("")

    if removed_keys:
        lines.append("## Removed\n")
        lines.append("| Module | QualifiedName | ObjectType |")
        lines.append("|--------|--------------|------------|")
        for key in removed_keys:
            row = previous[key]
            lines.append(f"| `{key[0]}` | `{key[1]}` | {row.get('ObjectType', '')} |")
        lines.append("")

    if changed:
        lines.append("## Changed Signatures\n")
        lines.append("| Module | QualifiedName | Field | Before | After |")
        lines.append("|--------|--------------|-------|--------|-------|")
        for key, field, before, after in changed:
            lines.append(
                f"| `{key[0]}` | `{key[1]}` | {field} | `{before}` | `{after}` |"
            )
        lines.append("")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Diff report written to {output}: {summary}")

    return summary


# ---------- Script Summaries ----------


def generate_script_summaries(
    root: str = ".",
    output_csv: str = "artifacts/script_summary.csv",
    output_md: str = "artifacts/script_summary.md",
    include_globs: Optional[List[str]] = None,
    exclude_globs: Optional[List[str]] = None,
) -> int:
    """Generate per-module summary CSV and markdown.

    Extracts module-level docstring, class count, function count, and line count
    for each Python file.

    Returns:
        Number of modules processed.
    """
    if include_globs is None:
        include_globs = []
    if exclude_globs is None:
        exclude_globs = list(DEFAULT_EXCLUDE_GLOBS)

    root_path = Path(root).resolve()
    files = list(iter_py_files(root_path, include_globs, exclude_globs))

    rows: list[dict] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(text, filename=str(f))
        except SyntaxError as e:
            logger.warning(f"[SyntaxError] {f}: {e}")
            continue
        except Exception as e:
            logger.warning(f"[Error] {f}: {e}")
            continue

        module_doc = ast.get_docstring(tree) or ""
        first_sent = _first_sentence(module_doc, 400) if module_doc else ""

        class_count = sum(1 for node in tree.body if isinstance(node, ast.ClassDef))
        func_count = sum(
            1
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        line_count = len(text.splitlines())
        rel_path = str(f.relative_to(root_path)).replace(os.sep, "/")

        rows.append(
            {
                "ModulePath": rel_path,
                "ModuleDocstring": first_sent,
                "ClassCount": class_count,
                "FunctionCount": func_count,
                "LineCount": line_count,
            }
        )

    # Write CSV
    csv_path = Path(output_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "ModulePath",
                "ModuleDocstring",
                "ClassCount",
                "FunctionCount",
                "LineCount",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    logger.info(f"Script summary CSV: {len(rows)} modules -> {csv_path}")

    # Write markdown
    md_path = Path(output_md)
    md_path.parent.mkdir(parents=True, exist_ok=True)

    md_lines: list[str] = [
        "# Script Summaries",
        f"_Generated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}_",
        f"_Total: {len(rows)} modules_\n",
    ]

    # Group by top-level package directory
    groups: dict[str, list[dict]] = {}
    for row in rows:
        parts = row["ModulePath"].split("/")
        group = (
            "/".join(parts[:3]) if len(parts) > 3 else "/".join(parts[:-1]) or "root"
        )
        groups.setdefault(group, []).append(row)

    for group_name in sorted(groups.keys()):
        group_rows = groups[group_name]
        md_lines.append(f"## `{group_name}/`\n")
        md_lines.append("| Module | Docstring | Classes | Functions | Lines |")
        md_lines.append("|--------|-----------|---------|-----------|-------|")
        for row in sorted(group_rows, key=lambda r: r["ModulePath"]):
            fname = row["ModulePath"].rsplit("/", 1)[-1]
            doc = row["ModuleDocstring"][:80]
            if len(row["ModuleDocstring"]) > 80:
                doc += "..."
            md_lines.append(
                f"| `{fname}` | {doc} | {row['ClassCount']} | "
                f"{row['FunctionCount']} | {row['LineCount']} |"
            )
        md_lines.append("")

    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    logger.info(f"Script summary MD: {len(rows)} modules -> {md_path}")

    return len(rows)


# ---------- Main function map generator ----------


def generate_function_map_with_purpose(
    root: str = ".",
    output: str = "artifacts/function_map.csv",
    include_globs: Optional[List[str]] = None,
    exclude_globs: Optional[List[str]] = None,
    simple: bool = False,
    enrich: bool = False,
    model: str = "gpt-4o-mini",
    batch_size: int = 15,
    enrich_dry_run: bool = False,
) -> int:
    """Generate function map CSV with optional purpose inference and LLM enrichment.

    Args:
        root: Repository root directory.
        output: Output CSV path.
        include_globs: Glob patterns to include (relative to root).
        exclude_globs: Glob patterns to exclude.
        simple: If True, output simple column set (no Purpose/Snippet/Calls).
        enrich: If True, use LLM to enrich undocumented functions.
        model: OpenAI model for enrichment.
        batch_size: Functions per LLM batch.
        enrich_dry_run: If True, show what would be enriched without API calls.

    Returns:
        Number of functions/methods/classes found.
    """
    if include_globs is None:
        include_globs = []
    if exclude_globs is None:
        exclude_globs = list(DEFAULT_EXCLUDE_GLOBS)

    root_path = Path(root).resolve()
    files = list(iter_py_files(root_path, include_globs, exclude_globs))
    logger.info(f"Scanning {len(files)} Python files under {root_path}")

    out_rows: list[dict] = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(text, filename=str(f))
            attach_parents(tree)
            collector = FunctionCollector(
                str(f.relative_to(root_path)).replace(os.sep, "/"), text
            )
            collector.visit(tree)
            out_rows.extend(collector.rows)
        except SyntaxError as e:
            logger.warning(f"[SyntaxError] {f}: {e}")
        except Exception as e:
            logger.warning(f"[Error] {f}: {e}")

    # LLM enrichment (if requested and not in simple mode)
    enrich_manifest = None
    if enrich and not simple:
        out_rows, enrich_manifest = _enrich_with_llm(
            out_rows,
            model=model,
            batch_size=batch_size,
            dry_run=enrich_dry_run,
        )

    # Select fieldnames based on mode
    if simple:
        fieldnames = SIMPLE_FIELDNAMES
    else:
        fieldnames = FULL_FIELDNAMES

    # Write CSV
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(out_rows)

    logger.info(f"Wrote {len(out_rows)} rows to {out}")

    # Write enrichment manifest if applicable
    if enrich_manifest:
        manifest_path = out.parent / "enrich_manifest.json"
        manifest_path.write_text(
            json.dumps(enrich_manifest, indent=2), encoding="utf-8"
        )
        logger.info(f"Enrichment manifest: {manifest_path}")

    return len(out_rows)


# ---------- CLI ----------


def main() -> int:
    """CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    ap = argparse.ArgumentParser(
        description="Generate a CSV map of all functions/methods/classes with purpose."
    )
    ap.add_argument("--root", type=str, default=".", help="Repository root directory")
    ap.add_argument(
        "--output",
        type=str,
        default="artifacts/function_map.csv",
        help="Output CSV path",
    )
    ap.add_argument(
        "--include",
        type=str,
        nargs="*",
        default=[],
        help="Glob(s) to include (relative to root)",
    )
    ap.add_argument(
        "--exclude",
        type=str,
        nargs="*",
        default=None,
        help="Glob(s) to exclude",
    )
    ap.add_argument(
        "--simple",
        action="store_true",
        help="Simple output (no Purpose, Code_Snippet, Called_Symbols)",
    )

    # LLM enrichment
    ap.add_argument("--enrich", action="store_true", help="Enable LLM enrichment")
    ap.add_argument(
        "--model", default="gpt-4o-mini", help="OpenAI model for enrichment"
    )
    ap.add_argument(
        "--batch-size", type=int, default=15, help="Functions per LLM batch"
    )
    ap.add_argument(
        "--enrich-dry-run",
        action="store_true",
        help="Show what would be enriched without API calls",
    )

    # Diff
    ap.add_argument(
        "--diff", type=str, default=None, help="Previous CSV path for diff comparison"
    )
    ap.add_argument(
        "--diff-output",
        type=str,
        default=None,
        help="Output path for diff report (default: alongside output CSV)",
    )

    # Script summaries
    ap.add_argument(
        "--script-summary",
        action="store_true",
        help="Also generate script-level summaries",
    )
    ap.add_argument(
        "--script-summary-output",
        type=str,
        default=None,
        help="Base path for script summary outputs (adds .csv and .md)",
    )

    args = ap.parse_args()

    # Generate function map
    count = generate_function_map_with_purpose(
        root=args.root,
        output=args.output,
        include_globs=args.include,
        exclude_globs=args.exclude,
        simple=args.simple,
        enrich=args.enrich,
        model=args.model,
        batch_size=args.batch_size,
        enrich_dry_run=args.enrich_dry_run,
    )
    print(f"Wrote {count} rows to {args.output}")

    # Diff report
    if args.diff:
        diff_output = args.diff_output
        if not diff_output:
            diff_output = str(Path(args.output).parent / "diff_report.md")
        summary = generate_diff_report(
            current_csv=Path(args.output),
            previous_csv=Path(args.diff),
            output=Path(diff_output),
        )
        print(
            f"Diff report: +{summary['added']} -{summary['removed']} ~{summary['changed']}"
        )

    # Script summaries
    if args.script_summary:
        base = args.script_summary_output
        if not base:
            base = str(Path(args.output).parent / "script_summary")
        sc = generate_script_summaries(
            root=args.root,
            output_csv=base + ".csv",
            output_md=base + ".md",
            include_globs=args.include,
            exclude_globs=args.exclude,
        )
        print(f"Script summaries: {sc} modules")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
