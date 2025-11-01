from __future__ import annotations
from pathlib import Path
import pandas as pd

def run_btc_pipeline(
    csv_path: str | Path,
    out_dir: str | Path,
    ema_windows: list[int] | None = None,
    resample: dict | None = None,
):
    """
    Orchestrate the BTC pipeline:
      1) load CSV (from csv_path)
      2) compute features / regimes (call your existing helpers)
      3) write outputs to out_dir
    """
    csv_path = Path(csv_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---- 1) Load data (NO hard-coded paths) ----
    df = pd.read_csv(csv_path)

    # TODO: call your existing feature/resample/regime functions here, e.g.:
    # df = add_base_features(df, ema_windows=ema_windows, resample=resample)
    # regimes = compute_regimes(df)
    # Save outputs:
    # df.to_parquet(out_dir / "daily_en.parquet")
    # regimes.to_parquet(out_dir / "daily_regimes.parquet")

    # For now just return a tiny status so CLI works:
    return {"rows": len(df), "out_dir": str(out_dir)}

if __name__ == "__main__":
    # Optional: ad-hoc local test; never runs during import.
    raise SystemExit("Use the CLI or call run_btc_pipeline() from code.")
