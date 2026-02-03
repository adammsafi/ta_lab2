from __future__ import annotations

"""
ema_multi_tf_cal_anchor.py

Compute multi-timeframe EMAs on *anchored calendar bars* (US or ISO),
consuming the pre-built daily-snapshot bar tables:

  - public.cmc_price_bars_multi_tf_cal_anchor_us
  - public.cmc_price_bars_multi_tf_cal_anchor_iso

and writing to:

  - public.cmc_ema_multi_tf_cal_anchor_us
  - public.cmc_ema_multi_tf_cal_anchor_iso

Important semantics (matches your bar-builder scripts)
-----------------------------------------------------
Your *_cal_anchor_* bar tables are **append-only daily snapshots** per (id, tf, bar_seq).

- A bar "exists" on many days while it is forming (same bar_seq, different time_close).
- The column `is_partial_end` is TRUE **until** the scheduled anchored window end-day is reached.
  Therefore:
    * canonical bar-close rows     => is_partial_end = FALSE
    * non-canonical snapshot rows  => is_partial_end = TRUE

This file treats canonical vs roll using `is_partial_end` (preferred),
NOT by inferring roll from whether an EMA value is NaN.

Derivatives (CORRECTED: swapped fields)
---------------------------------------
EMA fields:
- d1_roll, d2_roll  : daily diffs of `ema` on ALL rows (roll TRUE + FALSE)
- d1, d2            : canonical-only diffs computed BETWEEN CANONICAL ROWS
                      (roll FALSE only; NULL elsewhere)

Bar fields:
- d1_bar, d2_bar           : daily diffs of `ema_bar` on ALL rows
- d1_roll_bar, d2_roll_bar : canonical-only diffs BETWEEN CANONICAL ROWS
                             (roll_bar FALSE only; NULL elsewhere)

NaN/NULL handling
-----------------
- We never fill NaN with 0.
- Canonical-only derivative columns are forced to NULL on roll rows (even if 0).
- Before DB write, we convert NaN -> None for float columns so Postgres stores NULL.

Key fix in this version
-----------------------
ema_bar is NOT a sample-and-hold series.

Definition implemented:
- At each anchored close (roll_bar=FALSE) -> ema_bar equals canonical bar EMA.
- Between anchored closes (roll_bar=TRUE) -> ema_bar is carried forward DAILY using
  a daily-equivalent alpha on DAILY close, so it evolves smoothly intra-bar.

This makes ema_bar the "bar-space EMA" that still moves day-to-day for analytics,
while snapping to canonical at anchored closes.
"""

from dataclasses import dataclass
from typing import Iterable, List, Sequence

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text


# =============================================================================
# SQL helpers
# =============================================================================

@dataclass(frozen=True)
class TimeframeSpec:
    tf: str
    tf_days_nominal: int | None
    tf_days_min: int | None
    tf_days_max: int | None


def _engine(db_url: str):
    return create_engine(db_url, future=True)


def _table_has_column(eng, *, schema: str, table: str, column: str) -> bool:
    sql = text(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = :schema
          AND table_name   = :table
          AND column_name  = :col
        LIMIT 1
        """
    )
    with eng.begin() as conn:
        r = conn.execute(sql, {"schema": schema, "table": table, "col": column}).fetchone()
    return r is not None


def _load_timeframes_from_dim_timeframe(
    eng,
    *,
    schema: str,
    dim_timeframe_table: str,
    calendar_scheme: str,
) -> List[TimeframeSpec]:
    """
    Load anchored calendar timeframes from dim_timeframe (no hard-coded TFs).
    """
    sql = text(
        f"""
        SELECT
          tf,
          tf_days_nominal,
          tf_days_min,
          tf_days_max
        FROM {schema}.{dim_timeframe_table}
        WHERE alignment_type  = 'calendar'
          AND roll_policy     = 'calendar_anchor'
          AND has_roll_flag   = TRUE
          AND allow_partial_start = TRUE
          AND allow_partial_end   = TRUE
          AND (
            -- Weeks are scheme-specific: *_CAL_ANCHOR_US or *_CAL_ANCHOR_ISO
            (base_unit = 'W'
             AND calendar_scheme = :scheme
             AND tf LIKE ('%\\_CAL\\_ANCHOR\\_' || :scheme) ESCAPE '\\')
            OR
            -- Months/Years are scheme-agnostic in your dim_timeframe: *_CAL_ANCHOR
            (base_unit IN ('M','Y')
             AND tf LIKE '%\\_CAL\\_ANCHOR' ESCAPE '\\')
          )
        ORDER BY sort_order ASC
        """
    )

    df = pd.read_sql(sql, eng, params={"scheme": calendar_scheme})
    if df.empty:
        raise ValueError(
            f"No anchored calendar timeframes found in {schema}.{dim_timeframe_table} "
            f"for calendar_scheme={calendar_scheme!r}."
        )

    specs: List[TimeframeSpec] = []
    for r in df.itertuples(index=False):
        specs.append(
            TimeframeSpec(
                tf=str(r.tf),
                tf_days_nominal=int(r.tf_days_nominal) if r.tf_days_nominal is not None else None,
                tf_days_min=int(r.tf_days_min) if r.tf_days_min is not None else None,
                tf_days_max=int(r.tf_days_max) if r.tf_days_max is not None else None,
            )
        )
    return specs


def _load_daily_close(
    eng,
    *,
    schema: str,
    daily_table: str,
    ids: Sequence[int],
    start: str,
    end: str | None,
) -> pd.DataFrame:
    """
    Load daily close series (UTC timestamps) for ids in [start, end].
    Expects: id, timeclose, close.
    """
    where_end = "" if end is None else "AND timeclose <= :end_ts"
    sql = text(
        f"""
        SELECT id, timeclose AS ts, close
        FROM {schema}.{daily_table}
        WHERE id = ANY(:ids)
          AND timeclose >= :start_ts
          {where_end}
        ORDER BY id ASC, ts ASC
        """
    )
    params = {"ids": list(ids), "start_ts": start}
    if end is not None:
        params["end_ts"] = end
    df = pd.read_sql(sql, eng, params=params)
    if df.empty:
        raise ValueError(f"No daily rows found in {schema}.{daily_table} for ids={ids}.")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values(["id", "ts"], kind="stable").reset_index(drop=True)
    return df


def _load_anchor_bars(
    eng,
    *,
    schema: str,
    bars_table: str,
    ids: Sequence[int],
    tfs: Sequence[str],
    start: str,
    end: str | None,
) -> pd.DataFrame:
    """
    Load anchored bar snapshot rows for (id, tf).

    Minimum expected columns:
      - id, tf, tf_days, bar_seq, time_close (as ts), close

    Optional:
      - roll (boolean)
      - is_partial_end (boolean)  <-- preferred for canonical-vs-roll inference
      - is_partial_start (boolean)
      - is_missing_days (boolean)
    """
    has_roll_col = _table_has_column(eng, schema=schema, table=bars_table, column="roll")
    has_ipe_col = _table_has_column(eng, schema=schema, table=bars_table, column="is_partial_end")
    has_ips_col = _table_has_column(eng, schema=schema, table=bars_table, column="is_partial_start")
    has_imd_col = _table_has_column(eng, schema=schema, table=bars_table, column="is_missing_days")

    cols = [
        "id",
        "tf",
        "tf_days",
        "bar_seq",
        "time_close AS ts",
        "close",
    ]
    if has_roll_col:
        cols.append("roll")
    if has_ipe_col:
        cols.append("is_partial_end")
    if has_ips_col:
        cols.append("is_partial_start")
    if has_imd_col:
        cols.append("is_missing_days")

    where_end = "" if end is None else "AND time_close <= :end_ts"
    sql = text(
        f"""
        SELECT
          {", ".join(cols)}
        FROM {schema}.{bars_table}
        WHERE id = ANY(:ids)
          AND tf = ANY(:tfs)
          AND time_close >= :start_ts
          {where_end}
        ORDER BY id ASC, tf ASC, bar_seq ASC, ts ASC
        """
    )
    params = {"ids": list(ids), "tfs": list(tfs), "start_ts": start}
    if end is not None:
        params["end_ts"] = end
    df = pd.read_sql(sql, eng, params=params)
    if df.empty:
        raise ValueError(
            f"No bar rows found in {schema}.{bars_table} for ids={ids} and tfs={tfs}."
        )

    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    for c in ["roll", "is_partial_end", "is_partial_start", "is_missing_days"]:
        if c in df.columns:
            df[c] = df[c].astype("boolean")

    df = df.sort_values(["id", "tf", "bar_seq", "ts"], kind="stable").reset_index(drop=True)
    return df


# =============================================================================
# EMA + derivatives
# =============================================================================

def _ema(series: pd.Series, period: int) -> pd.Series:
    """Standard EMA with alpha=2/(period+1), with min_periods=period."""
    alpha = 2.0 / (period + 1.0)
    return series.ewm(alpha=alpha, adjust=False, min_periods=period).mean()


def _alpha_daily_equivalent(tf_days: int, period: int) -> float:
    """
    Convert a "bar-space" EMA alpha to a daily-step alpha using nominal tf_days.

      alpha_daily = 1 - (1 - alpha_bar)^(1/tf_days)
    """
    if tf_days <= 0:
        raise ValueError(f"tf_days must be positive, got {tf_days}.")
    alpha_bar = 2.0 / (period + 1.0)
    return 1.0 - (1.0 - alpha_bar) ** (1.0 / tf_days)


def _canonical_subset_diff(x: pd.Series, is_canonical: pd.Series) -> pd.Series:
    """
    Canonical-only diff computed BETWEEN CANONICAL ROWS (not day-to-day).

    Returns:
      - NaN on non-canonical rows
      - NaN on the first canonical row
      - (x_canon[i] - x_canon[i-1]) on canonical rows i>first
    """
    is_canonical = is_canonical.astype(bool)
    y = pd.Series(np.nan, index=x.index, dtype="float64")

    idx = x.index[is_canonical.values]
    if len(idx) <= 1:
        return y

    xc = x.loc[idx].astype("float64")
    dc = xc.diff()  # canonical-to-canonical
    y.loc[idx] = dc.values
    return y


def _infer_is_canonical_bar_row(b: pd.DataFrame) -> pd.Series:
    """
    Infer which rows in the bar snapshot table represent the *canonical* bar close.

    Priority:
      1) is_partial_end present: canonical is (is_partial_end == FALSE)
      2) roll present:           canonical is (roll == FALSE)
      3) otherwise:              assume every row is canonical
    """
    if "is_partial_end" in b.columns:
        return (b["is_partial_end"].fillna(True) == False)
    if "roll" in b.columns:
        return (b["roll"].fillna(True) == False)
    return pd.Series(True, index=b.index)


def _build_one_id_tf(
    daily: pd.DataFrame,
    bars_tf: pd.DataFrame,
    *,
    tf_days_for_alpha: int,
    period: int,
) -> pd.DataFrame:
    """
    Build full daily-grid output for a single (id, tf, period).

    Key correctness:
    - `roll` is determined by whether the day is a canonical bar-close day,
      NOT by whether an EMA value exists.
    - `ema` is the time-space daily EMA seeded from first canonical day with ema_bar.
    - `ema_bar` is bar-space EMA:
        * at anchored close -> equals canonical bar EMA
        * between closes    -> evolves daily using daily-equivalent alpha on daily close
    """
    df = daily[["ts", "close"]].copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts", kind="stable").reset_index(drop=True)

    b = bars_tf.copy()
    b["ts"] = pd.to_datetime(b["ts"], utc=True)
    b = b.sort_values(["bar_seq", "ts"], kind="stable").reset_index(drop=True)

    # ------------------------------
    # Identify canonical bar closes (dedupe to 1 canonical row per bar_seq)
    # ------------------------------
    is_canon_row = _infer_is_canonical_bar_row(b)
    canon_b = b.loc[is_canon_row.values].copy()

    canon_b = (
        canon_b.sort_values(["bar_seq", "ts"], kind="stable")
        .drop_duplicates(subset=["bar_seq"], keep="last")
        .sort_values(["ts"], kind="stable")
        .reset_index(drop=True)
    )

    canonical_ts = canon_b["ts"].drop_duplicates().sort_values()

    # roll on the daily grid: TRUE if NOT a canonical bar-close timestamp
    is_canonical_day = df["ts"].isin(canonical_ts.to_list())
    roll = (~is_canonical_day).astype(bool)

    # ------------------------------
    # roll_bar: MUST be TRUE on non-canonical days
    # ------------------------------
    if "is_partial_end" in b.columns:
        roll_src = b[["ts", "is_partial_end"]].drop_duplicates(subset=["ts"], keep="last")
        m_roll = df.merge(roll_src, on="ts", how="left")
        roll_bar = m_roll["is_partial_end"].fillna(True).astype(bool)
    elif "roll" in b.columns:
        roll_src = b[["ts", "roll"]].drop_duplicates(subset=["ts"], keep="last")
        m_roll = df.merge(roll_src, on="ts", how="left")
        roll_bar = m_roll["roll"].fillna(True).astype(bool)
    else:
        roll_bar = roll.copy()

    # Guardrail: force canonical_ts days to roll_bar FALSE
    if len(canonical_ts) > 0:
        roll_bar = np.where(df["ts"].isin(canonical_ts.to_list()), False, roll_bar).astype(bool)

    # ------------------------------
    # Canonical (bar-space) EMA at anchored closes
    # ------------------------------
    canon_b["ema_close"] = _ema(canon_b["close"].astype("float64"), period=int(period))
    canon_map = canon_b[["ts", "ema_close"]].drop_duplicates(subset=["ts"])

    m = df.merge(canon_map, on="ts", how="left")

    # ------------------------------
    # ema_bar: bar-space EMA that EVOLVES intra-bar (FIXED)
    # ------------------------------
    alpha_d_bar = _alpha_daily_equivalent(int(tf_days_for_alpha), int(period))
    ema_bar = pd.Series(np.nan, index=m.index, dtype="float64")

    # Seed on first canonical day where canonical ema_close exists
    is_canon_bar_day = (~pd.Series(roll_bar, index=df.index).astype(bool)).to_numpy()
    seed_mask = is_canon_bar_day & (~m["ema_close"].isna().to_numpy())
    seed_pos = np.where(seed_mask)[0]

    closes = m["close"].astype("float64").to_numpy()
    ema_close_arr = m["ema_close"].astype("float64").to_numpy()  # will have nans

    if len(seed_pos) == 0:
        ema_bar[:] = np.nan
    else:
        i0 = int(seed_pos[0])
        ema_bar.iloc[:i0] = np.nan
        # At the first canonical close with a valid canonical EMA, snap to canonical
        ema_bar.iloc[i0] = float(ema_close_arr[i0])

        for i in range(i0 + 1, len(m)):
            prev = float(ema_bar.iloc[i - 1])
            x = float(closes[i])

            # Evolve daily using daily-equivalent alpha
            v = alpha_d_bar * x + (1.0 - alpha_d_bar) * prev

            # Snap on anchored close days when canonical ema_close exists
            if is_canon_bar_day[i] and not np.isnan(ema_close_arr[i]):
                v = float(ema_close_arr[i])

            ema_bar.iloc[i] = v

    # ------------------------------
    # Preview EMA (time-space daily updated) seeded from ema_bar on first roll=FALSE
    # ------------------------------
    alpha_d = _alpha_daily_equivalent(int(tf_days_for_alpha), int(period))
    ema = pd.Series(np.nan, index=m.index, dtype="float64")

    seed_mask_time = (~roll.values) & (~ema_bar.isna().to_numpy())
    seed_pos_time = np.where(seed_mask_time)[0]
    if len(seed_pos_time) == 0:
        ema[:] = np.nan
    else:
        j0 = int(seed_pos_time[0])
        ema.iloc[:j0] = np.nan
        ema.iloc[j0] = float(ema_bar.iloc[j0])

        for i in range(j0 + 1, len(m)):
            prev = float(ema.iloc[i - 1])
            x = float(closes[i])
            ema.iloc[i] = alpha_d * x + (1.0 - alpha_d) * prev

    out = pd.DataFrame(
        {
            "ts": df["ts"],
            "roll": roll.astype(bool),
            "ema": ema.astype("float64"),
            "ema_bar": ema_bar.astype("float64"),
            "roll_bar": pd.Series(roll_bar, index=df.index).astype(bool),
        }
    )

    # ------------------------------
    # Derivatives (CORRECTED: swap fields)
    # ------------------------------
    # Daily diffs
    ema_d1_daily = out["ema"].diff()
    ema_d2_daily = ema_d1_daily.diff()

    bar_d1_daily = out["ema_bar"].diff()
    bar_d2_daily = bar_d1_daily.diff()

    # Canonical-only diffs (between canonical rows)
    is_canon = ~out["roll"]
    ema_d1_canon = _canonical_subset_diff(out["ema"], is_canon)
    ema_d2_canon = _canonical_subset_diff(ema_d1_canon, is_canon)

    is_canon_bar = ~out["roll_bar"]
    bar_d1_canon = _canonical_subset_diff(out["ema_bar"], is_canon_bar)
    bar_d2_canon = _canonical_subset_diff(bar_d1_canon, is_canon_bar)

    # WRITE WITH SWAPPED NAMES
    # EMA:
    out["d1_roll"] = ema_d1_daily
    out["d2_roll"] = ema_d2_daily
    out["d1"] = ema_d1_canon
    out["d2"] = ema_d2_canon

    # BAR:
    out["d1_bar"] = bar_d1_daily
    out["d2_bar"] = bar_d2_daily
    out["d1_roll_bar"] = bar_d1_canon
    out["d2_roll_bar"] = bar_d2_canon

    # ------------------------------
    # NULL enforcement (keep semantics tight)
    # ------------------------------
    # Canonical-only EMA diffs must be NULL on roll days
    out.loc[out["roll"].astype(bool), ["d1", "d2"]] = np.nan

    # Canonical-only BAR diffs must be NULL on roll_bar days
    out.loc[out["roll_bar"].astype(bool), ["d1_roll_bar", "d2_roll_bar"]] = np.nan

    # Safety: if underlying series is NULL, diffs must be NULL
    out.loc[out["ema"].isna(), ["d1_roll", "d2_roll"]] = np.nan
    out.loc[out["ema_bar"].isna(), ["d1_bar", "d2_bar", "d1_roll_bar", "d2_roll_bar"]] = np.nan

    # ------------------------------
    # Trim: drop rows before the first ema_bar exists
    # ------------------------------
    first_valid = out["ema_bar"].first_valid_index()
    if first_valid is None:
        return out.iloc[0:0].copy()

    out = out.loc[first_valid:].reset_index(drop=True)
    return out


# =============================================================================
# Public API
# =============================================================================

def write_multi_timeframe_ema_cal_anchor_to_db(
    ids: Iterable[int],
    *,
    calendar_scheme: str,
    start: str = "2010-01-01",
    end: str | None = None,
    ema_periods: Iterable[int] = (6, 9, 10, 12, 14, 17, 20, 21, 26, 30, 50, 52, 77, 100, 200, 252, 365),
    db_url: str | None = None,
    schema: str = "public",
    dim_timeframe_table: str = "dim_timeframe",
    daily_table: str = "cmc_price_histories7",
    bars_table: str | None = None,
    out_table: str | None = None,
    update_existing: bool = True,
    verbose: bool = True,
) -> int:
    """
    Compute anchored calendar EMAs (US or ISO) by consuming the pre-built
    anchor bars snapshot table.

    Defaults:
      bars_table = cmc_price_bars_multi_tf_cal_anchor_{us|iso}
      out_table  = cmc_ema_multi_tf_cal_anchor_{us|iso}

    Output table must have a UNIQUE/PK on (id, tf, ts, period).
    """
    if db_url is None:
        raise ValueError("db_url is required (pass TARGET_DB_URL from env in the runner).")

    scheme = calendar_scheme.upper()
    if scheme not in {"US", "ISO"}:
        raise ValueError(f"calendar_scheme must be 'US' or 'ISO', got {calendar_scheme!r}.")

    if bars_table is None:
        bars_table = f"cmc_price_bars_multi_tf_cal_anchor_{scheme.lower()}"
    if out_table is None:
        out_table = f"cmc_ema_multi_tf_cal_anchor_{scheme.lower()}"

    ids_list = list(ids)
    if not ids_list:
        return 0

    eng = _engine(db_url)

    tf_specs = _load_timeframes_from_dim_timeframe(
        eng,
        schema=schema,
        dim_timeframe_table=dim_timeframe_table,
        calendar_scheme=scheme,
    )
    tfs = [s.tf for s in tf_specs]

    daily = _load_daily_close(
        eng,
        schema=schema,
        daily_table=daily_table,
        ids=ids_list,
        start=start,
        end=end,
    )

    bars = _load_anchor_bars(
        eng,
        schema=schema,
        bars_table=bars_table,
        ids=ids_list,
        tfs=tfs,
        start=start,
        end=end,
    )

    upsert_sql = text(
        f"""
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
          ingested_at  = now()
        """
    )

    total_written = 0

    with eng.begin() as conn:
        if not update_existing:
            where_end = "" if end is None else "AND ts <= :end_ts"
            del_sql = text(
                f"""
                DELETE FROM {schema}.{out_table}
                WHERE id = ANY(:ids)
                  AND ts >= :start_ts
                  {where_end}
                """
            )
            params = {"ids": ids_list, "start_ts": start}
            if end is not None:
                params["end_ts"] = end
            conn.execute(del_sql, params)

        for id_ in ids_list:
            daily_i = daily[daily["id"] == id_].copy()
            if daily_i.empty:
                continue

            bars_i = bars[bars["id"] == id_].copy()
            if bars_i.empty:
                continue

            for spec in tf_specs:
                tf = spec.tf

                tf_days = spec.tf_days_nominal or spec.tf_days_max
                if tf_days is None:
                    b_tf_any = bars_i[bars_i["tf"] == tf]
                    tf_days = int(b_tf_any["tf_days"].iloc[0]) if not b_tf_any.empty else None
                if tf_days is None:
                    raise ValueError(f"Could not determine tf_days for tf={tf!r} (scheme={scheme}).")

                bars_tf = bars_i[bars_i["tf"] == tf].copy()
                if bars_tf.empty:
                    continue

                for period in ema_periods:
                    out = _build_one_id_tf(
                        daily_i,
                        bars_tf,
                        tf_days_for_alpha=int(tf_days),
                        period=int(period),
                    )

                    if out.empty:
                        continue

                    out.insert(0, "id", id_)
                    out.insert(1, "tf", tf)
                    out.insert(3, "period", int(period))
                    out.insert(4, "tf_days", int(tf_days))

                    out["ts"] = pd.to_datetime(out["ts"], utc=True)

                    float_cols = [
                        "ema", "d1", "d2", "d1_roll", "d2_roll",
                        "ema_bar", "d1_bar", "d2_bar", "d1_roll_bar", "d2_roll_bar",
                    ]
                    for c in float_cols:
                        out[c] = pd.to_numeric(out[c], errors="coerce")

                    # Critical: convert NaN -> None (SQL NULL) for insert/upsert
                    out = out.replace({np.nan: None})

                    records = out.to_dict(orient="records")
                    if not records:
                        continue

                    conn.execute(upsert_sql, records)
                    total_written += len(records)

            if verbose:
                print(f"[ema_anchor_{scheme.lower()}] id={id_} total_written={total_written}")

    return total_written
