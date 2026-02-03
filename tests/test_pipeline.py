# tests/test_pipeline.py
import pandas as pd
from ta_lab2.pipelines.btc_pipeline import run_btc_pipeline


def test_pipeline_minimal(tmp_path):
    p = tmp_path / "btc.csv"
    pd.DataFrame(
        {
            "timestamp": ["2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z"],
            "open": [1, 1.1],
            "high": [1.1, 1.2],
            "low": [0.9, 1.0],
            "close": [1.05, 1.15],
            "volume": [10, 12],
        }
    ).to_csv(p, index=False)
    res = run_btc_pipeline(str(p))
    assert res["summary"]["n_rows"] == 2
