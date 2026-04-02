"""
sync_dashboard_to_vm.py

Push dashboard-relevant tables from local PostgreSQL to the Oracle Singapore VM.
This is the INVERTED pattern of sync_cmc_from_vm.py: local COPY TO STDOUT -> SSH
pipe -> VM COPY FROM STDIN.

The VM-hosted dashboard needs local research and operations data to render all
pages. This script is the data bridge.

Usage:
    python -m ta_lab2.scripts.etl.sync_dashboard_to_vm              # incremental
    python -m ta_lab2.scripts.etl.sync_dashboard_to_vm --full       # full resync
    python -m ta_lab2.scripts.etl.sync_dashboard_to_vm --dry-run    # report only
    python -m ta_lab2.scripts.etl.sync_dashboard_to_vm --table regimes  # single table
"""

from __future__ import annotations

import argparse
import io
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from sqlalchemy import text

from ta_lab2.io import get_engine

# ── VM connection details (Oracle Singapore VM) ───────────────────────────────
VM_HOST = "161.118.209.59"
VM_USER = "ubuntu"
VM_SSH_KEY = str(
    Path.home() / "Downloads" / "oracle_sg_keys" / "ssh-key-2026-03-10.key"
)
VM_DB = "hyperliquid"
VM_DB_USER = "hluser"
VM_DB_PASS = "hlpass"

SYNC_LOG_TABLE = "hyperliquid.sync_log"

# ── Table registry ────────────────────────────────────────────────────────────
#
# Each entry is a dict with:
#   strategy: "full_replace" | "incremental"
#   watermark_col: column used for incremental watermark (incremental only)
#   conflict_cols: PK columns for ON CONFLICT (incremental only)
#   batch_by_id: True for very large tables — loop over distinct id values
#
# Columns are discovered dynamically via information_schema.
# Only strategy metadata is hardcoded here.

FULL_REPLACE_TABLES: list[str] = [
    "dim_assets",
    "dim_timeframe",
    "dim_signals",
    "dim_ama_params",
    "dim_venues",
    "dim_sessions",
    "dim_executor_config",
    "dim_risk_limits",
    "dim_risk_state",
    "cmc_da_info",
    "cmc_da_ids",
    "asset_data_coverage",
]

# (table_name, watermark_col, conflict_cols, batch_by_id)
INCREMENTAL_TABLES: list[tuple[str, str, list[str], bool]] = [
    # Research tables
    ("strategy_bakeoff_results", "computed_at", ["id"], False),
    ("ic_results", "computed_at", ["id"], False),
    ("regimes", "updated_at", ["id", "venue_id", "ts", "tf"], False),
    ("regime_flips", "updated_at", ["id", "venue_id", "ts", "tf"], False),
    ("regime_stats", "updated_at", ["id", "venue_id", "tf"], False),
    ("regime_comovement", "updated_at", ["id1", "id2", "venue_id", "tf", "ts"], False),
    ("macro_regimes", "ts", ["ts"], False),
    ("portfolio_allocations", "created_at", ["id"], False),
    ("asset_stats", "updated_at", ["id", "venue_id"], False),
    # Large table — batch by id
    ("features", "updated_at", ["id", "venue_id", "ts", "tf"], True),
    # Signal tables
    ("signals_ema_crossover", "created_at", ["id", "venue_id", "ts", "tf"], False),
    ("signals_rsi_mean_revert", "created_at", ["id", "venue_id", "ts", "tf"], False),
    ("signals_atr_breakout", "created_at", ["id", "venue_id", "ts", "tf"], False),
    ("signals_macd_crossover", "created_at", ["id", "venue_id", "ts", "tf"], False),
    ("signals_ama_momentum", "created_at", ["id", "venue_id", "ts", "tf"], False),
    ("signals_ama_mean_reversion", "created_at", ["id", "venue_id", "ts", "tf"], False),
    (
        "signals_ama_regime_conditional",
        "created_at",
        ["id", "venue_id", "ts", "tf"],
        False,
    ),
    # Operations tables
    ("positions", "created_at", ["id"], False),
    ("fills", "created_at", ["id"], False),
    ("orders", "updated_at", ["id"], False),
    ("executor_run_log", "started_at", ["id"], False),
    ("pipeline_run_log", "started_at", ["run_id"], False),
    ("pipeline_stage_log", "started_at", ["run_id", "stage"], False),
    ("drift_metrics", "created_at", ["id", "venue_id", "ts"], False),
    ("risk_events", "event_ts", ["id"], False),
]


# ── SSH helpers (identical to sync_cmc_from_vm.py) ───────────────────────────


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
        f"PGPASSWORD={VM_DB_PASS} psql -h 127.0.0.1 -U {VM_DB_USER} "
        f'-d {VM_DB} -t -A -c "{sql}"'
    )
    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout
    )
    if result.returncode != 0:
        raise RuntimeError(f"SSH psql failed: {result.stderr}")
    return result.stdout.strip()


def _vm_psql_stdin(sql: str, csv_data: str, timeout: int = 600) -> None:
    """Run a psql COPY FROM STDIN on the VM, piping csv_data via stdin."""
    cmd = _ssh_cmd(
        f"PGPASSWORD={VM_DB_PASS} psql -h 127.0.0.1 -U {VM_DB_USER} "
        f'-d {VM_DB} -c "{sql}"'
    )
    result = subprocess.run(
        cmd,
        input=csv_data,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"SSH COPY FROM STDIN failed: {result.stderr[:500]}")


# ── Column discovery ─────────────────────────────────────────────────────────


def _get_local_columns(engine, table_name: str) -> list[str] | None:
    """
    Return ordered column list from information_schema.
    Returns None if table does not exist locally.
    """
    sql = text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :tname
        ORDER BY ordinal_position
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {"tname": table_name}).fetchall()
    if not rows:
        return None
    return [r[0] for r in rows]


def _ensure_vm_table(table_name: str, columns: list[str], engine) -> bool:
    """
    Check that the VM table exists and has the expected columns.
    Returns True if ready, False if table is missing on VM (skip gracefully).
    """
    try:
        out = _vm_psql(
            f"SELECT count(*) FROM information_schema.tables "
            f"WHERE table_schema='public' AND table_name='{table_name}'"
        )
        return int(out.strip()) > 0
    except Exception as exc:
        print(f"    [warn] VM check failed for {table_name}: {exc}")
        return False


# ── Watermark helpers ─────────────────────────────────────────────────────────


def _get_vm_watermark(table_name: str, watermark_col: str) -> str | None:
    """
    Get MAX(watermark_col) from the VM table.
    Returns None if table is empty or doesn't exist.
    """
    try:
        out = _vm_psql(f"SELECT MAX({watermark_col})::text FROM {table_name}")
        if out and out != "":
            return out
        return None
    except Exception:
        return None


def _get_local_count(engine, table_name: str, where: str = "") -> int:
    """Count rows in local table with optional WHERE clause."""
    clause = f" WHERE {where}" if where else ""
    sql = text(f"SELECT count(*) FROM {table_name}{clause}")
    try:
        with engine.connect() as conn:
            return conn.execute(sql).scalar() or 0
    except Exception:
        return -1


# ── Local COPY TO CSV ─────────────────────────────────────────────────────────


def _local_copy_to_csv(
    engine, query: str, columns: list[str], timeout: int = 600
) -> str:
    """
    Execute COPY (query) TO STDOUT CSV on local DB and return raw CSV string.
    Uses psycopg2 copy_expert for efficiency.
    """
    copy_sql = f"COPY ({query}) TO STDOUT WITH CSV"

    raw_conn = engine.raw_connection()
    try:
        cur = raw_conn.cursor()
        buf = io.BytesIO()
        cur.copy_expert(copy_sql, buf)
        return buf.getvalue().decode("utf-8")
    finally:
        raw_conn.close()


# ── Sync strategies ───────────────────────────────────────────────────────────


def _sync_full_replace(
    engine,
    table_name: str,
    columns: list[str],
    dry_run: bool = False,
) -> int:
    """
    Full replace: TRUNCATE VM table then COPY all local rows.
    Used for small dim/config tables.
    """
    col_sql = ", ".join(f'"{c}"' for c in columns)
    select_sql = f"SELECT {col_sql} FROM {table_name}"

    local_n = _get_local_count(engine, table_name)
    print(f"    strategy=full_replace  local={local_n:,} rows")

    if dry_run:
        return local_n

    if local_n == 0:
        print(f"    [skip] {table_name} is empty locally — nothing to push")
        return 0

    csv_data = _local_copy_to_csv(engine, select_sql, columns)
    if not csv_data.strip():
        print(f"    [skip] no CSV data produced for {table_name}")
        return 0

    n_rows = len([line for line in csv_data.split("\n") if line.strip()])

    # TRUNCATE + COPY on VM (single transaction via pipeline)
    _vm_psql(f"TRUNCATE TABLE {table_name} CASCADE")
    copy_cmd = f"COPY {table_name} ({col_sql}) FROM STDIN WITH CSV"
    _vm_psql_stdin(copy_cmd, csv_data)

    return n_rows


def _sync_incremental(
    engine,
    table_name: str,
    columns: list[str],
    watermark_col: str,
    conflict_cols: list[str],
    full: bool = False,
    dry_run: bool = False,
    batch_by_id: bool = False,
) -> int:
    """
    Incremental watermark sync: push rows newer than VM watermark.
    Uses staging table + ON CONFLICT DO UPDATE on VM.
    """
    col_sql = ", ".join(f'"{c}"' for c in columns)

    if full:
        vm_wm = None
    else:
        vm_wm = _get_vm_watermark(table_name, watermark_col)

    where = f"{watermark_col} > '{vm_wm}'" if vm_wm else ""
    local_n = _get_local_count(engine, table_name, where)
    print(
        f"    strategy=incremental  watermark={watermark_col}>{vm_wm or 'none'}"
        f"  pending={local_n:,} rows"
    )

    if dry_run:
        return local_n

    if local_n == 0:
        return 0

    if batch_by_id:
        return _sync_incremental_batched(
            engine,
            table_name,
            columns,
            watermark_col,
            conflict_cols,
            vm_wm,
            full,
        )

    # Build SELECT
    where_clause = f" WHERE {where}" if where else ""
    select_sql = f"SELECT {col_sql} FROM {table_name}{where_clause}"

    csv_data = _local_copy_to_csv(engine, select_sql, columns)
    if not csv_data.strip():
        return 0

    n_rows = len([line for line in csv_data.split("\n") if line.strip()])
    _vm_upsert_csv(table_name, columns, conflict_cols, csv_data)
    return n_rows


def _sync_incremental_batched(
    engine,
    table_name: str,
    columns: list[str],
    watermark_col: str,
    conflict_cols: list[str],
    vm_wm: str | None,
    full: bool,
) -> int:
    """
    Batch incremental sync for large tables (e.g. features).
    Iterates distinct id values to avoid huge single transactions.
    """
    col_sql = ", ".join(f'"{c}"' for c in columns)
    where_base = f"WHERE {watermark_col} > '{vm_wm}'" if vm_wm and not full else ""

    # Get distinct ids that have new rows
    id_sql = text(f"SELECT DISTINCT id FROM {table_name} {where_base} ORDER BY id")
    with engine.connect() as conn:
        ids = [r[0] for r in conn.execute(id_sql).fetchall()]

    if not ids:
        return 0

    print(f"    batching over {len(ids)} ids...")
    total = 0
    for asset_id in ids:
        id_where = f"id = {asset_id}"
        if where_base:
            id_where = f"{where_base[6:]} AND id = {asset_id}"  # strip "WHERE "
        select_sql = f"SELECT {col_sql} FROM {table_name} WHERE {id_where}"
        csv_data = _local_copy_to_csv(engine, select_sql, columns)
        if not csv_data.strip():
            continue
        n = len([line for line in csv_data.split("\n") if line.strip()])
        _vm_upsert_csv(table_name, columns, conflict_cols, csv_data)
        total += n

    return total


def _vm_upsert_csv(
    table_name: str,
    columns: list[str],
    conflict_cols: list[str],
    csv_data: str,
) -> None:
    """
    Push CSV data into VM table via staging + ON CONFLICT DO UPDATE.
    """
    col_sql = ", ".join(f'"{c}"' for c in columns)
    staging = f"_dash_staging_{table_name}"
    conflict_clause = ", ".join(f'"{c}"' for c in conflict_cols)
    update_cols = [c for c in columns if c not in conflict_cols]
    set_clause = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)

    # Use a regular table (not TEMP) so it persists across psql calls
    setup_sql = (
        f"DROP TABLE IF EXISTS {staging}; "
        f"CREATE TABLE {staging} (LIKE {table_name} INCLUDING DEFAULTS);"
    )
    copy_cmd = f"COPY {staging} ({col_sql}) FROM STDIN WITH CSV"
    upsert_sql = (
        f"INSERT INTO {table_name} ({col_sql}) "
        f"SELECT {col_sql} FROM {staging} "
        f"ON CONFLICT ({conflict_clause}) DO UPDATE SET {set_clause}; "
        f"DROP TABLE IF EXISTS {staging};"
    )

    _vm_psql(setup_sql, timeout=30)
    _vm_psql_stdin(copy_cmd, csv_data)
    _vm_psql(upsert_sql, timeout=300)


# ── Sync log ──────────────────────────────────────────────────────────────────


def _log_sync_vm(
    table_name: str, rows_synced: int, status: str, note: str = ""
) -> None:
    """Write a sync_log entry to the VM (reuse hyperliquid.sync_log)."""
    try:
        safe_note = note[:500].replace("'", "''")
        _vm_psql(
            f"INSERT INTO {SYNC_LOG_TABLE} (table_name, rows_synced, status, note) "
            f"VALUES ('{table_name}', {rows_synced}, '{status}', '{safe_note}')",
            timeout=30,
        )
    except Exception:
        pass  # sync_log table may not exist yet on VM


# ── Dry-run report ────────────────────────────────────────────────────────────


def _dry_run_report(engine, table_filter: str | None = None) -> None:
    """Print row counts and sync strategies for all configured tables."""
    print("\n[dry-run] Dashboard sync report")
    print(f"  {'Table':<45} {'Strategy':<15} {'Local rows':>12}")
    print("  " + "-" * 75)

    for table_name in FULL_REPLACE_TABLES:
        if table_filter and table_filter != table_name:
            continue
        n = _get_local_count(engine, table_name)
        flag = "(missing)" if n < 0 else ""
        print(f"  {table_name:<45} {'full_replace':<15} {max(n, 0):>12,}  {flag}")

    for table_name, watermark_col, conflict_cols, batch_by_id in INCREMENTAL_TABLES:
        if table_filter and table_filter != table_name:
            continue
        n = _get_local_count(engine, table_name)
        batch_flag = " [batch_by_id]" if batch_by_id else ""
        flag = "(missing)" if n < 0 else ""
        print(
            f"  {table_name:<45} {'incremental':<15} {max(n, 0):>12,}  "
            f"{watermark_col}{batch_flag}  {flag}"
        )

    print()


# ── Main ──────────────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Push dashboard tables from local PostgreSQL to Singapore VM"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full resync — ignore watermarks, re-push everything",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report row counts and sync strategy without writing",
    )
    parser.add_argument(
        "--table",
        metavar="TABLE",
        help="Sync a single table by name",
    )
    args = parser.parse_args()

    engine = get_engine()
    t0 = time.time()
    mode = "FULL" if args.full else "incremental"
    ts_str = datetime.now().isoformat(timespec="seconds")
    print(f"[dashboard-sync] {ts_str} — {mode} push to VM {VM_HOST}")

    if args.dry_run:
        _dry_run_report(engine, table_filter=args.table)
        return

    total_rows = 0
    tables_ok: list[str] = []
    tables_skipped: list[str] = []
    tables_failed: list[str] = []

    # ── Full replace tables ───────────────────────────────────────────
    for table_name in FULL_REPLACE_TABLES:
        if args.table and args.table != table_name:
            continue
        print(f"\n  [{table_name}]")
        columns = _get_local_columns(engine, table_name)
        if columns is None:
            print("    [skip] table not found locally")
            tables_skipped.append(table_name)
            continue
        if not _ensure_vm_table(table_name, columns, engine):
            print("    [skip] table not found on VM — create it first")
            tables_skipped.append(table_name)
            continue
        try:
            t1 = time.time()
            n = _sync_full_replace(engine, table_name, columns, dry_run=False)
            elapsed = time.time() - t1
            print(f"    pushed {n:,} rows in {elapsed:.1f}s")
            total_rows += n
            tables_ok.append(table_name)
            _log_sync_vm(table_name, n, "ok", f"{mode} full_replace")
        except Exception as exc:
            print(f"    [ERROR] {exc}", file=sys.stderr)
            tables_failed.append(table_name)
            _log_sync_vm(table_name, 0, "error", str(exc)[:500])

    # ── Incremental tables ───────────────────────────────────────────
    for table_name, watermark_col, conflict_cols, batch_by_id in INCREMENTAL_TABLES:
        if args.table and args.table != table_name:
            continue
        print(f"\n  [{table_name}]")
        columns = _get_local_columns(engine, table_name)
        if columns is None:
            print("    [skip] table not found locally")
            tables_skipped.append(table_name)
            continue
        if not _ensure_vm_table(table_name, columns, engine):
            print("    [skip] table not found on VM — create it first")
            tables_skipped.append(table_name)
            continue
        # Verify watermark column exists
        if watermark_col not in columns:
            print(f"    [skip] watermark column '{watermark_col}' not in table")
            tables_skipped.append(table_name)
            continue
        try:
            t1 = time.time()
            n = _sync_incremental(
                engine=engine,
                table_name=table_name,
                columns=columns,
                watermark_col=watermark_col,
                conflict_cols=conflict_cols,
                full=args.full,
                dry_run=False,
                batch_by_id=batch_by_id,
            )
            elapsed = time.time() - t1
            print(f"    pushed {n:,} rows in {elapsed:.1f}s")
            total_rows += n
            tables_ok.append(table_name)
            _log_sync_vm(table_name, n, "ok", f"{mode} incremental")
        except Exception as exc:
            print(f"    [ERROR] {exc}", file=sys.stderr)
            tables_failed.append(table_name)
            _log_sync_vm(table_name, 0, "error", str(exc)[:500])

    # ── Summary ──────────────────────────────────────────────────────
    elapsed_total = time.time() - t0
    print(f"\n[dashboard-sync] Done in {elapsed_total:.1f}s")
    print(f"  Tables synced:  {len(tables_ok)}")
    print(f"  Tables skipped: {len(tables_skipped)}")
    print(f"  Tables failed:  {len(tables_failed)}")
    print(f"  Total rows:     {total_rows:,}")
    if tables_failed:
        print(f"  FAILED: {tables_failed}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
