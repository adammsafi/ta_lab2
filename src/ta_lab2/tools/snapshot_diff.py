from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


def _human_bytes(n: int) -> str:
    # simple, stable formatter
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    x = float(max(0, n))
    i = 0
    while x >= 1024.0 and i < len(units) - 1:
        x /= 1024.0
        i += 1
    if i == 0:
        return f"{int(x)} {units[i]}"
    return f"{x:.2f} {units[i]}"


def _norm_rows(x: Any) -> Optional[int]:
    """Normalize approx row counts.

    Snapshots sometimes store unknown estimates as -1 or as strings like 'unknown'.
    Treat those as None so we don't compute bogus deltas.
    """
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x if x >= 0 else None
    if isinstance(x, str):
        s = x.strip().lower()
        if not s or s in {"unknown", "n/a", "na", "none", "null"}:
            return None
        try:
            v = int(s)
            return v if v >= 0 else None
        except Exception:
            return None
    return None


def _table_key(schema: str, table: str) -> str:
    return f"{schema}.{table}"


@dataclass(frozen=True)
class NormTable:
    schema: str
    table: str
    approx_rows: Optional[int]
    columns: Set[str]
    indexes: Set[str]         # names only (low noise)
    constraints: Set[str]     # names only (low noise)
    keys: Set[Tuple[str, Tuple[str, ...]]]  # (type, cols) where type in {"p","u"} if available
    total_bytes: Optional[int]
    table_bytes: Optional[int]
    index_bytes: Optional[int]


@dataclass(frozen=True)
class NormSnapshot:
    meta: Dict[str, Any]
    tables: Dict[str, NormTable]  # key "schema.table"


def load_snapshot(path: str | Path) -> NormSnapshot:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    meta = data.get("meta", {}) if isinstance(data, dict) else {}

    # Two supported shapes:
    # A) tables: dict, table_stats: dict, top_col_stats: dict (your minimal fixture)
    # B) tables: list[table_obj] with embedded fields
    tables_obj = data.get("tables")

    out: Dict[str, NormTable] = {}

    if isinstance(tables_obj, dict):
        # Shape A
        table_stats = data.get("table_stats", {}) or {}
        # columns/indexes/constraints/keys not guaranteed in this shape
        for k, t in tables_obj.items():
            schema = t.get("schema") or k.split(".", 1)[0]
            table = t.get("table") or k.split(".", 1)[1]
            approx_rows = _norm_rows(t.get("approx_rows"))
            ts = table_stats.get(_table_key(schema, table), {}) or {}

            nt = NormTable(
                schema=schema,
                table=table,
                approx_rows=approx_rows,
                columns=set(),
                indexes=set(),
                constraints=set(),
                keys=set(),
                total_bytes=ts.get("total_bytes"),
                table_bytes=ts.get("table_bytes"),
                index_bytes=ts.get("index_bytes"),
            )
            out[_table_key(schema, table)] = nt

    elif isinstance(tables_obj, list):
        # Shape B
        for t in tables_obj:
            schema = t.get("schema")
            table = t.get("table") or t.get("table_name")
            if not schema or not table:
                continue

            approx_rows = _norm_rows(t.get("approx_rows"))

            # Columns could be list of dicts or list of names
            cols: Set[str] = set()
            if isinstance(t.get("columns"), list):
                for c in t["columns"]:
                    if isinstance(c, str):
                        cols.add(c)
                    elif isinstance(c, dict) and c.get("column"):
                        cols.add(str(c["column"]))
                    elif isinstance(c, dict) and c.get("name"):
                        cols.add(str(c["name"]))

            idx: Set[str] = set()
            if isinstance(t.get("indexes"), list):
                for i in t["indexes"]:
                    if isinstance(i, str):
                        idx.add(i)
                    elif isinstance(i, dict) and i.get("name"):
                        idx.add(str(i["name"]))

            cons: Set[str] = set()
            if isinstance(t.get("constraints"), list):
                for c in t["constraints"]:
                    if isinstance(c, str):
                        cons.add(c)
                    elif isinstance(c, dict) and c.get("name"):
                        cons.add(str(c["name"]))

            keys: Set[Tuple[str, Tuple[str, ...]]] = set()
            if isinstance(t.get("keys"), list):
                # expected: [{"contype":"p","columns":["id","tf"]}, ...]
                for kk in t["keys"]:
                    if isinstance(kk, dict):
                        typ = str(kk.get("contype") or kk.get("type") or "")
                        cols2 = kk.get("columns") or []
                        if typ and isinstance(cols2, list) and all(isinstance(x, str) for x in cols2):
                            keys.add((typ, tuple(cols2)))

            stats = t.get("table_stats") or {}
            nt = NormTable(
                schema=schema,
                table=table,
                approx_rows=approx_rows,
                columns=cols,
                indexes=idx,
                constraints=cons,
                keys=keys,
                total_bytes=stats.get("total_bytes"),
                table_bytes=stats.get("table_bytes"),
                index_bytes=stats.get("index_bytes"),
            )
            out[_table_key(schema, table)] = nt

    else:
        raise ValueError(f"Unrecognized snapshot shape: tables={type(tables_obj)}")

    return NormSnapshot(meta=meta, tables=out)


def diff_snapshots(a: NormSnapshot, b: NormSnapshot, *, top_n: int = 25) -> Dict[str, Any]:
    a_keys = set(a.tables.keys())
    b_keys = set(b.tables.keys())

    added_tables = sorted(b_keys - a_keys)
    removed_tables = sorted(a_keys - b_keys)
    common = sorted(a_keys & b_keys)

    # Meta diffs (small, high-signal fields). We don't include volatile timestamps.
    meta_deltas: Dict[str, Dict[str, Any]] = {}
    meta_keys = sorted(set(a.meta.keys()) | set(b.meta.keys()))
    for k_meta in meta_keys:
        va = a.meta.get(k_meta)
        vb = b.meta.get(k_meta)
        if va != vb:
            meta_deltas[k_meta] = {"a": va, "b": vb}

    def _bytes(x: Optional[int]) -> int:
        return int(x) if isinstance(x, int) else 0

    table_deltas: List[Dict[str, Any]] = []
    shape_deltas: List[Dict[str, Any]] = []

    for k in common:
        ta = a.tables[k]
        tb = b.tables[k]

        da = _bytes(ta.total_bytes)
        db = _bytes(tb.total_bytes)
        delta_bytes = db - da

        ra = int(ta.approx_rows) if isinstance(ta.approx_rows, int) else None
        rb = int(tb.approx_rows) if isinstance(tb.approx_rows, int) else None
        delta_rows = (rb - ra) if (ra is not None and rb is not None) else None

        if delta_bytes != 0 or (delta_rows is not None and delta_rows != 0):
            table_deltas.append(
                {
                    "table": k,
                    "total_bytes_a": da,
                    "total_bytes_b": db,
                    "delta_bytes": delta_bytes,
                    "delta_bytes_human": _human_bytes(abs(delta_bytes)),
                    "approx_rows_a": ra,
                    "approx_rows_b": rb,
                    "delta_rows": delta_rows,
                }
            )

        # only if we actually have structural info
        if ta.columns or tb.columns or ta.indexes or tb.indexes or ta.keys or tb.keys or ta.constraints or tb.constraints:
            cols_added = sorted(tb.columns - ta.columns)
            cols_removed = sorted(ta.columns - tb.columns)

            idx_added = sorted(tb.indexes - ta.indexes)
            idx_removed = sorted(ta.indexes - tb.indexes)

            cons_added = sorted(tb.constraints - ta.constraints)
            cons_removed = sorted(ta.constraints - tb.constraints)

            keys_added = sorted(list(tb.keys - ta.keys))
            keys_removed = sorted(list(ta.keys - tb.keys))

            if cols_added or cols_removed or idx_added or idx_removed or cons_added or cons_removed or keys_added or keys_removed:
                shape_deltas.append(
                    {
                        "table": k,
                        "columns_added": cols_added,
                        "columns_removed": cols_removed,
                        "indexes_added": idx_added,
                        "indexes_removed": idx_removed,
                        "constraints_added": cons_added,
                        "constraints_removed": cons_removed,
                        "keys_added": [{"type": t, "columns": list(c)} for (t, c) in keys_added],
                        "keys_removed": [{"type": t, "columns": list(c)} for (t, c) in keys_removed],
                    }
                )

    table_deltas.sort(key=lambda d: abs(int(d["delta_bytes"])), reverse=True)
    shape_deltas.sort(key=lambda d: d["table"])

    return {
        "ok": True,
        "summary": {
            "meta_deltas": meta_deltas,
            "tables_added": len(added_tables),
            "tables_removed": len(removed_tables),
            "tables_common": len(common),
            "meta_changed": len(meta_deltas),
            "tables_with_size_or_row_change": len(table_deltas),
            "tables_with_shape_change": len(shape_deltas),
        },
        "tables_added": added_tables,
        "tables_removed": removed_tables,
        "top_table_deltas_by_abs_bytes": table_deltas[:top_n],
        "shape_changes": shape_deltas,
    }


def render_diff_md(diff: Dict[str, Any], *, title: str = "Snapshot diff") -> str:
    s = diff.get("summary", {})
    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- Tables added: **{s.get('tables_added', 0)}**")
    lines.append(f"- Tables removed: **{s.get('tables_removed', 0)}**")
    lines.append(f"- Tables changed (bytes/rows): **{s.get('tables_with_size_or_row_change', 0)}**")
    lines.append(f"- Tables changed (shape): **{s.get('tables_with_shape_change', 0)}**")

    # FIX: meta_deltas lives under diff["summary"]["meta_deltas"] in diff_snapshots()
    meta_deltas = (diff.get("summary", {}) or {}).get("meta_deltas") or {}
    if meta_deltas:
        lines.append("## Meta changes")
        lines.append("")
        lines.append("| key | a | b |")
        lines.append("|---|---|---|")
        for k in sorted(meta_deltas.keys()):
            va = meta_deltas[k].get("a")
            vb = meta_deltas[k].get("b")
            # keep it compact and readable
            lines.append(f"| `{k}` | `{va}` | `{vb}` |")
        lines.append("")

    lines.append("")

    added = diff.get("tables_added") or []
    removed = diff.get("tables_removed") or []

    if added:
        lines.append("## Tables added")
        lines.append("")
        for t in added:
            lines.append(f"- `{t}`")
        lines.append("")

    if removed:
        lines.append("## Tables removed")
        lines.append("")
        for t in removed:
            lines.append(f"- `{t}`")
        lines.append("")

    deltas = diff.get("top_table_deltas_by_abs_bytes") or []
    if deltas:
        lines.append("## Biggest size deltas")
        lines.append("")
        lines.append("| table | delta bytes | a total | b total | delta rows |")
        lines.append("|---|---:|---:|---:|---:|")
        for d in deltas:
            lines.append(
                f"| `{d['table']}` | {d['delta_bytes']} ({d['delta_bytes_human']}) | {d['total_bytes_a']} | {d['total_bytes_b']} | {d.get('delta_rows','')} |"
            )
        lines.append("")

    shapes = diff.get("shape_changes") or []
    if shapes:
        lines.append("## Shape changes")
        lines.append("")
        for ch in shapes:
            lines.append(f"### `{ch['table']}`")
            lines.append("")
            if ch["columns_added"] or ch["columns_removed"]:
                if ch["columns_added"]:
                    lines.append("- Columns added:")
                    for c in ch["columns_added"]:
                        lines.append(f"  - `{c}`")
                if ch["columns_removed"]:
                    lines.append("- Columns removed:")
                    for c in ch["columns_removed"]:
                        lines.append(f"  - `{c}`")
                lines.append("")
            if ch["indexes_added"] or ch["indexes_removed"]:
                if ch["indexes_added"]:
                    lines.append("- Indexes added:")
                    for i in ch["indexes_added"]:
                        lines.append(f"  - `{i}`")
                if ch["indexes_removed"]:
                    lines.append("- Indexes removed:")
                    for i in ch["indexes_removed"]:
                        lines.append(f"  - `{i}`")
                lines.append("")
            if ch["constraints_added"] or ch["constraints_removed"]:
                if ch["constraints_added"]:
                    lines.append("- Constraints added:")
                    for c in ch["constraints_added"]:
                        lines.append(f"  - `{c}`")
                if ch["constraints_removed"]:
                    lines.append("- Constraints removed:")
                    for c in ch["constraints_removed"]:
                        lines.append(f"  - `{c}`")
                lines.append("")
            if ch["keys_added"] or ch["keys_removed"]:
                if ch["keys_added"]:
                    lines.append("- Keys added:")
                    for k in ch["keys_added"]:
                        lines.append(f"  - `{k['type']}` {k['columns']}")
                if ch["keys_removed"]:
                    lines.append("- Keys removed:")
                    for k in ch["keys_removed"]:
                        lines.append(f"  - `{k['type']}` {k['columns']}")
                lines.append("")
    return "\n".join(lines)
