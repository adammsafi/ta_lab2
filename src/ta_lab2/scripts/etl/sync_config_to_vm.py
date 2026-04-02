"""
sync_config_to_vm.py

Push local config/dimension tables to the Oracle Singapore VM using a
full-replace strategy (TRUNCATE + COPY all rows).  These tables are small
and stateless so incremental sync is not needed.

Tables synced:
  - dim_executor_config  — executor strategy settings
  - dim_risk_limits      — per-strategy risk gate limits
  - dim_risk_state       — current risk state (kill-switch etc.)

Useful for urgent changes such as kill-switch activation that must reach
the VM immediately without waiting for the next daily signal push.

Usage:
    python -m ta_lab2.scripts.etl.sync_config_to_vm              # all tables
    python -m ta_lab2.scripts.etl.sync_config_to_vm --dry-run    # report only
    python -m ta_lab2.scripts.etl.sync_config_to_vm --table dim_executor_config
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

# ── Config tables: full-replace (TRUNCATE + COPY all rows) ───────────────────
CONFIG_TABLES: list[str] = [
    "dim_executor_config",
    "dim_risk_limits",
    "dim_risk_state",
]


# ── SSH helpers ──────────────────────────────────────────────────────────────


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
    """Run a psql command on the VM via SSH.  Returns stdout."""
    cmd = _ssh_cmd(
        f'PGPASSWORD={VM_DB_PASS} psql -h 127.0.0.1 -U {VM_DB_USER} -d {VM_DB} -t -A -c "{sql}"'
    )
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"SSH psql failed: {result.stderr}")
    return result.stdout.strip()


# ── Local export ─────────────────────────────────────────────────────────────


def _local_export_csv(engine, table: str) -> str:
    """Export all rows from a local table as CSV (with header) via COPY TO STDOUT."""
    try:
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            buf = io.StringIO()
            cur.copy_expert(f"COPY {table} TO STDOUT WITH CSV HEADER", buf)
            return buf.getvalue()
        finally:
            raw.close()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Local CSV export from {table} failed: {e}") from e


# ── VM push ──────────────────────────────────────────────────────────────────


def _truncate_vm_table(table: str, timeout: int = 30) -> None:
    """TRUNCATE *table* on the VM (safe because config tables have no FKs pointing in)."""
    try:
        _vm_psql(f"TRUNCATE TABLE {table}", timeout=timeout)
    except RuntimeError as e:
        err = str(e)
        if "does not exist" in err or "relation" in err:
            print(
                f"  [WARN] VM table {table} does not exist — skipping (run Phase 113 first)",
                file=sys.stderr,
            )
            return
        raise


def _push_csv_to_vm(csv_data: str, table: str, timeout: int = 60) -> int:
    """Stream *csv_data* (with header) into VM *table* via SSH psql COPY FROM STDIN.

    Returns the number of rows inserted as reported by psql ("COPY N").
    """
    if not csv_data.strip():
        return 0

    cmd = _ssh_cmd(
        f"PGPASSWORD={VM_DB_PASS} psql -h 127.0.0.1 -U {VM_DB_USER} -d {VM_DB} "
        f'-c "COPY {table} FROM STDIN WITH CSV HEADER"'
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
                f"  [WARN] VM table {table} does not exist — skipping (run Phase 113 first)",
                file=sys.stderr,
            )
            return 0
        raise RuntimeError(f"SSH COPY push to {table} failed: {err}")

    for line in result.stdout.splitlines():
        if line.startswith("COPY "):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                pass

    # Fallback: count lines minus header
    lines = [ln for ln in csv_data.split("\n") if ln.strip()]
    return max(0, len(lines) - 1)


# ── Per-table sync ────────────────────────────────────────────────────────────


def sync_one_table(engine, table: str, verbose: bool = False) -> int:
    """Full-replace sync of a single config table: TRUNCATE then COPY all rows.

    Returns number of rows pushed.
    """
    t_start = time.perf_counter()
    print(f"  Syncing {table}...")

    csv_data = _local_export_csv(engine, table)
    _truncate_vm_table(table)
    rows = _push_csv_to_vm(csv_data, table)

    elapsed = time.perf_counter() - t_start
    if verbose or rows > 0:
        print(f"    {rows:,} rows pushed ({elapsed:.1f}s)")
    return rows


def _local_counts(engine) -> dict[str, int]:
    """Return local row counts for all config tables (for dry-run reporting)."""
    counts: dict[str, int] = {}
    for table in CONFIG_TABLES:
        try:
            with engine.connect() as conn:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            counts[table] = n or 0
        except Exception:
            counts[table] = -1
    return counts


# ── Public API ────────────────────────────────────────────────────────────────


def sync_config(
    *,
    dry_run: bool = False,
    table: str | None = None,
    verbose: bool = False,
) -> None:
    """Programmatic entry-point: push config tables from local to VM.

    Called automatically by sync_signals() after signal push, and also
    usable directly for urgent config pushes (e.g., kill-switch activation).

    Parameters
    ----------
    dry_run:
        Print local counts only; no VM connectivity required.
    table:
        Full table name to sync.  None = all config tables.
    verbose:
        Print per-table timing and row counts.
    """
    engine = get_engine()

    if dry_run:
        counts = _local_counts(engine)
        for t, n in counts.items():
            status = f"{n:,} rows" if n >= 0 else "(table missing)"
            print(f"  {t:<35}  {status}  [full-replace]")
        return

    tables = [table] if table else CONFIG_TABLES
    total = 0
    failed: list[str] = []

    for t in tables:
        try:
            rows = sync_one_table(engine, t, verbose=verbose)
            total += rows
        except Exception as e:
            print(f"  [ERROR] {t}: {e}", file=sys.stderr)
            failed.append(t)

    print(f"[config-sync] {total:,} rows pushed ({len(failed)} failures)")
    if failed:
        print(f"  Failed: {', '.join(failed)}", file=sys.stderr)


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Push local config/dimension tables to the Oracle Singapore VM. "
            "Full-replace (TRUNCATE + COPY) since tables are small and stateless. "
            "Use for urgent changes such as kill-switch activation."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Push all config tables
  python -m ta_lab2.scripts.etl.sync_config_to_vm

  # Dry run (no VM connection needed)
  python -m ta_lab2.scripts.etl.sync_config_to_vm --dry-run

  # Single table (e.g. after kill-switch activation)
  python -m ta_lab2.scripts.etl.sync_config_to_vm --table dim_risk_state
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
        help="Report local row counts only.  No VM connectivity required.",
    )
    parser.add_argument(
        "--table",
        choices=CONFIG_TABLES,
        default=None,
        help="Sync a single table (default: all)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show per-table timing and row counts",
    )
    args = parser.parse_args(argv)

    try:
        engine = get_engine(args.db_url) if args.db_url else get_engine()
    except Exception as e:
        print(f"[ERROR] Could not connect to local DB: {e}", file=sys.stderr)
        return 1

    now = datetime.now(tz=timezone.utc).isoformat()
    mode = "DRY-RUN" if args.dry_run else "full-replace"
    print(f"[config-sync] {now} — {mode}")

    if args.dry_run:
        counts = _local_counts(engine)
        for t, n in counts.items():
            status = f"{n:,} rows" if n >= 0 else "(table missing)"
            print(f"  {t:<35}  {status}  [full-replace]")
        print("\n[DRY-RUN] No data pushed.")
        return 0

    tables = [args.table] if args.table else CONFIG_TABLES
    total = 0
    failed: list[str] = []
    start_all = time.perf_counter()

    for t in tables:
        try:
            rows = sync_one_table(engine, t, verbose=args.verbose)
            total += rows
        except Exception as e:
            elapsed_t = time.perf_counter() - start_all
            print(
                f"  [ERROR] {t} failed after {elapsed_t:.1f}s: {e}",
                file=sys.stderr,
            )
            failed.append(t)

    total_elapsed = time.perf_counter() - start_all
    print(
        f"\n[config-sync] Done. {total:,} rows pushed in {total_elapsed:.1f}s "
        f"({len(tables) - len(failed)} tables ok, {len(failed)} failed)"
    )
    if failed:
        print(f"  Failed tables: {', '.join(failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
