from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> dict:
    p = subprocess.run(cmd, capture_output=True, text=True)
    assert p.returncode == 0, f"STDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}\n"
    return json.loads(p.stdout)


def test_snapshot_diff_added_removed_and_deltas(tmp_path: Path) -> None:
    a = tmp_path / "a.json"
    b = tmp_path / "b.json"

    a.write_text(
        json.dumps(
            {
                "meta": {},
                "schemas": ["public"],
                "tables": {
                    "public.t1": {"schema": "public", "table": "t1", "approx_rows": 10}
                },
                "table_stats": {
                    "public.t1": {
                        "total_bytes": 100,
                        "table_bytes": 70,
                        "index_bytes": 30,
                    }
                },
                "top_col_stats": {"public.t1": []},
            }
        ),
        encoding="utf-8",
    )

    b.write_text(
        json.dumps(
            {
                "meta": {},
                "schemas": ["public"],
                "tables": {
                    "public.t1": {"schema": "public", "table": "t1", "approx_rows": 30},
                    "public.t2": {"schema": "public", "table": "t2", "approx_rows": 1},
                },
                "table_stats": {
                    "public.t1": {
                        "total_bytes": 300,
                        "table_bytes": 210,
                        "index_bytes": 90,
                    },
                    "public.t2": {
                        "total_bytes": 50,
                        "table_bytes": 50,
                        "index_bytes": 0,
                    },
                },
                "top_col_stats": {"public.t1": [], "public.t2": []},
            }
        ),
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        "-m",
        "ta_lab2.tools.dbtool",
        "snapshot-diff",
        "--a",
        str(a),
        "--b",
        str(b),
        "--top-n",
        "25",
    ]
    out = _run(cmd)

    assert out["ok"] is True
    assert out["summary"]["tables_added"] == 1
    assert out["summary"]["tables_removed"] == 0
    assert "public.t2" in out["tables_added"]

    deltas = out["top_table_deltas_by_abs_bytes"]
    assert deltas and deltas[0]["table"] == "public.t1"
    assert deltas[0]["delta_bytes"] == 200
