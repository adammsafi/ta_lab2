"""
audit_db.py — Shared helpers for writing audit results to the audit_results DB table.

The audit_results table uses the same DDL pattern as stats tables:
  (stat_id, table_name, test_name, asset_id, tf, period, status, actual, expected, extra, checked_at)

Usage from audit scripts:
    from ta_lab2.scripts.audit.audit_db import ensure_audit_table, write_audit_results

    engine = get_engine(resolve_db_url(None))
    ensure_audit_table(engine)

    # After running coverage/audit/spacing, convert and write:
    write_audit_results(engine, df_coverage, "ema", "coverage", thresholds=COVERAGE_THRESHOLDS)
    write_audit_results(engine, df_audit, "ema", "audit", thresholds=AUDIT_THRESHOLDS)
    write_audit_results(engine, df_spacing, "ema", "spacing", thresholds=SPACING_THRESHOLDS)
"""

from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

AUDIT_TABLE = "public.audit_results"

DDL_CREATE_AUDIT = f"""
CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
    stat_id     BIGSERIAL PRIMARY KEY,
    table_name  TEXT NOT NULL,
    test_name   TEXT NOT NULL,

    asset_id    BIGINT,
    tf          TEXT,
    period      INTEGER,

    status      TEXT NOT NULL,        -- PASS/WARN/FAIL
    actual      NUMERIC,
    expected    NUMERIC,
    extra       JSONB,
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def ensure_audit_table(engine: Engine) -> None:
    """Create audit_results table if it doesn't exist."""
    with engine.begin() as conn:
        conn.execute(text(DDL_CREATE_AUDIT))


def clear_audit_results(
    engine: Engine,
    source: str,
    audit_type: str,
) -> int:
    """Delete prior audit results for a given source + audit_type.

    Returns number of rows deleted.
    """
    with engine.begin() as conn:
        r = conn.execute(
            text(
                f"""
                DELETE FROM {AUDIT_TABLE}
                WHERE table_name = :source
                  AND test_name LIKE :pattern
            """
            ),
            {"source": source, "pattern": f"{audit_type}_%"},
        )
        return r.rowcount


def _to_python(v: Any) -> Any:
    """Convert numpy/pandas scalars to Python natives for JSON serialization."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if hasattr(v, "item"):
        return v.item()
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


def _make_extra(row: dict, exclude_keys: set[str]) -> dict:
    """Build JSONB extra from remaining columns."""
    return {
        k: _to_python(v)
        for k, v in row.items()
        if k not in exclude_keys
        and v is not None
        and not (isinstance(v, float) and pd.isna(v))
    }


# ── Coverage audit → audit_results ──────────────────────────────────────


def write_coverage_to_db(
    engine: Engine,
    df: pd.DataFrame,
    source: str,
) -> int:
    """Convert coverage audit DataFrame to audit_results rows.

    Each row becomes one audit_results entry with test_name='coverage'.
    Status: PASS if missing_share == 0, WARN if <= 0.05, FAIL otherwise.
    """
    if df.empty:
        return 0

    rows = []
    exclude = {
        "table_name",
        "n_expected_combos",
        "n_actual_combos",
        "n_missing_combos",
        "missing_share",
        "audit_generated_at",
    }

    for _, r in df.iterrows():
        miss_share = float(r.get("missing_share", 0) or 0)
        if miss_share == 0:
            status = "PASS"
        elif miss_share <= 0.05:
            status = "WARN"
        else:
            status = "FAIL"

        rows.append(
            {
                "table_name": str(r.get("table_name", source)),
                "test_name": "coverage_expected_vs_actual",
                "asset_id": None,
                "tf": None,
                "period": None,
                "status": status,
                "actual": _to_python(r.get("n_actual_combos")),
                "expected": _to_python(r.get("n_expected_combos")),
                "extra": json.dumps(_make_extra(dict(r), exclude)),
            }
        )

    return _insert_rows(engine, rows)


# ── Table audit → audit_results ─────────────────────────────────────────


def write_table_audit_to_db(
    engine: Engine,
    df: pd.DataFrame,
    source: str,
) -> int:
    """Convert table audit DataFrame to audit_results rows.

    Each (table, id, tf, [period]) row generates multiple test entries:
    - dup_key_check: PASS if n_dup_keys == 0
    - dup_snapshot_key_check: PASS if n_dup_snapshot_keys == 0 (bars only)
    - final_row_uniqueness: PASS if n_extra_final_rows == 0 (bars only)
    """
    if df.empty:
        return 0

    rows = []
    for _, r in df.iterrows():
        rd = dict(r)
        table_name = str(rd.get("table_name", source))
        asset_id = _to_python(rd.get("id"))
        tf = str(rd.get("tf", "")) if pd.notna(rd.get("tf")) else None
        period = _to_python(rd.get("period"))

        # PK duplicate check
        n_dup = int(rd.get("n_dup_keys", 0) or 0)
        rows.append(
            {
                "table_name": table_name,
                "test_name": "audit_pk_duplicates",
                "asset_id": asset_id,
                "tf": tf,
                "period": period,
                "status": "PASS" if n_dup == 0 else "FAIL",
                "actual": n_dup,
                "expected": 0,
                "extra": json.dumps(
                    {
                        "n_rows": _to_python(rd.get("n_rows")),
                        "dup_key_share": _to_python(rd.get("dup_key_share")),
                    }
                ),
            }
        )

        # Snapshot duplicate check (bars only)
        if "n_dup_snapshot_keys" in rd:
            n_snap_dup = int(rd.get("n_dup_snapshot_keys", 0) or 0)
            rows.append(
                {
                    "table_name": table_name,
                    "test_name": "audit_snapshot_duplicates",
                    "asset_id": asset_id,
                    "tf": tf,
                    "period": period,
                    "status": "PASS" if n_snap_dup == 0 else "FAIL",
                    "actual": n_snap_dup,
                    "expected": 0,
                    "extra": json.dumps(
                        {
                            "dup_snapshot_key_share": _to_python(
                                rd.get("dup_snapshot_key_share")
                            ),
                        }
                    ),
                }
            )

        # Final row uniqueness (bars only)
        if "n_extra_final_rows" in rd:
            n_extra = int(rd.get("n_extra_final_rows", 0) or 0)
            rows.append(
                {
                    "table_name": table_name,
                    "test_name": "audit_final_row_uniqueness",
                    "asset_id": asset_id,
                    "tf": tf,
                    "period": period,
                    "status": "PASS" if n_extra == 0 else "FAIL",
                    "actual": n_extra,
                    "expected": 0,
                    "extra": json.dumps(
                        {
                            "n_missing_final_barseq": _to_python(
                                rd.get("n_missing_final_barseq")
                            ),
                        }
                    ),
                }
            )

    return _insert_rows(engine, rows)


# ── Spacing audit → audit_results ───────────────────────────────────────


def write_spacing_to_db(
    engine: Engine,
    df: pd.DataFrame,
    source: str,
) -> int:
    """Convert spacing audit DataFrame to audit_results rows.

    Status: PASS if bad_delta_share == 0, WARN if <= 0.05, FAIL otherwise.
    """
    if df.empty:
        return 0

    rows = []
    exclude = {
        "table_name",
        "id",
        "tf",
        "period",
        "n_deltas",
        "n_bad_deltas",
        "bad_delta_share",
        "audit_generated_at",
    }

    for _, r in df.iterrows():
        rd = dict(r)
        bad_share = float(rd.get("bad_delta_share", 0) or 0)
        if bad_share == 0:
            status = "PASS"
        elif bad_share <= 0.05:
            status = "WARN"
        else:
            status = "FAIL"

        rows.append(
            {
                "table_name": str(rd.get("table_name", source)),
                "test_name": "audit_spacing_delta",
                "asset_id": _to_python(rd.get("id")),
                "tf": str(rd.get("tf", "")) if pd.notna(rd.get("tf")) else None,
                "period": _to_python(rd.get("period")),
                "status": status,
                "actual": _to_python(rd.get("n_bad_deltas")),
                "expected": 0,
                "extra": json.dumps(_make_extra(rd, exclude)),
            }
        )

        # Bar sequence gaps (bars only)
        if "n_barseq_gaps" in rd:
            n_gaps = int(rd.get("n_barseq_gaps", 0) or 0)
            rows.append(
                {
                    "table_name": str(rd.get("table_name", source)),
                    "test_name": "audit_barseq_continuity",
                    "asset_id": _to_python(rd.get("id")),
                    "tf": str(rd.get("tf", "")) if pd.notna(rd.get("tf")) else None,
                    "period": _to_python(rd.get("period")),
                    "status": "PASS" if n_gaps == 0 else "FAIL",
                    "actual": n_gaps,
                    "expected": 0,
                    "extra": json.dumps(
                        {
                            "max_barseq_gap": _to_python(rd.get("max_barseq_gap")),
                        }
                    ),
                }
            )

    return _insert_rows(engine, rows)


# ── Internal ────────────────────────────────────────────────────────────


def _insert_rows(engine: Engine, rows: list[dict]) -> int:
    """Batch insert rows into audit_results."""
    if not rows:
        return 0

    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                INSERT INTO {AUDIT_TABLE}
                (table_name, test_name, asset_id, tf, period,
                 status, actual, expected, extra)
                VALUES (:table_name, :test_name, :asset_id, :tf, :period,
                        :status, :actual, :expected, :extra)
            """
            ),
            rows,
        )
    return len(rows)
