from __future__ import annotations
# -*- coding: utf-8 -*-

"""
audit_price_bars_integrity.py

One-stop integrity audit for the 5 price bars tables.

Leverages (and subsumes) your existing scripts:
  - audit_price_bars_tables.py   (per-(table,id,tf) summary metrics)
  - audit_price_bars_samples.py  (human eyeball samples)

Adds the missing Week-4-style pieces (analogous to EMA integrity):
  1) Expected coverage by (id, tf) using dim_timeframe-driven TF selection rules
  2) Duplicate snapshot key checks:
       - duplicates on (id, tf, bar_seq, time_close) when columns exist
  3) Final-row uniqueness per bar_seq:
       - at most 1 row with is_partial_end = FALSE per (id, tf, bar_seq)
  4) Spacing checks vs dim_timeframe on *canonical* closes:
       - canonical rows defined as is_partial_end=FALSE when present
       - validate ts deltas against dim_timeframe.tf_days_min/max (or nominal ±0.5d)
  5) Bar sequence continuity checks on canonical rows:
       - detect gaps in bar_seq sequence when bar_seq exists

Outputs (CSV files):
  - --out-coverage: expected coverage summary per table
  - --out-audit: per-(table,id,tf) summary metrics (incl dup/final violations when possible)
  - --out-spacing: per-(table,id,tf) spacing + bar_seq continuity diagnostics
  - --out-samples: sampled rows for eyeballing (optional; can be large)

Run:
  python audit_price_bars_integrity.py --ids all --run all

Spyder runfile:
  runfile(
    r"C:\\Users\\asafi\\Downloads\\ta_lab2\\src\\ta_lab2\\scripts\\bars\\audit_price_bars_integrity.py",
    wdir=r"C:\\Users\\asafi\\Downloads\\ta_lab2",
    args="--ids all --run all"
  )

Notes:
- Uses TARGET_DB_URL env var.
- Assumes dim_timeframe contains:
    tf, alignment_type, base_unit, calendar_scheme, calendar_anchor,
    tf_days_nominal, tf_days_min, tf_days_max, is_canonical, allow_partial_start, allow_partial_end
  If your dim_timeframe uses different column names, update DIM_TF_COLS and TF selectors below.
"""

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ta_lab2.scripts.bars.common_snapshot_contract import (
    get_engine,
    resolve_db_url,
    parse_ids,
    load_all_ids,
)


# ----------------------------
# Tables / Defaults
# ----------------------------

BAR_TABLES: Dict[str, str] = {
    "public.cmc_price_bars_multi_tf": "TF_DAY",
    "public.cmc_price_bars_multi_tf_cal_us": "CAL_US",
    "public.cmc_price_bars_multi_tf_cal_iso": "CAL_ISO",
    "public.cmc_price_bars_multi_tf_cal_anchor_us": "ANCHOR_US",
    "public.cmc_price_bars_multi_tf_cal_anchor_iso": "ANCHOR_ISO",
}

DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"
DEFAULT_DIM_TF = "public.dim_timeframe"

DIM_TF_COLS = [
    "tf",
    "alignment_type",
    "base_unit",
    "calendar_scheme",
    "calendar_anchor",
    "tf_days_nominal",
    "tf_days_min",
    "tf_days_max",
    "is_canonical",
    "allow_partial_start",
    "allow_partial_end",
]


def _log(msg: str) -> None:
    print(f"[bars_integrity] {msg}")


def table_exists(engine: Engine, full_name: str) -> bool:
    if "." in full_name:
        schema, table = full_name.split(".", 1)
    else:
        schema, table = "public", full_name
    q = text(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = :schema AND table_name = :table
        LIMIT 1
        """
    )
    df = pd.read_sql(q, engine, params={"schema": schema, "table": table})
    return not df.empty


def get_columns(engine: Engine, full_name: str) -> List[str]:
    if "." in full_name:
        schema, table = full_name.split(".", 1)
    else:
        schema, table = "public", full_name
    q = text(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = :schema AND table_name = :table
        ORDER BY ordinal_position
        """
    )
    df = pd.read_sql(q, engine, params={"schema": schema, "table": table})
    return df["column_name"].tolist()


def best_ts_col(colset: set[str]) -> Optional[str]:
    for cand in ["timestamp", "time_close", "ts"]:
        if cand in colset:
            return cand
    return None


# ----------------------------
# TF selection (expected coverage)
# ----------------------------


def _load_dim_timeframe(engine: Engine, dim_tf: str) -> pd.DataFrame:
    df = pd.read_sql(text(f"SELECT {', '.join(DIM_TF_COLS)} FROM {dim_tf}"), engine)
    missing = [c for c in DIM_TF_COLS if c not in df.columns]
    if missing:
        raise RuntimeError(
            f"dim_timeframe missing columns needed for bars integrity audit: {missing}"
        )
    return df


def tfs_for_family(df_tf: pd.DataFrame, family: str) -> List[str]:
    """
    Mirrors your current conventions:
      - TF_DAY: alignment_type='tf_day', is_canonical=TRUE
      - CAL_US / CAL_ISO: alignment_type='calendar', calendar_anchor=FALSE, canonical-only,
          * weeks scheme-specific (tf ends with _CAL_US / _CAL_ISO)
          * months/years scheme-agnostic (tf ends with _CAL and does not contain _CAL_)
      - ANCHOR_US / ANCHOR_ISO: alignment_type='calendar', calendar_anchor=TRUE, canonical-only,
          * weeks scheme-specific (tf ends with _CAL_ANCHOR_US / _CAL_ANCHOR_ISO)
          * months/years scheme-agnostic (tf ends with _CAL_ANCHOR)
    """
    df = df_tf.copy()
    df = df[df["is_canonical"] == True]  # noqa: E712
    if family == "TF_DAY":
        df = df[df["alignment_type"] == "tf_day"]
        return df["tf"].astype(str).tolist()

    if family in {"CAL_US", "CAL_ISO"}:
        scheme = "US" if family == "CAL_US" else "ISO"
        df = df[(df["alignment_type"] == "calendar") & (df["calendar_anchor"] == False)]  # noqa: E712
        # Weeks: scheme-specific suffix
        weeks = df[
            (df["base_unit"] == "W")
            & (df["tf"].astype(str).str.endswith(f"_CAL_{scheme}"))
        ]
        # Months/years: scheme-agnostic "_CAL" without extra suffix
        my = df[
            (df["base_unit"].isin(["M", "Y"]))
            & (df["tf"].astype(str).str.endswith("_CAL"))
        ]
        my = my[~my["tf"].astype(str).str.contains("_CAL_")]
        out = pd.concat([weeks, my], ignore_index=True)
        return out["tf"].astype(str).tolist()

    if family in {"ANCHOR_US", "ANCHOR_ISO"}:
        scheme = "US" if family == "ANCHOR_US" else "ISO"
        df = df[(df["alignment_type"] == "calendar") & (df["calendar_anchor"] == True)]  # noqa: E712
        weeks = df[
            (df["base_unit"] == "W")
            & (df["tf"].astype(str).str.endswith(f"_CAL_ANCHOR_{scheme}"))
        ]
        my = df[
            (df["base_unit"].isin(["M", "Y"]))
            & (df["tf"].astype(str).str.endswith("_CAL_ANCHOR"))
        ]
        out = pd.concat([weeks, my], ignore_index=True)
        return out["tf"].astype(str).tolist()

    raise ValueError(f"Unknown family: {family}")


def run_coverage(
    engine: Engine, ids: List[int], dim_tf: str, out_csv: str
) -> pd.DataFrame:
    df_tf = _load_dim_timeframe(engine, dim_tf)

    rows = []
    for table, family in BAR_TABLES.items():
        if not table_exists(engine, table):
            rows.append(
                dict(
                    table_name=table,
                    family=family,
                    exists=False,
                    n_ids=len(ids),
                    n_tfs_expected=0,
                    n_expected=len(ids) * 0,
                    n_actual=0,
                    n_missing=len(ids) * 0,
                    missing_share=0.0,
                    audit_generated_at=datetime.now(UTC).isoformat(),
                )
            )
            continue

        tfs = tfs_for_family(df_tf, family)
        in_clause = ",".join(str(int(i)) for i in ids)
        actual = pd.read_sql(
            text(
                f"SELECT DISTINCT id::int AS id, tf::text AS tf FROM {table} WHERE id IN ({in_clause})"
            ),
            engine,
        )
        exp = len(ids) * len(tfs)
        act = len(actual)
        missing = max(exp - act, 0)
        miss_share = (missing / exp) if exp else 0.0

        rows.append(
            dict(
                table_name=table,
                family=family,
                exists=True,
                n_ids=len(ids),
                n_tfs_expected=len(tfs),
                n_expected=exp,
                n_actual=act,
                n_missing=missing,
                missing_share=round(miss_share, 8),
                audit_generated_at=datetime.now(UTC).isoformat(),
            )
        )

    out_df = pd.DataFrame(rows).sort_values(["table_name"]).reset_index(drop=True)
    out_df.to_csv(out_csv, index=False)
    _log(f"[coverage] Wrote {len(out_df)} rows -> {out_csv}")
    return out_df


# ----------------------------
# Table audit (summary + dup/final checks when possible)
# ----------------------------


def audit_table_summary(engine: Engine, table: str, ids: Sequence[int]) -> pd.DataFrame:
    """
    Produces per-(table,id,tf) metrics, based on whatever columns exist.
    Adds:
      - duplicate snapshot key count when (bar_seq,time_close) exist
      - final-row uniqueness violations when (bar_seq,is_partial_end) exist
    """
    if not table_exists(engine, table):
        _log(f"[audit] SKIP missing table: {table}")
        return pd.DataFrame()

    cols = get_columns(engine, table)
    colset = set(cols)
    if not {"id", "tf"}.issubset(colset):
        _log(f"[audit] SKIP {table}: missing id/tf")
        return pd.DataFrame()

    ts_col = best_ts_col(colset)
    has_bar_seq = "bar_seq" in colset
    has_is_partial_end = "is_partial_end" in colset
    has_is_partial_start = "is_partial_start" in colset
    has_tf_days = "tf_days" in colset
    has_is_missing_days = "is_missing_days" in colset
    has_count_days = "count_days" in colset
    has_count_days_remaining = "count_days_remaining" in colset

    in_clause = ",".join(str(int(i)) for i in ids)

    select_parts = [
        f"'{table}'::text AS table_name",
        "id",
        "tf",
        "COUNT(*)::bigint AS n_rows",
    ]
    if ts_col:
        select_parts += [f"MIN({ts_col}) AS min_ts", f"MAX({ts_col}) AS max_ts"]
    if has_bar_seq:
        select_parts += ["COUNT(DISTINCT bar_seq)::bigint AS n_bar_seq"]
    if has_tf_days:
        select_parts += [
            "MIN(tf_days)::int AS tf_days_min",
            "MAX(tf_days)::int AS tf_days_max",
        ]
    if has_is_partial_end:
        select_parts += [
            "SUM(CASE WHEN is_partial_end THEN 1 ELSE 0 END)::bigint AS n_partial_end_true",
            "SUM(CASE WHEN NOT is_partial_end THEN 1 ELSE 0 END)::bigint AS n_partial_end_false",
        ]
    if has_is_partial_start:
        select_parts += [
            "SUM(CASE WHEN is_partial_start THEN 1 ELSE 0 END)::bigint AS n_partial_start_true",
            "SUM(CASE WHEN NOT is_partial_start THEN 1 ELSE 0 END)::bigint AS n_partial_start_false",
        ]
    if has_is_missing_days:
        select_parts += [
            "SUM(CASE WHEN is_missing_days THEN 1 ELSE 0 END)::bigint AS n_missing_days_true",
            "SUM(CASE WHEN NOT is_missing_days THEN 1 ELSE 0 END)::bigint AS n_missing_days_false",
        ]
    if has_count_days:
        select_parts += [
            "MIN(count_days)::int AS count_days_min",
            "MAX(count_days)::int AS count_days_max",
        ]
    if has_count_days_remaining:
        select_parts += [
            "MIN(count_days_remaining)::int AS count_days_remaining_min",
            "MAX(count_days_remaining)::int AS count_days_remaining_max",
        ]

    q = text(
        f"""
        SELECT {", ".join(select_parts)}
        FROM {table}
        WHERE id IN ({in_clause})
        GROUP BY id, tf
        ORDER BY id, tf
        """
    )
    df = pd.read_sql(q, engine)
    if df.empty:
        return df

    df["audit_generated_at"] = datetime.now(UTC).isoformat()

    # Derived
    if "n_bar_seq" in df.columns:
        df["rows_per_bar_seq"] = (df["n_rows"] / df["n_bar_seq"]).round(6)
        df["has_snapshot_multiplicity"] = df["n_rows"] > df["n_bar_seq"]

    if "n_partial_end_false" in df.columns:
        df["canonical_share"] = (df["n_partial_end_false"] / df["n_rows"]).round(8)

    if "n_missing_days_true" in df.columns:
        df["missing_days_share"] = (df["n_missing_days_true"] / df["n_rows"]).round(8)

    if "tf_days_min" in df.columns and "tf_days_max" in df.columns:
        df["tf_days_constant"] = df["tf_days_min"] == df["tf_days_max"]
        df["tf_days_span"] = df["tf_days_max"] - df["tf_days_min"]

    if "n_partial_start_true" in df.columns:
        df["partial_start_share"] = (df["n_partial_start_true"] / df["n_rows"]).round(8)

    # ---- Added checks (require additional DB aggregations) ----
    # Duplicate snapshot key: (id,tf,bar_seq,timestamp) duplicates
    if has_bar_seq and "timestamp" in colset:
        q_dup = text(
            f"""
            SELECT id::int AS id, tf::text AS tf,
                   SUM(CASE WHEN c > 1 THEN (c - 1) ELSE 0 END)::bigint AS n_dup_snapshot_keys
            FROM (
              SELECT id, tf, bar_seq, "timestamp", COUNT(*)::bigint AS c
              FROM {table}
              WHERE id IN ({in_clause})
              GROUP BY id, tf, bar_seq, "timestamp"
            ) x
            GROUP BY id, tf
            """
        )
        dup = pd.read_sql(q_dup, engine)
        df = df.merge(dup, on=["id", "tf"], how="left")
        df["n_dup_snapshot_keys"] = df["n_dup_snapshot_keys"].fillna(0).astype("int64")
        df["dup_snapshot_key_share"] = (df["n_dup_snapshot_keys"] / df["n_rows"]).round(
            8
        )
    else:
        df["n_dup_snapshot_keys"] = 0
        df["dup_snapshot_key_share"] = 0.0

    # Final-row uniqueness: at most one final row (is_partial_end=FALSE) per (id,tf,bar_seq)
    if has_bar_seq and has_is_partial_end:
        q_final = text(
            f"""
            SELECT id::int AS id, tf::text AS tf,
                   SUM(CASE WHEN final_c > 1 THEN (final_c - 1) ELSE 0 END)::bigint AS n_extra_final_rows,
                   SUM(CASE WHEN final_c = 0 THEN 1 ELSE 0 END)::bigint AS n_missing_final_barseq
            FROM (
              SELECT id, tf, bar_seq,
                     SUM(CASE WHEN NOT is_partial_end THEN 1 ELSE 0 END)::bigint AS final_c
              FROM {table}
              WHERE id IN ({in_clause})
              GROUP BY id, tf, bar_seq
            ) y
            GROUP BY id, tf
            """
        )
        fin = pd.read_sql(q_final, engine)
        df = df.merge(fin, on=["id", "tf"], how="left")
        df["n_extra_final_rows"] = df["n_extra_final_rows"].fillna(0).astype("int64")
        df["n_missing_final_barseq"] = (
            df["n_missing_final_barseq"].fillna(0).astype("int64")
        )
    else:
        df["n_extra_final_rows"] = 0
        df["n_missing_final_barseq"] = 0

    return df


def run_audit(engine: Engine, ids: List[int], out_csv: str) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for table in BAR_TABLES.keys():
        df_t = audit_table_summary(engine, table, ids)
        if not df_t.empty:
            frames.append(df_t)
    if not frames:
        raise RuntimeError(
            "No audit results. Check table names/schema and permissions."
        )
    out_df = pd.concat(frames, ignore_index=True)
    out_df = out_df.sort_values(["table_name", "id", "tf"]).reset_index(drop=True)
    out_df.to_csv(out_csv, index=False)
    _log(f"[audit] Wrote {len(out_df)} rows -> {out_csv}")
    return out_df


# ----------------------------
# Spacing + bar_seq continuity (canonical rows)
# ----------------------------


@dataclass(frozen=True)
class TfSpec:
    tf: str
    alignment_type: str
    tf_days_nominal: Optional[float]
    tf_days_min: Optional[float]
    tf_days_max: Optional[float]


def load_tf_specs(engine: Engine, dim_tf: str) -> Dict[str, TfSpec]:
    df = _load_dim_timeframe(engine, dim_tf)
    out: Dict[str, TfSpec] = {}
    for _, r in df.iterrows():
        tf = str(r["tf"])
        out[tf] = TfSpec(
            tf=tf,
            alignment_type=str(r["alignment_type"])
            if pd.notna(r["alignment_type"])
            else "",
            tf_days_nominal=float(r["tf_days_nominal"])
            if pd.notna(r["tf_days_nominal"])
            else None,
            tf_days_min=float(r["tf_days_min"]) if pd.notna(r["tf_days_min"]) else None,
            tf_days_max=float(r["tf_days_max"]) if pd.notna(r["tf_days_max"]) else None,
        )
    return out


def fetch_canonical_closes(
    engine: Engine, table: str, ids: Sequence[int]
) -> pd.DataFrame:
    cols = get_columns(engine, table)
    colset = set(cols)
    if not {"id", "tf"}.issubset(colset):
        return pd.DataFrame()

    ts_col = best_ts_col(colset)
    if not ts_col:
        return pd.DataFrame()

    has_bar_seq = "bar_seq" in colset
    has_is_partial_end = "is_partial_end" in colset

    in_clause = ",".join(str(int(i)) for i in ids)

    where = f"WHERE id IN ({in_clause})"
    if has_is_partial_end:
        where += " AND is_partial_end = FALSE"

    sel = ["id::int AS id", "tf::text AS tf", f"{ts_col} AS ts"]
    if has_bar_seq:
        sel.append("bar_seq::bigint AS bar_seq")

    q = text(
        f"""
        SELECT {", ".join(sel)}
        FROM {table}
        {where}
        ORDER BY id, tf, ts
        """
    )
    return pd.read_sql(q, engine)


def spacing_eval(
    ts: pd.Series, spec: Optional[TfSpec]
) -> Tuple[int, int, float, float, float]:
    if ts.size < 2:
        return (0, 0, float("nan"), float("nan"), 0.0)
    t = pd.to_datetime(ts, utc=True).sort_values()
    deltas = t.diff().dropna().dt.total_seconds() / 86400.0
    n = int(deltas.size)
    mn = float(deltas.min())
    mx = float(deltas.max())

    if spec is None:
        return (0, n, mn, mx, 0.0)

    if spec.tf_days_min is not None and spec.tf_days_max is not None:
        bad = (deltas < spec.tf_days_min) | (deltas > spec.tf_days_max)
    elif spec.tf_days_nominal is not None:
        tol = 0.5
        bad = (deltas < (spec.tf_days_nominal - tol)) | (
            deltas > (spec.tf_days_nominal + tol)
        )
    else:
        return (0, n, mn, mx, 0.0)

    n_bad = int(bad.sum())
    share = float(n_bad / n) if n else 0.0
    return (n_bad, n, mn, mx, share)


def barseq_continuity_eval(bar_seq: pd.Series) -> Tuple[int, int]:
    """
    Returns (n_gaps, max_gap) on sorted bar_seq values.
    A gap is any jump > 1.
    """
    if bar_seq is None or bar_seq.size < 2:
        return (0, 0)
    s = pd.to_numeric(bar_seq, errors="coerce").dropna().astype("int64").sort_values()
    if s.size < 2:
        return (0, 0)
    diffs = s.diff().dropna()
    gaps = diffs[diffs > 1]
    n_gaps = int(gaps.size)
    max_gap = int(gaps.max()) if n_gaps else 0
    return (n_gaps, max_gap)


def run_spacing(
    engine: Engine, ids: List[int], dim_tf: str, out_csv: str
) -> pd.DataFrame:
    specs = load_tf_specs(engine, dim_tf)

    rows = []
    for table in BAR_TABLES.keys():
        if not table_exists(engine, table):
            continue
        df = fetch_canonical_closes(engine, table, ids)
        if df.empty:
            continue

        has_bar_seq = "bar_seq" in df.columns
        group_cols = ["id", "tf"]
        for (id_, tf), sub in df.groupby(group_cols, sort=True):
            spec = specs.get(str(tf))
            n_bad, n_deltas, mn, mx, bad_share = spacing_eval(sub["ts"], spec)
            n_gaps, max_gap = (
                barseq_continuity_eval(sub["bar_seq"]) if has_bar_seq else (0, 0)
            )

            rows.append(
                dict(
                    table_name=table,
                    id=int(id_),
                    tf=str(tf),
                    alignment_type=spec.alignment_type if spec else None,
                    tf_days_nominal=spec.tf_days_nominal if spec else None,
                    tf_days_min=spec.tf_days_min if spec else None,
                    tf_days_max=spec.tf_days_max if spec else None,
                    n_deltas=n_deltas,
                    n_bad_deltas=n_bad,
                    bad_delta_share=round(bad_share, 8),
                    min_delta_days=None if pd.isna(mn) else round(mn, 6),
                    max_delta_days=None if pd.isna(mx) else round(mx, 6),
                    n_barseq_gaps=n_gaps,
                    max_barseq_gap=max_gap,
                    audit_generated_at=datetime.now(UTC).isoformat(),
                )
            )

    out_df = pd.DataFrame(rows)
    if out_df.empty:
        raise RuntimeError(
            "No spacing results produced. Check table names/schema and permissions."
        )
    out_df = out_df.sort_values(
        ["bad_delta_share", "n_barseq_gaps", "table_name", "id", "tf"],
        ascending=[False, False, True, True, True],
    ).reset_index(drop=True)
    out_df.to_csv(out_csv, index=False)
    _log(f"[spacing] Wrote {len(out_df)} rows -> {out_csv}")
    return out_df


# ----------------------------
# Samples (ported from audit_price_bars_samples.py)
# ----------------------------


def get_tf_pairs(
    engine: Engine, table: str, ids: Sequence[int], max_tfs_per_id: Optional[int]
) -> pd.DataFrame:
    in_clause = ",".join(str(int(i)) for i in ids)
    q = text(
        f"""
        SELECT id, tf
        FROM (
          SELECT DISTINCT id, tf
          FROM {table}
          WHERE id IN ({in_clause})
        ) x
        ORDER BY id, tf
        """
    )
    df = pd.read_sql(q, engine)
    if df.empty:
        return df
    if not max_tfs_per_id or max_tfs_per_id <= 0:
        return df
    out = []
    for id_, sub in df.groupby("id", sort=True):
        out.append(sub.head(max_tfs_per_id))
    return pd.concat(out, ignore_index=True)


def pick_sample_cols(colset: set[str]) -> List[str]:
    preferred = [
        "id",
        "tf",
        "bar_seq",
        "time_close",
        "ts",
        "timestamp",
        "time_open",
        "time_high",
        "time_low",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "market_cap",
        "tf_days",
        "count_days",
        "count_days_remaining",
        "is_partial_start",
        "is_partial_end",
        "is_missing_days",
        "count_missing_days",
        "count_missing_days_start",
        "count_missing_days_interior",
        "count_missing_days_end",
        "missing_days_where",
        "ingested_at",
    ]
    return [c for c in preferred if c in colset]


def sample_group(
    engine: Engine, table: str, cols: List[str], id_: int, tf: str, per_group: int
) -> pd.DataFrame:
    colset = set(cols)
    ts_col = best_ts_col(colset)
    has_bar_seq = "bar_seq" in colset
    if ts_col and has_bar_seq:
        order_by = f"{ts_col} DESC, bar_seq DESC"
    elif ts_col:
        order_by = f"{ts_col} DESC"
    elif has_bar_seq:
        order_by = "bar_seq DESC"
    else:
        order_by = "id DESC"

    q = text(
        f"""
        SELECT {", ".join(cols)}
        FROM {table}
        WHERE id = :id AND tf = :tf
        ORDER BY {order_by}
        LIMIT :lim
        """
    )
    df = pd.read_sql(
        q, engine, params={"id": int(id_), "tf": str(tf), "lim": int(per_group)}
    )
    if df.empty:
        return df
    df.insert(0, "table_name", table)
    return df


def run_samples(
    engine: Engine,
    ids: List[int],
    per_group: int,
    max_tfs_per_id: Optional[int],
    out_csv: str,
) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for table in BAR_TABLES.keys():
        if not table_exists(engine, table):
            _log(f"[samples] SKIP missing table: {table}")
            continue
        colset = set(get_columns(engine, table))
        if "id" not in colset or "tf" not in colset:
            _log(f"[samples] SKIP {table}: missing id/tf")
            continue

        cols = pick_sample_cols(colset)
        if "id" not in cols:
            cols = ["id"] + cols
        if "tf" not in cols:
            cols = ["tf"] + cols

        tf_pairs = get_tf_pairs(engine, table, ids, max_tfs_per_id)
        if tf_pairs.empty:
            _log(f"[samples] No rows for {table} with requested ids.")
            continue

        _log(
            f"[samples] Sampling {table}: {len(tf_pairs)} (id,tf) groups * {per_group} rows each (max)."
        )
        for _, r in tf_pairs.iterrows():
            df_g = sample_group(
                engine, table, cols, int(r["id"]), str(r["tf"]), per_group
            )
            if not df_g.empty:
                frames.append(df_g)

    if not frames:
        raise RuntimeError(
            "No samples produced. Check ids/table names and permissions."
        )

    out_df = pd.concat(frames, ignore_index=True)
    out_df["sample_generated_at"] = datetime.now(UTC).isoformat()

    sort_cols = [c for c in ["table_name", "id", "tf"] if c in out_df.columns]
    ts_sort = None
    for cand in ["timestamp", "time_close", "ts"]:
        if cand in out_df.columns:
            ts_sort = cand
            break

    if ts_sort:
        out_df = out_df.sort_values(
            sort_cols + [ts_sort], ascending=[True, True, True, False]
        ).reset_index(drop=True)
    else:
        out_df = out_df.sort_values(sort_cols).reset_index(drop=True)

    out_df.to_csv(out_csv, index=False)
    _log(f"[samples] Wrote {len(out_df)} rows -> {out_csv}")
    return out_df


# ----------------------------
# CLI
# ----------------------------


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Bars integrity audit (coverage + table metrics + spacing + samples)."
    )
    ap.add_argument(
        "--ids", required=True, help="all OR comma-separated list like 1,52"
    )
    ap.add_argument(
        "--daily-table",
        default=DEFAULT_DAILY_TABLE,
        help="Used only to resolve --ids all",
    )
    ap.add_argument("--dim-tf", default=DEFAULT_DIM_TF)

    ap.add_argument(
        "--run",
        default="all",
        help="Comma list: coverage,audit,spacing,samples or 'all' (default)",
    )

    ap.add_argument("--out-coverage", default="price_bars_expected_coverage.csv")
    ap.add_argument("--out-audit", default="price_bars_audit.csv")
    ap.add_argument("--out-spacing", default="price_bars_spacing.csv")
    ap.add_argument("--out-samples", default="price_bars_samples.csv")

    ap.add_argument(
        "--per-group", type=int, default=25, help="Samples: rows per (table,id,tf)"
    )
    ap.add_argument(
        "--max-tfs-per-id",
        type=int,
        default=0,
        help="Samples: cap TFs per id (0 = no cap)",
    )

    args = ap.parse_args()

    db_url = resolve_db_url(None)
    engine = get_engine(db_url)

    ids_result = parse_ids(args.ids)
    if ids_result == "all":
        ids = load_all_ids(db_url, args.daily_table)
    else:
        ids = ids_result

    run_set = {
        s.strip().lower()
        for s in (args.run.split(",") if args.run else [])
        if s.strip()
    }
    if "all" in run_set or not run_set:
        run_set = {"coverage", "audit", "spacing", "samples"}

    ran = []
    if "coverage" in run_set:
        run_coverage(engine, ids, args.dim_tf, args.out_coverage)
        ran.append("coverage")
    if "audit" in run_set:
        run_audit(engine, ids, args.out_audit)
        ran.append("audit")
    if "spacing" in run_set:
        run_spacing(engine, ids, args.dim_tf, args.out_spacing)
        ran.append("spacing")
    if "samples" in run_set:
        max_tfs = (
            args.max_tfs_per_id
            if args.max_tfs_per_id and args.max_tfs_per_id > 0
            else None
        )
        run_samples(engine, ids, args.per_group, max_tfs, args.out_samples)
        ran.append("samples")

    _log(f"Done. Ran: {ran}")


if __name__ == "__main__":
    main()
