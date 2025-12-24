from __future__ import annotations

"""
run_go_forward_daily_refresh.py

Go-forward orchestrator:
- Only runs the pipeline if public.cmc_price_histories7 has NEW daily rows
  since the last successful pipeline run (tracked in a small state table).
- If new data exists, run these steps in order:

  1) refresh_cmc_price_bars_multi_tf.py
  2) refresh_cmc_price_bars_multi_tf_cal_us.py
  3) refresh_cmc_price_bars_multi_tf_cal_iso.py
  4) refresh_cmc_price_bars_multi_tf_cal_anchor_us.py
  5) refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py
  6) run_all_ema_refreshes.py
  7) sync_cmc_ema_multi_tf_u.py

Notes:
- This is intentionally "go-forward only".
- The underlying scripts already implement incremental append-only semantics
  and will only append new snapshot rows for new daily closes (unless they detect backfill).
- Requires TARGET_DB_URL set in env (same convention as your scripts).

Run:
  python run_go_forward_daily_refresh.py

Spyder:
  runfile(
    r"C:\\Users\\asafi\\Downloads\\ta_lab2\\src\\ta_lab2\\scripts\\pipeline\\run_go_forward_daily_refresh.py",
    wdir=r"C:\\Users\\asafi\\Downloads\\ta_lab2"
  )
"""

import argparse
import os
import runpy
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


# ----------------------------
# DB / State
# ----------------------------

DAILY_TABLE = "public.cmc_price_histories7"
STATE_TABLE = "public.ta_lab2_pipeline_state"
STATE_KEY = "go_forward_daily_refresh:last_daily_max_ts"


def _log(msg: str) -> None:
    print(f"[go_forward] {msg}")


def _require_env() -> None:
    if not os.getenv("TARGET_DB_URL"):
        raise RuntimeError("TARGET_DB_URL env var is required.")


def get_engine() -> Engine:
    return create_engine(os.environ["TARGET_DB_URL"], future=True)


def ensure_state_table(engine: Engine) -> None:
    ddl = f"""
    CREATE TABLE IF NOT EXISTS {STATE_TABLE} (
      state_key   text PRIMARY KEY,
      state_value timestamptz NULL,
      updated_at  timestamptz NOT NULL DEFAULT now()
    );
    """
    with engine.begin() as conn:
        conn.execute(text(ddl))


def get_last_state(engine: Engine) -> Optional[pd.Timestamp]:
    q = text(f"SELECT state_value FROM {STATE_TABLE} WHERE state_key = :k;")
    df = pd.read_sql(q, engine, params={"k": STATE_KEY})
    if df.empty or pd.isna(df.loc[0, "state_value"]):
        return None
    return pd.to_datetime(df.loc[0, "state_value"], utc=True)


def set_last_state(engine: Engine, ts: pd.Timestamp) -> None:
    q = text(
        f"""
        INSERT INTO {STATE_TABLE} (state_key, state_value, updated_at)
        VALUES (:k, :v, now())
        ON CONFLICT (state_key) DO UPDATE SET
          state_value = EXCLUDED.state_value,
          updated_at  = now();
        """
    )
    with engine.begin() as conn:
        conn.execute(q, {"k": STATE_KEY, "v": ts.to_pydatetime()})


def get_daily_max_ts(engine: Engine) -> Optional[pd.Timestamp]:
    q = text(f'SELECT MAX("timestamp") AS mx FROM {DAILY_TABLE};')
    df = pd.read_sql(q, engine)
    mx = df.loc[0, "mx"]
    if pd.isna(mx):
        return None
    return pd.to_datetime(mx, utc=True)


# ----------------------------
# Script runner (in-process)
# ----------------------------

@dataclass
class Step:
    name: str
    path: Path
    argv: List[str]


def run_step(step: Step) -> None:
    _log(f"=== [{step.name}] RUN ===")
    _log(f"[{step.name}] path: {step.path}")
    _log(f"[{step.name}] argv: {' '.join(shlex.quote(a) for a in step.argv)}")

    old_argv = sys.argv[:]
    t0 = time.time()
    try:
        sys.argv = [str(step.path), *step.argv]
        runpy.run_path(str(step.path), run_name="__main__")
    except SystemExit as e:
        code = int(e.code) if e.code is not None else 0
        if code != 0:
            raise RuntimeError(f"[{step.name}] exited with code {code}") from e
    finally:
        sys.argv = old_argv

    _log(f"[{step.name}] OK ({time.time() - t0:.1f}s)")


def build_steps(repo_root: Path, ids: str, periods: str) -> List[Step]:
    """
    We pass only lightweight args:
    - bars scripts: --ids all (incremental by default in your scripts)
    - EMA orchestrator: --ids all --periods lut (or user provided)
    - _u sync: --use-ingested-at (safe if present, falls back otherwise)
    """
    bars_dir = repo_root / "src" / "ta_lab2" / "scripts" / "bars"
    emas_dir = repo_root / "src" / "ta_lab2" / "scripts" / "emas"

    return [
        Step("bars_multi_tf", bars_dir / "refresh_cmc_price_bars_multi_tf.py", ["--ids", ids]),
        Step("bars_cal_us", bars_dir / "refresh_cmc_price_bars_multi_tf_cal_us.py", ["--ids", ids]),
        Step("bars_cal_iso", bars_dir / "refresh_cmc_price_bars_multi_tf_cal_iso.py", ["--ids", ids]),
        Step("bars_cal_anchor_us", bars_dir / "refresh_cmc_price_bars_multi_tf_cal_anchor_us.py", ["--ids", ids]),
        Step("bars_cal_anchor_iso", bars_dir / "refresh_cmc_price_bars_multi_tf_cal_anchor_iso.py", ["--ids", ids]),
        Step("emas_all", emas_dir / "run_all_ema_refreshes.py", ["--ids", ids, "--periods", periods]),
        Step("ema_u_sync", emas_dir / "sync_cmc_ema_multi_tf_u.py", ["--use-ingested-at"]),
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="Go-forward pipeline runner (only runs if new daily data exists).")
    ap.add_argument("--ids", default="all", help="Ids to run (default: all).")
    ap.add_argument("--periods", default="lut", help="EMA periods (default: lut).")
    ap.add_argument(
        "--repo-root",
        default="",
        help="Optional path to repo root. If omitted, inferred as 3 levels up from this file (scripts/pipeline/...).",
    )
    ap.add_argument("--force", action="store_true", help="Run pipeline even if no new daily data is detected.")
    args = ap.parse_args()

    _require_env()
    engine = get_engine()
    ensure_state_table(engine)

    daily_max = get_daily_max_ts(engine)
    if daily_max is None:
        _log(f"No rows found in {DAILY_TABLE}. Nothing to do.")
        return

    last_run = get_last_state(engine)

    if not args.force and last_run is not None and daily_max <= last_run:
        _log(f"No new daily data. daily_max={daily_max} <= last_run={last_run}. Exiting.")
        return

    if last_run is None:
        _log(f"First run (no state). daily_max={daily_max}. Running pipeline.")
    else:
        _log(f"New daily data detected. daily_max={daily_max} > last_run={last_run}. Running pipeline.")

    here = Path(__file__).resolve()
    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        # expected: repo/src/ta_lab2/scripts/pipeline/this_file.py  => go up 5 to repo root
        # pipeline -> scripts -> ta_lab2 -> src -> repo
        repo_root = here.parents[4]

    steps = build_steps(repo_root=repo_root, ids=args.ids, periods=args.periods)

    # run everything; if any step fails, we do NOT advance the watermark
    for step in steps:
        if not step.path.exists():
            raise FileNotFoundError(f"Missing script: {step.path}")
        run_step(step)

    # if all OK, advance watermark to the latest daily max
    set_last_state(engine, daily_max)
    _log(f"Done. Updated state {STATE_KEY} = {daily_max.isoformat()}")


if __name__ == "__main__":
    main()
