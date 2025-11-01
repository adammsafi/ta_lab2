@@
-# ---- load your CSV ---------------------------------------------------------
-csv_path = r"C:/Users/asafi/Downloads/ta_lab2/Bitcoin_01_1_2016-10_26_2025_historical_data_coinmarketcap.csv"
-df2 = pd.read_csv(csv_path)
-# Normalize headers to stable names
-df2.columns = _clean_headers(df2.columns)
-...   # (rest of pipeline at import time)
+from pathlib import Path
+import pandas as pd
+import logging
+
+log = logging.getLogger(__name__)
+
+def run_btc_pipeline(csv_path: str | Path, out_dir: str | Path, **kwargs) -> dict:
+    """
+    Run the BTC pipeline.
+    Parameters
+    ----------
+    csv_path : path to source CSV
+    out_dir  : output directory for artifacts (parquet/csv)
+    kwargs   : optional tuning params (ema windows, resample rules, etc.)
+    Returns
+    -------
+    dict with key outputs, e.g. file paths or small result stats
+    """
+    csv_path = Path(csv_path)
+    out_dir = Path(out_dir)
+    out_dir.mkdir(parents=True, exist_ok=True)
+
+    if not csv_path.exists():
+        raise FileNotFoundError(f"Input CSV not found: {csv_path}")
+
+    log.info("Loading data from %s", csv_path)
+    df2 = pd.read_csv(csv_path)
+    df2.columns = _clean_headers(df2.columns)  # your existing helper
+
+    # ... your existing transforms/features/resampling/regimes here ...
+    # write outputs to out_dir
+    # e.g., (keep your current filenames, just write relative to out_dir)
+    # df_daily.to_parquet(out_dir / "daily_en.parquet")
+    # df_weekly.to_parquet(out_dir / "weekly_en.parquet")
+    # stats.to_csv(out_dir / "regime_stats.csv", index=False)
+
+    return {
+        "input": str(csv_path),
+        "out_dir": str(out_dir),
+        # "n_rows": len(df2),
+        # "artifacts": [str(out_dir / "daily_en.parquet"), ...]
+    }
+
+if __name__ == "__main__":
+    # Local manual run (kept for convenience)
+    DEFAULT_ROOT = Path(__file__).resolve().parents[3]
+    csv = DEFAULT_ROOT / "data" / "Bitcoin_01_1_2016-10_26_2025_historical_data_coinmarketcap.csv"
+    out_ = DEFAULT_ROOT / "out"
+    run_btc_pipeline(csv_path=csv, out_dir=out_)
