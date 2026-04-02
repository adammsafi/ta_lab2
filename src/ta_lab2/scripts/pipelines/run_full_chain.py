"""
Full pipeline chain: Data -> Features -> Signals -> sync_signals_to_vm.

Thin wrapper that calls the three local pipelines in sequence via subprocess,
then optionally syncs signals to the Oracle VM. Each pipeline is unaware of
the chain — this wrapper handles sequencing and halt-on-failure logic.

This replaces `run_daily_refresh.py --all` with explicit pipeline separation.

Usage:
    python -m ta_lab2.scripts.pipelines.run_full_chain --ids all
    python -m ta_lab2.scripts.pipelines.run_full_chain --ids 1,52,825 --dry-run
    python -m ta_lab2.scripts.pipelines.run_full_chain --ids all --no-sync-signals
    python -m ta_lab2.scripts.pipelines.run_full_chain --ids all --no-sync-vms

Stage order:
    1. Data pipeline     (sync VMs, bars, bar returns)
    2. Features pipeline (EMAs, AMAs, returns, macro, regimes, features)
    3. Signals pipeline  (macro gates, macro alerts, signals, gate, IC check)
    4. sync_signals_to_vm (push signals + config to Oracle VM)

Halt behavior:
    - Any pipeline failure halts the chain (subsequent pipelines not started).
    - sync_signals_to_vm failure is non-fatal (local pipeline is complete).
    - Telegram alert sent on chain halt.

PIPELINE_NAME used in pipeline_utils logging.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

PIPELINE_NAME = "full_chain"

# ── Pipeline sequence (module, display name) ────────────────────────────────
_PIPELINES = [
    ("data", "ta_lab2.scripts.pipelines.run_data_pipeline"),
    ("features", "ta_lab2.scripts.pipelines.run_features_pipeline"),
    ("signals", "ta_lab2.scripts.pipelines.run_signals_pipeline"),
]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Full pipeline chain: Data -> Features -> Signals -> sync_signals_to_vm. "
            "Replaces run_daily_refresh.py --all with explicit pipeline separation."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full chain for all assets
  python -m ta_lab2.scripts.pipelines.run_full_chain --ids all

  # Dry run
  python -m ta_lab2.scripts.pipelines.run_full_chain --ids all --dry-run

  # Skip VM sync (e.g. already synced today)
  python -m ta_lab2.scripts.pipelines.run_full_chain --ids all --no-sync-vms

  # Skip final VM push (local only)
  python -m ta_lab2.scripts.pipelines.run_full_chain --ids all --no-sync-signals

  # Skip GARCH and macro analytics (faster iteration)
  python -m ta_lab2.scripts.pipelines.run_full_chain --ids all --no-garch --no-macro-analytics

  # Parallel bar builders
  python -m ta_lab2.scripts.pipelines.run_full_chain --ids all -n 8
        """,
    )

    # ── Core args ────────────────────────────────────────────────────────────
    p.add_argument(
        "--ids",
        required=True,
        help="Asset IDs: comma-separated integers or 'all'",
    )
    p.add_argument(
        "--db-url",
        default=os.environ.get("TARGET_DB_URL", ""),
        help="Database URL (default: from TARGET_DB_URL or db_config.env)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Pass --dry-run to all pipelines (no DB writes)",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Pass --verbose to all pipelines",
    )
    p.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Pass --continue-on-error to all pipelines (stage failures don't halt pipeline)",
    )

    # ── Data pipeline flags ──────────────────────────────────────────────────
    p.add_argument(
        "--no-sync-vms",
        action="store_true",
        help="Skip VM sync stages in Data pipeline",
    )
    p.add_argument(
        "--source",
        default=None,
        help="Data source filter forwarded to Data pipeline",
    )
    p.add_argument(
        "-n",
        "--num-processes",
        type=int,
        default=None,
        help="Parallel worker count forwarded to Data and Features pipelines",
    )

    # ── Features pipeline flags ──────────────────────────────────────────────
    p.add_argument(
        "--skip-stale-check",
        action="store_true",
        help="Skip bar staleness check in Features pipeline",
    )
    p.add_argument(
        "--staleness-hours",
        type=int,
        default=None,
        help="Bar staleness threshold (hours) forwarded to Features pipeline",
    )
    p.add_argument(
        "--no-garch",
        action="store_true",
        help="Skip GARCH stage in Features pipeline",
    )
    p.add_argument(
        "--no-macro-analytics",
        action="store_true",
        help="Skip macro analytics stage in Features pipeline",
    )

    # ── Signals pipeline flags ───────────────────────────────────────────────
    p.add_argument(
        "--no-signal-gate",
        action="store_true",
        help="Skip signal validation gate in Signals pipeline",
    )
    p.add_argument(
        "--no-ic-staleness",
        action="store_true",
        help="Skip IC staleness check in Signals pipeline",
    )

    # ── Chain flags ──────────────────────────────────────────────────────────
    p.add_argument(
        "--no-sync-signals",
        action="store_true",
        help="Skip sync_signals_to_vm after Signals pipeline (local only)",
    )

    return p


def _build_data_cmd(args: argparse.Namespace) -> list[str]:
    """Build subprocess command for the Data pipeline."""
    cmd = [sys.executable, "-m", "ta_lab2.scripts.pipelines.run_data_pipeline"]
    cmd.extend(["--ids", args.ids])
    if args.db_url:
        cmd.extend(["--db-url", args.db_url])
    if args.dry_run:
        cmd.append("--dry-run")
    if args.verbose:
        cmd.append("--verbose")
    if args.continue_on_error:
        cmd.append("--continue-on-error")
    if args.no_sync_vms:
        cmd.append("--no-sync-vms")
    if args.source:
        cmd.extend(["--source", args.source])
    if args.num_processes:
        cmd.extend(["-n", str(args.num_processes)])
    return cmd


def _build_features_cmd(args: argparse.Namespace) -> list[str]:
    """Build subprocess command for the Features pipeline."""
    cmd = [sys.executable, "-m", "ta_lab2.scripts.pipelines.run_features_pipeline"]
    cmd.extend(["--ids", args.ids])
    if args.db_url:
        cmd.extend(["--db-url", args.db_url])
    if args.dry_run:
        cmd.append("--dry-run")
    if args.verbose:
        cmd.append("--verbose")
    if args.continue_on_error:
        cmd.append("--continue-on-error")
    if args.skip_stale_check:
        cmd.append("--skip-stale-check")
    if args.staleness_hours:
        cmd.extend(["--staleness-hours", str(args.staleness_hours)])
    if args.no_garch:
        cmd.append("--no-garch")
    if args.no_macro_analytics:
        cmd.append("--no-macro-analytics")
    if args.num_processes:
        cmd.extend(["-n", str(args.num_processes)])
    return cmd


def _build_signals_cmd(args: argparse.Namespace) -> list[str]:
    """Build subprocess command for the Signals pipeline."""
    cmd = [sys.executable, "-m", "ta_lab2.scripts.pipelines.run_signals_pipeline"]
    if args.db_url:
        cmd.extend(["--db-url", args.db_url])
    if args.dry_run:
        cmd.append("--dry-run")
    if args.verbose:
        cmd.append("--verbose")
    if args.continue_on_error:
        cmd.append("--continue-on-error")
    if args.no_signal_gate:
        cmd.append("--no-signal-gate")
    if args.no_ic_staleness:
        cmd.append("--no-ic-staleness")
    return cmd


def _build_sync_cmd(args: argparse.Namespace) -> list[str]:
    """Build subprocess command for sync_signals_to_vm."""
    cmd = [sys.executable, "-m", "ta_lab2.scripts.etl.sync_signals_to_vm"]
    if args.db_url:
        cmd.extend(["--db-url", args.db_url])
    if args.verbose:
        cmd.append("--verbose")
    return cmd


def _send_telegram_alert(pipeline_name: str, returncode: int) -> None:
    """Best-effort Telegram alert when a pipeline halts the chain."""
    try:
        from ta_lab2.notifications import telegram  # type: ignore[attr-defined]

        if telegram.is_configured():
            telegram.send_alert(
                f"Pipeline Chain HALTED at {pipeline_name}",
                f"{pipeline_name} pipeline failed with exit code {returncode}. "
                "Subsequent pipelines not started.",
                severity="warning",
            )
    except Exception:
        pass  # Never let alert failure crash the chain script


def main(argv: list[str] | None = None) -> int:
    p = _build_parser()
    args = p.parse_args(argv)

    chain_start = time.perf_counter()
    print(f"\n{'=' * 70}")
    print(f"CHAIN START: Data -> Features -> Signals (ids={args.ids})")
    print(f"{'=' * 70}")

    # ── Build pipeline commands ──────────────────────────────────────────────
    pipeline_cmds = [
        ("Data", _build_data_cmd(args)),
        ("Features", _build_features_cmd(args)),
        ("Signals", _build_signals_cmd(args)),
    ]

    # ── Execute pipelines sequentially ──────────────────────────────────────
    import subprocess

    completed: list[str] = []
    for name, cmd in pipeline_cmds:
        print(f"\n{'=' * 70}")
        print(f"CHAIN: Running {name} pipeline")
        if args.verbose:
            print(f"  cmd: {' '.join(cmd)}")
        print(f"{'=' * 70}")

        stage_start = time.perf_counter()
        result = subprocess.run(cmd, check=False)
        stage_elapsed = time.perf_counter() - stage_start

        if result.returncode != 0:
            print(
                f"\n[CHAIN HALTED] {name} pipeline failed "
                f"(exit {result.returncode}, {stage_elapsed:.0f}s)"
            )
            _send_telegram_alert(name, result.returncode)
            return result.returncode

        print(f"\n[CHAIN OK] {name} pipeline complete ({stage_elapsed:.0f}s)")
        completed.append(name)

    # ── All 3 pipelines succeeded — sync signals to VM ───────────────────────
    if not args.no_sync_signals and not args.dry_run:
        print(f"\n{'=' * 70}")
        print("CHAIN: Syncing signals to Oracle VM")
        print(f"{'=' * 70}")

        sync_cmd = _build_sync_cmd(args)
        if args.verbose:
            print(f"  cmd: {' '.join(sync_cmd)}")

        sync_start = time.perf_counter()
        sync_result = subprocess.run(sync_cmd, check=False)
        sync_elapsed = time.perf_counter() - sync_start

        if sync_result.returncode != 0:
            # Non-fatal: local pipeline is complete; VM sync is best-effort
            print(
                f"[WARN] sync_signals_to_vm failed (exit {sync_result.returncode}, "
                f"{sync_elapsed:.0f}s) — signals not pushed to VM. "
                "Local pipeline complete."
            )
        else:
            print(f"[CHAIN OK] sync_signals_to_vm complete ({sync_elapsed:.0f}s)")
    elif args.no_sync_signals:
        print("\n[CHAIN] Skipping sync_signals_to_vm (--no-sync-signals)")
    elif args.dry_run:
        print("\n[CHAIN] Skipping sync_signals_to_vm (--dry-run)")

    total_elapsed = time.perf_counter() - chain_start
    print(f"\n{'=' * 70}")
    print(f"CHAIN COMPLETE: {' -> '.join(completed)}  [{total_elapsed:.0f}s]")
    print(f"{'=' * 70}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
