"""
sync_results_from_vm.py

Pull execution state from the Oracle Singapore VM to local DB.
Same SSH + psql COPY pattern as sync_hl_from_vm.py, direction reversed
(VM → local instead of VM → local for HL data).

9 tables:
  - orders          (incremental by created_at)
  - fills           (incremental by filled_at)
  - positions       (incremental by updated_at)
  - paper_orders    (incremental by created_at)
  - executor_run_log (incremental by started_at)
  - drift_metrics   (incremental by computed_at)
  - risk_events     (incremental by created_at)
  - order_events    (incremental by created_at)
  - dim_risk_state  (full replace: TRUNCATE + COPY — small config table)

Watermarks are stored in a local `sync_results_watermarks` table that is
auto-created on first run.

Usage:
    python -m ta_lab2.scripts.etl.sync_results_from_vm              # incremental
    python -m ta_lab2.scripts.etl.sync_results_from_vm --full       # full resync all tables
    python -m ta_lab2.scripts.etl.sync_results_from_vm --dry-run    # report only (no data moved)
    python -m ta_lab2.scripts.etl.sync_results_from_vm --table orders   # sync one table

Suggested crontab (every 4 hours):
    0 */4 * * * /path/to/venv/bin/python -m ta_lab2.scripts.etl.sync_results_from_vm
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import text

from ta_lab2.io import get_engine

# ── VM connection details (same Oracle VM as sync_hl_from_vm.py) ──────────────
VM_HOST = "161.118.209.59"
VM_USER = "ubuntu"
VM_SSH_KEY = str(
    Path.home() / "Downloads" / "oracle_sg_keys" / "ssh-key-2026-03-10.key"
)
VM_DB = "hyperliquid"
VM_DB_USER = "hluser"
VM_DB_PASS = "hlpass"

# ── Watermark tracking table (auto-created on first run) ──────────────────────
_WATERMARKS_TABLE = "sync_results_watermarks"
_CREATE_WATERMARKS_DDL = f"""
CREATE TABLE IF NOT EXISTS {_WATERMARKS_TABLE} (
    table_name   TEXT        PRIMARY KEY,
    last_synced  TIMESTAMPTZ NOT NULL,
    rows_last    INTEGER     NOT NULL DEFAULT 0,
    synced_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


# ── Table registry ─────────────────────────────────────────────────────────────


class TableSpec(NamedTuple):
    name: str  # table name (same on VM and local)
    wm_col: str | None  # watermark column; None → full_replace
    pk_cols: list[str]  # conflict columns for ON CONFLICT upsert
    update_cols: list[str] | None = None  # None → DO NOTHING; list → DO UPDATE SET
    full_replace: bool = False  # True → TRUNCATE local + COPY all VM rows
    timeout: int = 120  # COPY timeout in seconds


_INCREMENTAL_TABLES: list[TableSpec] = [
    TableSpec(
        name="orders",
        wm_col="created_at",
        pk_cols=["order_id"],
        update_cols=None,  # orders are immutable once created (fills update fills table)
    ),
    TableSpec(
        name="fills",
        wm_col="filled_at",
        pk_cols=["fill_id"],
        update_cols=None,
    ),
    TableSpec(
        name="positions",
        wm_col="updated_at",
        pk_cols=["position_id"],
        update_cols=[
            "updated_at",
            "status",
            "quantity",
            "avg_entry_price",
            "realized_pnl",
            "unrealized_pnl",
            "closed_at",
        ],
    ),
    TableSpec(
        name="paper_orders",
        wm_col="created_at",
        pk_cols=["paper_order_id"],
        update_cols=None,
    ),
    TableSpec(
        name="executor_run_log",
        wm_col="started_at",
        pk_cols=["run_id"],
        update_cols=[
            "ended_at",
            "status",
            "signals_processed",
            "orders_placed",
            "error_message",
        ],
    ),
    TableSpec(
        name="drift_metrics",
        wm_col="computed_at",
        pk_cols=["id", "metric_name", "ts"],
        update_cols=["computed_at", "value", "threshold", "status"],
    ),
    TableSpec(
        name="risk_events",
        wm_col="created_at",
        pk_cols=["event_id"],
        update_cols=None,
    ),
    TableSpec(
        name="order_events",
        wm_col="created_at",
        pk_cols=["event_id"],
        update_cols=None,
    ),
]

_FULL_REPLACE_TABLES: list[TableSpec] = [
    TableSpec(
        name="dim_risk_state",
        wm_col=None,
        pk_cols=["state_id"],
        full_replace=True,
        timeout=30,
    ),
]

ALL_TABLES: list[TableSpec] = _INCREMENTAL_TABLES + _FULL_REPLACE_TABLES

# Map of short CLI name → TableSpec for --table argument
_TABLE_CHOICES: dict[str, TableSpec] = {spec.name: spec for spec in ALL_TABLES}


# ── SSH helpers (identical pattern to sync_hl_from_vm.py) ─────────────────────


def _ssh_cmd(remote_cmd: str) -> list[str]:
    """Build SSH command list for subprocess."""
    return [
        "ssh",
        "-i",
        VM_SSH_KEY,
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
        f"{VM_USER}@{VM_HOST}",
        remote_cmd,
    ]


def _vm_psql(sql: str, timeout: int = 60) -> str:
    """Run a psql command on the VM via SSH. Returns stdout."""
    cmd = _ssh_cmd(
        f'PGPASSWORD={VM_DB_PASS} psql -h 127.0.0.1 -U {VM_DB_USER} -d {VM_DB} -t -A -c "{sql}"'
    )
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"SSH psql failed: {result.stderr}")
    return result.stdout.strip()


def _vm_copy_to_stdout(copy_sql: str, timeout: int = 300) -> str:
    """Run COPY ... TO STDOUT on VM via SSH. Returns CSV data (no header)."""
    cmd = _ssh_cmd(
        f"PGPASSWORD={VM_DB_PASS} psql -h 127.0.0.1 -U {VM_DB_USER} -d {VM_DB} "
        f'-c "COPY ({copy_sql}) TO STDOUT WITH CSV"'
    )
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        if not result.stdout.strip():
            return ""
        raise RuntimeError(f"SSH COPY failed: {result.stderr}")
    return result.stdout.strip()


# ── Watermark helpers ─────────────────────────────────────────────────────────


def _ensure_watermarks_table(engine) -> None:
    """Create sync_results_watermarks if it doesn't exist."""
    with engine.begin() as conn:
        conn.execute(text(_CREATE_WATERMARKS_DDL))


def _get_local_watermark(engine, table_name: str) -> str | None:
    """Read last_synced from sync_results_watermarks. Returns ISO string or None."""
    try:
        sql = text(
            f"SELECT last_synced::text FROM {_WATERMARKS_TABLE} WHERE table_name = :t"
        )
        with engine.connect() as conn:
            row = conn.execute(sql, {"t": table_name}).fetchone()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def _set_local_watermark(engine, table_name: str, ts: str, rows: int) -> None:
    """Upsert watermark after successful sync."""
    sql = text(f"""
        INSERT INTO {_WATERMARKS_TABLE} (table_name, last_synced, rows_last, synced_at)
        VALUES (:t, :ts::timestamptz, :rows, NOW())
        ON CONFLICT (table_name) DO UPDATE SET
            last_synced = EXCLUDED.last_synced,
            rows_last   = EXCLUDED.rows_last,
            synced_at   = EXCLUDED.synced_at
    """)
    with engine.begin() as conn:
        conn.execute(sql, {"t": table_name, "ts": ts, "rows": rows})


def _get_vm_max_ts(table_name: str, wm_col: str, timeout: int = 30) -> str | None:
    """Query MAX(wm_col) from VM table. Returns ISO string or None."""
    try:
        raw = _vm_psql(f"SELECT MAX({wm_col})::text FROM {table_name}", timeout=timeout)
        return raw if raw else None
    except RuntimeError as e:
        err = str(e)
        if "does not exist" in err or "relation" in err:
            print(
                f"    [WARN] VM table {table_name} does not exist — run Phase 113 setup first",
                file=sys.stderr,
            )
            return None
        raise


# ── Upsert helper ─────────────────────────────────────────────────────────────


def _upsert_from_csv(
    engine,
    csv_data: str,
    local_table: str,
    pk_cols: list[str],
    update_cols: list[str] | None = None,
) -> int:
    """Load CSV (no header) into local table via temp table + upsert.

    Returns row count inserted/updated.
    update_cols=None → ON CONFLICT DO NOTHING
    update_cols=[...] → ON CONFLICT DO UPDATE SET ...
    """
    if not csv_data:
        return 0

    n_rows = len([line for line in csv_data.split("\n") if line.strip()])

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        f.write(csv_data)
        tmp_path = f.name

    try:
        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            cur.execute(f"""
                CREATE TEMP TABLE _results_staging (LIKE {local_table} INCLUDING DEFAULTS)
                ON COMMIT DROP
            """)
            with open(tmp_path, "r", encoding="utf-8") as f:
                cur.copy_expert("COPY _results_staging FROM STDIN WITH CSV", f)

            conflict_clause = f"ON CONFLICT ({', '.join(pk_cols)})"
            if update_cols:
                set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
                action = f"DO UPDATE SET {set_clause}"
            else:
                action = "DO NOTHING"

            cur.execute(f"""
                INSERT INTO {local_table}
                SELECT * FROM _results_staging
                {conflict_clause} {action}
            """)
            raw_conn.commit()
        except Exception:
            raw_conn.rollback()
            raise
        finally:
            raw_conn.close()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return n_rows


# ── Per-table sync functions ──────────────────────────────────────────────────


def _build_select_sql(spec: TableSpec, watermark: str | None) -> str:
    """Build VM SELECT query, filtered by watermark if provided."""
    if watermark and spec.wm_col:
        return (
            f"SELECT * FROM {spec.name} "
            f"WHERE {spec.wm_col} > '{watermark}' "
            f"ORDER BY {spec.wm_col}"
        )
    return f"SELECT * FROM {spec.name} ORDER BY {spec.wm_col or '1'}"


def sync_table_incremental(engine, spec: TableSpec, full: bool = False) -> int:
    """Incremental sync: pull VM rows newer than local watermark.

    If full=True, ignores watermark and pulls all VM rows.
    Returns rows synced.
    """
    assert spec.wm_col is not None, (
        f"sync_table_incremental called on {spec.name} (no wm_col)"
    )

    if full:
        watermark = None
        print(f"  Syncing {spec.name} (full)...")
    else:
        watermark = _get_local_watermark(engine, spec.name)
        if watermark:
            print(f"  Syncing {spec.name} (since {watermark})...")
        else:
            print(f"  Syncing {spec.name} (no watermark — full pull)...")

    select_sql = _build_select_sql(spec, watermark)

    try:
        csv_data = _vm_copy_to_stdout(select_sql, timeout=spec.timeout)
    except RuntimeError as e:
        err = str(e)
        if "does not exist" in err or "relation" in err:
            print(
                f"    [WARN] VM table {spec.name} does not exist — skipping",
                file=sys.stderr,
            )
            return 0
        raise

    n = _upsert_from_csv(engine, csv_data, spec.name, spec.pk_cols, spec.update_cols)
    print(f"    {n:,} rows synced")

    # Advance watermark to VM MAX after successful sync
    vm_max = _get_vm_max_ts(spec.name, spec.wm_col)
    if vm_max:
        _set_local_watermark(engine, spec.name, vm_max, n)

    return n


def sync_table_full_replace(engine, spec: TableSpec) -> int:
    """Full replace: TRUNCATE local table then COPY all VM rows.

    Used for small config tables (dim_risk_state).
    Returns rows synced.
    """
    print(f"  Syncing {spec.name} (full replace)...")

    select_sql = f"SELECT * FROM {spec.name}"
    try:
        csv_data = _vm_copy_to_stdout(select_sql, timeout=spec.timeout)
    except RuntimeError as e:
        err = str(e)
        if "does not exist" in err or "relation" in err:
            print(
                f"    [WARN] VM table {spec.name} does not exist — skipping",
                file=sys.stderr,
            )
            return 0
        raise

    if not csv_data:
        print("    0 rows (VM table is empty)")
        return 0

    n_rows = len([line for line in csv_data.split("\n") if line.strip()])

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        f.write(csv_data)
        tmp_path = f.name

    try:
        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            cur.execute(f"TRUNCATE TABLE {spec.name}")
            with open(tmp_path, "r", encoding="utf-8") as f:
                cur.copy_expert(f"COPY {spec.name} FROM STDIN WITH CSV", f)
            raw_conn.commit()
        except Exception:
            raw_conn.rollback()
            raise
        finally:
            raw_conn.close()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    print(f"    {n_rows:,} rows replaced")
    return n_rows


# ── Dry-run report ────────────────────────────────────────────────────────────


def get_dry_run_report(engine) -> None:
    """Print VM and local row counts for all result tables (no data moved)."""
    print("\n[DRY-RUN] VM vs local row counts:\n")

    vm_count_sql_parts = []
    for spec in ALL_TABLES:
        vm_count_sql_parts.append(
            f"SELECT '{spec.name}' AS tbl, COUNT(*) AS cnt FROM {spec.name}"
        )
    vm_stats_sql = " UNION ALL ".join(vm_count_sql_parts)

    try:
        raw = _vm_psql(vm_stats_sql, timeout=60)
        vm_counts: dict[str, int] = {}
        for line in raw.split("\n"):
            if "|" in line:
                parts = line.split("|")
                vm_counts[parts[0].strip()] = int(parts[1].strip())
    except Exception as e:
        print(f"  [WARN] Could not query VM counts: {e}", file=sys.stderr)
        vm_counts = {}

    print(
        f"  {'Table':<25}  {'VM Rows':>10}  {'Local Rows':>10}  {'Mode':<15}  Watermark"
    )
    print(f"  {'-' * 25}  {'-' * 10}  {'-' * 10}  {'-' * 15}  {'-' * 30}")

    for spec in ALL_TABLES:
        vm_n = vm_counts.get(spec.name, "?")
        wm = _get_local_watermark(engine, spec.name) or "none"
        mode = "full-replace" if spec.full_replace else "incremental"

        try:
            with engine.connect() as conn:
                local_n = conn.execute(
                    text(f"SELECT COUNT(*) FROM {spec.name}")
                ).scalar()
        except Exception:
            local_n = "missing"

        print(
            f"  {spec.name:<25}  {str(vm_n):>10}  {str(local_n):>10}  {mode:<15}  {wm}"
        )

    print("\n[DRY-RUN] No data synced.")


# ── Verify integrity ──────────────────────────────────────────────────────────


def verify_integrity(engine) -> bool:
    """Compare local vs VM row counts. Returns True if local >= VM for all tables."""
    print("\nVerifying integrity...")
    ok = True

    for spec in ALL_TABLES:
        if spec.wm_col is None:
            # Full-replace tables: exact equality expected
            vm_count_str = _vm_psql(f"SELECT COUNT(*) FROM {spec.name}", timeout=30)
            vm_count = int(vm_count_str) if vm_count_str else 0
            with engine.connect() as conn:
                local_count = (
                    conn.execute(text(f"SELECT COUNT(*) FROM {spec.name}")).scalar()
                    or 0
                )
            match = local_count == vm_count
            status = "OK" if match else "MISMATCH"
            diff = local_count - vm_count
            print(
                f"  {spec.name}: VM={vm_count:,}, local={local_count:,} "
                f"(diff={diff:+,}) [{status}]"
            )
            if not match:
                ok = False
        else:
            # Incremental tables: local may lag VM (normal), but should not be ahead
            vm_count_str = _vm_psql(f"SELECT COUNT(*) FROM {spec.name}", timeout=30)
            vm_count = int(vm_count_str) if vm_count_str else 0
            with engine.connect() as conn:
                local_count = (
                    conn.execute(text(f"SELECT COUNT(*) FROM {spec.name}")).scalar()
                    or 0
                )
            status = "OK" if local_count <= vm_count else "AHEAD"
            diff = local_count - vm_count
            print(
                f"  {spec.name}: VM={vm_count:,}, local={local_count:,} "
                f"(diff={diff:+,}) [{status}]"
            )
            if local_count > vm_count:
                ok = False

    return ok


# ── Main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Pull execution state from Oracle Singapore VM to local DB. "
            "Mirrors SSH+COPY pattern from sync_hl_from_vm.py (VM→local direction). "
            "Suggested cron: '0 */4 * * *' (every 4 hours)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Incremental pull of all 9 execution tables
  python -m ta_lab2.scripts.etl.sync_results_from_vm

  # Full resync (ignore watermarks)
  python -m ta_lab2.scripts.etl.sync_results_from_vm --full

  # Dry run (no data moved — shows VM vs local counts)
  python -m ta_lab2.scripts.etl.sync_results_from_vm --dry-run

  # Single table
  python -m ta_lab2.scripts.etl.sync_results_from_vm --table orders

  # Single table, full resync
  python -m ta_lab2.scripts.etl.sync_results_from_vm --table fills --full
""",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full resync: ignore watermarks, pull all VM rows",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report VM vs local counts only; no data moved",
    )
    parser.add_argument(
        "--table",
        choices=list(_TABLE_CHOICES.keys()),
        default=None,
        help="Sync only this table (default: all 9 tables)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip post-sync integrity check",
    )
    args = parser.parse_args(argv)

    engine = get_engine()
    mode = "FULL" if args.full else "incremental"
    now = datetime.now(tz=timezone.utc).isoformat()
    print(f"[results-sync] {now} — {mode} pull")

    # Ensure watermark table exists
    _ensure_watermarks_table(engine)

    # ── Dry run ──────────────────────────────────────────────────────────────
    if args.dry_run:
        get_dry_run_report(engine)
        return 0

    # ── Determine which tables to sync ───────────────────────────────────────
    if args.table:
        specs: list[TableSpec] = [_TABLE_CHOICES[args.table]]
    else:
        specs = list(ALL_TABLES)

    # ── Execute sync with per-table error isolation ───────────────────────────
    total_rows = 0
    tables_ok: list[str] = []
    tables_failed: list[str] = []
    start_all = time.perf_counter()

    for spec in specs:
        t_start = time.perf_counter()
        try:
            if spec.full_replace:
                n = sync_table_full_replace(engine, spec)
            else:
                n = sync_table_incremental(engine, spec, full=args.full)
            elapsed = time.perf_counter() - t_start
            if n > 0:
                print(f"    ({elapsed:.1f}s)")
            total_rows += n
            tables_ok.append(spec.name)
        except Exception as e:
            elapsed = time.perf_counter() - t_start
            print(
                f"    [ERROR] {spec.name} failed after {elapsed:.1f}s: {e}",
                file=sys.stderr,
            )
            tables_failed.append(spec.name)
            # Continue to next table — partial sync is better than none

    # ── Integrity verification ────────────────────────────────────────────────
    if not args.skip_verify and not args.table and tables_ok:
        try:
            verify_integrity(engine)
        except Exception as e:
            print(f"  [WARN] Integrity check failed: {e}", file=sys.stderr)

    # ── Summary ──────────────────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - start_all
    print(
        f"\n[results-sync] Done. {total_rows:,} rows pulled in {total_elapsed:.1f}s "
        f"({len(tables_ok)} tables ok, {len(tables_failed)} failed)"
    )
    if tables_failed:
        print(f"  Failed tables: {', '.join(tables_failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
