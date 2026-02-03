"""I/O utilities for economic data.

Extracted from fedtools2.utils.io and cleaned up with:
- Full type hints
- Comprehensive docstrings
- Removed environment-specific paths

Original source: .archive/external-packages/2026-02-03/fedtools2/src/fedtools2/utils/io.py
"""
from pathlib import Path
from typing import Union

import pandas as pd


def read_csv(path: Union[str, Path]) -> pd.DataFrame:
    """Read a CSV file into a DataFrame.

    Simple wrapper around pd.read_csv for consistency in economic data
    loading. Handles both string and Path inputs.

    Args:
        path: Path to the CSV file

    Returns:
        DataFrame with CSV contents

    Example:
        >>> df = read_csv("data/FEDFUNDS.csv")
        >>> df.columns.tolist()
        ['observation_date', 'FEDFUNDS']
    """
    return pd.read_csv(path)


def ensure_dir(path: Union[str, Path]) -> Path:
    """Create a directory with parents if it doesn't exist.

    Thread-safe directory creation that handles race conditions
    via exist_ok=True.

    Args:
        path: Directory path to create

    Returns:
        Path object for the directory

    Example:
        >>> output_dir = ensure_dir("output/economic")
        >>> output_dir.exists()
        True
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path
