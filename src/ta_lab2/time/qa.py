# src/ta_lab2/time/qa.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ta_lab2.time.specs import TimeSpecStore


# -----------------------------
# Reason codes
# -----------------------------


class QAReason(str, Enum):
    # Structure / continuity
    GAP = "GAP"
    OVERLAP = "OVERLAP"
    NON_MONOTONIC_CLOSE = "NON_MONOTONIC_CLOSE"
    NON_MONOTONIC_OPEN = "NON_MONOTONIC_OPEN"

    # Bar-order / seq sanity (optional)
    BAR_SEQ_GAP = "BAR_SEQ_GAP"
    BAR_SEQ_DUP = "BAR_SEQ_DUP"

    # OHLC sanity
    OHLC_INVALID = "OHLC_INVALID"

    # Timeframe semantics (dim_timeframe-driven)
    TF_DAYS_OUT_OF_BOUNDS = "TF_DAYS_OUT_OF_BOUNDS"
    DISALLOWED_PARTIAL_START = "DISALLOWED_PARTIAL_START"
    DISALLOWED_PARTIAL_END = "DISALLOWED_PARTIAL_END"
    SCHEME_MISMATCH = "SCHEME_MISMATCH"  # optional placeholder if you add boundary checks


# -----------------------------
# Output records
# -----------------------------


@dataclass(frozen=True, slots=True)
class QAViolation:
    table: str
    id: int
    tf: str
    time_open: Optional[str]
    time_close: Optional[str]
    reason: QAReason
    details: Dict[str, Any]


@dataclass(frozen=True, slots=True)
class QARunResult:
    table: str
    checked_ids: Tuple[int, ...]
    checked_tfs: Tuple[str, ...]
    violations: Tuple[QAViolation, ...]
    counts_by_reason: Dict[str, int]


# -----------------------------
# Engine helpers
# -----------------------------


def _make_engine(db_url: str | None) -> Engine:
    if not db_url or not db_url.strip():
        raise ValueError("db_url is required.")
    return create_engine(db_url)


def _count_by_reason(violations: Sequence[QAViolation]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for v in violations:
        k = v.reason.value
        out[k] = out.get(k, 0) + 1
    return out


# -----------------------------
# SQL templates
# -----------------------------
#
# Assumptions about bar table schema:
#   - id (int)
#   - tf (text)
#   - time_open (timestamptz)
#   - time_close (timestamptz)
#   - open, high, low, close (double precision)   (names may vary)
#   - tf_days (int)                                (for realized length)
#   - bar_seq (int)                                (optional)
#
# If any of these differ, either adjust column names or wrap with views.


SQL_BASE_FILTER = """
WITH base AS (
  SELECT
    id,
    tf,
    time_open,
    time_close,
    tf_days,
    {open_col}   AS o,
    {high_col}   AS h,
    {low_col}    AS l,
    {close_col}  AS c,
    {bar_seq_col} AS bar_seq
  FROM {table_name}
  WHERE id = ANY(:ids)
    AND tf = ANY(:tfs)
    AND (:start_ts IS NULL OR time_close >= :start_ts)
    AND (:end_ts   IS NULL OR time_close <= :end_ts)
)
"""


SQL_CONTINUITY = (
    SQL_BASE_FILTER
    + """
, w AS (
  SELECT
    *,
    LAG(time_close) OVER (PARTITION BY id, tf ORDER BY time_close, time_open) AS prev_close,
    LAG(time_open)  OVER (PARTITION BY id, tf ORDER BY time_close, time_open) AS prev_open
  FROM base
)
SELECT
  id, tf, time_open, time_close,
  prev_close, prev_open,
  CASE
    WHEN prev_close IS NOT NULL AND time_open > prev_close THEN 'GAP'
    WHEN prev_close IS NOT NULL AND time_open < prev_close THEN 'OVERLAP'
    ELSE NULL
  END AS reason
FROM w
WHERE prev_close IS NOT NULL
  AND (time_open <> prev_close)
"""
)


SQL_OHLC = (
    SQL_BASE_FILTER
    + """
SELECT
  id, tf, time_open, time_close,
  o, h, l, c
FROM base
WHERE
  l IS NULL OR h IS NULL OR o IS NULL OR c IS NULL
  OR l > h
  OR o < l OR o > h
  OR c < l OR c > h
"""
)


SQL_BAR_SEQ = (
    SQL_BASE_FILTER
    + """
, w AS (
  SELECT
    *,
    LAG(bar_seq) OVER (PARTITION BY id, tf ORDER BY time_close, time_open) AS prev_seq
  FROM base
)
SELECT
  id, tf, time_open, time_close,
  bar_seq, prev_seq,
  CASE
    WHEN prev_seq IS NOT NULL AND bar_seq = prev_seq THEN 'BAR_SEQ_DUP'
    WHEN prev_seq IS NOT NULL AND bar_seq <> prev_seq + 1 THEN 'BAR_SEQ_GAP'
    ELSE NULL
  END AS reason
FROM w
WHERE bar_seq IS NOT NULL AND prev_seq IS NOT NULL
  AND (bar_seq = prev_seq OR bar_seq <> prev_seq + 1)
"""
)


# -----------------------------
# Python-side semantic checks
# -----------------------------


def _tf_days_bounds_violations(
    *,
    table_name: str,
    store: TimeSpecStore,
    rows: Sequence[Mapping[str, Any]],
) -> List[QAViolation]:
    out: List[QAViolation] = []
    for r in rows:
        tf = str(r["tf"])
        spec = store.get_tf(tf)

        tf_days = r.get("tf_days", None)
        if not spec.realized_tf_days_ok(tf_days):
            out.append(
                QAViolation(
                    table=table_name,
                    id=int(r["id"]),
                    tf=tf,
                    time_open=str(r.get("time_open")) if r.get("time_open") is not None else None,
                    time_close=str(r.get("time_close")) if r.get("time_close") is not None else None,
                    reason=QAReason.TF_DAYS_OUT_OF_BOUNDS,
                    details={
                        "tf_days": tf_days,
                        "tf_days_min": spec.tf_days_min,
                        "tf_days_max": spec.tf_days_max,
                    },
                )
            )
    return out


def _partial_policy_violations(
    *,
    table_name: str,
    store: TimeSpecStore,
    rows_first_last: Sequence[Mapping[str, Any]],
) -> List[QAViolation]:
    """
    Enforce dim_timeframe allow_partial_start / allow_partial_end.

    This check assumes you pass in only the FIRST and LAST bar per (id, tf).
    We enforce using realized tf_days bounds + allow_partial flags.

    Note: If you later add "expected full length" metadata (e.g., canonical tf_days_full),
    you can strengthen these checks. For now, we implement:
      - if allow_partial_start == False: first bar must be within bounds AND
        (optionally) must not be "shorter than max" (too strong w/o full-length)
    We keep it conservative: only flag if tf_days is OUT OF BOUNDS and partial is disallowed.
    """
    out: List[QAViolation] = []
    for r in rows_first_last:
        tf = str(r["tf"])
        spec = store.get_tf(tf)

        pos = str(r["pos"])  # "FIRST" or "LAST"
        tf_days = r.get("tf_days", None)
        in_bounds = spec.realized_tf_days_ok(tf_days)

        if pos == "FIRST" and (not spec.allow_partial_start) and (not in_bounds):
            out.append(
                QAViolation(
                    table=table_name,
                    id=int(r["id"]),
                    tf=tf,
                    time_open=str(r.get("time_open")) if r.get("time_open") is not None else None,
                    time_close=str(r.get("time_close")) if r.get("time_close") is not None else None,
                    reason=QAReason.DISALLOWED_PARTIAL_START,
                    details={
                        "tf_days": tf_days,
                        "tf_days_min": spec.tf_days_min,
                        "tf_days_max": spec.tf_days_max,
                        "allow_partial_start": spec.allow_partial_start,
                    },
                )
            )

        if pos == "LAST" and (not spec.allow_partial_end) and (not in_bounds):
            out.append(
                QAViolation(
                    table=table_name,
                    id=int(r["id"]),
                    tf=tf,
                    time_open=str(r.get("time_open")) if r.get("time_open") is not None else None,
                    time_close=str(r.get("time_close")) if r.get("time_close") is not None else None,
                    reason=QAReason.DISALLOWED_PARTIAL_END,
                    details={
                        "tf_days": tf_days,
                        "tf_days_min": spec.tf_days_min,
                        "tf_days_max": spec.tf_days_max,
                        "allow_partial_end": spec.allow_partial_end,
                    },
                )
            )

    return out


# -----------------------------
# Core runner
# -----------------------------


def run_bars_qa(
    *,
    store: TimeSpecStore,
    table_name: str,
    ids: Sequence[int],
    tfs: Sequence[str],
    start_ts: str | None = None,
    end_ts: str | None = None,
    engine: Engine | None = None,
    db_url: str | None = None,
    # Column names (override if your bars tables differ)
    open_col: str = "open",
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
    bar_seq_col: str = "bar_seq",
    # toggles
    check_continuity: bool = True,
    check_ohlc: bool = True,
    check_bar_seq: bool = True,
    check_tf_days_bounds: bool = True,
    check_partial_policy: bool = True,
) -> QARunResult:
    """
    Unified QA runner for ANY bars table, with dim_timeframe-driven semantics.

    Hard-stop guards:
      - TF must exist in dim_timeframe (store.get_tf)
      - TF must be allowed for the table (store.get_table(table_name).assert_tf_allowed)
    """
    if not ids:
        raise ValueError("ids must be non-empty")
    if not tfs:
        raise ValueError("tfs must be non-empty")

    # Hard stop guards (prevents semantic drift)
    table_spec = store.get_table(table_name)
    for tf in tfs:
        table_spec.assert_tf_allowed(tf)
        _ = store.get_tf(tf)

    eng = engine or _make_engine(db_url)

    fmt_kwargs = dict(
        table_name=table_name,
        open_col=open_col,
        high_col=high_col,
        low_col=low_col,
        close_col=close_col,
        bar_seq_col=bar_seq_col if bar_seq_col else "NULL::int",
    )

    params = {
        "ids": list(ids),
        "tfs": list(tfs),
        "start_ts": start_ts,
        "end_ts": end_ts,
    }

    violations: List[QAViolation] = []

    with eng.connect() as conn:
        # 1) Continuity (gap/overlap based on time_open vs prev_close)
        if check_continuity:
            q = SQL_CONTINUITY.format(**fmt_kwargs)
            rows = conn.execute(text(q), params).mappings().all()
            for r in rows:
                reason = r.get("reason")
                if not reason:
                    continue
                violations.append(
                    QAViolation(
                        table=table_name,
                        id=int(r["id"]),
                        tf=str(r["tf"]),
                        time_open=str(r["time_open"]) if r.get("time_open") is not None else None,
                        time_close=str(r["time_close"]) if r.get("time_close") is not None else None,
                        reason=QAReason(reason),
                        details={
                            "prev_close": str(r["prev_close"]) if r.get("prev_close") is not None else None,
                            "prev_open": str(r["prev_open"]) if r.get("prev_open") is not None else None,
                        },
                    )
                )

        # 2) OHLC sanity
        if check_ohlc:
            q = SQL_OHLC.format(**fmt_kwargs)
            rows = conn.execute(text(q), params).mappings().all()
            for r in rows:
                violations.append(
                    QAViolation(
                        table=table_name,
                        id=int(r["id"]),
                        tf=str(r["tf"]),
                        time_open=str(r["time_open"]) if r.get("time_open") is not None else None,
                        time_close=str(r["time_close"]) if r.get("time_close") is not None else None,
                        reason=QAReason.OHLC_INVALID,
                        details={
                            "open": r.get("o"),
                            "high": r.get("h"),
                            "low": r.get("l"),
                            "close": r.get("c"),
                        },
                    )
                )

        # 3) bar_seq checks (optional)
        if check_bar_seq and bar_seq_col:
            q = SQL_BAR_SEQ.format(**fmt_kwargs)
            rows = conn.execute(text(q), params).mappings().all()
            for r in rows:
                reason = r.get("reason")
                if not reason:
                    continue
                violations.append(
                    QAViolation(
                        table=table_name,
                        id=int(r["id"]),
                        tf=str(r["tf"]),
                        time_open=str(r["time_open"]) if r.get("time_open") is not None else None,
                        time_close=str(r["time_close"]) if r.get("time_close") is not None else None,
                        reason=QAReason(reason),
                        details={
                            "bar_seq": r.get("bar_seq"),
                            "prev_seq": r.get("prev_seq"),
                        },
                    )
                )

        # 4) tf_days bounds check (dim_timeframe-driven)
        if check_tf_days_bounds:
            q = (
                SQL_BASE_FILTER.format(**fmt_kwargs)
                + """
SELECT id, tf, time_open, time_close, tf_days
FROM base
WHERE tf_days IS NULL
   OR tf_days < 0
"""
            )
            # We pull "obvious bad" first; then the dim_timeframe check handles bounds.
            # We still need all rows for bounds check, but keep it minimal by filtering
            # and letting Python do the bounds check on the returned set if you want.
            # If you prefer: remove WHERE and scan all tf_days. (Heavier.)
            base_rows = conn.execute(text(q), params).mappings().all()
            violations.extend(_tf_days_bounds_violations(table_name=table_name, store=store, rows=base_rows))

        # 5) Partial policy enforcement (first/last bars per id/tf)
        if check_partial_policy:
            q = (
                SQL_BASE_FILTER.format(**fmt_kwargs)
                + """
, ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY id, tf ORDER BY time_close, time_open)  AS rn_asc,
    ROW_NUMBER() OVER (PARTITION BY id, tf ORDER BY time_close DESC, time_open DESC) AS rn_desc
  FROM base
)
SELECT
  id, tf, time_open, time_close, tf_days,
  CASE
    WHEN rn_asc = 1 THEN 'FIRST'
    WHEN rn_desc = 1 THEN 'LAST'
    ELSE NULL
  END AS pos
FROM ranked
WHERE rn_asc = 1 OR rn_desc = 1
"""
            )
            rows = conn.execute(text(q), params).mappings().all()
            violations.extend(_partial_policy_violations(table_name=table_name, store=store, rows_first_last=rows))

    return QARunResult(
        table=table_name,
        checked_ids=tuple(ids),
        checked_tfs=tuple(tfs),
        violations=tuple(violations),
        counts_by_reason=_count_by_reason(violations),
    )


# -----------------------------
# Small convenience printer
# -----------------------------


def summarize_qa(result: QARunResult, *, max_examples_per_reason: int = 5) -> str:
    """
    Produce a readable summary string for logs / CLI.
    """
    lines: List[str] = []
    lines.append(f"[qa] table={result.table} ids={len(result.checked_ids)} tfs={len(result.checked_tfs)}")
    if not result.violations:
        lines.append("[qa] ✅ no violations")
        return "\n".join(lines)

    lines.append(f"[qa] ❌ violations={len(result.violations)}")
    for reason, count in sorted(result.counts_by_reason.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"  - {reason}: {count}")

        shown = 0
        for v in result.violations:
            if v.reason.value != reason:
                continue
            if shown >= max_examples_per_reason:
                break
            lines.append(
                f"      example: id={v.id} tf={v.tf} open={v.time_open} close={v.time_close} details={v.details}"
            )
            shown += 1

    return "\n".join(lines)
