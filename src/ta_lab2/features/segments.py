# src/ta_lab2/features/segments.py
"""
Flip-segment builder

Turns per-bar trend state labels into contiguous segments with start/end metadata.
"""

from __future__ import annotations
import numpy as np
import pandas as pd


def build_flip_segments(
    df: pd.DataFrame,
    price_col: str = "close",
    state_col: str = "trend_state",
    timestamp_col: str | None = None,
) -> pd.DataFrame:
    """
    Build contiguous segments of identical trend states.

    Parameters
    ----------
    df : pd.DataFrame
        Must include state_col and price_col (and optionally timestamp_col).
    price_col : str, default "close"
        Column used to measure segment returns.
    state_col : str, default "trend_state"
        Column with integer or categorical trend labels.
    timestamp_col : str or None
        Optional timestamp column for segment start/end markers.

    Returns
    -------
    segs : pd.DataFrame
        Columns:
        - seg_id, state, start_idx, end_idx
        - start_price, end_price, seg_return, seg_len
        - start_time, end_time (if timestamp_col provided)
    """
    if state_col not in df or price_col not in df:
        raise KeyError(f"DataFrame must include '{state_col}' and '{price_col}'.")

    states = df[state_col].to_numpy()
    changes = np.concatenate(
        [[0], np.nonzero(np.diff(states, prepend=states[0]))[0] + 1]
    )
    seg_ids = np.repeat(np.arange(len(changes)), np.diff(np.append(changes, len(df))))
    seg_df = df.copy()
    seg_df["seg_id"] = seg_ids

    # Aggregate by segment id
    gb = seg_df.groupby("seg_id", sort=False)
    segs = gb.agg(
        state=(state_col, "first"),
        start_idx=(price_col, lambda x: x.index[0]),
        end_idx=(price_col, lambda x: x.index[-1]),
        start_price=(price_col, "first"),
        end_price=(price_col, "last"),
        seg_len=(price_col, "size"),
    ).reset_index()

    segs["seg_return"] = segs["end_price"] / segs["start_price"] - 1

    if timestamp_col and timestamp_col in df:
        gb_t = (
            seg_df.groupby("seg_id", sort=False)[timestamp_col]
            .agg(["first", "last"])
            .rename(columns={"first": "start_time", "last": "end_time"})
        )
        segs = segs.join(gb_t, on="seg_id")

    return segs


__all__ = ["build_flip_segments"]
