# test_bar_ohlc_correctness.py
from __future__ import annotations

import os
from typing import Any, List, Optional, Sequence, Tuple, Dict

import pytest

# Optional: Polars for nicer mismatch reporting (not required for correctness).
try:
    import polars as pl  # type: ignore

    HAVE_POLARS = True
except Exception:
    pl = None
    HAVE_POLARS = False

# Prefer psycopg (v3); fall back to psycopg2
try:
    import psycopg  # type: ignore

    PSYCOPG3 = True
except Exception:
    psycopg = None
    PSYCOPG3 = False

try:
    import psycopg2  # type: ignore

    PSYCOPG2 = True
except Exception:
    psycopg2 = None
    PSYCOPG2 = False


def _normalize_db_url(url: str) -> str:
    """
    psycopg2/psycopg want a plain Postgres URI (postgresql://.),
    but users often provide SQLAlchemy URLs like postgresql+psycopg2://.
    """
    if not url:
        return url

    replacements = (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql+psycopg3://",
        "postgres+psycopg2://",
        "postgres+psycopg://",
        "postgres+psycopg3://",
    )
    for prefix in replacements:
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix) :]
    return url


DB_URL = os.environ.get("TARGET_DB_URL") or os.environ.get("TA_LAB2_DB_URL") or ""
if not DB_URL:
    pytest.skip(
        "DB tests skipped: set TARGET_DB_URL (or TA_LAB2_DB_URL) to run.",
        allow_module_level=True,
    )

# --- Mode / window controls ---
MODE = (
    (
        os.environ.get("TA_LAB2_BAR_TEST_MODE")
        or os.environ.get("BARS_TEST_MODE")
        or "sample"
    )
    .strip()
    .lower()
)
assert MODE in {"sample", "full"}, "TA_LAB2_BAR_TEST_MODE must be 'sample' or 'full'"

TIME_MIN = os.environ.get("TA_LAB2_TEST_TIME_MIN") or os.environ.get(
    "BARS_TEST_TIME_MIN"
)
TIME_MAX = os.environ.get("TA_LAB2_TEST_TIME_MAX") or os.environ.get(
    "BARS_TEST_TIME_MAX"
)

MAX_BARS_PER_TF = int(os.environ.get("MAX_BARS_PER_TF", "200"))

# Missing-days policy:
# - "allow": don't fail missing-days bars
# - "skip":  skip missing-days bars entirely
# - "fail":  fail any missing-days bar
MISSING_DAYS_POLICY = os.environ.get("BARS_TEST_MISSING_DAYS", "allow").strip().lower()
assert MISSING_DAYS_POLICY in {"allow", "skip", "fail"}

# Tables under test
BAR_TABLES = [
    "public.cmc_price_bars_1d",
    "public.cmc_price_bars_multi_tf_cal_us",
    "public.cmc_price_bars_multi_tf_cal_iso",
    "public.cmc_price_bars_multi_tf_cal_anchor_us",
    "public.cmc_price_bars_multi_tf_cal_anchor_iso",
    "public.cmc_price_bars_multi_tf",
]

# Source daily table
SRC_TABLE = os.environ.get("SRC_TABLE", "public.cmc_price_histories7")


# -----------------------------------------------------------------------------
# DB helpers
# -----------------------------------------------------------------------------
def _connect():
    url = _normalize_db_url(DB_URL)
    if PSYCOPG3:
        # autocommit avoids idle-in-txn issues for read-only test runs
        return psycopg.connect(url, autocommit=True)
    if PSYCOPG2:
        conn = psycopg2.connect(url)
        conn.autocommit = True
        return conn
    raise RuntimeError("Neither psycopg (v3) nor psycopg2 is installed.")


def _fetchall(
    conn, sql: str, params: Optional[Sequence[Any]] = None
) -> List[Tuple[Any, ...]]:
    params = params or []
    if PSYCOPG3:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return rows


def _list_tfs(conn, bar_table: str) -> List[str]:
    sql = f"SELECT DISTINCT tf FROM {bar_table} ORDER BY tf"
    return [r[0] for r in _fetchall(conn, sql)]


def _has_column(conn, table: str, column: str) -> bool:
    schema, name = table.split(".", 1) if "." in table else ("public", table)
    rows = _fetchall(
        conn,
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
          AND lower(column_name) = lower(%s)
        LIMIT 1
        """,
        [schema, name, column],
    )
    return bool(rows)


def _pick_first_existing_column(
    conn, table: str, candidates: Sequence[str]
) -> Optional[str]:
    """
    Return the first column name (from candidates) that exists on table, else None.
    """
    for c in candidates:
        if _has_column(conn, table, c):
            return c
    return None


# Resolve SRC_TABLE column names so the SQL works for either histories7-style
# (timestamp only) or bars-style (time_open/time_close/time_high/time_low).
def _resolve_src_cols(conn, src_table: str) -> Dict[str, str]:
    """
    Return a mapping of canonical source roles -> actual column names in SRC_TABLE.

    Canonical roles used by mismatch SQL:
      ts, time_open, time_close, th, tl, o, h, l, c
    """
    schema, name = (
        src_table.split(".", 1) if "." in src_table else ("public", src_table)
    )

    rows = _fetchall(
        conn,
        """
        SELECT lower(column_name)
        FROM information_schema.columns
        WHERE table_schema = %s
          AND table_name = %s
        """,
        [schema, name],
    )
    cols = {r[0] for r in rows}

    def pick_optional(*candidates: str) -> Optional[str]:
        for c in candidates:
            if c.lower() in cols:
                return c
        return None

    def require(*candidates: str) -> str:
        v = pick_optional(*candidates)
        if v is None:
            raise RuntimeError(
                f"SRC_TABLE={src_table} missing expected columns; tried: {candidates}"
            )
        return v

    # Always require timestamp and OHLC
    ts_col = "timestamp" if "timestamp" in cols else require("timestamp")
    o_col = require("open")
    h_col = require("high")
    l_col = require("low")
    c_col = require("close")

    # Prefer bar-style time columns when available; else fall back to timestamp
    time_open_col = pick_optional("timeopen", "time_open")
    time_close_col = pick_optional("timeclose", "time_close")
    th_col = pick_optional("timehigh", "time_high")
    tl_col = pick_optional("timelow", "time_low")

    # For raw sources, treat all time roles as timestamp
    if time_open_col is None:
        time_open_col = ts_col
    if time_close_col is None:
        time_close_col = ts_col
    if th_col is None:
        th_col = ts_col
    if tl_col is None:
        tl_col = ts_col

    return {
        "ts": f'"{ts_col}"',
        "time_open": time_open_col,
        "time_close": time_close_col,
        "th": th_col,
        "tl": tl_col,
        "o": o_col,
        "h": h_col,
        "l": l_col,
        "c": c_col,
    }


# -----------------------------------------------------------------------------
# Set-based (batch) validation query
# -----------------------------------------------------------------------------
# Key fix for multi_tf snapshots:
#   expectations must be computed per BAR ROW, not per (id, tf, bar_seq).
#   We use (id, tf, bar_seq, time_close) as the per-row key so snapshot rows
#   (different time_close within the same bar_seq) validate against their own window.
def _mismatch_sql(
    bar_table: str,
    *,
    src_cols: Dict[str, str],
    cutoff_col: Optional[str],
) -> str:
    """
    Return ONLY failing rows for one (bar_table, tf) selection.
    """

    def qident(col: str) -> str:
        return f'"{col}"'

    cutoff_expr = qident(cutoff_col) if cutoff_col else "NULL"
    eff_close_expr = f"""
      CASE
        WHEN {cutoff_expr} IS NOT NULL THEN LEAST(time_close, {cutoff_expr})
        ELSE time_close
      END
    """

    return f"""
WITH bars AS (
  SELECT
    id, tf, bar_seq,
    "timestamp", time_open, time_close, time_high, time_low,
    open  AS open_got,
    high  AS high_got,
    low   AS low_got,
    close AS close_got,
    is_partial_start, is_partial_end, is_missing_days,
    {cutoff_expr} AS cutoff_ts,
    {eff_close_expr} AS eff_close
  FROM {bar_table}
  WHERE tf = %s
    AND (%s IS NULL OR "timestamp" >= %s)
    AND (%s IS NULL OR "timestamp" <  %s)
    AND (%s <> 'skip' OR NOT is_missing_days)
  ORDER BY id, bar_seq DESC, "timestamp" DESC
  {{limit_clause}}
),

d AS (
  SELECT
    b.id, b.tf, b.bar_seq, b."timestamp",
    b.time_open, b.time_close, b.eff_close,
    b.time_high AS time_high_got,
    b.time_low  AS time_low_got,
    b.open_got, b.high_got, b.low_got, b.close_got,
    b.is_missing_days,

    s.{src_cols["ts"]} AS ts,

    s.{src_cols["o"]} AS o,
    s.{src_cols["c"]} AS c,

    -- repaired (time_high, high)
    CASE
      WHEN s.{src_cols["th"]} IS NULL
        OR s.{src_cols["th"]} < s.{src_cols["time_open"]}
        OR s.{src_cols["th"]} > s.{src_cols["time_close"]}
      THEN CASE WHEN s.{src_cols["c"]} >= s.{src_cols["o"]}
                THEN s.{src_cols["time_close"]}
                ELSE s.{src_cols["time_open"]}
           END
      ELSE s.{src_cols["th"]}
    END AS th,

    CASE
      WHEN s.{src_cols["th"]} IS NULL
        OR s.{src_cols["th"]} < s.{src_cols["time_open"]}
        OR s.{src_cols["th"]} > s.{src_cols["time_close"]}
      THEN GREATEST(s.{src_cols["o"]}, s.{src_cols["c"]})
      ELSE s.{src_cols["h"]}
    END AS h,

    -- repaired (time_low, low)
    CASE
      WHEN s.{src_cols["tl"]} IS NULL
        OR s.{src_cols["tl"]} < s.{src_cols["time_open"]}
        OR s.{src_cols["tl"]} > s.{src_cols["time_close"]}
      THEN CASE WHEN s.{src_cols["c"]} <= s.{src_cols["o"]}
                THEN s.{src_cols["time_close"]}
                ELSE s.{src_cols["time_open"]}
           END
      ELSE s.{src_cols["tl"]}
    END AS tl,

    CASE
      WHEN s.{src_cols["tl"]} IS NULL
        OR s.{src_cols["tl"]} < s.{src_cols["time_open"]}
        OR s.{src_cols["tl"]} > s.{src_cols["time_close"]}
      THEN LEAST(s.{src_cols["o"]}, s.{src_cols["c"]})
      ELSE s.{src_cols["l"]}
    END AS l

  FROM bars b
  JOIN {SRC_TABLE} s
    ON s.id = b.id
   AND s.{src_cols["ts"]} >= b.time_open
   AND s.{src_cols["ts"]} <= b.eff_close
),

open_rows AS (
  SELECT DISTINCT ON (id, tf, bar_seq, "timestamp")
    id, tf, bar_seq, "timestamp",
    o AS open_exp
  FROM d
  ORDER BY id, tf, bar_seq, "timestamp", ts ASC
),

close_rows AS (
  SELECT DISTINCT ON (id, tf, bar_seq, "timestamp")
    id, tf, bar_seq, "timestamp",
    c AS close_exp
  FROM d
  ORDER BY id, tf, bar_seq, "timestamp", ts DESC
),

agg AS (
  SELECT
    id, tf, bar_seq, "timestamp",
    max(h) AS high_exp,
    min(l) AS low_exp,
    max(h) AS max_high,
    min(l) AS min_low,
    count(*) AS n_src
  FROM d
  GROUP BY id, tf, bar_seq, "timestamp"
),

base AS (
  SELECT
    a.id, a.tf, a.bar_seq, a."timestamp",
    a.n_src,
    o.open_exp,
    c.close_exp,
    a.high_exp,
    a.low_exp,
    a.max_high,
    a.min_low
  FROM agg a
  JOIN open_rows o USING (id, tf, bar_seq, "timestamp")
  JOIN close_rows c USING (id, tf, bar_seq, "timestamp")
),

tie AS (
  SELECT
    d.id, d.tf, d.bar_seq, d."timestamp",
    min(d.th) FILTER (WHERE d.h = b.max_high) AS time_high_exp,
    min(d.tl) FILTER (WHERE d.l = b.min_low)  AS time_low_exp
  FROM d
  JOIN base b USING (id, tf, bar_seq, "timestamp")
  GROUP BY d.id, d.tf, d.bar_seq, d."timestamp"
),

exp AS (
  SELECT
    b.id, b.tf, b.bar_seq, b."timestamp",
    b.n_src,
    b.open_exp, b.close_exp, b.high_exp, b.low_exp,
    t.time_high_exp, t.time_low_exp
  FROM base b
  JOIN tie t USING (id, tf, bar_seq, "timestamp")
),

joined AS (
  SELECT
    g.id, g.tf, g.bar_seq,
    g.time_open, g.time_close, g.eff_close,
    g.open_got, g.close_got, g.high_got, g.low_got,
    g.time_high AS time_high_got,
    g.time_low  AS time_low_got,
    g.is_partial_start, g.is_partial_end, g.is_missing_days,
    e.n_src,
    e.open_exp, e.close_exp, e.high_exp, e.low_exp,
    e.time_high_exp, e.time_low_exp
  FROM bars g
  LEFT JOIN exp e USING (id, tf, bar_seq, "timestamp")
)

SELECT
  CASE
    WHEN is_missing_days AND %s = 'fail' THEN 'missing_days'
    WHEN n_src IS NULL OR n_src = 0 THEN 'no_source_rows'
    WHEN time_high_got IS NULL OR time_low_got IS NULL THEN 'null_time_high_low'
    WHEN NOT (time_open <= time_high_got AND time_high_got <= eff_close) THEN 'time_high_outside_window'
    WHEN NOT (time_open <= time_low_got  AND time_low_got  <= eff_close) THEN 'time_low_outside_window'
    WHEN open_got  IS DISTINCT FROM open_exp  THEN 'open_mismatch'
    WHEN close_got IS DISTINCT FROM close_exp THEN 'close_mismatch'
    WHEN high_got  IS DISTINCT FROM high_exp  THEN 'high_mismatch'
    WHEN low_got   IS DISTINCT FROM low_exp   THEN 'low_mismatch'
    WHEN time_high_got IS DISTINCT FROM time_high_exp THEN 'time_high_mismatch'
    WHEN time_low_got  IS DISTINCT FROM time_low_exp  THEN 'time_low_mismatch'
    ELSE NULL
  END AS reason,
  *
FROM joined
WHERE
  (is_missing_days AND %s = 'fail')
  OR (n_src IS NULL OR n_src = 0)
  OR (time_high_got IS NULL OR time_low_got IS NULL)
  OR NOT (time_open <= time_high_got AND time_high_got <= eff_close)
  OR NOT (time_open <= time_low_got  AND time_low_got  <= eff_close)
  OR (open_got  IS DISTINCT FROM open_exp)
  OR (close_got IS DISTINCT FROM close_exp)
  OR (high_got  IS DISTINCT FROM high_exp)
  OR (low_got   IS DISTINCT FROM low_exp)
  OR (time_high_got IS DISTINCT FROM time_high_exp)
  OR (time_low_got  IS DISTINCT FROM time_low_exp)
ORDER BY id, bar_seq DESC, "timestamp" DESC;
"""


def _select_limit_clause() -> str:
    if MODE == "sample":
        return f"LIMIT {MAX_BARS_PER_TF}"
    return ""


def pytest_generate_tests(metafunc):
    if "bar_table" in metafunc.fixturenames and "tf_value" in metafunc.fixturenames:
        conn = _connect()
        try:
            pairs: List[Tuple[str, str]] = []
            for t in BAR_TABLES:
                tfs = _list_tfs(conn, t)
                for tf in tfs:
                    pairs.append((t, tf))
        finally:
            conn.close()

        metafunc.parametrize("bar_table,tf_value", pairs)


def _format_mismatches(
    rows: List[Tuple[Any, ...]], cols: List[str], max_rows: int = 30
) -> str:
    if not rows:
        return ""

    if HAVE_POLARS:
        df = pl.DataFrame(rows, schema=cols)  # type: ignore[arg-type]
        df2 = df.head(max_rows)
        return df2.__repr__() + (
            "" if df.height <= max_rows else f"\n... ({df.height - max_rows} more rows)"
        )
    lines = []
    for r in rows[:max_rows]:
        d = dict(zip(cols, r))
        lines.append(
            f"reason={d.get('reason')} id={d.get('id')} tf={d.get('tf')} bar_seq={d.get('bar_seq')} "
            f"timestamp={d.get('timestamp')} "
            f"got_ohlc=({d.get('open_got')},{d.get('high_got')},{d.get('low_got')},{d.get('close_got')}) "
            f"exp_ohlc=({d.get('open_exp')},{d.get('high_exp')},{d.get('low_exp')},{d.get('close_exp')})"
        )
    if len(rows) > max_rows:
        lines.append(f"... ({len(rows) - max_rows} more rows)")
    return "\n".join(lines)


def test_bar_ohlc_correctness(bar_table: str, tf_value: str) -> None:
    conn = _connect()
    try:
        src_cols = _resolve_src_cols(conn, SRC_TABLE)

        cutoff_col = _pick_first_existing_column(
            conn,
            bar_table,
            [
                "last_ts_half_open",
                "last_ts_inclusive",
                "last_ts",
                "last_ts_at_close",
                "timestamp",  # fallback for snapshot tables that store row snapshot time
            ],
        )

        sql = _mismatch_sql(
            bar_table, src_cols=src_cols, cutoff_col=cutoff_col
        ).replace("{limit_clause}", _select_limit_clause())

        params: List[Any] = [
            tf_value,
            TIME_MIN,
            TIME_MIN,
            TIME_MAX,
            TIME_MAX,
            MISSING_DAYS_POLICY,
            MISSING_DAYS_POLICY,
            MISSING_DAYS_POLICY,
        ]

        if PSYCOPG3:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
                cols = [d.name for d in cur.description]
        else:
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            cur.close()

        if not rows:
            where = ["tf = %s"]
            p2: List[Any] = [tf_value]
            if TIME_MIN:
                where.append('"timestamp" >= %s')
                p2.append(TIME_MIN)
            if TIME_MAX:
                where.append('"timestamp" < %s')
                p2.append(TIME_MAX)
            if MISSING_DAYS_POLICY == "skip":
                where.append("NOT is_missing_days")

            q = f"SELECT 1 FROM {bar_table} WHERE " + " AND ".join(where)
            if MODE == "sample":
                q += f" LIMIT {MAX_BARS_PER_TF}"
            any_rows = _fetchall(conn, q, p2)
            if not any_rows:
                pytest.skip(
                    f"No bars for {bar_table} tf={tf_value} under current filters. "
                    f"MODE={MODE} TIME_MIN={TIME_MIN} TIME_MAX={TIME_MAX} "
                    f"MAX_BARS_PER_TF={MAX_BARS_PER_TF} MISSING_DAYS_POLICY={MISSING_DAYS_POLICY}"
                )
            return

        msg = _format_mismatches(rows, cols, max_rows=30)
        pytest.fail(
            f"{bar_table}: {len(rows)} invariant failure(s) for tf={tf_value} "
            f"(MODE={MODE} TIME_MIN={TIME_MIN} TIME_MAX={TIME_MAX} MAX_BARS_PER_TF={MAX_BARS_PER_TF} "
            f"MISSING_DAYS_POLICY={MISSING_DAYS_POLICY})\n\n{msg}"
        )

    finally:
        conn.close()


# -----------------------------------------------------------------------------
# Speed tips (no behavior change)
# -----------------------------------------------------------------------------
# 1) Install pytest-xdist and run in parallel across (bar_table, tf):
#      pytest -n auto -k bar_ohlc_correctness
#
# 2) Ensure you have these indexes (if not already present):
#      -- source table (range join)
#      CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_cmc_price_histories7_id_ts
#        ON public.cmc_price_histories7 (id, "timestamp");
#
#      -- bar tables (sampling)
#      CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_<bars>_tf_timestamp
#        ON <bars_table> (tf, "timestamp" DESC);
# -----------------------------------------------------------------------------
