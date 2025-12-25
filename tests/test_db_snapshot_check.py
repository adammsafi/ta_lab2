from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

r"""
From repo root (recommended):
python -m pytest -q tests/test_db_snapshot_check.py

More verbose output:
python -m pytest -vv tests/test_db_snapshot_check.py

Run just this one test function:
python -m pytest -q tests/test_db_snapshot_check.py::test_snapshot_check_output_shape_and_warning_gating

Spyder (IPython console), from repo root:
%run -m pytest -q tests/test_db_snapshot_check.py

Spyder, verbose:
%run -m pytest -vv tests/test_db_snapshot_check.py

Spyder, single test:
%run -m pytest -q tests/test_db_snapshot_check.py::test_snapshot_check_output_shape_and_warning_gating
"""

FIXTURE = Path(__file__).parent / "fixtures" / "db_schema_snapshot_min.json"


def _run_snapshot_check() -> dict:
    """
    Prefer calling the CLI (most end-to-end, catches wiring regressions).
    Fallback: if you want pure import-based, add a second helper below
    once you confirm your dbtool exposes a callable main(argv).
    """
    if not FIXTURE.exists():
        raise FileNotFoundError(f"Missing fixture at {FIXTURE}")

    # Try console script first (most realistic)
    cmd = ["ta-lab2", "db", "snapshot-check", "--in-path", str(FIXTURE), "--min-rows", "1", "--top-n", "20"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if p.returncode == 0:
            return json.loads(p.stdout)
    except FileNotFoundError:
        # console script not on PATH in CI/venv context; fall through
        pass

    # Fallback: python -m (more reliable in CI if entry point isn't installed)
    # Adjust module path if your dbtool is elsewhere.
    cmd2 = [
        sys.executable,
        "-m",
        "ta_lab2.tools.dbtool",
        "snapshot-check",
        "--in-path",
        str(FIXTURE),
        "--min-rows",
        "1",
        "--top-n",
        "20",
    ]
    p2 = subprocess.run(cmd2, capture_output=True, text=True, check=True)
    return json.loads(p2.stdout)


def test_snapshot_check_output_shape_and_warning_gating():
    out = _run_snapshot_check()

    # Output keys stable
    for k in ["meta", "ok", "source", "warnings", "top_tables_by_total_bytes", "top_tables_by_rows"]:
        assert k in out, f"Missing key: {k}"

    assert out["ok"] is True
    assert out["source"]  # should be path-like string

    warnings = out["warnings"]
    assert isinstance(warnings, list)

    # No duplicates
    assert len(warnings) == len(set(warnings)), "Warnings list has duplicates"

    # Warning gating: only the table missing pg_stats should warn about analyze timestamps
    expected = {
        "public.table_missing_pg_stats: pg_stats missing",
        "public.table_missing_pg_stats: no analyze timestamps",
    }
    assert set(warnings) == expected

    # Sorting: total_bytes desc in top_tables_by_total_bytes
    topb = out["top_tables_by_total_bytes"]
    assert isinstance(topb, list) and len(topb) >= 2
    totals = [t["total_bytes"] for t in topb]
    assert totals == sorted(totals, reverse=True)

    # Rows list exists and is desc-sorted
    topr = out["top_tables_by_rows"]
    assert isinstance(topr, list) and len(topr) >= 2
    rows = [t["approx_rows"] for t in topr]
    assert rows == sorted(rows, reverse=True)
