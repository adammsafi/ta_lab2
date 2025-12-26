# src/ta_lab2/tools/dbtool.py
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from datetime import datetime, timezone, timedelta

# Prefer psycopg (v3). Fall back to psycopg2 if needed.
try:
    import psycopg  # type: ignore

    _PSYCOPG_V3 = True
except Exception:
    psycopg = None
    _PSYCOPG_V3 = False

try:
    import psycopg2  # type: ignore
    import psycopg2.extras  # type: ignore
except Exception:
    psycopg2 = None

RE_DANGEROUS = re.compile(
    r"\b("
    r"insert|update|delete|merge|upsert|truncate|drop|alter|create|grant|revoke|"
    r"vacuum|analyze\s+table|cluster|reindex|refresh\s+materialized|"
    r"copy\s+.*\s+from|copy\s+.*\s+to|call|do\b|execute\b|listen|notify|"
    r"set\s+role|set\s+session|set\s+transaction\b"
    r")\b",
    re.IGNORECASE,
)

RE_MULTI_STMT = re.compile(r";\s*\S", re.MULTILINE)

DEFAULT_TIMEOUT_MS = 15_000
DEFAULT_ROW_LIMIT = 200
DEFAULT_IDLE_TX_TIMEOUT_MS = 15_000


@dataclass(frozen=True)
class DbConfig:
    url: str
    statement_timeout_ms: int = DEFAULT_TIMEOUT_MS
    idle_in_tx_timeout_ms: int = DEFAULT_IDLE_TX_TIMEOUT_MS
    row_limit: int = DEFAULT_ROW_LIMIT


# -----------------------
# URL + env helpers
# -----------------------
def _normalize_db_url(url: str) -> str:
    """
    Accept SQLAlchemy-style URLs and convert to psycopg/psycopg2-compatible URLs.
    """
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql://", 1)
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url


def _find_repo_root(start: Optional[Path] = None) -> Path:
    start = start or Path.cwd()
    cur = start.resolve()
    for _ in range(12):
        if (cur / "pyproject.toml").exists() or (cur / ".git").exists():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start.resolve()


def _load_env_file_if_present(repo_root: Path) -> None:
    """
    Loads db_config.env from repo root *only if* TARGET_DB_URL / MARKETDATA_DB_URL
    are not already set in the environment.
    """
    if os.environ.get("TARGET_DB_URL") or os.environ.get("MARKETDATA_DB_URL"):
        return

    env_path = repo_root / "db_config.env"
    if not env_path.exists():
        return

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


def _resolve_db_url() -> str:
    url = os.environ.get("TARGET_DB_URL") or os.environ.get("MARKETDATA_DB_URL")
    if not url:
        raise RuntimeError(
            "No DB URL found. Set TARGET_DB_URL or MARKETDATA_DB_URL, "
            "or provide db_config.env at repo root."
        )
    return _normalize_db_url(url)


# -----------------------
# SQL safety helpers
# -----------------------
def _normalize_sql(sql: str) -> str:
    s = sql.strip()
    # Drop trailing semicolon (single statement only)
    if s.endswith(";"):
        s = s[:-1].rstrip()
    return s


def _enforce_read_only(sql: str) -> None:
    s = sql.strip()
    if RE_MULTI_STMT.search(s):
        raise ValueError("Multiple SQL statements are not allowed (single statement only).")
    if RE_DANGEROUS.search(s):
        raise ValueError("Rejected: query contains potentially write/unsafe keyword(s). Read-only tool.")
    # Allow SELECT / WITH / EXPLAIN only
    head = s.lstrip().split(None, 1)[0].lower() if s.strip() else ""
    if head not in {"select", "with", "explain"}:
        raise ValueError("Rejected: only SELECT/WITH/EXPLAIN queries are allowed.")


def _ensure_limit(sql: str, limit: int) -> str:
    """
    Adds LIMIT if query appears to be SELECT/WITH and has no LIMIT.
    Not perfect SQL parsing, but works well for interactive exploration.
    """
    s = sql.strip()
    head = s.lstrip().split(None, 1)[0].lower() if s.strip() else ""
    if head not in {"select", "with"}:
        return s
    if re.search(r"\blimit\b", s, re.IGNORECASE):
        return s
    # Don’t append LIMIT to queries that obviously aggregate to 1 row
    if re.search(r"\bcount\s*\(\s*\*\s*\)\b", s, re.IGNORECASE):
        return s
    return f"{s}\nLIMIT {int(limit)}"


def _redact_url(url: str) -> str:
    # redact password in postgres://user:pass@host/db
    return re.sub(r":([^:@/]+)@", r":***@", url)


def _quote_ident(name: str) -> str:
    # minimal identifier quoting; doubles internal quotes
    return '"' + name.replace('"', '""') + '"'


def _validate_simple_ident(name: str, what: str) -> None:
    # allow typical postgres identifiers; if you use exotic names, they must still be passed,
    # but we keep this strict on purpose.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"Invalid {what} identifier: {name!r}")


def _validate_sql_fragment(fragment: Optional[str], what: str) -> None:
    """
    Guardrails for user-supplied clause fragments (WHERE/GROUP/HAVING/ORDER/select list).
    This is NOT full SQL parsing; it’s a safety net.
    """
    if fragment is None:
        return
    s = fragment.strip()
    if not s:
        return
    if RE_MULTI_STMT.search(s) or ";" in s:
        raise ValueError(f"{what} contains a semicolon or multiple statements (not allowed).")
    if RE_DANGEROUS.search(s):
        raise ValueError(f"{what} contains potentially write/unsafe keyword(s).")
    # Disallow comments (avoid hiding content)
    if "--" in s or "/*" in s or "*/" in s:
        raise ValueError(f"{what} contains SQL comments (not allowed).")


# -----------------------
# Connection + execution
# -----------------------
def _connect_v3(cfg: DbConfig):
    assert psycopg is not None
    # autocommit = False so we can SET TRANSACTION READ ONLY
    return psycopg.connect(cfg.url, autocommit=False)


def _connect_v2(cfg: DbConfig):
    assert psycopg2 is not None
    return psycopg2.connect(cfg.url)


def _apply_safety_session_settings(cur: Any, cfg: DbConfig) -> None:
    # Keep these LOCAL to the transaction scope when possible.
    cur.execute(f"SET LOCAL statement_timeout = {int(cfg.statement_timeout_ms)};")
    cur.execute(f"SET LOCAL idle_in_transaction_session_timeout = {int(cfg.idle_in_tx_timeout_ms)};")


def _execute_sql(cfg: DbConfig, sql: str, params: Optional[Sequence[Any]] = None) -> Dict[str, Any]:
    sql = _normalize_sql(sql)
    _enforce_read_only(sql)

    # Default LIMIT for interactive browsing
    sql = _ensure_limit(sql, cfg.row_limit)

    result: Dict[str, Any] = {
        "ok": False,
        "sql": sql,
        "row_count": 0,
        "columns": [],
        "rows": [],
        "notice": None,
        "error": None,
    }

    try:
        if _PSYCOPG_V3:
            conn = _connect_v3(cfg)
            try:
                with conn.cursor() as cur:
                    cur.execute("BEGIN;")
                    _apply_safety_session_settings(cur, cfg)
                    cur.execute("SET TRANSACTION READ ONLY;")

                    cur.execute(sql, params)
                    if cur.description:
                        cols = [d.name for d in cur.description]
                        rows = cur.fetchall()
                        result["columns"] = cols
                        result["rows"] = rows
                        result["row_count"] = len(rows)

                    cur.execute("ROLLBACK;")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        else:
            if psycopg2 is None:
                raise RuntimeError("Neither psycopg (v3) nor psycopg2 is installed.")
            conn = _connect_v2(cfg)
            try:
                conn.autocommit = False
                with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute("BEGIN;")
                    _apply_safety_session_settings(cur, cfg)
                    cur.execute("SET TRANSACTION READ ONLY;")

                    cur.execute(sql, params)
                    if cur.description:
                        rows = cur.fetchall()
                        result["columns"] = list(rows[0].keys()) if rows else []
                        result["rows"] = rows
                        result["row_count"] = len(rows)

                    cur.execute("ROLLBACK;")
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

        result["ok"] = True
        return result

    except Exception as e:
        result["error"] = {
            "type": type(e).__name__,
            "message": str(e),
        }
        return result


# -----------------------
# Introspection helpers
# -----------------------
def schema_overview_sql() -> str:
    return r"""
WITH nsp AS (
  SELECT n.oid, n.nspname
  FROM pg_namespace n
  WHERE n.nspname NOT IN ('pg_catalog','information_schema')
    AND n.nspname NOT LIKE 'pg_toast%'
    AND n.nspname NOT LIKE 'pg_temp_%'
)
SELECT
  n.nspname AS schema,
  COUNT(c.oid) FILTER (WHERE c.relkind IN ('r','p')) AS n_tables,
  COUNT(c.oid) FILTER (WHERE c.relkind = 'v') AS n_views,
  COUNT(c.oid) FILTER (WHERE c.relkind = 'm') AS n_matviews
FROM nsp n
LEFT JOIN pg_class c ON c.relnamespace = n.oid
GROUP BY 1
ORDER BY 1;
""".strip()

def table_stats_sql() -> str:
    """
    Fast table-level "shape" stats (no full scans):
      - sizes: total/table/index bytes
      - approx rows: from pg_stat_user_tables.n_live_tup
      - last analyze/vacuum timestamps
    Includes only non-system schemas and ordinary/partitioned tables.
    """
    return r"""
SELECT
  n.nspname AS schema,
  c.relname AS table_name,
  pg_total_relation_size(c.oid)::bigint AS total_bytes,
  pg_relation_size(c.oid)::bigint AS table_bytes,
  pg_indexes_size(c.oid)::bigint AS index_bytes,
  COALESCE(st.n_live_tup, 0)::bigint AS approx_rows,
  st.last_vacuum,
  st.last_autovacuum,
  st.last_analyze,
  st.last_autoanalyze
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stat_user_tables st ON st.relid = c.oid
WHERE c.relkind IN ('r','p')
  AND n.nspname NOT IN ('pg_catalog','information_schema')
  AND n.nspname NOT LIKE 'pg_toast%'
  AND n.nspname NOT LIKE 'pg_temp_%'
ORDER BY pg_total_relation_size(c.oid) DESC;
""".strip()

def col_stats_sql() -> str:
    """
    Snapshot-only column ranking.

    Uses pg_stats to return an ORDERED + LIMITED list of the most
    "interesting" columns for a table.

    Intended use:
      - DB snapshot JSON (top_col_stats)
      - Snapshot Markdown rendering
      - NOT for interactive CLI profiling

    Params:
      1) schema (text)
      2) table  (text)
      3) limit  (int)
    """
    return r"""
SELECT
  schemaname AS schema,
  tablename  AS table_name,
  attname    AS column_name,
  null_frac,
  n_distinct,
  correlation,
  most_common_vals,
  most_common_freqs
FROM pg_stats
WHERE schemaname = %s
  AND tablename  = %s
ORDER BY
  null_frac DESC,
  abs(n_distinct) DESC
LIMIT %s;
""".strip()


def list_tables_sql(schema: Optional[str]) -> str:
    if schema:
        return r"""
SELECT
  n.nspname AS schema,
  c.relname AS table_name,
  COALESCE(NULLIF(s.n_live_tup, 0), c.reltuples::bigint, 0)::bigint AS approx_rows
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stat_user_tables s
  ON s.schemaname = n.nspname AND s.relname = c.relname
WHERE n.nspname = %s
  AND c.relkind IN ('r','p')
ORDER BY n.nspname, c.relname;
""".strip()

    return r"""
SELECT
  n.nspname AS schema,
  c.relname AS table_name,
  COALESCE(NULLIF(s.n_live_tup, 0), c.reltuples::bigint, 0)::bigint AS approx_rows
FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
LEFT JOIN pg_stat_user_tables s
  ON s.schemaname = n.nspname AND s.relname = c.relname
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND c.relkind IN ('r','p')
ORDER BY n.nspname, c.relname;
""".strip()



def describe_table_sql(schema: str, table: str) -> str:
    return r"""
SELECT
  c.ordinal_position,
  c.column_name,
  c.data_type,
  c.is_nullable,
  c.column_default
FROM information_schema.columns c
WHERE c.table_schema = %s
  AND c.table_name = %s
ORDER BY c.ordinal_position;
""".strip()


def indexes_detail_sql(schema: str, table: str) -> str:
    # Includes method (btree/gin/...), uniqueness, primary, predicate (partial index), and full definition
    return r"""
SELECT
  cls_i.relname AS index_name,
  am.amname     AS index_method,
  idx.indisunique  AS is_unique,
  idx.indisprimary AS is_primary,
  CASE
    WHEN idx.indpred IS NOT NULL THEN pg_get_expr(idx.indpred, idx.indrelid)
    ELSE NULL
  END AS predicate,
  pg_get_indexdef(idx.indexrelid) AS indexdef
FROM pg_index idx
JOIN pg_class cls_t ON cls_t.oid = idx.indrelid
JOIN pg_namespace nsp ON nsp.oid = cls_t.relnamespace
JOIN pg_class cls_i ON cls_i.oid = idx.indexrelid
JOIN pg_am am ON am.oid = cls_i.relam
WHERE nsp.nspname = %s
  AND cls_t.relname = %s
ORDER BY cls_i.relname;
""".strip()


def constraints_sql(schema: str, table: str) -> str:
    return r"""
SELECT
  tc.constraint_type,
  tc.constraint_name
FROM information_schema.table_constraints tc
WHERE tc.table_schema = %s
  AND tc.table_name = %s
ORDER BY 1,2;
""".strip()


def keys_sql(schema: str, table: str) -> str:
    # Returns PK + UNIQUE constraints with their column lists
    return r"""
WITH c AS (
  SELECT
    n.nspname AS schema,
    t.relname AS table_name,
    con.conname AS constraint_name,
    con.contype AS contype,
    array_agg(a.attname ORDER BY u.ord) AS columns
  FROM pg_constraint con
  JOIN pg_class t ON t.oid = con.conrelid
  JOIN pg_namespace n ON n.oid = t.relnamespace
  JOIN unnest(con.conkey) WITH ORDINALITY AS u(attnum, ord) ON TRUE
  JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = u.attnum
  WHERE n.nspname = %s
    AND t.relname = %s
    AND con.contype IN ('p','u')
  GROUP BY 1,2,3,4
)
SELECT
  schema,
  table_name,
  CASE contype WHEN 'p' THEN 'PRIMARY KEY' WHEN 'u' THEN 'UNIQUE' ELSE contype::text END AS key_type,
  constraint_name,
  columns
FROM c
ORDER BY key_type, constraint_name;
""".strip()


def profile_table_queries(schema: str, table: str) -> List[Tuple[str, str, Optional[Sequence[Any]]]]:
    fq = f"{_quote_ident(schema)}.{_quote_ident(table)}"
    return [
        ("rowcount", f"SELECT COUNT(*)::bigint AS n FROM {fq}", None),
        ("sample", f"SELECT * FROM {fq} LIMIT 20", None),
    ]


def explain_sql(sql: str) -> str:
    sql = _normalize_sql(sql)
    _enforce_read_only(sql)
    return f"EXPLAIN (FORMAT JSON) {sql}"


def column_profile_sql(schema: str, table: str) -> str:
    """
    Full column profile for interactive inspection (profile-cols command).

    - Returns ALL columns (no limit)
    - Ordered by ordinal_position
    - LEFT JOIN pg_stats when available

    Intended use:
      - ta-lab2 db profile-cols <schema> <table>
      - Human / LLM inspection of table structure
    """
    return r"""
WITH cols AS (
  SELECT
    c.ordinal_position,
    c.column_name,
    c.data_type
  FROM information_schema.columns c
  WHERE c.table_schema = %s
    AND c.table_name = %s
),
st AS (
  SELECT
    s.attname,
    s.null_frac,
    s.n_distinct,
    s.most_common_vals,
    s.most_common_freqs
  FROM pg_stats s
  WHERE s.schemaname = %s
    AND s.tablename = %s
)
SELECT
  cols.ordinal_position,
  cols.column_name,
  cols.data_type,
  st.null_frac,
  st.n_distinct,
  st.most_common_vals,
  st.most_common_freqs
FROM cols
LEFT JOIN st ON st.attname = cols.column_name
ORDER BY cols.ordinal_position;
""".strip()


def time_profile_sql(
    schema: str,
    table: str,
    ts_col: str,
    bucket: str,
    max_buckets: int,
) -> Tuple[str, Sequence[Any]]:
    """
    Returns:
      - 1 summary row: min/max/count + estimated number of buckets
      - up to `max_buckets` bucket rows: date_trunc(bucket, ts_col) counts
      - missing-bucket computation is gated: ONLY computed when n_buckets <= max_buckets

    Output schema:
      section ('summary'|'buckets'),
      bucket (timestamptz),
      n (bigint),
      min_ts, max_ts (timestamptz),
      n_total (bigint),
      n_buckets (bigint),
      computed_missing (boolean),
      n_missing (bigint)
    """
    _validate_simple_ident(schema, "schema")
    _validate_simple_ident(table, "table")
    _validate_simple_ident(ts_col, "ts-col")

    bucket = bucket.lower().strip()
    allowed = {"hour", "day", "week", "month"}
    if bucket not in allowed:
        raise ValueError(f"--bucket must be one of {sorted(allowed)}")

    if max_buckets <= 0:
        raise ValueError("--max-buckets must be positive")

    fq = f"{_quote_ident(schema)}.{_quote_ident(table)}"
    qts = _quote_ident(ts_col)

    step = {
        "hour": "1 hour",
        "day": "1 day",
        "week": "1 week",
        "month": "1 month",
    }[bucket]

    # 1 summary row + up to max_buckets bucket rows
    limit_rows = 1 + int(max_buckets)

    sql = f"""
WITH base AS (
  SELECT
    MIN({qts}) AS min_ts,
    MAX({qts}) AS max_ts,
    COUNT(*)::bigint AS n_total
  FROM {fq}
),
counts AS (
  SELECT
    date_trunc(%s, {qts}) AS bucket,
    COUNT(*)::bigint AS n
  FROM {fq}
  GROUP BY 1
),
bounds AS (
  SELECT
    min_ts,
    max_ts,
    n_total,
    CASE
      WHEN min_ts IS NULL OR max_ts IS NULL THEN 0::bigint
      WHEN date_trunc(%s, max_ts) < date_trunc(%s, min_ts) THEN 0::bigint
      ELSE (
        EXTRACT(EPOCH FROM (date_trunc(%s, max_ts) - date_trunc(%s, min_ts))) /
        EXTRACT(EPOCH FROM (%s::interval))
      )::bigint + 1
    END AS n_buckets
  FROM base
),
missing AS (
  -- IMPORTANT: gated to avoid huge generate_series on wide ranges
  SELECT gs.bucket
  FROM bounds b
  JOIN LATERAL (
    SELECT generate_series(
      date_trunc(%s, b.min_ts),
      date_trunc(%s, b.max_ts),
      %s::interval
    ) AS bucket
  ) gs ON TRUE
  LEFT JOIN counts c ON c.bucket = gs.bucket
  WHERE b.n_buckets <= %s
    AND c.bucket IS NULL
)
SELECT
  'summary'::text AS section,
  NULL::timestamptz AS bucket,
  NULL::bigint AS n,
  b.min_ts,
  b.max_ts,
  b.n_total,
  b.n_buckets,
  CASE WHEN b.n_buckets <= %s THEN TRUE ELSE FALSE END AS computed_missing,
  CASE WHEN b.n_buckets <= %s THEN (SELECT COUNT(*)::bigint FROM missing) ELSE NULL::bigint END AS n_missing
FROM bounds b

UNION ALL
SELECT
  'buckets'::text AS section,
  c.bucket,
  c.n,
  NULL::timestamptz AS min_ts,
  NULL::timestamptz AS max_ts,
  NULL::bigint AS n_total,
  NULL::bigint AS n_buckets,
  NULL::boolean AS computed_missing,
  NULL::bigint AS n_missing
FROM counts c
ORDER BY section, bucket
LIMIT {limit_rows};
""".strip()

    params: List[Any] = [
        bucket,  # counts date_trunc
        bucket,  # bounds: trunc max
        bucket,  # bounds: trunc min
        bucket,  # bounds: trunc max for diff
        bucket,  # bounds: trunc min for diff
        step,    # bounds: interval step
        bucket,  # missing: trunc min
        bucket,  # missing: trunc max
        step,    # missing: interval step
        int(max_buckets),  # missing gate: b.n_buckets <= max_buckets
        int(max_buckets),  # summary: computed_missing
        int(max_buckets),  # summary: n_missing
    ]
    return sql, params


def dupes_sql(schema: str, table: str, key_cols: List[str], limit: int) -> str:
    _validate_simple_ident(schema, "schema")
    _validate_simple_ident(table, "table")
    for c in key_cols:
        _validate_simple_ident(c, "key column")

    fq = f"{_quote_ident(schema)}.{_quote_ident(table)}"
    cols = ", ".join(_quote_ident(c) for c in key_cols)
    # Return only dupes with examples; limit result set
    return f"""
SELECT
  {cols},
  COUNT(*)::bigint AS n
FROM {fq}
GROUP BY {cols}
HAVING COUNT(*) > 1
ORDER BY n DESC
LIMIT {int(limit)};
""".strip()


def agg_sql(
    schema: str,
    table: str,
    select_list: str,
    where: Optional[str],
    group_by: Optional[str],
    having: Optional[str],
    order_by: Optional[str],
    limit: int,
) -> str:
    """
    Safe-ish single-table aggregation builder. You provide the select list and optional clauses.
    We validate fragments to avoid semicolons/comments/dangerous keywords.
    """
    _validate_simple_ident(schema, "schema")
    _validate_simple_ident(table, "table")
    _validate_sql_fragment(select_list, "SELECT list")
    _validate_sql_fragment(where, "WHERE")
    _validate_sql_fragment(group_by, "GROUP BY")
    _validate_sql_fragment(having, "HAVING")
    _validate_sql_fragment(order_by, "ORDER BY")

    fq = f"{_quote_ident(schema)}.{_quote_ident(table)}"

    sql = [f"SELECT {select_list}", f"FROM {fq}"]
    if where:
        sql.append(f"WHERE {where}")
    if group_by:
        sql.append(f"GROUP BY {group_by}")
    if having:
        sql.append(f"HAVING {having}")
    if order_by:
        sql.append(f"ORDER BY {order_by}")
    sql.append(f"LIMIT {int(limit)}")
    return "\n".join(sql)


# -----------------------
# Snapshot (existing)
# -----------------------

def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _parse_snapshot_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _human_bytes(n: Any) -> str:
    try:
        x = float(n)
    except Exception:
        return "None"
    if x < 0:
        return str(n)
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    i = 0
    while x >= 1024.0 and i < len(units) - 1:
        x /= 1024.0
        i += 1
    if i == 0:
        return f"{int(x)} {units[i]}"
    return f"{x:.2f} {units[i]}"


def _snapshot_check_summary(
    snap: Dict[str, Any],
    source: str,
    stale_days: int,
    min_rows: int,
    top_n: int,
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    tables: Dict[str, Any] = snap.get("tables", {}) or {}
    table_stats: Dict[str, Any] = snap.get("table_stats", {}) or {}
    top_col_stats: Dict[str, Any] = snap.get("top_col_stats", {}) or {}

    warnings: List[str] = []
    top_by_bytes: List[Dict[str, Any]] = []
    top_by_rows: List[Dict[str, Any]] = []

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=int(stale_days))

    for fq, tinfo in tables.items():
        if not isinstance(tinfo, dict):
            tinfo = {}
        approx_rows = _safe_int(tinfo.get("approx_rows", 0))

        stats = table_stats.get(fq, {}) or {}
        if not isinstance(stats, dict):
            stats = {}
        total_bytes = _safe_int(stats.get("total_bytes", 0))

        last_analyze = _parse_snapshot_ts(stats.get("last_analyze"))
        last_autoanalyze = _parse_snapshot_ts(stats.get("last_autoanalyze"))

        col_stats = top_col_stats.get(fq, [])
        has_col_stats = isinstance(col_stats, list) and len(col_stats) > 0

        if approx_rows >= min_rows:
            if not has_col_stats:
                warnings.append(f"{fq}: pg_stats missing")

                # IMPORTANT: Option B (low noise)
                # Only care about analyze timestamps when pg_stats is missing.
                if last_analyze is None and last_autoanalyze is None:
                    warnings.append(f"{fq}: no analyze timestamps")
                else:
                    latest = max(x for x in (last_analyze, last_autoanalyze) if x is not None)
                    if latest < stale_cutoff:
                        warnings.append(f"{fq}: stale analyze")

        top_by_bytes.append(
            {"table": fq, "total_bytes": total_bytes, "human": _human_bytes(total_bytes)}
        )
        top_by_rows.append({"table": fq, "approx_rows": approx_rows})

    top_by_bytes.sort(key=lambda x: x.get("total_bytes", 0), reverse=True)
    top_by_rows.sort(key=lambda x: x.get("approx_rows", 0), reverse=True)
    warnings = list(dict.fromkeys(warnings))
    warnings.sort()

    return {
        "meta": meta,
        "ok": True,
        "source": source,
        "warnings": warnings,
        "top_tables_by_total_bytes": top_by_bytes[: max(0, int(top_n))],
        "top_tables_by_rows": top_by_rows[: max(0, int(top_n))],
    }

def _rows_to_dicts(out: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Normalize _execute_sql output rows to list[dict] for both psycopg v3 (tuples)
    and psycopg2 RealDictCursor (dicts).
    """
    rows = out.get("rows") or []
    if not rows:
        return []
    if isinstance(rows[0], dict):
        return rows  # type: ignore[return-value]

    cols = out.get("columns") or []
    out_rows: List[Dict[str, Any]] = []
    for row in rows:
        d = {cols[i]: row[i] for i in range(min(len(cols), len(row)))}
        out_rows.append(d)
    return out_rows

def _snapshot_db(cfg: DbConfig, repo_root: Path) -> Dict[str, Any]:
    """
    Build a schema snapshot across all non-system schemas.
    Captures: schemas, tables, columns, indexes, constraints, approx row counts.
    """
    snap: Dict[str, Any] = {
        "meta": {
            "db_url_redacted": _redact_url(cfg.url),
            "statement_timeout_ms": cfg.statement_timeout_ms,
            "idle_in_transaction_session_timeout_ms": cfg.idle_in_tx_timeout_ms,
            "default_row_limit": cfg.row_limit,
            "psycopg_v3": _PSYCOPG_V3,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "repo_root": str(repo_root),
        },
        "schemas": [],
        "tables": {},       # key: "schema.table"
        "columns": {},      # key: "schema.table" -> list[columns]
        "indexes": {},      # key: "schema.table" -> list[index defs]
        "table_stats": {},  # key: "schema.table" -> size + last analyze/vacuum
        "top_col_stats": {},    # key: "schema.table" -> list of column stats (top N)
        "constraints": {},  # key: "schema.table" -> list[constraint names/types]
        "keys": {},         # key: "schema.table" -> pk/unique cols
    }

    sch = _execute_sql(cfg, schema_overview_sql())
    if not sch.get("ok"):
        snap["error"] = sch.get("error")
        return snap

    sch_rows = _rows_to_dicts(sch)
    schemas: List[str] = [x for x in (r.get("schema") for r in sch_rows) if isinstance(x, str)]
    snap["schemas"] = schemas

    tbls = _execute_sql(cfg, list_tables_sql(None))
    if not tbls.get("ok"):
        snap["error"] = tbls.get("error")
        return snap

    tbl_rows = _rows_to_dicts(tbls)

    pairs: List[Tuple[str, str, int]] = []
    for r in tbl_rows:
        s = r.get("schema")
        t = r.get("table_name")
        if isinstance(s, str) and isinstance(t, str) and s in schemas:
            pairs.append((s, t, int(r.get("approx_rows", 0) or 0)))

    # ---- table_stats (one query across all tables) ----
    ts_out = _execute_sql(cfg, table_stats_sql())
    if ts_out.get("ok"):
        for row in (ts_out.get("rows") or []):
            # psycopg2 RealDictCursor returns dict-like rows; psycopg v3 may return tuples
            if isinstance(row, dict):
                schema = row.get("schema")
                table = row.get("table_name")
                fq = f"{schema}.{table}"
                snap["table_stats"][fq] = row
            else:
                cols = ts_out.get("columns", []) or []
                d = {cols[i]: row[i] for i in range(min(len(cols), len(row)))}
                schema = d.get("schema")
                table = d.get("table_name")
                fq = f"{schema}.{table}"
                snap["table_stats"][fq] = d
    else:
        # keep table_stats a dict keyed by fq; store error separately to avoid shape changes
        snap["table_stats_error"] = ts_out.get("error")

    # ---- col_stats limit (define once) ----
    COL_STATS_LIMIT = 20

    for s, t, approx_rows in pairs:
        key = f"{s}.{t}"
        snap["tables"][key] = {"schema": s, "table": t, "approx_rows": approx_rows}

        desc = _execute_sql(cfg, describe_table_sql(s, t), params=[s, t])
        snap["columns"][key] = _rows_to_dicts(desc) if desc.get("ok") else {"error": desc.get("error")}

        # ---- col_stats (pg_stats) per table ----
        cs_out = _execute_sql(cfg, col_stats_sql(), params=[s, t, COL_STATS_LIMIT])
        if cs_out.get("ok"):
            rows_out: List[Dict[str, Any]] = []
            for row in (cs_out.get("rows") or []):
                if isinstance(row, dict):
                    rows_out.append(row)
                else:
                    cols = cs_out.get("columns", []) or []
                    rows_out.append({cols[i]: row[i] for i in range(min(len(cols), len(row)))})
            snap["top_col_stats"][key] = rows_out
        else:
            snap["top_col_stats"][key] = {"error": cs_out.get("error")}

        idx = _execute_sql(cfg, indexes_detail_sql(s, t), params=[s, t])
        snap["indexes"][key] = _rows_to_dicts(idx) if idx.get("ok") else {"error": idx.get("error")}

        con = _execute_sql(cfg, constraints_sql(s, t), params=[s, t])
        snap["constraints"][key] = _rows_to_dicts(con) if con.get("ok") else {"error": con.get("error")}

        k = _execute_sql(cfg, keys_sql(s, t), params=[s, t])
        snap["keys"][key] = _rows_to_dicts(k) if k.get("ok") else {"error": k.get("error")}

    return snap

def _md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def _render_snapshot_md(snap: Dict[str, Any]) -> str:
    """
    Render db_schema_snapshot.json into a compact, grep-friendly Markdown doc.

    Structure:
      1) Header + metadata
      2) Quick navigation (anchors)
      3) Top tables by approx_rows (top 25)
      4) Tables by schema (with approx_rows + links)
      5) Per-table sections (anchors) for every schema.table
    """
    lines: List[str] = []
    meta = snap.get("meta", {}) or {}

    schemas = snap.get("schemas", []) or []
    tables: Dict[str, Any] = snap.get("tables", {}) or {}
    columns: Dict[str, Any] = snap.get("columns", {}) or {}
    indexes: Dict[str, Any] = snap.get("indexes", {}) or {}
    constraints: Dict[str, Any] = snap.get("constraints", {}) or {}
    keys: Dict[str, Any] = snap.get("keys", {}) or {}
    table_stats: Dict[str, Any] = snap.get("table_stats", {}) or {}
    top_col_stats: Dict[str, Any] = snap.get("top_col_stats", {}) or {}

    def sort_key(fq: str) -> tuple[str, str]:
        if "." in fq:
            a, b = fq.split(".", 1)
            return (a, b)
        return ("", fq)

    def _anchor(fq: str) -> str:
        # GitHub-style-ish anchor: "public.cmc_ema" -> "public-cmc-ema"
        # We also emit explicit <a id="..."> to avoid renderer differences.
        return re.sub(r"[^a-z0-9]+", "-", fq.lower()).strip("-")

    def _schema_of(fq: str) -> str:
        return fq.split(".", 1)[0] if "." in fq else ""

    def _table_of(fq: str) -> str:
        return fq.split(".", 1)[1] if "." in fq else fq

    def _human_bytes(n: Any) -> str:
        try:
            x = float(n)
        except Exception:
            return "None"
        if x < 0:
            return str(n)
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        i = 0
        while x >= 1024.0 and i < len(units) - 1:
            x /= 1024.0
            i += 1
        if i == 0:
            return f"{int(x)} {units[i]}"
        return f"{x:.2f} {units[i]}"

    def _fmt_ts(v: Any) -> str:
        if v is None:
            return "None"
        return str(v)

    def _top_values(mcv: Any, n: int = 5, max_len: int = 80) -> str:
        if mcv is None:
            return ""
        vals: List[str] = []

        # If it’s already a list/tuple, use it
        if isinstance(mcv, (list, tuple)):
            vals = [str(x) for x in mcv[:n]]
        else:
            s = str(mcv).strip()
            # If it looks like "{...}", try to split on commas
            if s.startswith("{") and s.endswith("}"):
                inner = s[1:-1].strip()
                if inner:
                    vals = [x.strip().strip('"') for x in inner.split(",")[:n]]
            else:
                vals = [s[:max_len]]

        out = ", ".join(vals)
        if len(out) > max_len:
            out = out[: max_len - 3] + "..."
        return out

    # -------------------------
    # 1) Header + metadata
    # -------------------------
    lines.append("# DB Schema Snapshot")
    lines.append("")
    lines.append("## Meta")
    lines.append("")
    if meta.get("db_url_redacted") is not None:
        lines.append(f"- db_url: `{meta.get('db_url_redacted', '')}`")
    if meta.get("generated_at") is not None:
        lines.append(f"- generated_at: `{meta.get('generated_at', '')}`")
    if meta.get("repo_root") is not None:
        lines.append(f"- repo_root: `{meta.get('repo_root', '')}`")
    lines.append(f"- statement_timeout_ms: `{meta.get('statement_timeout_ms', '')}`")
    lines.append(
        f"- idle_in_transaction_session_timeout_ms: `{meta.get('idle_in_transaction_session_timeout_ms', meta.get('idle_in_tx_timeout_ms', ''))}`"
    )
    lines.append(f"- default_row_limit: `{meta.get('default_row_limit', meta.get('row_limit', ''))}`")
    lines.append(f"- psycopg_v3: `{meta.get('psycopg_v3', '')}`")
    lines.append("")

    # -------------------------
    # 2) Quick navigation
    # -------------------------
    lines.append("## Quick links")
    lines.append("")
    lines.append("- [Top tables by approx_rows](#top-tables-by-approx_rows)")
    lines.append("- [Schemas](#schemas)")
    lines.append("- [Tables (A–Z)](#tables-a-z)")
    lines.append("")

    # -------------------------
    # 3) Top tables by approx_rows
    # -------------------------
    lines.append("## Top tables by approx_rows")
    lines.append('<a id="top-tables-by-approx_rows"></a>')
    lines.append("")
    table_rows: List[tuple[str, int]] = []
    for fq, tinfo in tables.items():
        approx = (tinfo or {}).get("approx_rows", None)
        if approx is None:
            continue
        try:
            table_rows.append((fq, int(approx)))
        except Exception:
            continue
    table_rows.sort(key=lambda x: x[1], reverse=True)

    if table_rows:
        lines.append("| rank | table | approx_rows |")
        lines.append("|---:|---|---:|")
        for i, (fq, approx) in enumerate(table_rows[:25], start=1):
            a = _anchor(fq)
            lines.append(f"| {i} | [`{_md_escape(fq)}`](#{a}) | `{approx}` |")
    else:
        lines.append("_No approx_rows available in snapshot._")
    lines.append("")

    # -------------------------
    # 4) Schemas (simple list)
    # -------------------------
    lines.append("## Schemas")
    lines.append('<a id="schemas"></a>')
    lines.append("")
    if schemas:
        for s in schemas:
            lines.append(f"- `{_md_escape(str(s))}`")
    else:
        lines.append("_None_")
    lines.append("")

    # -------------------------
    # 4b) Tables by schema (with links + approx_rows)
    # -------------------------
    lines.append("## Tables by schema")
    lines.append("")
    by_schema: Dict[str, List[str]] = {}
    for fq in tables.keys():
        sch = _schema_of(fq) or "(unknown)"
        by_schema.setdefault(sch, []).append(fq)

    for sch in sorted(by_schema.keys()):
        lines.append(f"### `{_md_escape(sch)}`")
        lines.append("")
        fqs = sorted(by_schema[sch], key=sort_key)
        lines.append("| table | approx_rows |")
        lines.append("|---|---:|")
        for fq in fqs:
            tinfo = tables.get(fq, {}) or {}
            approx = tinfo.get("approx_rows", "")
            a = _anchor(fq)
            lines.append(f"| [`{_md_escape(_table_of(fq))}`](#{a}) | `{_md_escape(str(approx))}` |")
        lines.append("")

    # -------------------------
    # 4c) Tables (A–Z) quick list
    # -------------------------
    lines.append("## Tables (A–Z)")
    lines.append('<a id="tables-a-z"></a>')
    lines.append("")
    all_fq = sorted(tables.keys(), key=sort_key)
    if all_fq:
        for fq in all_fq:
            a = _anchor(fq)
            lines.append(f"- [`{_md_escape(fq)}`](#{a})")
    else:
        lines.append("_None_")
    lines.append("")

    # -------------------------
    # 5) Per-table sections (anchors)
    # -------------------------
    for fq in all_fq:
        tinfo = tables.get(fq, {}) or {}
        approx = tinfo.get("approx_rows", None)

        a = _anchor(fq)
        # Put the explicit anchor BEFORE the header (more renderer-proof)
        lines.append(f'<a id="{a}"></a>')
        lines.append(f"## `{_md_escape(fq)}`")

        if approx is not None:
            lines.append(f"- approx_rows: `{_md_escape(str(approx))}`")

        # -------------------------
        # Shape (sizes + analyze/vacuum)
        # -------------------------
        lines.append("### Shape")
        lines.append("")
        ts = table_stats.get(fq)

        if isinstance(ts, dict) and ts.get("error"):
            lines.append(f"- error: `{_md_escape(str(ts.get('error')) )}`")
        elif isinstance(ts, dict) and ts:
            total_b = ts.get("total_bytes")
            table_b = ts.get("table_bytes")
            index_b = ts.get("index_bytes")

            lines.append(f"- total_bytes: `{_md_escape(str(total_b))}` ({_md_escape(_human_bytes(total_b))})")
            lines.append(f"- table_bytes: `{_md_escape(str(table_b))}` ({_md_escape(_human_bytes(table_b))})")
            lines.append(f"- index_bytes: `{_md_escape(str(index_b))}` ({_md_escape(_human_bytes(index_b))})")
            lines.append("")
            lines.append(f"- last_analyze: `{_md_escape(_fmt_ts(ts.get('last_analyze')) )}`")
            lines.append(f"- last_autoanalyze: `{_md_escape(_fmt_ts(ts.get('last_autoanalyze')) )}`")
            lines.append(f"- last_vacuum: `{_md_escape(_fmt_ts(ts.get('last_vacuum')) )}`")
            lines.append(f"- last_autovacuum: `{_md_escape(_fmt_ts(ts.get('last_autovacuum')) )}`")
        else:
            lines.append("_None_")

        lines.append("")

        # -------------------------
        # Column stats (pg_stats)
        # -------------------------
        lines.append("### Column stats (pg_stats)")
        lines.append("")

        cs = top_col_stats.get(fq)
        if isinstance(cs, dict) and cs.get("error"):
            lines.append(f"- error: `{_md_escape(str(cs.get('error')) )}`")
        elif isinstance(cs, list) and cs:
            lines.append("| column_name | null_frac | n_distinct | top_values |")
            lines.append("|---|---:|---:|---|")
            for r in cs:
                col = str(r.get("column_name", ""))
                null_frac = r.get("null_frac", "")
                n_distinct = r.get("n_distinct", "")
                top_vals = _top_values(r.get("most_common_vals"), n=5, max_len=80)
                # Normalize newlines so the markdown table doesn't break
                top_vals = top_vals.replace("\n", " ").replace("\r", " ")
                lines.append(
                    f"| `{_md_escape(col)}` | `{_md_escape(str(null_frac))}` | `{_md_escape(str(n_distinct))}` | `{_md_escape(top_vals)}` |"
                )
        else:
            lines.append("_None_")

        lines.append("")
        lines.append("")

        # Keys (PK / unique constraints + columns)
        k = keys.get(fq)
        lines.append("### Keys")
        lines.append("")
        if isinstance(k, dict) and k.get("error"):
            lines.append(f"- error: `{_md_escape(str(k.get('error')) )}`")
        elif k:
            lines.append("| key_type | constraint_name | columns |")
            lines.append("|---|---|---|")
            for r in k:
                cols = r.get("columns", [])
                cols_s = ", ".join(str(x) for x in cols) if isinstance(cols, list) else str(cols)
                lines.append(
                    f"| `{_md_escape(str(r.get('key_type','')) )}` | `{_md_escape(str(r.get('constraint_name','')) )}` | `{_md_escape(cols_s)}` |"
                )
        else:
            lines.append("_None_")
        lines.append("")

        # Columns
        c = columns.get(fq)
        lines.append("### Columns")
        lines.append("")
        if isinstance(c, dict) and c.get("error"):
            lines.append(f"- error: `{_md_escape(str(c.get('error')) )}`")
        elif c:
            lines.append("| # | column_name | data_type | nullable | default |")
            lines.append("|---:|---|---|---|---|")
            for r in c:
                lines.append(
                    f"| {r.get('ordinal_position','')} | `{_md_escape(str(r.get('column_name','')) )}` | `{_md_escape(str(r.get('data_type','')) )}` | `{_md_escape(str(r.get('is_nullable','')) )}` | `{_md_escape(str(r.get('column_default','')) )}` |"
                )
        else:
            lines.append("_None_")
        lines.append("")

        # Indexes (method/type + uniqueness + predicate if partial)
        ix = indexes.get(fq)
        lines.append("### Indexes")
        lines.append("")
        if isinstance(ix, dict) and ix.get("error"):
            lines.append(f"- error: `{_md_escape(str(ix.get('error')) )}`")
        elif ix:
            lines.append("| index_name | method | unique | primary | predicate | definition |")
            lines.append("|---|---|---|---|---|---|")
            for r in ix:
                # Support both old/new shapes
                predicate = r.get("predicate", r.get("indpred", ""))
                lines.append(
                    f"| `{_md_escape(str(r.get('index_name','')) )}`"
                    f" | `{_md_escape(str(r.get('index_method','')) )}`"
                    f" | `{_md_escape(str(r.get('is_unique','')) )}`"
                    f" | `{_md_escape(str(r.get('is_primary','')) )}`"
                    f" | `{_md_escape(str(predicate) if predicate else 'None')}`"
                    f" | `{_md_escape(str(r.get('indexdef','')) )}` |"
                )
        else:
            lines.append("_None_")
        lines.append("")

        # Constraints summary (PK/FK/unique/check)
        con = constraints.get(fq)
        lines.append("### Constraints")
        lines.append("")
        if isinstance(con, dict) and con.get("error"):
            lines.append(f"- error: `{_md_escape(str(con.get('error')) )}`")
        elif con:
            lines.append("| constraint_type | constraint_name |")
            lines.append("|---|---|")
            for r in con:
                lines.append(
                    f"| `{_md_escape(str(r.get('constraint_type','')) )}` | `{_md_escape(str(r.get('constraint_name','')) )}` |"
                )
        else:
            lines.append("_None_")
        lines.append("")

    return "\n".join(lines) + "\n"

# -----------------------
# CLI
# -----------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = argv or sys.argv[1:]
    repo_root = _find_repo_root()
    _load_env_file_if_present(repo_root)

    p = argparse.ArgumentParser(prog="ta_lab2_dbtool", add_help=True)
    p.add_argument("--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS)
    p.add_argument("--idle-tx-timeout-ms", type=int, default=DEFAULT_IDLE_TX_TIMEOUT_MS)
    p.add_argument("--limit", type=int, default=DEFAULT_ROW_LIMIT)

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("schemas", help="List non-system schemas + counts")

    sp_tables = sub.add_parser("tables", help="List tables (optionally for one schema)")
    sp_tables.add_argument("--schema", type=str, default=None)

    sp_desc = sub.add_parser("describe", help="Describe columns for a table")
    sp_desc.add_argument("schema", type=str)
    sp_desc.add_argument("table", type=str)

    # upgraded: includes method/type/unique/primary
    sp_idx = sub.add_parser("indexes", help="Show index definitions for a table (incl. method/type)")
    sp_idx.add_argument("schema", type=str)
    sp_idx.add_argument("table", type=str)

    sp_con = sub.add_parser("constraints", help="Show constraints for a table")
    sp_con.add_argument("schema", type=str)
    sp_con.add_argument("table", type=str)

    # NEW: keys (PK + UNIQUE columns)
    sp_keys = sub.add_parser("keys", help="Show primary/unique keys (constraint + columns)")
    sp_keys.add_argument("schema", type=str)
    sp_keys.add_argument("table", type=str)

    sp_q = sub.add_parser("query", help="Run a read-only SQL query (SELECT/WITH/EXPLAIN only)")
    sp_q.add_argument("sql", type=str)

    sp_ex = sub.add_parser("explain", help="EXPLAIN (FORMAT JSON) for a read-only query")
    sp_ex.add_argument("sql", type=str)

    sp_prof = sub.add_parser("profile", help="Basic profile (rowcount + sample) for a table")
    sp_prof.add_argument("schema", type=str)
    sp_prof.add_argument("table", type=str)

    # NEW: profile-cols
    sp_pcols = sub.add_parser("profile-cols", help="Column-level profile via pg_stats (null_frac, n_distinct, MCV)")
    sp_pcols.add_argument("schema", type=str)
    sp_pcols.add_argument("table", type=str)

    # NEW: profile-time
    sp_ptime = sub.add_parser("profile-time", help="Time-series profile: min/max/count + bucketed counts + missing")
    sp_ptime.add_argument("schema", type=str)
    sp_ptime.add_argument("table", type=str)
    sp_ptime.add_argument("--ts-col", required=True, type=str, help="Timestamp column name (e.g., ts, time_close)")
    sp_ptime.add_argument("--bucket", default="day", type=str, help="hour|day|week|month (default: day)")
    sp_ptime.add_argument(
        "--max-buckets",
        default=2000,
        type=int,
        help="Compute missing buckets only if bucket range <= this value (default: 2000)",
    )

    # NEW: dupes
    sp_dupes = sub.add_parser("dupes", help="Duplicate probe: group by key columns, return keys with count>1")
    sp_dupes.add_argument("schema", type=str)
    sp_dupes.add_argument("table", type=str)
    sp_dupes.add_argument(
        "--key",
        required=True,
        type=str,
        help="Comma-separated key columns (e.g., id,tf,period,ts)",
    )

    # NEW: agg (single-table builder)
    sp_agg = sub.add_parser("agg", help="Single-table aggregation with where/group/having/order (read-only)")
    sp_agg.add_argument("schema", type=str)
    sp_agg.add_argument("table", type=str)
    sp_agg.add_argument(
        "--select",
        required=True,
        type=str,
        help="SELECT list (e.g., \"count(*) as n, min(ts) as min_ts\")",
    )
    sp_agg.add_argument("--where", default=None, type=str, help="WHERE clause (without 'WHERE')")
    sp_agg.add_argument("--group-by", default=None, type=str, help="GROUP BY clause (without 'GROUP BY')")
    sp_agg.add_argument("--having", default=None, type=str, help="HAVING clause (without 'HAVING')")
    sp_agg.add_argument("--order-by", default=None, type=str, help="ORDER BY clause (without 'ORDER BY')")
    sp_agg.add_argument(
        "--agg-limit",
        dest="agg_limit",
        default=None,
        type=int,
        help="Row limit for agg output (overrides global --limit)",
    )


    # snapshot
    sp_snap = sub.add_parser("snapshot", help="Write a DB schema snapshot JSON (all non-system schemas)")
    sp_snap.add_argument("--out", type=str, required=True, help="Output path (e.g., artifacts/db_schema_snapshot.json)")
    sp_snap_md = sub.add_parser("snapshot-md", help="Write a DB schema snapshot Markdown (optionally from JSON)")
    sp_snap_md.add_argument(
        "--in-path",
        dest="in_path",
        type=str,
        default=None,
        help="Optional input JSON snapshot path (if omitted, snapshot is generated live from DB)",
    )
    sp_snap_md.add_argument("--out", type=str, required=True, help="Output Markdown path (e.g., artifacts/db_schema_snapshot.md)")
    sp_snap_check = sub.add_parser("snapshot-check", help="Read a snapshot JSON and emit a compact health summary")
    sp_snap_check.add_argument("--in-path", dest="in_path", type=str, required=True, help="Input JSON snapshot path")
    sp_snap_check.add_argument("--stale-days", type=int, default=30, help="Warn if analyze older than N days (default: 30)")
    sp_snap_check.add_argument("--min-rows", type=int, default=100000, help="Row threshold for warnings (default: 100000)")
    sp_snap_check.add_argument("--top-n", type=int, default=20, help="Top N tables for size/row summaries (default: 20)")

    args = p.parse_args(argv)

    def dump(obj: Any) -> None:
        print(json.dumps(obj, indent=2, default=str))

    # -----------------------
    # DB-less commands
    # -----------------------
    meta_dbless = {
        "repo_root": str(repo_root),
        "db_url_redacted": None,
        "statement_timeout_ms": int(args.timeout_ms),
        "idle_in_transaction_session_timeout_ms": int(args.idle_tx_timeout_ms),
        "default_row_limit": int(args.limit),
        "psycopg_v3": _PSYCOPG_V3,
    }

    if args.cmd == "snapshot-check":
        in_path = Path(args.in_path)
        if not in_path.exists():
            dump({"meta": meta_dbless, "ok": False, "error": {"type": "FileNotFoundError", "message": str(in_path)}})
            return 2
        try:
            snap = json.loads(in_path.read_text(encoding="utf-8"))
        except Exception as e:
            dump({"meta": meta_dbless, "ok": False, "error": {"type": type(e).__name__, "message": str(e)}})
            return 2

        out = _snapshot_check_summary(
            snap,
            source=str(in_path),
            stale_days=int(args.stale_days),
            min_rows=int(args.min_rows),
            top_n=int(args.top_n),
            meta=meta_dbless,
        )
        dump(out)
        return 0

    # snapshot-md can run from JSON without DB access if --in-path is provided
    if args.cmd == "snapshot-md" and getattr(args, "in_path", None):
        in_path = Path(args.in_path)
        if not in_path.exists():
            dump({"meta": meta_dbless, "ok": False, "error": {"type": "FileNotFoundError", "message": str(in_path)}})
            return 2
        try:
            snap = json.loads(in_path.read_text(encoding="utf-8"))
        except Exception as e:
            dump({"meta": meta_dbless, "ok": False, "error": {"type": type(e).__name__, "message": str(e)}})
            return 2

        md = _render_snapshot_md(snap)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")

        dump({"meta": meta_dbless, "ok": True, "source": str(in_path), "wrote": str(out_path)})
        return 0

    # -----------------------
    # DB-required commands
    # -----------------------
    cfg = DbConfig(
        url=_resolve_db_url(),
        statement_timeout_ms=args.timeout_ms,
        idle_in_tx_timeout_ms=args.idle_tx_timeout_ms,
        row_limit=args.limit,
    )

    meta = {
        "repo_root": str(repo_root),
        "db_url_redacted": _redact_url(cfg.url),
        "statement_timeout_ms": cfg.statement_timeout_ms,
        "idle_in_transaction_session_timeout_ms": cfg.idle_in_tx_timeout_ms,
        "default_row_limit": cfg.row_limit,
        "psycopg_v3": _PSYCOPG_V3,
    }


    if args.cmd == "schemas":
        out = _execute_sql(cfg, schema_overview_sql())
        dump({"meta": meta, "result": out})
        return 0

    if args.cmd == "tables":
        if args.schema:
            out = _execute_sql(cfg, list_tables_sql(args.schema), params=[args.schema])
        else:
            out = _execute_sql(cfg, list_tables_sql(None))
        dump({"meta": meta, "result": out})
        return 0

    if args.cmd == "describe":
        out = _execute_sql(cfg, describe_table_sql(args.schema, args.table), params=[args.schema, args.table])
        dump({"meta": meta, "result": out})
        return 0

    if args.cmd == "indexes":
        out = _execute_sql(cfg, indexes_detail_sql(args.schema, args.table), params=[args.schema, args.table])
        dump({"meta": meta, "result": out})
        return 0

    if args.cmd == "constraints":
        out = _execute_sql(cfg, constraints_sql(args.schema, args.table), params=[args.schema, args.table])
        dump({"meta": meta, "result": out})
        return 0

    if args.cmd == "keys":
        out = _execute_sql(cfg, keys_sql(args.schema, args.table), params=[args.schema, args.table])
        dump({"meta": meta, "result": out})
        return 0

    if args.cmd == "query":
        out = _execute_sql(cfg, args.sql)
        dump({"meta": meta, "result": out})
        return 0

    if args.cmd == "explain":
        out = _execute_sql(cfg, explain_sql(args.sql))
        dump({"meta": meta, "result": out})
        return 0

    if args.cmd == "profile":
        results: Dict[str, Any] = {"meta": meta, "profile": []}
        for name, sql, params in profile_table_queries(args.schema, args.table):
            results["profile"].append({"name": name, "result": _execute_sql(cfg, sql, params=params)})
        dump(results)
        return 0

    if args.cmd == "profile-cols":
        out = _execute_sql(cfg, column_profile_sql(args.schema, args.table), params=[args.schema, args.table, args.schema, args.table])
        dump({"meta": meta, "result": out})
        return 0

    if args.cmd == "profile-time":
        sql, params = time_profile_sql(args.schema, args.table, args.ts_col, args.bucket, int(args.max_buckets))
        out = _execute_sql(cfg, sql, params=params)
        dump({"meta": meta, "result": out})
        return 0

    if args.cmd == "dupes":
        key_cols = [c.strip() for c in args.key.split(",") if c.strip()]
        if not key_cols:
            dump({"meta": meta, "result": {"ok": False, "error": {"type": "ValueError", "message": "Empty --key"}}})
            return 2
        sql = dupes_sql(args.schema, args.table, key_cols=key_cols, limit=cfg.row_limit)
        out = _execute_sql(cfg, sql)
        dump({"meta": meta, "result": out})
        return 0

    if args.cmd == "agg":
        # p_agg uses --limit as a command-level override; if omitted, use global cfg.row_limit
        lim = int(args.agg_limit) if args.agg_limit is not None else cfg.row_limit

        sql = agg_sql(
            args.schema,
            args.table,
            select_list=args.select,
            where=args.where,
            group_by=getattr(args, "group_by", None),
            having=args.having,
            order_by=getattr(args, "order_by", None),
            limit=lim,
        )
        out = _execute_sql(cfg, sql)
        dump({"meta": meta, "result": out})
        return 0

    if args.cmd == "snapshot":
        snap = _snapshot_db(cfg, repo_root)
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(snap, indent=2, default=str), encoding="utf-8")
        dump({"meta": meta, "ok": True, "wrote": str(out_path)})
        return 0

    if args.cmd == "snapshot-md":
        # If --in is provided, render from JSON. Otherwise, generate snapshot live.
        if args.in_path:
            in_path = Path(args.in_path)
            if not in_path.exists():
                dump({"meta": meta, "ok": False, "error": {"type": "FileNotFoundError", "message": str(in_path)}})
                return 2
            snap = json.loads(in_path.read_text(encoding="utf-8"))
            src = str(in_path)
        else:
            snap = _snapshot_db(cfg, repo_root)
            src = "live_db"

        md = _render_snapshot_md(snap)

        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")

        dump({"meta": meta, "ok": True, "source": src, "wrote": str(out_path)})
        return 0

    raise RuntimeError(f"Unknown cmd: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
