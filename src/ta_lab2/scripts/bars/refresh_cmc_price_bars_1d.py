from __future__ import annotations
r"""
Full rebuild of public.cmc_price_bars_1d (DROP + rebuild):
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py --rebuild --keep-rejects --fail-on-rejects

Incremental (default behavior):
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py --keep-rejects

Incremental for a single id:
python src/ta_lab2/scripts/bars/refresh_cmc_price_bars_1d.py --ids 1 --keep-rejects
"""
import argparse
import os
from dataclasses import dataclass
from typing import Any, Optional, Sequence, List, Tuple

# Prefer psycopg v3, fall back to psycopg2
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
    if not url:
        return url
    for prefix in (
        "postgresql+psycopg2://",
        "postgresql+psycopg://",
        "postgresql+psycopg3://",
        "postgres+psycopg2://",
        "postgres+psycopg://",
        "postgres+psycopg3://",
    ):
        if url.startswith(prefix):
            return "postgresql://" + url[len(prefix):]
    return url


def _connect(db_url: str):
    url = _normalize_db_url(db_url)
    if PSYCOPG3:
        return psycopg.connect(url, autocommit=True)
    if PSYCOPG2:
        conn = psycopg2.connect(url)
        conn.autocommit = True
        return conn
    raise RuntimeError("Neither psycopg (v3) nor psycopg2 is installed.")


def _exec(conn, sql: str, params: Optional[Sequence[Any]] = None) -> None:
    params = params or []
    if PSYCOPG3:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return
    cur = conn.cursor()
    cur.execute(sql, params)
    cur.close()


def _fetchall(conn, sql: str, params: Optional[Sequence[Any]] = None) -> List[Tuple[Any, ...]]:
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


def _fetchone(conn, sql: str, params: Optional[Sequence[Any]] = None) -> Optional[Tuple[Any, ...]]:
    params = params or []
    if PSYCOPG3:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    cur.close()
    return row


# -----------------------------------------------------------------------------
# DDL
# -----------------------------------------------------------------------------

DDL_DROP_DST = """
DROP TABLE IF EXISTS {dst};
"""

DDL_DROP_STATE = """
DROP TABLE IF EXISTS {state};
"""

DDL_DROP_REJECTS = """
DROP TABLE IF EXISTS {rej};
"""

DDL_CREATE_DST = """
CREATE TABLE IF NOT EXISTS {dst} (
  id          integer NOT NULL,
  "timestamp" timestamptz NOT NULL,

  tf          text NOT NULL,
  bar_seq     bigint NOT NULL,

  time_open   timestamptz NOT NULL,
  time_close  timestamptz NOT NULL,
  time_high   timestamptz NOT NULL,
  time_low    timestamptz NOT NULL,

  open   double precision NOT NULL,
  high   double precision NOT NULL,
  low    double precision NOT NULL,
  close  double precision NOT NULL,
  volume     double precision NOT NULL,
  market_cap double precision NOT NULL,

  -- NEW: columns expected by test_bar_ohlc_correctness.py
  is_partial_start boolean NOT NULL DEFAULT false,
  is_partial_end   boolean NOT NULL DEFAULT false,
  is_missing_days  boolean NOT NULL DEFAULT false,

  src_name     text,
  src_load_ts  timestamptz,
  src_file     text,

  repaired_timehigh boolean NOT NULL DEFAULT false,
  repaired_timelow  boolean NOT NULL DEFAULT false,

  PRIMARY KEY (id, "timestamp")
);

-- Optional but very useful: guarantee (id, tf, bar_seq) uniqueness for bar semantics
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'cmc_price_bars_1d_id_tf_bar_seq_uniq'
  ) THEN
    ALTER TABLE {dst}
      ADD CONSTRAINT cmc_price_bars_1d_id_tf_bar_seq_uniq UNIQUE (id, tf, bar_seq);
  END IF;
END $$;
"""

DDL_CREATE_REJECTS = """
CREATE TABLE IF NOT EXISTS {rej} (
  id          integer,
  "timestamp" timestamptz,

  tf      text,
  bar_seq bigint,

  reason      text NOT NULL,

  time_open   timestamptz,
  time_close  timestamptz,
  time_high   timestamptz,
  time_low    timestamptz,

  open   double precision,
  high   double precision,
  low    double precision,
  close  double precision,
  volume     double precision,
  market_cap double precision,

  -- NEW: carry these through for rejects too (handy for debugging)
  is_partial_start boolean,
  is_partial_end   boolean,
  is_missing_days  boolean,

  src_name    text,
  src_load_ts timestamptz,
  src_file    text
);
"""

DDL_CREATE_STATE = """
CREATE TABLE IF NOT EXISTS {state} (
  id integer PRIMARY KEY,

  last_src_ts timestamptz,             -- max src."timestamp" processed for this id (after lookback)
  last_run_ts timestamptz NOT NULL DEFAULT now(),

  last_upserted integer NOT NULL DEFAULT 0,
  last_repaired_timehigh integer NOT NULL DEFAULT 0,
  last_repaired_timelow  integer NOT NULL DEFAULT 0,
  last_rejected integer NOT NULL DEFAULT 0
);
"""

DDL_TRUNCATE_REJECTS = """
TRUNCATE TABLE {rej};
"""


# -----------------------------------------------------------------------------
# SQL building blocks
# -----------------------------------------------------------------------------

def _parse_ids_arg(ids_arg: str) -> Optional[List[int]]:
    s = (ids_arg or "").strip().lower()
    if s in ("", "all"):
        return None
    out: List[int] = []
    for part in s.split(","):
        p = part.strip()
        if not p:
            continue
        out.append(int(p))
    return out


def _list_all_ids(conn, src: str) -> List[int]:
    rows = _fetchall(conn, f"SELECT DISTINCT id FROM {src} ORDER BY id;")
    return [int(r[0]) for r in rows]


def _get_last_src_ts(conn, state: str, id_: int) -> Optional[str]:
    row = _fetchone(conn, f"SELECT last_src_ts FROM {state} WHERE id = %s;", [id_])
    if not row or row[0] is None:
        return None
    return str(row[0])


@dataclass(frozen=True)
class RunWindow:
    effective_min_ts: Optional[str]
    effective_max_ts: Optional[str]


def _compute_effective_window(
    *,
    last_src_ts: Optional[str],
    time_min: Optional[str],
    time_max: Optional[str],
    lookback_days: int,
) -> RunWindow:
    return RunWindow(effective_min_ts=time_min, effective_max_ts=time_max)


def _insert_valid_and_return_stats_sql(dst: str, src: str) -> str:
    """
    One statement:
      - selects src rows for a single id within window
      - computes tf + bar_seq deterministically
      - applies repair expression
      - re-enforces OHLC invariants
      - upserts into dst
      - returns aggregate stats: upserted, repaired_hi, repaired_lo, max_src_ts
    """
    return f"""
WITH ranked_all AS (
  SELECT
    s.id,
    s."timestamp",
    dense_rank() OVER (PARTITION BY s.id ORDER BY s."timestamp" ASC)::bigint AS bar_seq
  FROM {src} s
  WHERE s.id = %s
    AND (%s IS NULL OR s."timestamp" < %s)
),
src_rows AS (
  SELECT
    s.id,
    s.name,
    s.source_file,
    s.load_ts,

    s.timeopen  AS time_open,
    s.timeclose AS time_close,
    s.timehigh  AS time_high,
    s.timelow   AS time_low,

    s."timestamp",

    s.open,
    s.high,
    s.low,
    s.close,
    s.volume,
    s.marketcap AS market_cap,

    r.bar_seq
  FROM {src} s
  JOIN ranked_all r
    ON r.id = s.id
   AND r."timestamp" = s."timestamp"
  WHERE s.id = %s
    AND (%s IS NULL OR s."timestamp" >= %s)
    AND (%s IS NULL OR s."timestamp" <  %s)
    AND (
      %s IS NULL
      OR s."timestamp" > (%s::timestamptz - (%s * INTERVAL '1 day'))
    )
),
base AS (
  SELECT
    id,
    "timestamp",
    bar_seq,

    name,
    source_file,
    load_ts,

    time_open,
    time_close,

    (time_high IS NULL OR time_high < time_open OR time_high > time_close) AS needs_timehigh_repair,
    (time_low  IS NULL OR time_low  < time_open OR time_low  > time_close) AS needs_timelow_repair,

    open, high, low, close, volume, market_cap,
    time_high,
    time_low
  FROM src_rows
),
repaired AS (
  SELECT
    id,
    "timestamp",
    bar_seq,

    name,
    source_file,
    load_ts,

    time_open,
    time_close,

    CASE
      WHEN needs_timehigh_repair THEN
        CASE WHEN close >= open THEN time_close ELSE time_open END
      ELSE time_high
    END AS time_high_fix,

    CASE
      WHEN needs_timelow_repair THEN
        CASE WHEN close <= open THEN time_close ELSE time_open END
      ELSE time_low
    END AS time_low_fix,

    CASE
      WHEN needs_timehigh_repair THEN GREATEST(open, close)
      ELSE high
    END AS high_1,

    CASE
      WHEN needs_timelow_repair THEN LEAST(open, close)
      ELSE low
    END AS low_1,

    open,
    close,
    volume,
    market_cap,

    needs_timehigh_repair AS repaired_timehigh,
    needs_timelow_repair  AS repaired_timelow
  FROM base
),
final AS (
  SELECT
    id,
    "timestamp",
    '1D'::text AS tf,
    bar_seq,

    time_open,
    time_close,

    time_high_fix,
    time_low_fix,

    open,
    close,
    volume,
    market_cap,

    GREATEST(high_1, open, close, low_1) AS high_fix,
    LEAST(low_1,  open, close, high_1)  AS low_fix,

    -- For 1D, these are always false (canonical bars, no partial snapshots).
    false::boolean AS is_partial_start,
    false::boolean AS is_partial_end,
    false::boolean AS is_missing_days,

    repaired_timehigh,
    repaired_timelow,

    name,
    load_ts,
    source_file
  FROM repaired
),
ins AS (
  INSERT INTO {dst} (
    id, "timestamp",
    tf, bar_seq,
    time_open, time_close, time_high, time_low,
    open, high, low, close, volume, market_cap,
    is_partial_start, is_partial_end, is_missing_days,
    src_name, src_load_ts, src_file,
    repaired_timehigh, repaired_timelow
  )
  SELECT
    id, "timestamp",
    tf, bar_seq,
    time_open, time_close, time_high_fix, time_low_fix,
    open, high_fix, low_fix, close, volume, market_cap,
    is_partial_start, is_partial_end, is_missing_days,
    name, load_ts, source_file,
    repaired_timehigh, repaired_timelow
  FROM final
  WHERE
    id IS NOT NULL
    AND "timestamp" IS NOT NULL
    AND tf IS NOT NULL
    AND bar_seq IS NOT NULL
    AND time_open IS NOT NULL
    AND time_close IS NOT NULL
    AND open IS NOT NULL
    AND close IS NOT NULL
    AND volume IS NOT NULL
    AND market_cap IS NOT NULL
    AND time_high_fix IS NOT NULL
    AND time_low_fix IS NOT NULL
    AND high_fix IS NOT NULL
    AND low_fix IS NOT NULL
    AND time_open <= time_close
    AND time_open <= time_high_fix AND time_high_fix <= time_close
    AND time_open <= time_low_fix  AND time_low_fix  <= time_close
    AND high_fix >= low_fix
    AND high_fix >= GREATEST(open, close, low_fix)
    AND low_fix  <= LEAST(open, close, high_fix)
  ON CONFLICT (id, "timestamp") DO UPDATE SET
    tf = EXCLUDED.tf,
    bar_seq = EXCLUDED.bar_seq,
    time_open = EXCLUDED.time_open,
    time_close = EXCLUDED.time_close,
    time_high = EXCLUDED.time_high,
    time_low = EXCLUDED.time_low,
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low  = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    market_cap = EXCLUDED.market_cap,
    is_partial_start = EXCLUDED.is_partial_start,
    is_partial_end   = EXCLUDED.is_partial_end,
    is_missing_days  = EXCLUDED.is_missing_days,
    src_name = EXCLUDED.src_name,
    src_load_ts = EXCLUDED.src_load_ts,
    src_file = EXCLUDED.src_file,
    repaired_timehigh = EXCLUDED.repaired_timehigh,
    repaired_timelow  = EXCLUDED.repaired_timelow
  RETURNING repaired_timehigh, repaired_timelow, "timestamp"
)
SELECT
  count(*)::int AS upserted,
  coalesce(sum((repaired_timehigh)::int), 0)::int AS repaired_timehigh,
  coalesce(sum((repaired_timelow)::int), 0)::int  AS repaired_timelow,
  max("timestamp") AS max_src_ts
FROM ins;
"""


def _insert_rejects_sql(rej: str, src: str) -> str:
    """
    Logs any rows in the incremental window that fail the final filter.
    Includes tf + bar_seq and the three partial/missing flags.
    Returns: count of rejects inserted.
    """
    return f"""
WITH ranked_all AS (
  SELECT
    s.id,
    s."timestamp",
    dense_rank() OVER (PARTITION BY s.id ORDER BY s."timestamp" ASC)::bigint AS bar_seq
  FROM {src} s
  WHERE s.id = %s
    AND (%s IS NULL OR s."timestamp" < %s)
),
src_rows AS (
  SELECT
    s.id,
    s.name,
    s.source_file,
    s.load_ts,

    s.timeopen  AS time_open,
    s.timeclose AS time_close,
    s.timehigh  AS time_high,
    s.timelow   AS time_low,

    s."timestamp",

    s.open,
    s.high,
    s.low,
    s.close,
    s.volume,
    s.marketcap AS market_cap,

    r.bar_seq
  FROM {src} s
  JOIN ranked_all r
    ON r.id = s.id
   AND r."timestamp" = s."timestamp"
  WHERE s.id = %s
    AND (%s IS NULL OR s."timestamp" >= %s)
    AND (%s IS NULL OR s."timestamp" <  %s)
    AND (
      %s IS NULL
      OR s."timestamp" > (%s::timestamptz - (%s * INTERVAL '1 day'))
    )
),
base AS (
  SELECT
    id,
    "timestamp",
    '1D'::text AS tf,
    bar_seq,
    name,
    source_file,
    load_ts,
    time_open,
    time_close,
    (time_high IS NULL OR time_high < time_open OR time_high > time_close) AS needs_timehigh_repair,
    (time_low  IS NULL OR time_low  < time_open OR time_low  > time_close) AS needs_timelow_repair,
    open, high, low, close, volume, market_cap, time_high, time_low
  FROM src_rows
),
repaired AS (
  SELECT
    id, "timestamp", tf, bar_seq,
    name, source_file, load_ts,
    time_open, time_close,
    CASE
      WHEN needs_timehigh_repair THEN CASE WHEN close >= open THEN time_close ELSE time_open END
      ELSE time_high
    END AS time_high_fix,
    CASE
      WHEN needs_timelow_repair THEN CASE WHEN close <= open THEN time_close ELSE time_open END
      ELSE time_low
    END AS time_low_fix,
    CASE WHEN needs_timehigh_repair THEN GREATEST(open, close) ELSE high END AS high_1,
    CASE WHEN needs_timelow_repair  THEN LEAST(open, close)    ELSE low  END AS low_1,
    open, close, volume, market_cap
  FROM base
),
final AS (
  SELECT
    *,
    GREATEST(high_1, open, close, low_1) AS high_fix,
    LEAST(low_1,  open, close, high_1)  AS low_fix
  FROM repaired
),
rej_rows AS (
  SELECT
    id,
    "timestamp",
    tf,
    bar_seq,
    CASE
      WHEN id IS NULL OR "timestamp" IS NULL THEN 'null_pk'
      WHEN tf IS NULL OR bar_seq IS NULL THEN 'null_tf_or_bar_seq'
      WHEN time_open IS NULL OR time_close IS NULL THEN 'null_time_open_time_close'
      WHEN open IS NULL OR close IS NULL THEN 'null_open_close'
      WHEN volume IS NULL THEN 'null_volume'
      WHEN market_cap IS NULL THEN 'null_market_cap'
      WHEN time_open > time_close THEN 'time_open_gt_time_close'
      WHEN time_high_fix IS NULL OR time_low_fix IS NULL THEN 'null_time_high_time_low_after_repair'
      WHEN NOT (time_open <= time_high_fix AND time_high_fix <= time_close) THEN 'time_high_outside_window_after_repair'
      WHEN NOT (time_open <= time_low_fix  AND time_low_fix  <= time_close) THEN 'time_low_outside_window_after_repair'
      WHEN high_fix IS NULL OR low_fix IS NULL THEN 'null_ohlc_after_repair'
      WHEN high_fix < low_fix THEN 'high_lt_low_after_repair'
      WHEN high_fix < GREATEST(open, close, low_fix) THEN 'high_lt_greatest(open,close,low)_after_repair'
      WHEN low_fix  > LEAST(open, close, high_fix) THEN 'low_gt_least(open,close,high)_after_repair'
      ELSE 'failed_final_filter_unknown'
    END AS reason,
    time_open,
    time_close,
    time_high_fix AS time_high,
    time_low_fix  AS time_low,
    open,
    high_fix AS high,
    low_fix  AS low,
    close,
    volume,
    market_cap,
    false::boolean AS is_partial_start,
    false::boolean AS is_partial_end,
    false::boolean AS is_missing_days,
    name AS src_name,
    load_ts AS src_load_ts,
    source_file AS src_file
  FROM final
  WHERE NOT (
    id IS NOT NULL
    AND "timestamp" IS NOT NULL
    AND tf IS NOT NULL
    AND bar_seq IS NOT NULL
    AND time_open IS NOT NULL
    AND time_close IS NOT NULL
    AND open IS NOT NULL
    AND close IS NOT NULL
    AND time_high_fix IS NOT NULL
    AND time_low_fix IS NOT NULL
    AND high_fix IS NOT NULL
    AND low_fix IS NOT NULL
    AND time_open <= time_close
    AND time_open <= time_high_fix AND time_high_fix <= time_close
    AND time_open <= time_low_fix  AND time_low_fix  <= time_close
    AND high_fix >= low_fix
    AND high_fix >= GREATEST(open, close, low_fix)
    AND low_fix  <= LEAST(open, close, high_fix)
  )
),
ins AS (
  INSERT INTO {rej} (
    id, "timestamp", tf, bar_seq, reason,
    time_open, time_close, time_high, time_low,
    open, high, low, close, volume, market_cap,
    is_partial_start, is_partial_end, is_missing_days,
    src_name, src_load_ts, src_file
  )
  SELECT
    id, "timestamp", tf, bar_seq, reason,
    time_open, time_close, time_high, time_low,
    open, high, low, close, volume, market_cap,
    is_partial_start, is_partial_end, is_missing_days,
    src_name, src_load_ts, src_file
  FROM rej_rows
  RETURNING 1
)
SELECT count(*)::int FROM ins;
"""


# -----------------------------------------------------------------------------
# Driver
# -----------------------------------------------------------------------------

def build_1d_incremental(
    *,
    conn,
    src: str,
    dst: str,
    state: str,
    rejects: str,
    ids: Optional[List[int]],
    time_min: Optional[str],
    time_max: Optional[str],
    lookback_days: int,
    rebuild: bool,
    keep_rejects: bool,
    fail_on_rejects: bool,
) -> None:
    # Rebuild means DROP + recreate so schema changes always take effect
    if rebuild:
        _exec(conn, DDL_DROP_DST.format(dst=dst))
        _exec(conn, DDL_DROP_STATE.format(state=state))
        if keep_rejects:
            _exec(conn, DDL_DROP_REJECTS.format(rej=rejects))

    _exec(conn, DDL_CREATE_DST.format(dst=dst))
    _exec(conn, DDL_CREATE_STATE.format(state=state))
    if keep_rejects:
        _exec(conn, DDL_CREATE_REJECTS.format(rej=rejects))
        if rebuild:
            _exec(conn, DDL_TRUNCATE_REJECTS.format(rej=rejects))

    id_list = ids if ids is not None else _list_all_ids(conn, src)

    ins_sql = _insert_valid_and_return_stats_sql(dst=dst, src=src)
    rej_sql = _insert_rejects_sql(rej=rejects, src=src) if keep_rejects else None

    total_upserted = 0
    total_rep_hi = 0
    total_rep_lo = 0
    total_rej = 0

    for id_ in id_list:
        last_src_ts = _get_last_src_ts(conn, state, id_)

        # Params order MUST match the SQL:
        # ranked_all: (id, time_max, time_max)
        # src_rows:   (id, time_min, time_min, time_max, time_max, last_src_ts, last_src_ts, lookback_days)
        params: List[Any] = [
            id_,
            time_max, time_max,
            id_,
            time_min, time_min,
            time_max, time_max,
            last_src_ts, last_src_ts, lookback_days,
        ]

        rejected = 0
        if keep_rejects and rej_sql is not None:
            row = _fetchone(conn, rej_sql, params)
            rejected = int(row[0]) if row and row[0] is not None else 0

        row = _fetchone(conn, ins_sql, params)
        upserted = int(row[0]) if row and row[0] is not None else 0
        rep_hi = int(row[1]) if row and row[1] is not None else 0
        rep_lo = int(row[2]) if row and row[2] is not None else 0
        max_src_ts = row[3] if row else None

        if max_src_ts is not None or rejected > 0:
            _exec(
                conn,
                f"""
                INSERT INTO {state} (id, last_src_ts, last_run_ts,
                                    last_upserted, last_repaired_timehigh, last_repaired_timelow, last_rejected)
                VALUES (%s, %s, now(), %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  last_src_ts = COALESCE(EXCLUDED.last_src_ts, {state}.last_src_ts),
                  last_run_ts = now(),
                  last_upserted = EXCLUDED.last_upserted,
                  last_repaired_timehigh = EXCLUDED.last_repaired_timehigh,
                  last_repaired_timelow  = EXCLUDED.last_repaired_timelow,
                  last_rejected = EXCLUDED.last_rejected;
                """,
                [id_, max_src_ts, upserted, rep_hi, rep_lo, rejected],
            )

        total_upserted += upserted
        total_rep_hi += rep_hi
        total_rep_lo += rep_lo
        total_rej += rejected

    print(f"[bars_1d] src={src}")
    print(f"[bars_1d] dst={dst}")
    print(f"[bars_1d] state={state}")
    if keep_rejects:
        print(f"[bars_1d] rejects={rejects}")
    print(f"[bars_1d] ids_processed={len(id_list)} lookback_days={lookback_days}")
    print(f"[bars_1d] total_upserted={total_upserted} repaired_timehigh={total_rep_hi} repaired_timelow={total_rep_lo}")
    if keep_rejects:
        print(f"[bars_1d] total_rejected={total_rej}")
        if fail_on_rejects and total_rej > 0:
            raise SystemExit(f"[bars_1d] FAIL: {total_rej} rejects inserted into {rejects}")


def main() -> None:
    p = argparse.ArgumentParser(description="Incremental build of canonical 1D bars table with state tracking.")
    p.add_argument("--db-url", default=os.environ.get("TARGET_DB_URL") or os.environ.get("TA_LAB2_DB_URL") or "")
    p.add_argument("--src", default="public.cmc_price_histories7")
    p.add_argument("--dst", default="public.cmc_price_bars_1d")
    p.add_argument("--state", default="public.cmc_price_bars_1d_state")
    p.add_argument("--rejects", default="public.cmc_price_bars_1d_rejects")
    p.add_argument("--ids", default="all", help="all or comma-separated list, e.g. 1,1027,1975")
    p.add_argument("--time-min", default=None, help='Optional inclusive bound on src."timestamp"')
    p.add_argument("--time-max", default=None, help='Optional exclusive bound on src."timestamp"')
    p.add_argument("--lookback-days", type=int, default=3, help="Reprocess this many days back from last_src_ts (handles late revisions)")
    p.add_argument("--rebuild", action="store_true", help="DROP + recreate dst + state (and rejects if kept) before building")
    p.add_argument("--keep-rejects", action="store_true", help="Log rejected rows to rejects table")
    p.add_argument("--fail-on-rejects", action="store_true", help="Exit non-zero if any rejects were logged")
    args = p.parse_args()

    if not args.db_url:
        raise SystemExit("Set TARGET_DB_URL (or TA_LAB2_DB_URL) or pass --db-url.")

    ids = _parse_ids_arg(args.ids)

    conn = _connect(args.db_url)
    try:
        build_1d_incremental(
            conn=conn,
            src=args.src,
            dst=args.dst,
            state=args.state,
            rejects=args.rejects,
            ids=ids,
            time_min=args.time_min,
            time_max=args.time_max,
            lookback_days=args.lookback_days,
            rebuild=args.rebuild,
            keep_rejects=args.keep_rejects,
            fail_on_rejects=args.fail_on_rejects,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
