from __future__ import annotations

"""
Calendar-aligned multi-timeframe EMA builder for cmc_ema_multi_tf_cal_*.

Implements the specification provided:

Core concepts
1) Canonical calendar closes (roll = FALSE) come from calendar bars tables:
   - public.cmc_price_bars_multi_tf_cal_us
   - public.cmc_price_bars_multi_tf_cal_iso
   Using is_partial_end = FALSE only (no partial periods).

2) Timeframe universe comes from public.dim_timeframe:
   alignment_type='calendar',
   - scheme='US' selects:
    * weeks: *_CAL_US
    * months/years: *_CAL (no _US suffix)
  - scheme='ISO' selects:
    * weeks: *_CAL_ISO
    * months/years: only if present (otherwise none)
   allow_partial_start=FALSE, allow_partial_end=FALSE
   and exclude *_ANCHOR.

ema (daily-space EMA)
- Continuous DAILY EMA updated every day using daily-equivalent alpha.
- Seeded once at the first valid canonical bar EMA point.
- Never snaps to the bar EMA after seeding.
- roll flags are labels only, not behavior switches.

ema_bar (bar-space EMA with daily preview)
- Canonical value defined on true TF closes (canonical closes).
- At each TF close: snaps to the canonical bar EMA (bar-space EMA computed on closes).
- Between TF closes: daily "preview" propagation using daily-equivalent alpha on price.

Derivatives naming (MATCHES DOC SPEC)
ema-space:
- d1_roll/d2_roll: DAILY diffs on ema across all rows (continuous daily momentum/accel).
- d1/d2: canonical-only diffs on ema (roll=FALSE only; period-to-period momentum/accel).

bar-space:
- d1_roll_bar/d2_roll_bar: DAILY diffs on ema_bar across all rows (daily preview momentum/accel).
- d1_bar/d2_bar: canonical-only diffs on ema_bar (roll_bar=FALSE only; bar-to-bar momentum/accel).

IMPORTANT DB NOTE
- Pandas/NumPy NaN is NOT NULL in Postgres; COUNT(col) counts NaN.
- Before writing, we convert NaN -> None so Postgres stores NULL for "not applicable"
  values (e.g., d1 on roll=TRUE rows).

Only runner input that varies is scheme: US|ISO|BOTH.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


__all__ = [
    "build_multi_timeframe_ema_cal_frame",
    "write_multi_timeframe_ema_cal_to_db",
]


# ---------------------------------------------------------------------------
# Alpha LUT loader
# ---------------------------------------------------------------------------

def _load_alpha_lookup(engine: Engine, schema: str, table: str) -> pd.DataFrame:
    """
    Expected minimum columns:
      - tf (text)
      - period (int)
      - alpha_daily_eq (float)  # daily alpha equivalent
    """
    sql = text(f"""
      SELECT tf, period, alpha_ema_dailyspace AS alpha
      FROM {schema}.{table}
    """)
    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    if df.empty:
        raise RuntimeError(f"alpha lookup table {schema}.{table} returned 0 rows")

    df["period"] = df["period"].astype(int)
    df["tf"] = df["tf"].astype(str)
    df["alpha"] = df["alpha"].astype(float)
    return df


# ---------------------------------------------------------------------------
# Daily normalizer
# ---------------------------------------------------------------------------

def _normalize_daily(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values(["id", "ts"]).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# dim_timeframe calendar TFs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CalTfSpec:
    tf: str
    tf_days: int


def _load_calendar_tf_specs(engine: Engine, *, scheme: str) -> List[CalTfSpec]:
    """
    Load the CAL (non-anchor) calendar-aligned timeframe universe from public.dim_timeframe.

    IMPORTANT:
      Your dim_timeframe currently uses roll_policy='calendar_anchor' for BOTH:
        - CAL (e.g. 1W_CAL_US, 1M_CAL, 1Y_CAL)
        - CAL_ANCHOR (e.g. 1W_CAL_ANCHOR_US)
      Therefore, we must NOT filter by roll_policy to separate CAL vs CAL_ANCHOR.
      We separate using TF naming:
        - exclude anything containing '_ANCHOR' or '_CAL_ANCHOR_'
        - weeks are scheme-specific via suffix (_CAL_US / _CAL_ISO)
        - months/years are scheme-agnostic via *_CAL with no extra suffix
    """
    scheme_u = scheme.strip().upper()

    if scheme_u == "US":
        tf_where = """
          (
            -- US weeks: e.g. 1W_CAL_US, 2W_CAL_US, ...
            (base_unit = 'W' AND tf ~ '_CAL_US$')
            OR
            -- Scheme-agnostic months/years: e.g. 1M_CAL, 2M_CAL, 1Y_CAL, ...
            (base_unit IN ('M','Y') AND tf ~ '_CAL$' AND tf !~ '_CAL_')
          )
        """
    elif scheme_u == "ISO":
        tf_where = """
          (
            -- ISO weeks: e.g. 1W_CAL_ISO, 2W_CAL_ISO, ...
            (base_unit = 'W' AND tf ~ '_CAL_ISO$')
            OR
            -- Scheme-agnostic months/years: e.g. 1M_CAL, 2M_CAL, 1Y_CAL, ...
            (base_unit IN ('M','Y') AND tf ~ '_CAL$' AND tf !~ '_CAL_')
          )
        """
    else:
        raise ValueError(f"Unsupported scheme: {scheme} (expected US or ISO)")

    sql = text(f"""
      SELECT
        tf,
        COALESCE(tf_days_min, tf_days_max, tf_days_nominal) AS tf_days
      FROM public.dim_timeframe
      WHERE alignment_type = 'calendar'
        -- Exclude all anchor families by name (most reliable in your current dim_timeframe)
        AND tf NOT LIKE '%\\_CAL\\_ANCHOR\\_%' ESCAPE '\\'
        AND tf NOT LIKE '%\\_ANCHOR%' ESCAPE '\\'
        AND {tf_where}
      ORDER BY sort_order, tf;
    """)

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn)

    if df.empty:
        raise RuntimeError(f"No calendar TFs found in dim_timeframe for scheme={scheme_u}")

    df["tf"] = df["tf"].astype(str)
    df["tf_days"] = df["tf_days"].astype(int)
    return [CalTfSpec(tf=r.tf, tf_days=int(r.tf_days)) for r in df.itertuples(index=False)]



def _bars_table_for_scheme(scheme: str) -> str:
    s = scheme.strip().upper()
    if s == "US":
        return "public.cmc_price_bars_multi_tf_cal_us"
    if s == "ISO":
        return "public.cmc_price_bars_multi_tf_cal_iso"
    raise ValueError(f"Unsupported scheme: {scheme} (expected US or ISO)")


# ---------------------------------------------------------------------------
# Canonical closes loader from bars tables
# ---------------------------------------------------------------------------

def _load_canonical_closes_from_bars(
    engine: Engine,
    *,
    bars_table: str,
    ids: Sequence[int],
    tfs: Sequence[str],
    start: Optional[pd.Timestamp],
    end: Optional[pd.Timestamp],
) -> pd.DataFrame:
    """
    Returns canonical close rows from the bars table (is_partial_end = FALSE).
    Columns returned:
      id, tf, ts_close (UTC), bar_seq, tf_days
    """
    if not ids or not tfs:
        return pd.DataFrame(columns=["id", "tf", "ts_close", "bar_seq", "tf_days"])

    where = ["id = ANY(:ids)", "tf = ANY(:tfs)", "is_partial_end = FALSE"]
    params = {"ids": list(map(int, ids)), "tfs": list(map(str, tfs))}

    if start is not None:
        where.append("time_close >= :start")
        params["start"] = pd.to_datetime(start, utc=True)
    if end is not None:
        where.append("time_close <= :end")
        params["end"] = pd.to_datetime(end, utc=True)

    sql = text(f"""
      SELECT
        id,
        tf,
        time_close AS ts_close,
        bar_seq,
        tf_days
      FROM {bars_table}
      WHERE {" AND ".join(where)}
      ORDER BY id, tf, time_close;
    """)

    with engine.connect() as conn:
        df = pd.read_sql(sql, conn, params=params)

    if df.empty:
        return df

    df["id"] = df["id"].astype(int)
    df["tf"] = df["tf"].astype(str)
    df["ts_close"] = pd.to_datetime(df["ts_close"], utc=True)
    df["bar_seq"] = df["bar_seq"].astype(int)
    df["tf_days"] = df["tf_days"].astype(int)
    return df


# ---------------------------------------------------------------------------
# Bar EMA helper: period=p bars, min_periods=p
# ---------------------------------------------------------------------------

def _compute_bar_ema_on_closes(close_prices: np.ndarray, alpha_bar: float, min_periods: int) -> np.ndarray:
    """
    Compute EMA in bar-space on the sequence of canonical close prices.
    - For i < min_periods-1: NaN
    - At i == min_periods-1: seed with the simple mean of first min_periods closes
    - For i > min_periods-1: standard EMA recursion
    """
    n = len(close_prices)
    out = np.full(n, np.nan, dtype=float)
    if n < min_periods:
        return out

    seed_idx = min_periods - 1
    seed_val = float(np.mean(close_prices[:min_periods]))
    out[seed_idx] = seed_val

    prev = seed_val
    for i in range(seed_idx + 1, n):
        px = float(close_prices[i])
        prev = (alpha_bar * px) + (1.0 - alpha_bar) * prev
        out[i] = prev

    return out


# ---------------------------------------------------------------------------
# Frame builder (spec-correct)
# ---------------------------------------------------------------------------

def build_multi_timeframe_ema_cal_frame(
    df_daily: pd.DataFrame,
    *,
    tf_closes: pd.DataFrame,
    tf_days_map: Dict[str, int],
    ema_periods: Sequence[int],
    alpha_lut: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build spec-correct calendar-aligned multi-timeframe EMA frame.

    Inputs:
      - df_daily: id, ts, close
      - tf_closes: id, tf, ts_close (canonical close timestamps)
      - tf_days_map: {tf: tf_days} metadata only
      - ema_periods: (10, 21, ...)
      - alpha_lut: columns tf, period, alpha  (daily alpha equivalent)

    Output columns:
      id, tf, ts, period, tf_days,
      roll, ema, d1, d2, d1_roll, d2_roll,
      ema_bar, d1_bar, d2_bar, roll_bar, d1_roll_bar, d2_roll_bar
    """
    if df_daily.empty or tf_closes.empty:
        return pd.DataFrame()

    df_daily = _normalize_daily(df_daily)
    if "close" not in df_daily.columns:
        raise ValueError("df_daily must include 'close' column")

    alpha_map = {(r.tf, int(r.period)): float(r.alpha) for r in alpha_lut.itertuples(index=False)}

    out_frames: List[pd.DataFrame] = []
    closes_g = tf_closes.groupby(["id", "tf"])["ts_close"].apply(list).to_dict()

    for (id_, tf), close_list in closes_g.items():
        if tf not in tf_days_map:
            continue

        close_list = sorted(pd.to_datetime(close_list, utc=True))
        close_set = set(close_list)
        tf_days = int(tf_days_map[tf])

        df_id = df_daily[df_daily["id"] == id_].copy()
        if df_id.empty:
            continue
        df_id = df_id.sort_values("ts").reset_index(drop=True)

        df_closes = df_id[df_id["ts"].isin(close_set)].copy()
        if df_closes.empty:
            continue
        df_closes = df_closes.sort_values("ts").reset_index(drop=True)

        close_ts_arr = df_closes["ts"].to_numpy()
        close_px_arr = df_closes["close"].astype(float).to_numpy()

        for period in [int(p) for p in ema_periods]:
            alpha_daily = alpha_map.get((tf, period))
            if alpha_daily is None:
                effective_days = max(1, tf_days * period)
                alpha_daily = 2.0 / (effective_days + 1.0)

            alpha_bar = 2.0 / (float(period) + 1.0)

            bar_ema_on_closes = _compute_bar_ema_on_closes(
                close_prices=close_px_arr,
                alpha_bar=alpha_bar,
                min_periods=period,
            )

            valid_mask = ~np.isnan(bar_ema_on_closes)
            if not valid_mask.any():
                continue

            first_valid_idx = int(np.argmax(valid_mask))
            first_valid_close_ts = pd.Timestamp(close_ts_arr[first_valid_idx]).tz_convert("UTC")

            canonical_bar_map = {
                pd.Timestamp(t).tz_convert("UTC"): float(v)
                for t, v in zip(close_ts_arr, bar_ema_on_closes)
                if not np.isnan(v)
            }

            df_out = df_id[df_id["ts"] >= first_valid_close_ts].copy()
            if df_out.empty:
                continue

            df_out["id"] = int(id_)
            df_out["tf"] = tf
            df_out["period"] = int(period)
            df_out["tf_days"] = tf_days

            # Roll flags are LABELS ONLY.
            df_out["roll"] = ~df_out["ts"].isin(close_set)
            df_out["roll_bar"] = df_out["roll"]

            # ------------------------------------------------------------------
            # ema_bar: bar-anchored EMA with daily preview and snapping at TF closes
            # - On TF close: snap to canonical bar EMA
            # - Between closes: propagate daily using alpha_daily on price (preview)
            # ------------------------------------------------------------------
            ema_bar_vals: List[float] = []
            ema_bar_prev: Optional[float] = None

            for ts, px in zip(
                df_out["ts"].to_numpy(),
                df_out["close"].astype(float).to_numpy(),
            ):
                ts_u = pd.Timestamp(ts).tz_convert("UTC")
                canon = canonical_bar_map.get(ts_u)

                if canon is not None:
                    ema_bar_today = float(canon)
                else:
                    # daily preview propagation in between closes
                    if ema_bar_prev is None:
                        # df_out starts at the first valid canonical close; fallback safety only
                        ema_bar_today = float(px)
                    else:
                        ema_bar_today = (alpha_daily * float(px)) + (1.0 - alpha_daily) * float(ema_bar_prev)

                ema_bar_vals.append(float(ema_bar_today))
                ema_bar_prev = float(ema_bar_today)

            df_out["ema_bar"] = ema_bar_vals

            # ------------------------------------------------------------------
            # ema: continuous daily EMA, seeded once, never snaps again
            # - Seed at first row to the canonical bar EMA level (df_out starts there)
            # - Thereafter: ALWAYS daily recursion using alpha_daily on price
            # ------------------------------------------------------------------
            ema_vals: List[float] = []
            ema_prev: Optional[float] = None

            for i, (px, eb) in enumerate(
                zip(
                    df_out["close"].astype(float).to_numpy(),
                    df_out["ema_bar"].astype(float).to_numpy(),
                )
            ):
                if ema_prev is None:
                    # one-time seed at the first valid canonical bar EMA point
                    ema_today = float(eb)
                else:
                    ema_today = (alpha_daily * float(px)) + (1.0 - alpha_daily) * float(ema_prev)

                ema_vals.append(float(ema_today))
                ema_prev = float(ema_today)

            df_out["ema"] = ema_vals

            # ------------------------------------------------------------------
            # Derivatives (MATCHES DOC SPEC)
            # ------------------------------------------------------------------

            # DAILY diffs on ema (all rows) -> d1_roll/d2_roll
            df_out["d1_roll"] = df_out["ema"].diff()
            df_out["d2_roll"] = df_out["d1_roll"].diff()

            # Canonical-only diffs on ema -> d1/d2 only on roll=FALSE
            df_out["d1"] = np.nan
            df_out["d2"] = np.nan
            mask_can = df_out["roll"] == False
            if mask_can.any():
                can_df = df_out.loc[mask_can, ["ts", "ema"]].copy()
                can_df["d1"] = can_df["ema"].diff()
                can_df["d2"] = can_df["d1"].diff()
                df_out.loc[mask_can, "d1"] = can_df["d1"].to_numpy()
                df_out.loc[mask_can, "d2"] = can_df["d2"].to_numpy()

            # DAILY diffs on ema_bar (all rows) -> d1_roll_bar/d2_roll_bar
            df_out["d1_roll_bar"] = df_out["ema_bar"].diff()
            df_out["d2_roll_bar"] = df_out["d1_roll_bar"].diff()

            # Canonical-only diffs on ema_bar -> d1_bar/d2_bar only on roll_bar=FALSE
            df_out["d1_bar"] = np.nan
            df_out["d2_bar"] = np.nan
            mask_bar_can = df_out["roll_bar"] == False
            if mask_bar_can.any():
                bar_can = df_out.loc[mask_bar_can, ["ts", "ema_bar"]].copy()
                bar_can["d1_bar"] = bar_can["ema_bar"].diff()
                bar_can["d2_bar"] = bar_can["d1_bar"].diff()
                df_out.loc[mask_bar_can, "d1_bar"] = bar_can["d1_bar"].to_numpy()
                df_out.loc[mask_bar_can, "d2_bar"] = bar_can["d2_bar"].to_numpy()

            out_frames.append(
                df_out[
                    [
                        "id", "tf", "ts", "period", "tf_days",
                        "roll", "ema", "d1", "d2", "d1_roll", "d2_roll",
                        "ema_bar", "d1_bar", "d2_bar", "roll_bar", "d1_roll_bar", "d2_roll_bar",
                    ]
                ]
            )

    if not out_frames:
        return pd.DataFrame()

    out = pd.concat(out_frames, ignore_index=True)
    out["id"] = out["id"].astype(int)
    out["tf"] = out["tf"].astype(str)
    out["ts"] = pd.to_datetime(out["ts"], utc=True)
    out["period"] = out["period"].astype(int)
    out["tf_days"] = out["tf_days"].astype(int)
    out["roll"] = out["roll"].astype(bool)
    out["roll_bar"] = out["roll_bar"].astype(bool)
    return out


# ---------------------------------------------------------------------------
# DB writer
# ---------------------------------------------------------------------------

def write_multi_timeframe_ema_cal_to_db(
    engine_or_db_url,
    ids,
    *,
    scheme: str = "US",
    start=None,
    end=None,
    update_existing: bool = True,
    ema_periods=(6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365),
    schema: str = "public",
    out_table: Optional[str] = None,
    alpha_schema: str = "public",
    alpha_table: str = "ema_alpha_lookup",
) -> int:
    """
    Compute calendar-aligned multi-timeframe EMAs and upsert into:
      cmc_ema_multi_tf_cal_{us|iso}

    Only scheme-specific input is scheme = US|ISO.
    """
    if isinstance(engine_or_db_url, str):
        engine = create_engine(engine_or_db_url, future=True)
    else:
        engine = engine_or_db_url
        if not isinstance(engine, Engine):
            raise TypeError("engine_or_db_url must be a SQLAlchemy Engine or db_url string")

    scheme_u = scheme.strip().upper()
    bars_table = _bars_table_for_scheme(scheme_u)

    if out_table is None:
        out_table = f"cmc_ema_multi_tf_cal_{scheme_u.lower()}"

    tf_specs = _load_calendar_tf_specs(engine, scheme=scheme_u)
    tfs = [s.tf for s in tf_specs]
    tf_days_map = {s.tf: int(s.tf_days) for s in tf_specs}

    alpha_lut = _load_alpha_lookup(engine, alpha_schema, alpha_table)

    where = ["id = ANY(:ids)"]
    params = {"ids": list(map(int, ids))}
    if start is not None:
        where.append('"timestamp" >= :start')
        params["start"] = pd.to_datetime(start, utc=True)
    if end is not None:
        where.append('"timestamp" <= :end')
        params["end"] = pd.to_datetime(end, utc=True)

    daily_sql = text(f"""
      SELECT
        id,
        "timestamp" AS ts,
        close
      FROM public.cmc_price_histories7
      WHERE {" AND ".join(where)}
      ORDER BY id, "timestamp";
    """)
    with engine.connect() as conn:
        df_daily = pd.read_sql(daily_sql, conn, params=params)

    if df_daily.empty:
        return 0

    df_daily["ts"] = pd.to_datetime(df_daily["ts"], utc=True)

    tf_closes = _load_canonical_closes_from_bars(
        engine,
        bars_table=bars_table,
        ids=list(map(int, ids)),
        tfs=tfs,
        start=pd.to_datetime(start, utc=True) if start is not None else None,
        end=pd.to_datetime(end, utc=True) if end is not None else None,
    )
    if tf_closes.empty:
        return 0

    df_out = build_multi_timeframe_ema_cal_frame(
        df_daily,
        tf_closes=tf_closes[["id", "tf", "ts_close"]],
        tf_days_map=tf_days_map,
        ema_periods=ema_periods,
        alpha_lut=alpha_lut,
    )
    if df_out.empty:
        return 0

    # CRITICAL: convert NaN -> None so Postgres stores NULL (COUNT() won't count NaN)
    df_out = df_out.replace({np.nan: None})

    upsert_sql = text(f"""
      INSERT INTO {schema}.{out_table} (
        id, tf, ts, period, tf_days,
        roll, ema, d1, d2, d1_roll, d2_roll,
        ema_bar, d1_bar, d2_bar, roll_bar, d1_roll_bar, d2_roll_bar,
        ingested_at
      )
      VALUES (
        :id, :tf, :ts, :period, :tf_days,
        :roll, :ema, :d1, :d2, :d1_roll, :d2_roll,
        :ema_bar, :d1_bar, :d2_bar, :roll_bar, :d1_roll_bar, :d2_roll_bar,
        now()
      )
      ON CONFLICT (id, tf, ts, period) DO UPDATE SET
        tf_days      = EXCLUDED.tf_days,
        roll         = EXCLUDED.roll,
        ema          = EXCLUDED.ema,
        d1           = EXCLUDED.d1,
        d2           = EXCLUDED.d2,
        d1_roll      = EXCLUDED.d1_roll,
        d2_roll      = EXCLUDED.d2_roll,
        ema_bar      = EXCLUDED.ema_bar,
        d1_bar       = EXCLUDED.d1_bar,
        d2_bar       = EXCLUDED.d2_bar,
        roll_bar     = EXCLUDED.roll_bar,
        d1_roll_bar  = EXCLUDED.d1_roll_bar,
        d2_roll_bar  = EXCLUDED.d2_roll_bar,
        ingested_at  = now();
    """)

    payload = df_out.to_dict(orient="records")
    with engine.begin() as conn:
        conn.execute(upsert_sql, payload)

    return len(df_out)
