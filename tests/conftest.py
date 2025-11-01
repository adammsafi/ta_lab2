from pathlib import Path
import pandas as pd
import pytest

@pytest.fixture
def tiny_csv(tmp_path: Path) -> Path:
    df = pd.DataFrame({
        "Date": ["2024-01-01","2024-01-02","2024-01-03"],
        "Open": [100, 101, 102],
        "High": [101, 102, 103],
        "Low":  [ 99, 100, 101],
        "Close":[100.5, 101.5, 102.5],
        "Volume": [1000, 1200, 1100],
        "Market Cap": [1e9, 1.01e9, 1.02e9],
    })
    p = tmp_path / "tiny.csv"
    df.to_csv(p, index=False)
    return p
