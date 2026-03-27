"""
sync_hl_from_vm.py

Incremental sync of Hyperliquid data from Singapore VM to local
hyperliquid.* schema. Uses SSH + psql COPY for fast transfer.

Usage:
    python -m ta_lab2.scripts.etl.sync_hl_from_vm              # incremental
    python -m ta_lab2.scripts.etl.sync_hl_from_vm --full       # full resync
    python -m ta_lab2.scripts.etl.sync_hl_from_vm --dry-run    # report only
    python -m ta_lab2.scripts.etl.sync_hl_from_vm --table candles   # sync one table
    python -m ta_lab2.scripts.etl.sync_hl_from_vm --table funding   # sync one table
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import text

from ta_lab2.io import get_engine

# ── VM connection details ──────────────────────────────────────────
VM_HOST = "161.118.209.59"
VM_USER = "ubuntu"
VM_SSH_KEY = str(
    Path.home() / "Downloads" / "oracle_sg_keys" / "ssh-key-2026-03-10.key"
)
VM_DB = "hyperliquid"
VM_DB_USER = "hluser"
VM_DB_PASS = "hlpass"

# ── Local target ───────────────────────────────────────────────────
SCHEMA = "hyperliquid"
LOCAL_ASSETS = f"{SCHEMA}.hl_assets"
LOCAL_CANDLES = f"{SCHEMA}.hl_candles"
LOCAL_FUNDING = f"{SCHEMA}.hl_funding_rates"
LOCAL_OI = f"{SCHEMA}.hl_open_interest"
LOCAL_OI_SNAP = f"{SCHEMA}.hl_oi_snapshots"
LOCAL_ORDERBOOK = f"{SCHEMA}.hl_orderbook"
LOCAL_OB_METRICS = f"{SCHEMA}.hl_orderbook_metrics"
LOCAL_SYNC_LOG = f"{SCHEMA}.sync_log"


def _ssh_cmd(remote_cmd: str) -> list[str]:
    """Build SSH command list for subprocess."""
    return [
        "ssh",
        "-i",
        VM_SSH_KEY,
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ConnectTimeout=15",
        f"{VM_USER}@{VM_HOST}",
        remote_cmd,
    ]


def _vm_psql(sql: str, timeout: int = 60) -> str:
    """Run a psql command on the VM via SSH. Returns stdout."""
    cmd = _ssh_cmd(
        f'PGPASSWORD={VM_DB_PASS} psql -h 127.0.0.1 -U {VM_DB_USER} -d {VM_DB} -t -A -c "{sql}"'
    )
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"SSH psql failed: {result.stderr}")
    return result.stdout.strip()


def _vm_copy_to_stdout(copy_sql: str, timeout: int = 300) -> str:
    """Run COPY ... TO STDOUT on VM via SSH. Returns CSV data."""
    cmd = _ssh_cmd(
        f"PGPASSWORD={VM_DB_PASS} psql -h 127.0.0.1 -U {VM_DB_USER} -d {VM_DB} "
        f'-c "COPY ({copy_sql}) TO STDOUT WITH CSV"'
    )
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        if not result.stdout.strip():
            return ""
        raise RuntimeError(f"SSH COPY failed: {result.stderr}")
    return result.stdout.strip()


def _upsert_from_csv(
    engine,
    csv_data: str,
    local_table: str,
    conflict_cols: list[str],
    update_cols: list[str] | None = None,
    csv_cols: list[str] | None = None,
) -> int:
    """Load CSV into local table via temp table + upsert. Returns row count.

    Args:
        csv_cols: If set, the CSV maps to these columns only (for tables where
                  local schema has extra columns not present on the VM).
    """
    if not csv_data:
        return 0

    n_rows = len(csv_data.split("\n"))

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        f.write(csv_data)
        tmp_path = f.name

    col_list = f"({', '.join(csv_cols)})" if csv_cols else ""
    select_cols = ", ".join(csv_cols) if csv_cols else "*"

    try:
        raw_conn = engine.raw_connection()
        try:
            cur = raw_conn.cursor()
            cur.execute(f"""
                CREATE TEMP TABLE _hl_staging (LIKE {local_table} INCLUDING DEFAULTS)
                ON COMMIT DROP
            """)
            with open(tmp_path, "r", encoding="utf-8") as f:
                cur.copy_expert(f"COPY _hl_staging {col_list} FROM STDIN WITH CSV", f)

            if csv_cols:
                insert_into = f"INSERT INTO {local_table} ({select_cols})"
                select_from = f"SELECT {select_cols} FROM _hl_staging"
            else:
                insert_into = f"INSERT INTO {local_table}"
                select_from = "SELECT * FROM _hl_staging"

            if update_cols:
                set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
                cur.execute(f"""
                    {insert_into}
                    {select_from}
                    ON CONFLICT ({", ".join(conflict_cols)}) DO UPDATE SET
                        {set_clause}
                """)
            else:
                cur.execute(f"""
                    {insert_into}
                    {select_from}
                    ON CONFLICT ({", ".join(conflict_cols)}) DO NOTHING
                """)

            raw_conn.commit()
        except Exception:
            raw_conn.rollback()
            raise
        finally:
            raw_conn.close()
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return n_rows


# ── Sync: hl_assets (full replace each time — small table) ────────


def sync_assets(engine) -> int:
    """Full sync of asset universe. Always upsert all."""
    print("  Syncing hl_assets...")
    _ASSET_COLS = (
        "asset_id, symbol, sz_decimals, max_leverage, only_isolated, is_delisted, "
        "mark_px, oracle_px, funding, open_interest, premium, day_ntl_vlm, "
        "updated_at, asset_type, base_token, quote_token, api_name, dex"
    )
    csv_data = _vm_copy_to_stdout(f"SELECT {_ASSET_COLS} FROM hl_assets")
    if not csv_data:
        print("    No asset data on VM")
        return 0

    asset_cols = [
        "asset_id",
        "symbol",
        "sz_decimals",
        "max_leverage",
        "only_isolated",
        "is_delisted",
        "mark_px",
        "oracle_px",
        "funding",
        "open_interest",
        "premium",
        "day_ntl_vlm",
        "updated_at",
        "asset_type",
        "base_token",
        "quote_token",
        "api_name",
        "dex",
    ]
    update_cols = asset_cols[1:]  # everything except asset_id
    n = _upsert_from_csv(
        engine, csv_data, LOCAL_ASSETS, ["asset_id"], update_cols, csv_cols=asset_cols
    )
    print(f"    {n:,} assets upserted")
    return n


# ── Sync: hl_candles (incremental by max ts) ─────────────────────


def get_local_candle_watermark(engine) -> str | None:
    """Get global max ts from local candles."""
    sql = text(f"SELECT max(ts)::text FROM {LOCAL_CANDLES}")
    with engine.connect() as conn:
        row = conn.execute(sql).fetchone()
    return row[0] if row and row[0] else None


_CANDLE_COLS = 'asset_id, "interval", ts, open, high, low, close, volume, num_trades, open_oi, close_oi'
_FUNDING_COLS = "asset_id, ts, funding_rate, premium"
_ORDERBOOK_COLS = "asset_id, ts, side, level, price, size"
_OB_METRICS_COLS = (
    "asset_id, ts, mid_price, spread_abs, spread_bps, "
    "bid_depth_pct_01, bid_depth_pct_05, bid_depth_pct_1, bid_depth_pct_2, bid_depth_pct_5, bid_depth_pct_10, "
    "ask_depth_pct_01, ask_depth_pct_05, ask_depth_pct_1, ask_depth_pct_2, ask_depth_pct_5, ask_depth_pct_10, "
    "bid_total_notional, ask_total_notional, "
    "cum_66_bid_level, cum_66_bid_pct, cum_66_ask_level, cum_66_ask_pct, "
    "imbalance_tob, imbalance_1pct, imbalance_5pct"
)


def sync_candles_full(engine) -> int:
    """Full sync of all candles."""
    print("  Full candles sync...")
    csv_data = _vm_copy_to_stdout(
        f"SELECT {_CANDLE_COLS} FROM hl_candles ORDER BY asset_id, interval, ts",
        timeout=600,
    )
    n = _upsert_from_csv(
        engine, csv_data, LOCAL_CANDLES, ["asset_id", "interval", "ts"]
    )
    print(f"    {n:,} candle rows synced")
    return n


def sync_candles_incremental(engine) -> int:
    """Incremental candles: only rows newer than local max ts."""
    max_ts = get_local_candle_watermark(engine)

    if max_ts is None:
        return sync_candles_full(engine)

    print(f"  Incremental candles (ts > '{max_ts}')...")
    csv_data = _vm_copy_to_stdout(
        f"SELECT {_CANDLE_COLS} FROM hl_candles WHERE ts > '{max_ts}' ORDER BY asset_id, interval, ts",
        timeout=300,
    )
    n = _upsert_from_csv(
        engine, csv_data, LOCAL_CANDLES, ["asset_id", "interval", "ts"]
    )
    print(f"    {n:,} candle rows synced")
    return n


# ── Sync: hl_funding_rates (incremental by max ts) ───────────────


def get_local_funding_watermark(engine) -> str | None:
    """Get global max ts from local funding rates."""
    sql = text(f"SELECT max(ts)::text FROM {LOCAL_FUNDING}")
    with engine.connect() as conn:
        row = conn.execute(sql).fetchone()
    return row[0] if row and row[0] else None


def sync_funding_full(engine) -> int:
    """Full sync of all funding rates."""
    print("  Full funding sync...")
    csv_data = _vm_copy_to_stdout(
        f"SELECT {_FUNDING_COLS} FROM hl_funding_rates ORDER BY asset_id, ts",
        timeout=600,
    )
    n = _upsert_from_csv(engine, csv_data, LOCAL_FUNDING, ["asset_id", "ts"])
    print(f"    {n:,} funding rows synced")
    return n


def sync_funding_incremental(engine) -> int:
    """Incremental funding: only rows newer than local max ts."""
    max_ts = get_local_funding_watermark(engine)

    if max_ts is None:
        return sync_funding_full(engine)

    print(f"  Incremental funding (ts > '{max_ts}')...")
    csv_data = _vm_copy_to_stdout(
        f"SELECT {_FUNDING_COLS} FROM hl_funding_rates WHERE ts > '{max_ts}' ORDER BY asset_id, ts",
        timeout=300,
    )
    n = _upsert_from_csv(engine, csv_data, LOCAL_FUNDING, ["asset_id", "ts"])
    print(f"    {n:,} funding rows synced")
    return n


# ── Sync: hl_open_interest (incremental by max ts) ───────────────


def get_local_oi_watermark(engine) -> str | None:
    """Get global max ts from local open interest."""
    sql = text(f"SELECT max(ts)::text FROM {LOCAL_OI}")
    with engine.connect() as conn:
        row = conn.execute(sql).fetchone()
    return row[0] if row and row[0] else None


def sync_oi_full(engine) -> int:
    """Full sync of all open interest."""
    print("  Full open interest sync...")
    csv_data = _vm_copy_to_stdout(
        "SELECT * FROM hl_open_interest ORDER BY asset_id, ts",
        timeout=600,
    )
    n = _upsert_from_csv(
        engine, csv_data, LOCAL_OI, ["asset_id", "ts"], ["open", "high", "low", "close"]
    )
    print(f"    {n:,} OI rows synced")
    return n


def sync_oi_incremental(engine) -> int:
    """Incremental OI: only rows newer than local max ts."""
    max_ts = get_local_oi_watermark(engine)

    if max_ts is None:
        return sync_oi_full(engine)

    print(f"  Incremental OI (ts > '{max_ts}')...")
    csv_data = _vm_copy_to_stdout(
        f"SELECT * FROM hl_open_interest WHERE ts > '{max_ts}' ORDER BY asset_id, ts",
        timeout=300,
    )
    n = _upsert_from_csv(
        engine, csv_data, LOCAL_OI, ["asset_id", "ts"], ["open", "high", "low", "close"]
    )
    print(f"    {n:,} OI rows synced")
    return n


# ── Sync: hl_oi_snapshots (incremental by max ts) ────────────────


def get_local_oi_snap_watermark(engine) -> str | None:
    """Get global max ts from local OI snapshots."""
    sql = text(f"SELECT max(ts)::text FROM {LOCAL_OI_SNAP}")
    with engine.connect() as conn:
        row = conn.execute(sql).fetchone()
    return row[0] if row and row[0] else None


def sync_oi_snap_full(engine) -> int:
    """Full sync of all OI snapshots."""
    print("  Full OI snapshots sync...")
    csv_data = _vm_copy_to_stdout(
        "SELECT * FROM hl_oi_snapshots ORDER BY asset_id, ts",
        timeout=300,
    )
    n = _upsert_from_csv(
        engine,
        csv_data,
        LOCAL_OI_SNAP,
        ["asset_id", "ts"],
        ["open_interest", "mark_px"],
    )
    print(f"    {n:,} OI snapshot rows synced")
    return n


def sync_oi_snap_incremental(engine) -> int:
    """Incremental OI snapshots: only rows newer than local max ts."""
    max_ts = get_local_oi_snap_watermark(engine)

    if max_ts is None:
        return sync_oi_snap_full(engine)

    print(f"  Incremental OI snapshots (ts > '{max_ts}')...")
    csv_data = _vm_copy_to_stdout(
        f"SELECT * FROM hl_oi_snapshots WHERE ts > '{max_ts}' ORDER BY asset_id, ts",
        timeout=300,
    )
    n = _upsert_from_csv(
        engine,
        csv_data,
        LOCAL_OI_SNAP,
        ["asset_id", "ts"],
        ["open_interest", "mark_px"],
    )
    print(f"    {n:,} OI snapshot rows synced")
    return n


# ── Sync: hl_orderbook (incremental by max ts) ───────────────────


def get_local_orderbook_watermark(engine) -> str | None:
    """Get global max ts from local orderbook."""
    sql = text(f"SELECT max(ts)::text FROM {LOCAL_ORDERBOOK}")
    with engine.connect() as conn:
        row = conn.execute(sql).fetchone()
    return row[0] if row and row[0] else None


def sync_orderbook_full(engine) -> int:
    """Full sync of all orderbook rows."""
    print("  Full orderbook sync...")
    csv_data = _vm_copy_to_stdout(
        f"SELECT {_ORDERBOOK_COLS} FROM hl_orderbook ORDER BY asset_id, ts, side, level",
        timeout=900,
    )
    n = _upsert_from_csv(
        engine,
        csv_data,
        LOCAL_ORDERBOOK,
        ["asset_id", "ts", "side", "level"],
        ["price", "size"],
    )
    print(f"    {n:,} orderbook rows synced")
    return n


def sync_orderbook_incremental(engine) -> int:
    """Incremental orderbook: only rows newer than local max ts."""
    max_ts = get_local_orderbook_watermark(engine)

    if max_ts is None:
        return sync_orderbook_full(engine)

    print(f"  Incremental orderbook (ts > '{max_ts}')...")
    csv_data = _vm_copy_to_stdout(
        f"SELECT {_ORDERBOOK_COLS} FROM hl_orderbook WHERE ts > '{max_ts}' ORDER BY asset_id, ts, side, level",
        timeout=600,
    )
    n = _upsert_from_csv(
        engine,
        csv_data,
        LOCAL_ORDERBOOK,
        ["asset_id", "ts", "side", "level"],
        ["price", "size"],
    )
    print(f"    {n:,} orderbook rows synced")
    return n


# ── Sync: hl_orderbook_metrics (incremental by max ts) ──────────


def get_local_ob_metrics_watermark(engine) -> str | None:
    """Get global max ts from local orderbook metrics."""
    sql = text(f"SELECT max(ts)::text FROM {LOCAL_OB_METRICS}")
    with engine.connect() as conn:
        row = conn.execute(sql).fetchone()
    return row[0] if row and row[0] else None


def sync_ob_metrics_full(engine) -> int:
    """Full sync of all orderbook metrics."""
    print("  Full orderbook metrics sync...")
    csv_data = _vm_copy_to_stdout(
        f"SELECT {_OB_METRICS_COLS} FROM hl_orderbook_metrics ORDER BY asset_id, ts",
        timeout=300,
    )
    n = _upsert_from_csv(engine, csv_data, LOCAL_OB_METRICS, ["asset_id", "ts"])
    print(f"    {n:,} orderbook metrics rows synced")
    return n


def sync_ob_metrics_incremental(engine) -> int:
    """Incremental orderbook metrics: only rows newer than local max ts."""
    max_ts = get_local_ob_metrics_watermark(engine)

    if max_ts is None:
        return sync_ob_metrics_full(engine)

    print(f"  Incremental orderbook metrics (ts > '{max_ts}')...")
    csv_data = _vm_copy_to_stdout(
        f"SELECT {_OB_METRICS_COLS} FROM hl_orderbook_metrics WHERE ts > '{max_ts}' ORDER BY asset_id, ts",
        timeout=300,
    )
    n = _upsert_from_csv(engine, csv_data, LOCAL_OB_METRICS, ["asset_id", "ts"])
    print(f"    {n:,} orderbook metrics rows synced")
    return n


# ── Enrich: backfill name / market_type for new assets ───────────

# km symbol → (asset_class, name) — matches seed_hl_assets.py
_KM_NAMES: dict[str, str] = {
    "US500": "S&P 500",
    "USTECH": "Nasdaq 100",
    "JPN225": "Nikkei 225",
    "UK100": "FTSE 100",
    "EU50": "Euro Stoxx 50",
    "HK50": "Hang Seng 50",
    "GER40": "DAX 40",
    "FRA40": "CAC 40",
    "AUS200": "ASX 200",
    "CN50": "FTSE China A50",
    "SG30": "SGX MSCI Singapore",
    "IN50": "Nifty 50",
    "TWN": "Taiwan Weighted",
    "KR100": "KOSPI 200",
    "USOIL": "WTI Crude Oil",
    "UKOIL": "Brent Crude Oil",
    "SILVER": "Silver",
    "GOLD": "Gold",
    "NATGAS": "Natural Gas",
    "COPPER": "Copper",
    "WHEAT": "Wheat",
    "SOYBEAN": "Soybean",
    "EUR": "Euro / USD",
    "GBP": "British Pound / USD",
    "JPY": "USD / Japanese Yen",
    "BRL": "USD / Brazilian Real",
    "INR": "USD / Indian Rupee",
    "AAPL": "Apple",
    "GOOGL": "Alphabet",
    "NVDA": "NVIDIA",
    "MSFT": "Microsoft",
    "AMZN": "Amazon",
    "META": "Meta Platforms",
    "TSLA": "Tesla",
    "BABA": "Alibaba",
    "TSM": "TSMC",
    "MU": "Micron Technology",
    "PLTR": "Palantir",
    "TENCENT": "Tencent",
    "XIAOMI": "Xiaomi",
    "SEMI": "Semiconductor Index",
    "GLDMINE": "Gold Miners Index",
    "USENERGY": "US Energy Index",
    "BMNR": "Bitcoin Miners Index",
    "RTX": "Raytheon Technologies",
    "USBOND": "US Treasury Bond",
    "SMALL2000": "Russell 2000",
}


def enrich_assets(engine) -> int:
    """Backfill name and market_type for any hl_assets rows where they are NULL."""
    updated = 0
    with engine.begin() as conn:
        # 1. market_type: derive from asset_type + asset_id range
        #    perp + id>=20000 → km_perp, perp + id>=10000 → xyz_perp, perp → perp, spot → spot
        r = conn.execute(
            text(f"""
            UPDATE {LOCAL_ASSETS} SET market_type = CASE
                WHEN asset_type = 'perp' AND asset_id >= 20000 THEN 'km_perp'
                WHEN asset_type = 'perp' AND asset_id >= 10000 THEN 'xyz_perp'
                WHEN asset_type = 'perp' THEN 'perp'
                ELSE asset_type
            END
            WHERE market_type IS NULL
        """)
        )
        mt_count = r.rowcount
        if mt_count:
            print(f"    Enriched market_type for {mt_count} assets")
            updated += mt_count

        # 2. name for perps: use CMC name if available, else km map, else symbol
        rows = conn.execute(
            text(f"""
            SELECT a.asset_id, a.symbol
            FROM {LOCAL_ASSETS} a
            WHERE a.name IS NULL AND a.asset_type = 'perp'
        """)
        ).fetchall()

        if rows:
            # Build CMC name lookup
            try:
                cmc_names = dict(
                    conn.execute(
                        text("SELECT symbol, name FROM cmc_da_ids WHERE is_active = 1")
                    ).fetchall()
                )
            except Exception:
                cmc_names = {}

            for asset_id, symbol in rows:
                name = _KM_NAMES.get(symbol) or cmc_names.get(symbol) or symbol
                conn.execute(
                    text(f"""
                    UPDATE {LOCAL_ASSETS} SET name = :name WHERE asset_id = :aid
                """),
                    {"name": name, "aid": asset_id},
                )
                updated += 1

            print(f"    Enriched name for {len(rows)} perp assets")

        # 3. name for spot: use base token part of symbol (e.g. "RIP/USDC" → "RIP")
        r = conn.execute(
            text(f"""
            UPDATE {LOCAL_ASSETS}
            SET name = split_part(symbol, '/', 1)
            WHERE name IS NULL AND asset_type = 'spot'
        """)
        )
        spot_count = r.rowcount
        if spot_count:
            print(f"    Enriched name for {spot_count} spot assets")
            updated += spot_count

    return updated


# ── Verify integrity ──────────────────────────────────────────────


def verify_integrity(engine) -> bool:
    """Compare local vs VM row counts per table."""
    print("\nVerifying integrity...")
    ok = True

    for table, local_table in [
        ("hl_assets", LOCAL_ASSETS),
        ("hl_candles", LOCAL_CANDLES),
        ("hl_funding_rates", LOCAL_FUNDING),
        ("hl_open_interest", LOCAL_OI),
        ("hl_oi_snapshots", LOCAL_OI_SNAP),
        ("hl_orderbook", LOCAL_ORDERBOOK),
        ("hl_orderbook_metrics", LOCAL_OB_METRICS),
    ]:
        vm_count = int(_vm_psql(f"SELECT count(*) FROM {table}"))

        sql = text(f"SELECT count(*) FROM {local_table}")
        with engine.connect() as conn:
            local_count = conn.execute(sql).scalar()

        status = "OK" if local_count >= vm_count else "BEHIND"
        diff = local_count - vm_count
        print(
            f"  {table}: VM={vm_count:,}, local={local_count:,} (diff={diff:+,}) [{status}]"
        )
        if local_count < vm_count:
            ok = False

    return ok


# ── VM stats (for dry-run) ────────────────────────────────────────


def get_vm_stats() -> dict[str, int]:
    """Get row counts from VM."""
    # Single query, all counts
    out = _vm_psql(
        "SELECT 'assets', count(*) FROM hl_assets "
        "UNION ALL SELECT 'candles', count(*) FROM hl_candles "
        "UNION ALL SELECT 'funding', count(*) FROM hl_funding_rates "
        "UNION ALL SELECT 'oi', count(*) FROM hl_open_interest "
        "UNION ALL SELECT 'oi_snap', count(*) FROM hl_oi_snapshots "
        "UNION ALL SELECT 'orderbook', count(*) FROM hl_orderbook "
        "UNION ALL SELECT 'ob_metrics', count(*) FROM hl_orderbook_metrics"
    )
    stats = {}
    for line in out.split("\n"):
        if "|" in line:
            parts = line.split("|")
            stats[parts[0].strip()] = int(parts[1].strip())
    return stats


# ── Sync log ──────────────────────────────────────────────────────


def log_sync(engine, table_name: str, rows_synced: int, status: str, note: str = ""):
    """Write to hyperliquid.sync_log."""
    sql = text(f"""
        INSERT INTO {LOCAL_SYNC_LOG} (table_name, rows_synced, status, note)
        VALUES (:t, :r, :s, :n)
    """)
    with engine.begin() as conn:
        conn.execute(sql, {"t": table_name, "r": rows_synced, "s": status, "n": note})


# ── Main ──────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Sync Hyperliquid data from Singapore VM to local DB"
    )
    parser.add_argument(
        "--full", action="store_true", help="Full resync (not incremental)"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report counts only, don't sync"
    )
    parser.add_argument(
        "--table",
        choices=[
            "assets",
            "candles",
            "funding",
            "oi",
            "oi_snap",
            "orderbook",
            "ob_metrics",
        ],
        help="Sync only one table (default: all)",
    )
    parser.add_argument(
        "--skip-verify", action="store_true", help="Skip integrity verification"
    )
    args = parser.parse_args()

    engine = get_engine()
    mode = "FULL" if args.full else "incremental"
    print(f"[hl-sync] {datetime.now().isoformat()} — {mode} sync")

    if args.dry_run:
        stats = get_vm_stats()
        print(f"  VM assets:  {stats.get('assets', 0):,}")
        print(f"  VM candles: {stats.get('candles', 0):,}")
        print(f"  VM funding: {stats.get('funding', 0):,}")
        print(f"  VM OI:      {stats.get('oi', 0):,}")
        print(f"  VM OI snap: {stats.get('oi_snap', 0):,}")
        print(f"  VM orderbook:  {stats.get('orderbook', 0):,}")
        print(f"  VM ob_metrics: {stats.get('ob_metrics', 0):,}")

        # Local counts
        for table_name, local_table in [
            ("assets", LOCAL_ASSETS),
            ("candles", LOCAL_CANDLES),
            ("funding", LOCAL_FUNDING),
            ("oi", LOCAL_OI),
            ("oi_snap", LOCAL_OI_SNAP),
            ("orderbook", LOCAL_ORDERBOOK),
            ("ob_metrics", LOCAL_OB_METRICS),
        ]:
            try:
                sql = text(f"SELECT count(*) FROM {local_table}")
                with engine.connect() as conn:
                    n = conn.execute(sql).scalar()
                print(f"  Local {table_name}: {n:,}")
            except Exception:
                print(f"  Local {table_name}: (table missing — run alembic upgrade)")
        return

    tables = (
        [args.table]
        if args.table
        else [
            "assets",
            "candles",
            "funding",
            "oi",
            "oi_snap",
            "orderbook",
            "ob_metrics",
        ]
    )
    total = 0

    try:
        # Assets always first (FK dependency)
        if "assets" in tables:
            n = sync_assets(engine)
            log_sync(engine, "hl_assets", n, "ok", mode)
            total += n
            enrich_assets(engine)

        if "candles" in tables:
            n = (
                sync_candles_full(engine)
                if args.full
                else sync_candles_incremental(engine)
            )
            log_sync(engine, "hl_candles", n, "ok", mode)
            total += n

        if "funding" in tables:
            n = (
                sync_funding_full(engine)
                if args.full
                else sync_funding_incremental(engine)
            )
            log_sync(engine, "hl_funding_rates", n, "ok", mode)
            total += n

        if "oi" in tables:
            n = sync_oi_full(engine) if args.full else sync_oi_incremental(engine)
            log_sync(engine, "hl_open_interest", n, "ok", mode)
            total += n

        if "oi_snap" in tables:
            n = (
                sync_oi_snap_full(engine)
                if args.full
                else sync_oi_snap_incremental(engine)
            )
            log_sync(engine, "hl_oi_snapshots", n, "ok", mode)
            total += n

        if "orderbook" in tables:
            n = (
                sync_orderbook_full(engine)
                if args.full
                else sync_orderbook_incremental(engine)
            )
            log_sync(engine, "hl_orderbook", n, "ok", mode)
            total += n

        if "ob_metrics" in tables:
            n = (
                sync_ob_metrics_full(engine)
                if args.full
                else sync_ob_metrics_incremental(engine)
            )
            log_sync(engine, "hl_orderbook_metrics", n, "ok", mode)
            total += n

        # Verify
        if not args.skip_verify:
            verify_integrity(engine)

        print(f"\n[hl-sync] Done. {total:,} total rows synced.")

    except Exception as e:
        print(f"\n[hl-sync] ERROR: {e}", file=sys.stderr)
        try:
            log_sync(engine, "all", 0, "error", str(e)[:500])
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
