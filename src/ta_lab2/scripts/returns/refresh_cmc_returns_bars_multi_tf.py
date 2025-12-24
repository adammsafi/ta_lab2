from __future__ import annotations

r"""
refresh_cmc_returns_bars_multi_tf.py

Incremental bar returns builder from a bars table (default: public.cmc_price_bars_multi_tf).

Writes:
  public.cmc_returns_bars_multi_tf

State:
  public.cmc_returns_bars_multi_tf_state  (watermark per (id, tf): last_bar_seq)

Semantics:
  - Returns are computed close-to-close on bar snapshots using bar_seq ordering.
  - Computes both arithmetic and log returns.
  - Adds gap_bars = bar_seq - prev_bar_seq (normally 1).
  - Incremental by default:
      for each (id, tf), only inserts rows where bar_seq > last_bar_seq
      but pulls bar_seq >= last_bar_seq to seed prev_close for the first new row.
  - History recomputed only with --full-refresh.

Expected bars schema (minimum):
  - id (int)
  - tf (text)
  - bar_seq (int)
  - time_close (timestamptz)
  - close (float)

runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_cmc_returns_bars_multi_tf.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--ids 1 --tfs 1D,2D,3D,1W_ISO"
)

runfile(
  r"C:\Users\asafi\Downloads\ta_lab2\src\ta_lab2\scripts\returns\refresh_cmc_returns_bars_multi_tf.py",
  wdir=r"C:\Users\asafi\Downloads\ta_lab2",
  args="--ids all --tfs all"
)  
  
"""

import argparse
import os
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


DEFAULT_BARS_TABLE = "public.cmc_price_bars_multi_tf"
DEFAULT_OUT_TABLE = "public.cmc_returns_bars_multi_tf"
DEFAULT_STATE_TABLE = "public.cmc_returns_bars_multi_tf_state"


@dataclass(frozen=True)
class RunnerConfig:
    db_url: str
    ids: Optional[List[int]]          # None means ALL
    tfs: Optional[List[str]]          # None means ALL
    bars_table: str
    out_table: str
    state_table: str
    full_refresh: bool


def _print(msg: str) -> None:
    print(f"[ret_bars_multi_tf] {msg}")


def _get_engine(db_url: str) -> Engine:
    return create_engine(db_url, future=True)


def _load_all_ids(engine: Engine, bars_table: str) -> List[int]:
    sql = text(f"SELECT DISTINCT id FROM {bars_table} ORDER BY id;")
    with engine.begin() as cxn:
        rows = cxn.execute(sql).fetchall()
    return [int(r[0]) for r in rows]


def _load_all_tfs(engine: Engine, bars_table: str) -> List[str]:
    sql = text(f"SELECT DISTINCT tf FROM {bars_table} ORDER BY tf;")
    with engine.begin() as cxn:
        rows = cxn.execute(sql).fetchall()
    return [str(r[0]) for r in rows]


def _load_pairs(engine: Engine, bars_table: str, ids: List[int], tfs: List[str]) -> List[Tuple[int, str]]:
    sql = text(
        f"""
        SELECT DISTINCT id, tf
        FROM {bars_table}
        WHERE id = ANY(:ids) AND tf = ANY(:tfs)
        ORDER BY id, tf;
        """
    )
    with engine.begin() as cxn:
        rows = cxn.execute(sql, {"ids": ids, "tfs": tfs}).fetchall()
    return [(int(r[0]), str(r[1])) for r in rows]


def _ensure_state_rows(engine: Engine, state_table: str, pairs: Iterable[Tuple[int, str]]) -> None:
    pairs = [(int(i), str(tf)) for (i, tf) in pairs]
    if not pairs:
        return

    ids = [p[0] for p in pairs]
    tfs = [p[1] for p in pairs]

    # Use a join between two unnests to materialize candidate keys;
    # then filter to the exact pairs via EXISTS against a VALUES list built safely.
    # Easiest + safe approach: insert per pair in executemany.
    sql = text(
        f"""
        INSERT INTO {state_table} (id, tf, last_bar_seq)
        VALUES (:id, :tf, NULL)
        ON CONFLICT (id, tf) DO NOTHING;
        """
    )

    with engine.begin() as cxn:
        cxn.execute(sql, [{"id": i, "tf": tf} for (i, tf) in pairs])


def _full_refresh(engine: Engine, out_table: str, state_table: str, pairs: List[Tuple[int, str]]) -> None:
    if not pairs:
        return

    _print(f"--full-refresh: deleting existing rows for {len(pairs)} (id,tf) keys and resetting state.")

    sql_del_out = text(
        f"""
        DELETE FROM {out_table}
        WHERE (id, tf) IN (SELECT * FROM UNNEST(:ids::int[], :tfs::text[]));
        """
    )
    sql_del_state = text(
        f"""
        DELETE FROM {state_table}
        WHERE (id, tf) IN (SELECT * FROM UNNEST(:ids::int[], :tfs::text[]));
        """
    )
    ids = [p[0] for p in pairs]
    tfs = [p[1] for p in pairs]

    with engine.begin() as cxn:
        cxn.execute(sql_del_out, {"ids": ids, "tfs": tfs})
        cxn.execute(sql_del_state, {"ids": ids, "tfs": tfs})

    _ensure_state_rows(engine, state_table, pairs)


def _run_one_pair(engine: Engine, cfg: RunnerConfig, one_id: int, one_tf: str) -> None:
    sql = text(
        f"""
        WITH st AS (
            SELECT last_bar_seq
            FROM {cfg.state_table}
            WHERE id = :id AND tf = :tf
        ),
        src AS (
            SELECT
                b.id,
                b.tf,
                b.bar_seq,
                b.time_close,
                b.close
            FROM {cfg.bars_table} b
            CROSS JOIN st
            WHERE b.id = :id
              AND b.tf = :tf
              AND b.bar_seq >= COALESCE(st.last_bar_seq, 1)
        ),
        calc AS (
            SELECT
                id,
                tf,
                bar_seq,
                time_close,
                close,
                LAG(close) OVER (PARTITION BY id, tf ORDER BY bar_seq) AS prev_close,
                LAG(bar_seq) OVER (PARTITION BY id, tf ORDER BY bar_seq) AS prev_bar_seq
            FROM src
        ),
        to_insert AS (
            SELECT
                c.id,
                c.tf,
                c.bar_seq,
                c.time_close,
                c.close,
                c.prev_close,
                CASE
                    WHEN c.prev_bar_seq IS NULL THEN NULL
                    ELSE (c.bar_seq - c.prev_bar_seq)
                END AS gap_bars,
                CASE
                    WHEN c.prev_close IS NULL OR c.close IS NULL OR c.prev_close = 0 THEN NULL
                    ELSE (c.close / c.prev_close) - 1
                END AS ret_arith,
                CASE
                    WHEN c.prev_close IS NULL OR c.close IS NULL OR c.prev_close <= 0 OR c.close <= 0 THEN NULL
                    ELSE LN(c.close / c.prev_close)
                END AS ret_log
            FROM calc c
            CROSS JOIN st
            WHERE
                ((st.last_bar_seq IS NULL) OR (c.bar_seq > st.last_bar_seq))
                AND c.prev_close IS NOT NULL
        ),
        ins AS (
            INSERT INTO {cfg.out_table} (
                id, tf, bar_seq, time_close, close, prev_close, gap_bars, ret_arith, ret_log, ingested_at
            )
            SELECT
                id, tf, bar_seq, time_close, close, prev_close, gap_bars, ret_arith, ret_log, now()
            FROM to_insert
            ON CONFLICT (id, tf, bar_seq) DO NOTHING
            RETURNING bar_seq
        )
        UPDATE {cfg.state_table} s
        SET
            last_bar_seq = COALESCE((SELECT MAX(bar_seq) FROM ins), s.last_bar_seq),
            updated_at = now()
        WHERE s.id = :id AND s.tf = :tf;
        """
    )

    with engine.begin() as cxn:
        cxn.execute(sql, {"id": one_id, "tf": one_tf})


def main() -> None:
    p = argparse.ArgumentParser(description="Incremental bar returns builder (arith + log) from bar snapshots.")
    p.add_argument("--db-url", default=os.getenv("TARGET_DB_URL", ""), help="Postgres DB URL (or set TARGET_DB_URL).")

    p.add_argument("--ids", default="all", help="Comma-separated ids, or 'all'.")
    p.add_argument("--tfs", default="all", help="Comma-separated tfs, or 'all'.")

    p.add_argument("--bars-table", default=DEFAULT_BARS_TABLE, help="Source bars table.")
    p.add_argument("--out-table", default=DEFAULT_OUT_TABLE, help="Output returns table.")
    p.add_argument("--state-table", default=DEFAULT_STATE_TABLE, help="State table.")

    p.add_argument("--full-refresh", action="store_true", help="Recompute history for selected keys.")
    args = p.parse_args()

    db_url = args.db_url.strip()
    if not db_url:
        raise SystemExit("ERROR: Missing DB URL. Provide --db-url or set TARGET_DB_URL.")

    cfg = RunnerConfig(
        db_url=db_url,
        ids=None,
        tfs=None,
        bars_table=args.bars_table,
        out_table=args.out_table,
        state_table=args.state_table,
        full_refresh=bool(args.full_refresh),
    )

    _print("Using DB URL from TARGET_DB_URL env." if os.getenv("TARGET_DB_URL") else "Using DB URL from --db-url.")
    _print(
        f"Runner config: ids={args.ids}, tfs={args.tfs}, bars={cfg.bars_table}, out={cfg.out_table}, state={cfg.state_table}, full_refresh={cfg.full_refresh}"
    )

    engine = _get_engine(cfg.db_url)

    if args.ids.strip().lower() == "all":
        ids = _load_all_ids(engine, cfg.bars_table)
        _print(f"Loaded ALL ids from {cfg.bars_table}: {len(ids)}")
    else:
        ids = [int(x.strip()) for x in args.ids.split(",") if x.strip()]
        _print(f"Loaded ids from args: {ids}")

    if args.tfs.strip().lower() == "all":
        tfs = _load_all_tfs(engine, cfg.bars_table)
        _print(f"Loaded ALL tfs from {cfg.bars_table}: {len(tfs)}")
    else:
        tfs = [x.strip() for x in args.tfs.split(",") if x.strip()]
        _print(f"Loaded tfs from args: {tfs}")

    if not ids or not tfs:
        _print("No ids/tfs to process. Exiting.")
        return

    pairs = _load_pairs(engine, cfg.bars_table, ids, tfs)
    _print(f"Resolved (id,tf) pairs from bars table: {len(pairs)}")
    if not pairs:
        _print("No (id,tf) pairs found. Exiting.")
        return

    _ensure_state_rows(engine, cfg.state_table, pairs)

    if cfg.full_refresh:
        _full_refresh(engine, cfg.out_table, cfg.state_table, pairs)

    for i, (one_id, one_tf) in enumerate(pairs, start=1):
        _print(f"Processing (id,tf)=({one_id},{one_tf}) ({i}/{len(pairs)})")
        _run_one_pair(engine, cfg, one_id, one_tf)

    _print("Done.")


if __name__ == "__main__":
    main()
