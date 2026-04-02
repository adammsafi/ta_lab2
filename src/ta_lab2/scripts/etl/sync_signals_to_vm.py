"""
sync_signals_to_vm.py

Push local signal and configuration tables to the Oracle Singapore VM via
SSH + psql COPY (inverted pattern from sync_hl_from_vm.py).

Signal tables use incremental sync (watermark-based). Config/dim tables use
full-replace (TRUNCATE + COPY all rows) since they are small and stateless.

Usage:
    python -m ta_lab2.scripts.etl.sync_signals_to_vm              # incremental
    python -m ta_lab2.scripts.etl.sync_signals_to_vm --full       # push all rows
    python -m ta_lab2.scripts.etl.sync_signals_to_vm --dry-run    # report only (no VM connection)
    python -m ta_lab2.scripts.etl.sync_signals_to_vm --table signals_ema_crossover
    python -m ta_lab2.scripts.etl.sync_signals_to_vm --verbose

NOTE: The VM tables do not exist until Phase 113 (VM Execution Deployment) creates them.
      This script handles missing VM tables gracefully and continues to next table.
"""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import text

from ta_lab2.io import get_engine

# ── VM connection details (same Oracle VM as sync_hl_from_vm.py) ───────────
VM_HOST = "161.118.209.59"
VM_USER = "ubuntu"
VM_SSH_KEY = str(
    Path.home() / "Downloads" / "oracle_sg_keys" / "ssh-key-2026-03-10.key"
)
VM_DB = "hyperliquid"
VM_DB_USER = "hluser"
VM_DB_PASS = "hlpass"

# ── Table registry ──────────────────────────────────────────────────────────


class TableSpec(NamedTuple):
    name: str
    ts_col: str | None  # None → full-replace (config table)
    full_replace: bool = False  # True → TRUNCATE on VM then COPY all rows


# Signal tables: incremental by ts watermark
# Must match SIGNAL_TABLE_MAP in ta_lab2.executor.signal_reader
_SIGNAL_TABLES: list[TableSpec] = [
    TableSpec("signals_ema_crossover", ts_col="ts"),
    TableSpec("signals_rsi_mean_revert", ts_col="ts"),
    TableSpec("signals_atr_breakout", ts_col="ts"),
    TableSpec("signals_macd_crossover", ts_col="ts"),
    TableSpec("signals_ama_momentum", ts_col="ts"),
    TableSpec("signals_ama_mean_reversion", ts_col="ts"),
    TableSpec("signals_ama_regime_conditional", ts_col="ts"),
]

# Config tables: small, stateless → full replace
_CONFIG_TABLES: list[TableSpec] = [
    TableSpec("dim_executor_config", ts_col=None, full_replace=True),
    TableSpec("dim_risk_limits", ts_col=None, full_replace=True),
    TableSpec("dim_risk_state", ts_col=None, full_replace=True),
]

ALL_TABLES: list[TableSpec] = _SIGNAL_TABLES + _CONFIG_TABLES


def _ssh_cmd(remote_cmd: str) -> list[str]:
    """Build SSH command list for subprocess (same pattern as sync_hl_from_vm.py)."""
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


def _get_vm_watermark(table: str, ts_col: str, timeout: int = 30) -> datetime | None:
    """Query MAX(ts_col) from VM table.

    Returns None if the table is empty, does not exist, or VM is unreachable.
    A missing table is logged as a non-fatal warning (table will be created in Phase 113).
    """
    try:
        raw = _vm_psql(f"SELECT MAX({ts_col})::text FROM {table}", timeout=timeout)
        if not raw:
            return None
        return datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
    except RuntimeError as e:
        err = str(e)
        if "does not exist" in err or "relation" in err:
            print(
                f"    [WARN] VM table {table} does not exist — run Phase 113 first",
                file=sys.stderr,
            )
            return None
        raise


def _get_local_watermark(engine, table: str, ts_col: str) -> datetime | None:
    """Query MAX(ts_col) from local table. Returns None if empty or missing."""
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT MAX({ts_col})::text FROM {table}")
            ).fetchone()
        if row and row[0]:
            return datetime.fromisoformat(row[0]).replace(tzinfo=timezone.utc)
        return None
    except Exception:
        return None


def _local_export_csv(
    engine,
    table: str,
    since_ts: datetime | None = None,
    ts_col: str = "ts",
) -> str:
    """Export local rows to CSV string via COPY TO STDOUT.

    If since_ts is provided only rows with ts_col > since_ts are exported.
    """
    if since_ts is not None:
        select_sql = f"SELECT * FROM {table} WHERE {ts_col} > '{since_ts.isoformat()}'"
    else:
        select_sql = f"SELECT * FROM {table}"

    try:
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            buf = io.StringIO()
            cur.copy_expert(f"COPY ({select_sql}) TO STDOUT WITH CSV HEADER", buf)
            return buf.getvalue()
        finally:
            raw.close()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Local CSV export from {table} failed: {e}") from e


def _push_csv_to_vm(csv_data: str, vm_table: str, timeout: int = 300) -> int:
    """Push CSV data (with header) to VM table via SSH psql COPY FROM STDIN.

    Returns row count pushed.
    Raises RuntimeError if psql exits non-zero.
    """
    if not csv_data.strip():
        return 0

    # Count data rows (total lines minus header minus trailing newline)
    lines = [line for line in csv_data.split("\n") if line.strip()]
    row_count_estimate = max(0, len(lines) - 1)  # subtract header

    cmd = _ssh_cmd(
        f"PGPASSWORD={VM_DB_PASS} psql -h 127.0.0.1 -U {VM_DB_USER} -d {VM_DB} "
        f'-c "COPY {vm_table} FROM STDIN WITH CSV HEADER"'
    )
    result = subprocess.run(
        cmd,
        input=csv_data,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        err = result.stderr or result.stdout
        if "does not exist" in err or "relation" in err:
            print(
                f"    [WARN] VM table {vm_table} does not exist — run Phase 113 first",
                file=sys.stderr,
            )
            return 0
        raise RuntimeError(f"SSH COPY push to {vm_table} failed: {err}")

    # Parse actual row count from psql output ("COPY N")
    for line in result.stdout.splitlines():
        if line.startswith("COPY "):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                pass

    return row_count_estimate


def _truncate_vm_table(vm_table: str, timeout: int = 30) -> None:
    """TRUNCATE a VM table to prepare for full-replace sync."""
    try:
        _vm_psql(f"TRUNCATE TABLE {vm_table}", timeout=timeout)
    except RuntimeError as e:
        err = str(e)
        if "does not exist" in err or "relation" in err:
            print(
                f"    [WARN] VM table {vm_table} does not exist — run Phase 113 first",
                file=sys.stderr,
            )
            return
        raise


def sync_table_incremental(
    engine,
    spec: TableSpec,
    full: bool = False,
    verbose: bool = False,
) -> int:
    """Incremental sync of one signal table (local → VM).

    Queries VM watermark, exports new local rows, pushes via COPY.
    Returns rows pushed.
    """
    assert spec.ts_col is not None, "incremental sync requires ts_col"

    if full:
        vm_wm = None
    else:
        try:
            vm_wm = _get_vm_watermark(spec.name, spec.ts_col)
        except Exception as e:
            print(
                f"    [WARN] Could not read VM watermark for {spec.name}: {e}",
                file=sys.stderr,
            )
            vm_wm = None

    if verbose:
        if vm_wm:
            print(f"    VM watermark: {vm_wm.isoformat()}")
        else:
            print("    VM watermark: None (full push)")

    csv_data = _local_export_csv(engine, spec.name, since_ts=vm_wm, ts_col=spec.ts_col)
    rows = _push_csv_to_vm(csv_data, spec.name)
    return rows


def sync_table_full_replace(
    engine,
    spec: TableSpec,
    verbose: bool = False,
) -> int:
    """Full-replace sync for config/dim tables: TRUNCATE on VM then COPY all rows."""
    _truncate_vm_table(spec.name)
    csv_data = _local_export_csv(engine, spec.name, since_ts=None)
    rows = _push_csv_to_vm(csv_data, spec.name)
    return rows


def get_dry_run_report(engine) -> list[dict]:
    """Return a list of dicts with local table info without connecting to VM.

    Used by --dry-run mode (no VM connectivity required).
    """
    report = []
    for spec in ALL_TABLES:
        try:
            with engine.connect() as conn:
                count = conn.execute(text(f"SELECT COUNT(*) FROM {spec.name}")).scalar()
            wm_str = None
            if spec.ts_col:
                local_wm = _get_local_watermark(engine, spec.name, spec.ts_col)
                wm_str = local_wm.isoformat() if local_wm else "empty"
            report.append(
                {
                    "table": spec.name,
                    "local_rows": count,
                    "watermark": wm_str,
                    "sync_mode": "full-replace" if spec.full_replace else "incremental",
                    "status": "ok",
                }
            )
        except Exception as e:
            report.append(
                {
                    "table": spec.name,
                    "local_rows": 0,
                    "watermark": None,
                    "sync_mode": "full-replace" if spec.full_replace else "incremental",
                    "status": f"missing: {e}",
                }
            )
    return report


def sync_signals(
    *,
    dry_run: bool = False,
    full: bool = False,
    table: str | None = None,
    sync_config: bool = True,
) -> None:
    """Programmatic entry-point for use by run_daily_refresh.py and other callers.

    Pushes signal tables (and optionally config tables) from local to the VM.
    Errors per-table are isolated; a summary is printed but exceptions are NOT raised
    unless all tables fail.

    Parameters
    ----------
    dry_run:
        Print local counts only; no VM connectivity required.
    full:
        Ignore VM watermarks; push all local rows.
    table:
        Full table name (e.g. ``"signals_ema_crossover"``). None = all signal tables.
    sync_config:
        When True (default), also push config tables after signal tables.
        Set False to push signals only.
    """
    engine = get_engine()

    if dry_run:
        report = get_dry_run_report(engine)
        if table:
            report = [r for r in report if r["table"] == table]
        for r in report:
            wm = r["watermark"] or "n/a"
            print(
                f"  {r['table']:<40}  rows={r['local_rows']:>8,}  "
                f"wm={wm:<32}  mode={r['sync_mode']}  [{r['status']}]"
            )
        return

    # Determine tables to push
    if table:
        specs = [s for s in ALL_TABLES if s.name == table]
    else:
        specs = list(_SIGNAL_TABLES)
        if sync_config:
            specs += list(_CONFIG_TABLES)

    total_rows = 0
    tables_failed: list[str] = []

    for spec in specs:
        try:
            if spec.full_replace:
                rows = sync_table_full_replace(engine, spec)
            else:
                rows = sync_table_incremental(engine, spec, full=full)
            total_rows += rows
        except Exception as e:
            print(f"  [ERROR] {spec.name}: {e}", file=sys.stderr)
            tables_failed.append(spec.name)

    print(f"[signals-sync] {total_rows:,} rows pushed ({len(tables_failed)} failures)")
    if tables_failed:
        print(f"  Failed: {', '.join(tables_failed)}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Push local signal and config tables to Oracle Singapore VM. "
            "Inverted pattern from sync_hl_from_vm.py (push not pull)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Incremental push of all signal + config tables
  python -m ta_lab2.scripts.etl.sync_signals_to_vm

  # Dry run (no VM connection needed)
  python -m ta_lab2.scripts.etl.sync_signals_to_vm --dry-run

  # Full push (ignore VM watermarks)
  python -m ta_lab2.scripts.etl.sync_signals_to_vm --full

  # Single table
  python -m ta_lab2.scripts.etl.sync_signals_to_vm --table signals_ema_crossover
""",
    )
    parser.add_argument(
        "--db-url",
        default=os.environ.get("TARGET_DB_URL", ""),
        help="Local database URL (or set TARGET_DB_URL env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Report what would be synced based on local watermarks only. "
            "Does NOT require VM connectivity."
        ),
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full push (ignore VM watermarks, push all local rows)",
    )
    parser.add_argument(
        "--table",
        choices=[s.name for s in ALL_TABLES],
        default=None,
        help="Sync a single table (default: all)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show row counts, watermarks, and timing per table",
    )
    args = parser.parse_args(argv)

    # Build engine
    try:
        engine = get_engine(args.db_url) if args.db_url else get_engine()
    except Exception as e:
        print(f"[ERROR] Could not connect to local DB: {e}", file=sys.stderr)
        return 1

    mode = "FULL" if args.full else "incremental"
    now = datetime.now(tz=timezone.utc).isoformat()
    print(f"[signals-sync] {now} — {mode} push")

    # ── Dry run ──────────────────────────────────────────────────────────────
    if args.dry_run:
        print("\n[DRY-RUN] Local table state (no VM connection):\n")
        report = get_dry_run_report(engine)
        # Filter to requested table
        if args.table:
            report = [r for r in report if r["table"] == args.table]
        for r in report:
            wm = r["watermark"] or "n/a"
            print(
                f"  {r['table']:<40}  rows={r['local_rows']:>8,}  "
                f"wm={wm:<32}  mode={r['sync_mode']}  [{r['status']}]"
            )
        print("\n[DRY-RUN] No data pushed.")
        return 0

    # ── Determine which tables to sync ───────────────────────────────────────
    if args.table:
        specs = [s for s in ALL_TABLES if s.name == args.table]
    else:
        specs = list(ALL_TABLES)

    # ── Execute sync ─────────────────────────────────────────────────────────
    total_rows = 0
    tables_ok: list[str] = []
    tables_failed: list[str] = []
    start_all = time.perf_counter()

    for spec in specs:
        t_start = time.perf_counter()
        try:
            print(f"  Syncing {spec.name}...")
            if spec.full_replace:
                rows = sync_table_full_replace(engine, spec, verbose=args.verbose)
            else:
                rows = sync_table_incremental(
                    engine, spec, full=args.full, verbose=args.verbose
                )
            elapsed = time.perf_counter() - t_start
            if args.verbose or rows > 0:
                print(f"    {rows:,} rows pushed ({elapsed:.1f}s)")
            total_rows += rows
            tables_ok.append(spec.name)
        except Exception as e:
            elapsed = time.perf_counter() - t_start
            print(
                f"    [ERROR] {spec.name} failed after {elapsed:.1f}s: {e}",
                file=sys.stderr,
            )
            tables_failed.append(spec.name)
            # Continue to next table — partial sync is better than no sync

    # ── Summary ──────────────────────────────────────────────────────────────
    total_elapsed = time.perf_counter() - start_all
    print(
        f"\n[signals-sync] Done. {total_rows:,} rows pushed in {total_elapsed:.1f}s "
        f"({len(tables_ok)} tables ok, {len(tables_failed)} failed)"
    )
    if tables_failed:
        print(f"  Failed tables: {', '.join(tables_failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
