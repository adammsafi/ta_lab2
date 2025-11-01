
import pandas as pd
import pathlib

def write_parquet(df: pd.DataFrame, path: str, partition_cols=None):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if partition_cols:
        df.to_parquet(path, partition_cols=partition_cols, index=False)
    else:
        df.to_parquet(path, index=False)

def read_parquet(path: str) -> pd.DataFrame:
    return pd.read_parquet(path)
