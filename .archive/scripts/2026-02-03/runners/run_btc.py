# -*- coding: utf-8 -*-
"""
Runner for the BTC pipeline (Spyder- and CLI-friendly).
- Calls ta_lab2.pipelines.btc_pipeline.main(csv_path, config_path, save_artifacts)
- If --csv is omitted, the pipeline will auto-discover common CSV paths (e.g., data/btc.csv).
"""

from __future__ import annotations

import sys
import argparse
from pathlib import Path

# Make src importable when running from source
HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parent
SRC_DIR = REPO_ROOT / "src"
if SRC_DIR.exists():
    sys.path.insert(0, str(SRC_DIR))

from ta_lab2.pipelines.btc_pipeline import main  # noqa: E402


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Run the BTC pipeline end-to-end.")
    p.add_argument(
        "--csv", dest="csv_path", default=None, help="Path to input CSV (optional)."
    )
    p.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Path to YAML config (optional).",
    )
    p.add_argument(
        "--no-save",
        dest="save_artifacts",
        action="store_false",
        help="Do not write artifacts.",
    )
    return p.parse_args(argv)


def run(argv=None):
    args = parse_args(argv)
    df = main(
        csv_path=args.csv_path,
        config_path=args.config_path,
        save_artifacts=args.save_artifacts,
    )

    # Console summary (similar to your genesis scripts)
    try:
        import pandas as pd

        ts_col = "timestamp" if "timestamp" in df.columns else df.columns[0]
        ts_min = pd.to_datetime(df[ts_col].min())
        ts_max = pd.to_datetime(df[ts_col].max())
        print(f"Loaded rows: {len(df)}")
        print(f"Date range: {ts_min} → {ts_max}")
        print(
            f"Columns now: {list(df.columns)[:12]} ... (+{max(0, len(df.columns)-12)} more)"
        )
    except Exception:
        pass

    return df


if __name__ == "__main__":
    run()
