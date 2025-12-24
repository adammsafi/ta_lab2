from __future__ import annotations
# -*- coding: utf-8 -*-

"""
audit_ema_integrity.py

One-stop audit for EMA tables.

Combines:
  - audit_ema_expected_coverage.py (expected vs actual (id,tf,period) combos)
  - audit_ema_tables.py (per group metrics, duplicate key detection, roll shares, NULL shares)
  - audit_ema_samples.py (human-eyeball sampling CSV)

Adds (missing from the three originals):
  - Spacing checks vs dim_timeframe (canonical rows):
      * For each (table,id,tf,period), compute deltas between successive canonical ts.
      * Validate that deltas fall within [tf_days_min, tf_days_max] when available.
        If tf_days_min/max are NULL, fall back to tf_days_nominal (exact match, ±0.5 days).
  - Canonical-only duplicate check (semantic guardrail):
      * If a roll flag exists, check duplicates among canonical rows (roll=false) separately.

Outputs (CSV files):
  - --out-coverage: expected coverage summary per table
  - --out-audit: per-(table,id,tf,period) metrics (duplicates/nulls/roll shares)
  - --out-spacing: spacing diagnostics per-(table,id,tf,period) plus worst offenders
  - --out-samples: sampled rows for eyeballing (optional; can be large)

Run:
  python audit_ema_integrity.py --ids all

Common:
  python audit_ema_integrity.py --ids all --periods lut --run coverage,audit,spacing

Spyder runfile:
  runfile(
    r"C:\\Users\\asafi\\Downloads\\ta_lab2\\src\\ta_lab2\\scripts\\emas\\audit_ema_integrity.py",
    wdir=r"C:\\Users\\asafi\\Downloads\\ta_lab2",
    args="--ids all --periods lut --run all"
  )

Notes:
- Uses TARGET_DB_URL env var.
- Designed for your current small id set (7); uses simple IN (...) clauses for clarity.
- Spacing checks rely on dim_timeframe columns:
    tf, alignment_type, tf_days_nominal, tf_days_min, tf_days_max
  If your dim_timeframe uses different column names, update DIM_TF_COLS below.
"""

import argparse
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# ----------------------------
# Defaults / Tables
# ----------------------------

DEFAULT_DAILY_TABLE = "public.cmc_price_histories7"
DEFAULT_DIM_TF = "public.dim_timeframe"
DEFAULT_LUT = "public.ema_alpha_lookup"

EMA_TABLES: Dict[str, str] = {
    "public.cmc_ema_multi_tf": "TF_DAY",
    "public.cmc_ema_multi_tf_v2": "TF_DAY",
    "public.cmc_ema_multi_tf_cal_us": "CAL_US",
    "public.cmc_ema_multi_tf_cal_iso": "CAL_ISO",
    "public.cmc_ema_multi_tf_cal_anchor_us": "ANCHOR_US",
    "public.cmc_ema_multi_tf_cal_anchor_iso": "ANCHOR_ISO",
}

TABLES_FOR_SAMPLES = list(EMA_TABLES.keys())

# dim_timeframe columns expected for spacing checks
DIM_TF_COLS = ["tf", "alignment_type", "tf_days_nominal", "tf_days_min", "tf_days_max"]


def _log(msg: str) -> None:
    print(f"[ema_integrity] {msg}")


def get_engine() -> Engine:
    db_url = os.environ.get("TARGET_DB_URL")
    if not db_url:
        raise RuntimeError("TARGET_DB_URL env var is required.")
    _log("Using DB URL from TARGET_DB_URL env.")
    return create_engine(db_url, future=True)


def parse_ids(engine: Engine, ids_arg: str, daily_table: str) -> List[int]:
    if ids_arg.strip().lower() == "all":
        df = pd.read_sql(text(f"SELECT DISTINCT id FROM {daily_table} ORDER BY id"), engine)
        ids = [int(x) for x in df["id"].tolist()]
        _log(f"Loaded ALL ids from {daily_table}: {len(ids)}")
        return ids

    ids: List[int] = []
    for p in ids_arg.split(","):
        p = p.strip()
        if p:
            ids.append(int(p))
    if not ids:
        raise ValueError("No ids parsed.")
    return ids


def load_periods(engine: Engine, periods_arg: str, lut_table: str) -> List[int]:
    s = (periods_arg or "").strip().lower()
    if s == "lut":
        df = pd.read_sql(
            text(f"SELECT DISTINCT period::int AS period FROM {lut_table} ORDER BY period"),
            engine,
        )
        periods = [int(x) for x in df["period"].tolist()]
        _log(f"Loaded periods from {lut_table}: {len(periods)}")
        return periods

    periods: List[int] = []
    for p in s.split(","):
        p = p.strip()
        if p:
            periods.append(int(p))
    if not periods:
        raise ValueError("No periods parsed.")
    return periods


def load_tfs(engine: Engine, family: str, dim_tf_table: str) -> List[str]:
    """
    Return TF list per family using current dim_timeframe semantics:
      - tf_day: alignment_type='tf_day'
      - calendar aligned: calendar_anchor=FALSE
      - calendar anchored: calendar_anchor=TRUE

    Naming rules used:
      - Weeks are scheme-specific: *_CAL_US / *_CAL_ISO and *_CAL_ANCHOR_US / *_CAL_ANCHOR_ISO
      - Months/Years are scheme-agnostic: *_CAL and *_CAL_ANCHOR
    """
    if family == "TF_DAY":
        q = text(
            f"""
            SELECT tf
            FROM {dim_tf_table}
            WHERE alignment_type = 'tf_day'
              AND is_canonical = TRUE
            ORDER BY display_order, sort_order, tf
            """
        )
        df = pd.read_sql(q, engine)
        return [str(x) for x in df["tf"].tolist()]

    if family in {"CAL_US", "CAL_ISO"}:
        scheme = "US" if family == "CAL_US" else "ISO"
        q = text(
            f"""
            SELECT tf
            FROM {dim_tf_table}
            WHERE alignment_type = 'calendar'
              AND calendar_anchor = FALSE
              AND is_canonical = TRUE
              AND allow_partial_start = FALSE
              AND allow_partial_end   = FALSE
              AND tf NOT LIKE '%\\_CAL\\_ANCHOR\\_%' ESCAPE '\\'
              AND tf NOT LIKE '%\\_ANCHOR%' ESCAPE '\\'
              AND (
                    (base_unit = 'W' AND tf ~ ('_CAL_' || :scheme || '$'))
                    OR
                    (base_unit IN ('M','Y') AND tf ~ '_CAL$' AND tf !~ '_CAL_')
                  )
            ORDER BY display_order, sort_order, tf
            """
        )
        df = pd.read_sql(q, engine, params={"scheme": scheme})
        return [str(x) for x in df["tf"].tolist()]

    if family in {"ANCHOR_US", "ANCHOR_ISO"}:
        scheme = "US" if family == "ANCHOR_US" else "ISO"
        q = text(
            f"""
            SELECT tf
            FROM {dim_tf_table}
            WHERE alignment_type = 'calendar'
              AND calendar_anchor = TRUE
              AND is_canonical = TRUE
              AND allow_partial_start = TRUE
              AND allow_partial_end   = TRUE
              AND (
                    (base_unit = 'W' AND tf ~ ('_CAL_ANCHOR_' || :scheme || '$'))
                    OR
                    (base_unit IN ('M','Y') AND tf ~ '_CAL_ANCHOR$')
                  )
            ORDER BY display_order, sort_order, tf
            """
        )
        df = pd.read_sql(q, engine, params={"scheme": scheme})
        return [str(x) for x in df["tf"].tolist()]

    raise ValueError(f"Unknown family: {family}")


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


# ----------------------------
# Coverage audit
# ----------------------------

def actual_combos(engine: Engine, ema_table: str, ids: List[int]) -> pd.DataFrame:
    in_clause = ",".join(str(int(i)) for i in ids)
    q = text(
        f"""
        SELECT DISTINCT id::int AS id, tf::text AS tf, period::int AS period
        FROM {ema_table}
        WHERE id IN ({in_clause})
        """
    )
    return pd.read_sql(q, engine)


def run_coverage(engine: Engine, ids: List[int], periods: List[int], dim_tf: str, out_csv: str) -> pd.DataFrame:
    rows = []
    for ema_table, family in EMA_TABLES.items():
        tfs = load_tfs(engine, family, dim_tf)
        exp = len(ids) * len(tfs) * len(periods)
        act_df = actual_combos(engine, ema_table, ids)
        act = len(act_df)
        missing = max(exp - act, 0)
        miss_share = (missing / exp) if exp else 0.0
        rows.append(
            {
                "table_name": ema_table,
                "family": family,
                "n_ids": len(ids),
                "n_tfs": len(tfs),
                "n_periods": len(periods),
                "n_expected_combos": exp,
                "n_actual_combos": act,
                "n_missing_combos": missing,
                "missing_share": round(miss_share, 8),
                "audit_generated_at": datetime.now(UTC).isoformat(),
            }
        )
    out_df = pd.DataFrame(rows).sort_values(["table_name"]).reset_index(drop=True)
    out_df.to_csv(out_csv, index=False)
    _log(f"[coverage] Wrote {len(out_df)} rows -> {out_csv}")
    return out_df


# ----------------------------
# Table audit (duplicates, roll shares, null shares)
# ----------------------------

def audit_table(engine: Engine, table: str, ids: Sequence[int]) -> pd.DataFrame:
    if not table_exists(engine, table):
        _log(f"[audit] SKIP missing table: {table}")
        return pd.DataFrame()

    cols = get_columns(engine, table)
    colset = set(cols)

    required = {"id", "tf", "ts", "period"}
    if not required.issubset(colset):
        _log(f"[audit] SKIP {table}: missing {sorted(required - colset)}")
        return pd.DataFrame()

    has_roll = "roll" in colset
    has_roll_bar = "roll_bar" in colset

    maybe_cols = [
        "ema",
        "d1",
        "d2",
        "d1_roll",
        "d2_roll",
        "ema_bar",
        "d1_bar",
        "d2_bar",
        "d1_roll_bar",
        "d2_roll_bar",
        "tf_days",
    ]
    present_cols = [c for c in maybe_cols if c in colset]

    in_clause = ",".join(str(int(i)) for i in ids)

    select_parts = [
        f"'{table}'::text AS table_name",
        "id",
        "tf",
        "period",
        "COUNT(*)::bigint AS n_rows",
        "MIN(ts) AS min_ts",
        "MAX(ts) AS max_ts",
        "COUNT(DISTINCT (id, tf, ts, period))::bigint AS n_distinct_keys",
        "COUNT(*)::bigint - COUNT(DISTINCT (id, tf, ts, period))::bigint AS n_dup_keys",
    ]

    if has_roll:
        select_parts += [
            "SUM(CASE WHEN roll THEN 1 ELSE 0 END)::bigint AS n_roll_true",
            "SUM(CASE WHEN NOT roll THEN 1 ELSE 0 END)::bigint AS n_roll_false",
            # Canonical-only duplicates (semantic guardrail)
            "SUM(CASE WHEN NOT roll THEN 1 ELSE 0 END)::bigint - "
            "COUNT(DISTINCT (CASE WHEN NOT roll THEN (id, tf, ts, period) END))::bigint "
            "AS n_dup_keys_canonical",
        ]
    if has_roll_bar:
        select_parts += [
            "SUM(CASE WHEN roll_bar THEN 1 ELSE 0 END)::bigint AS n_roll_bar_true",
            "SUM(CASE WHEN NOT roll_bar THEN 1 ELSE 0 END)::bigint AS n_roll_bar_false",
        ]

    for c in present_cols:
        select_parts.append(f"SUM(CASE WHEN {c} IS NULL THEN 1 ELSE 0 END)::bigint AS n_{c}_null")

    q = text(
        f"""
        SELECT
          {", ".join(select_parts)}
        FROM {table}
        WHERE id IN ({in_clause})
        GROUP BY id, tf, period
        ORDER BY id, tf, period
        """
    )
    df = pd.read_sql(q, engine)
    if df.empty:
        return df

    df["audit_generated_at"] = datetime.now(UTC).isoformat()
    df["dup_key_share"] = (df["n_dup_keys"] / df["n_rows"]).round(8)

    if has_roll:
        df["roll_share"] = (df["n_roll_true"] / df["n_rows"]).round(8)
        df["canonical_share"] = (df["n_roll_false"] / df["n_rows"]).round(8)
        df["dup_key_canonical_share"] = (df["n_dup_keys_canonical"] / df["n_rows"]).round(8)

    if has_roll_bar:
        df["roll_bar_share"] = (df["n_roll_bar_true"] / df["n_rows"]).round(8)
        df["canonical_bar_share"] = (df["n_roll_bar_false"] / df["n_rows"]).round(8)

    for c in present_cols:
        df[f"{c}_null_share"] = (df[f"n_{c}_null"] / df["n_rows"]).round(8)

    return df


def run_audit(engine: Engine, ids: List[int], out_csv: str) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for t in EMA_TABLES.keys():
        df_t = audit_table(engine, t, ids)
        if not df_t.empty:
            frames.append(df_t)
    if not frames:
        raise RuntimeError("No audit results. Check table names/schema and permissions.")
    out_df = pd.concat(frames, ignore_index=True)
    out_df = out_df.sort_values(["table_name", "id", "tf", "period"]).reset_index(drop=True)
    out_df.to_csv(out_csv, index=False)
    _log(f"[audit] Wrote {len(out_df)} rows -> {out_csv}")
    return out_df


# ----------------------------
# Spacing audit (missing piece)
# ----------------------------

@dataclass(frozen=True)
class TfSpec:
    tf: str
    alignment_type: str
    tf_days_nominal: Optional[float]
    tf_days_min: Optional[float]
    tf_days_max: Optional[float]


def load_dim_timeframe_specs(engine: Engine, dim_tf: str) -> Dict[str, TfSpec]:
    # Try to load required columns; if missing, raise with a useful message.
    q = text(
        f"""
        SELECT {", ".join(DIM_TF_COLS)}
        FROM {dim_tf}
        """
    )
    df = pd.read_sql(q, engine)
    missing_cols = [c for c in DIM_TF_COLS if c not in df.columns]
    if missing_cols:
        raise RuntimeError(f"dim_timeframe missing columns needed for spacing audit: {missing_cols}")

    out: Dict[str, TfSpec] = {}
    for _, r in df.iterrows():
        tf = str(r["tf"])
        out[tf] = TfSpec(
            tf=tf,
            alignment_type=str(r["alignment_type"]) if pd.notna(r["alignment_type"]) else "",
            tf_days_nominal=float(r["tf_days_nominal"]) if pd.notna(r["tf_days_nominal"]) else None,
            tf_days_min=float(r["tf_days_min"]) if pd.notna(r["tf_days_min"]) else None,
            tf_days_max=float(r["tf_days_max"]) if pd.notna(r["tf_days_max"]) else None,
        )
    return out


def fetch_canonical_ts(engine: Engine, table: str, ids: Sequence[int]) -> pd.DataFrame:
    cols = get_columns(engine, table)
    colset = set(cols)
    required = {"id", "tf", "ts", "period"}
    if not required.issubset(colset):
        return pd.DataFrame()

    has_roll = "roll" in colset
    in_clause = ",".join(str(int(i)) for i in ids)

    if has_roll:
        where = "WHERE id IN ({}) AND roll = FALSE".format(in_clause)
    else:
        # No roll flag means table might already be canonical-only; keep all rows.
        where = "WHERE id IN ({})".format(in_clause)

    q = text(
        f"""
        SELECT id::int AS id, tf::text AS tf, period::int AS period, ts
        FROM {table}
        {where}
        ORDER BY id, tf, period, ts
        """
    )
    return pd.read_sql(q, engine)


def spacing_eval_for_group(ts_series: pd.Series, spec: Optional[TfSpec]) -> Tuple[int, int, float, float, float]:
    """
    Returns:
      n_gaps, n_total_deltas, min_delta_days, max_delta_days, bad_share
    """
    if ts_series.size < 2:
        return (0, 0, float("nan"), float("nan"), 0.0)

    t = pd.to_datetime(ts_series, utc=True).sort_values()
    deltas = t.diff().dropna().dt.total_seconds() / 86400.0  # days
    n = int(deltas.size)
    mn = float(deltas.min())
    mx = float(deltas.max())

    if spec is None:
        # No spec: can't validate, so return 0 bad
        return (0, n, mn, mx, 0.0)

    # Prefer min/max bounds when present (robust for calendar).
    if spec.tf_days_min is not None and spec.tf_days_max is not None:
        bad = (deltas < spec.tf_days_min) | (deltas > spec.tf_days_max)
    elif spec.tf_days_nominal is not None:
        # If only nominal exists, allow tiny tolerance for tz/rounding.
        tol = 0.5
        bad = (deltas < (spec.tf_days_nominal - tol)) | (deltas > (spec.tf_days_nominal + tol))
    else:
        return (0, n, mn, mx, 0.0)

    n_bad = int(bad.sum())
    bad_share = float(n_bad / n) if n else 0.0
    return (n_bad, n, mn, mx, bad_share)


def run_spacing(engine: Engine, ids: List[int], dim_tf: str, out_csv: str) -> pd.DataFrame:
    specs = load_dim_timeframe_specs(engine, dim_tf)

    rows = []
    for table in EMA_TABLES.keys():
        if not table_exists(engine, table):
            continue
        df = fetch_canonical_ts(engine, table, ids)
        if df.empty:
            continue

        for (id_, tf, period), sub in df.groupby(["id", "tf", "period"], sort=True):
            spec = specs.get(str(tf))
            n_bad, n_deltas, mn, mx, bad_share = spacing_eval_for_group(sub["ts"], spec)

            rows.append(
                {
                    "table_name": table,
                    "id": int(id_),
                    "tf": str(tf),
                    "period": int(period),
                    "alignment_type": spec.alignment_type if spec else None,
                    "tf_days_nominal": spec.tf_days_nominal if spec else None,
                    "tf_days_min": spec.tf_days_min if spec else None,
                    "tf_days_max": spec.tf_days_max if spec else None,
                    "n_deltas": n_deltas,
                    "n_bad_deltas": n_bad,
                    "bad_delta_share": round(bad_share, 8),
                    "min_delta_days": None if pd.isna(mn) else round(mn, 6),
                    "max_delta_days": None if pd.isna(mx) else round(mx, 6),
                    "audit_generated_at": datetime.now(UTC).isoformat(),
                }
            )

    out_df = pd.DataFrame(rows)
    if out_df.empty:
        raise RuntimeError("No spacing results produced. Check that tables exist and have data.")
    out_df = out_df.sort_values(["bad_delta_share", "table_name", "id", "tf", "period"], ascending=[False, True, True, True, True]).reset_index(drop=True)
    out_df.to_csv(out_csv, index=False)
    _log(f"[spacing] Wrote {len(out_df)} rows -> {out_csv}")
    return out_df


# ----------------------------
# Samples (human eyeball)
# ----------------------------

def pick_sample_cols(colset: set[str]) -> List[str]:
    preferred = [
        "id", "tf", "period", "ts", "tf_days",
        "roll", "ema", "d1", "d2", "d1_roll", "d2_roll",
        "roll_bar", "ema_bar", "d1_bar", "d2_bar", "d1_roll_bar", "d2_roll_bar",
        "ingested_at",
    ]
    return [c for c in preferred if c in colset]


def get_group_keys(engine: Engine, table: str, ids: Sequence[int], max_groups_per_id: Optional[int]) -> pd.DataFrame:
    in_clause = ",".join(str(int(i)) for i in ids)
    q = text(
        f"""
        SELECT id, tf, period
        FROM (
          SELECT DISTINCT id, tf, period
          FROM {table}
          WHERE id IN ({in_clause})
        ) x
        ORDER BY id, tf, period
        """
    )
    df = pd.read_sql(q, engine)
    if df.empty or not max_groups_per_id or max_groups_per_id <= 0:
        return df

    out = []
    for id_, sub in df.groupby("id", sort=True):
        out.append(sub.head(max_groups_per_id))
    return pd.concat(out, ignore_index=True)


def sample_group(engine: Engine, table: str, cols: List[str], id_: int, tf: str, period: int, per_group: int) -> pd.DataFrame:
    q = text(
        f"""
        SELECT {", ".join(cols)}
        FROM {table}
        WHERE id = :id AND tf = :tf AND period = :period
        ORDER BY ts DESC
        LIMIT :lim
        """
    )
    df = pd.read_sql(q, engine, params={"id": int(id_), "tf": str(tf), "period": int(period), "lim": int(per_group)})
    if df.empty:
        return df
    df.insert(0, "table_name", table)
    return df


def run_samples(engine: Engine, ids: List[int], per_group: int, max_groups_per_id: Optional[int], out_csv: str) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for table in TABLES_FOR_SAMPLES:
        if not table_exists(engine, table):
            _log(f"[samples] SKIP missing table: {table}")
            continue

        cols_all = get_columns(engine, table)
        colset = set(cols_all)
        required = {"id", "tf", "period", "ts"}
        if not required.issubset(colset):
            _log(f"[samples] SKIP {table}: missing {sorted(required - colset)}")
            continue

        cols = pick_sample_cols(colset)
        keys = get_group_keys(engine, table, ids, max_groups_per_id=max_groups_per_id)
        if keys.empty:
            _log(f"[samples] No groups found for {table} with requested ids.")
            continue

        _log(f"[samples] Sampling {table}: {len(keys)} groups * {per_group} rows each (max).")
        for _, r in keys.iterrows():
            df_g = sample_group(engine, table, cols, int(r["id"]), str(r["tf"]), int(r["period"]), per_group)
            if not df_g.empty:
                frames.append(df_g)

    if not frames:
        raise RuntimeError("No samples produced. Check ids/table names and permissions.")

    out_df = pd.concat(frames, ignore_index=True)
    out_df["sample_generated_at"] = datetime.now(UTC).isoformat()
    out_df = out_df.sort_values(["table_name", "id", "tf", "period", "ts"], ascending=[True, True, True, True, False]).reset_index(drop=True)
    out_df.to_csv(out_csv, index=False)
    _log(f"[samples] Wrote {len(out_df)} rows -> {out_csv}")
    return out_df


# ----------------------------
# CLI
# ----------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="EMA integrity audit (coverage + duplicates/nulls + spacing + samples).")
    ap.add_argument("--ids", required=True, help="all OR comma-separated list like 1,52")
    ap.add_argument("--daily-table", default=DEFAULT_DAILY_TABLE, help="Used only to resolve --ids all")
    ap.add_argument("--dim-tf", default=DEFAULT_DIM_TF)
    ap.add_argument("--lut", default=DEFAULT_LUT)
    ap.add_argument("--periods", default="lut", help="lut or comma list (used by coverage)")
    ap.add_argument(
        "--run",
        default="all",
        help="Comma list of audits to run: coverage,audit,spacing,samples or 'all' (default).",
    )

    ap.add_argument("--out-coverage", default="ema_expected_coverage.csv")
    ap.add_argument("--out-audit", default="ema_audit.csv")
    ap.add_argument("--out-spacing", default="ema_spacing.csv")
    ap.add_argument("--out-samples", default="ema_samples.csv")

    ap.add_argument("--per-group", type=int, default=50, help="Samples: rows per (table,id,tf,period) group")
    ap.add_argument("--max-groups-per-id", type=int, default=0, help="Samples: cap groups per id (0 = no cap)")

    args = ap.parse_args()

    engine = get_engine()
    ids = parse_ids(engine, args.ids, args.daily_table)

    run_set = {s.strip().lower() for s in (args.run.split(",") if args.run else []) if s.strip()}
    if "all" in run_set or not run_set:
        run_set = {"coverage", "audit", "spacing", "samples"}

    results: Dict[str, pd.DataFrame] = {}

    if "coverage" in run_set:
        periods = load_periods(engine, args.periods, args.lut)
        results["coverage"] = run_coverage(engine, ids, periods, args.dim_tf, args.out_coverage)

    if "audit" in run_set:
        results["audit"] = run_audit(engine, ids, args.out_audit)

    if "spacing" in run_set:
        results["spacing"] = run_spacing(engine, ids, args.dim_tf, args.out_spacing)

    if "samples" in run_set:
        max_groups = args.max_groups_per_id if args.max_groups_per_id and args.max_groups_per_id > 0 else None
        results["samples"] = run_samples(engine, ids, args.per_group, max_groups, args.out_samples)

    _log(f"Done. Ran: {sorted(results.keys())}")


if __name__ == "__main__":
    main()
