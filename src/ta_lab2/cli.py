from __future__ import annotations
import argparse
from pathlib import Path

# Import from root-level config.py, not from ta_lab2.config
from config import load_settings, project_root
from ta_lab2.regimes.run_btc_pipeline import run_btc_pipeline


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ta-lab2", description="ta_lab2 CLI")
    ap.add_argument(
        "--config", "-c",
        default="config/default.yaml",
        help="Path to YAML config relative to project root (default: config/default.yaml)"
    )
    args = ap.parse_args(argv)

    # Load settings from YAML via the root-level config.py
    settings = load_settings(args.config)

    # Resolve absolute paths for input and output
    csv = Path(settings.data_csv)
    out_dir = Path(settings.out_dir)

    # Run main pipeline
    result = run_btc_pipeline(
        csv_path=csv,
        out_dir=out_dir,
        ema_windows=settings.ema_windows,
        resample=settings.resample
    )

    print("Pipeline complete:", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
