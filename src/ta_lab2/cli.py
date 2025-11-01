from __future__ import annotations
import argparse
from pathlib import Path
from .config import load_settings, project_root
from .regimes.run_btc_pipeline import run_btc_pipeline

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ta-lab2", description="ta_lab2 CLI")
    ap.add_argument("--config", "-c", default="configs/default.yaml",
                    help="Path to YAML config relative to project root")
    args = ap.parse_args(argv)

    root = project_root()
    cfg_path = (root / args.config).resolve()
    settings = load_settings(cfg_path)

    csv = (root / settings.data_csv).resolve()
    out_dir = (root / settings.out_dir).resolve()

    result = run_btc_pipeline(csv_path=csv, out_dir=out_dir,
                              ema_windows=settings.ema_windows,
                              resample=settings.resample)
    print("Pipeline complete:", result)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
