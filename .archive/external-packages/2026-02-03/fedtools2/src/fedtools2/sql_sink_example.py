# sql_sink_example.py
from __future__ import annotations

import os
from typing import Optional, Dict
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import OperationalError
from dotenv import load_dotenv


@dataclass
class ConnInfo:
    """Connection parameters parsed from env/.env."""
    driver: str           # "postgresql+psycopg2" or "sqlite"
    user: str | None = None
    password: str | None = None
    host: str | None = None
    port: str | None = None
    database: str | None = None
    sqlite_path: str | None = None


def _load_conn_info_from_env() -> ConnInfo:
    """
    Load connection settings from db_config.env/.env or OS env vars.
    If any PG* var is present -> Postgres, otherwise fall back to SQLite file.
    """
    # Load env file if present (no error if missing)
    # Prefers db_config.env at repo root; falls back to .env
    for env_file in ("db_config.env", ".env"):
        if os.path.exists(env_file):
            load_dotenv(env_file, override=False)
            break

    pg_user = os.getenv("PGUSER")
    pg_pass = os.getenv("PGPASS")
    pg_host = os.getenv("PGHOST")
    pg_port = os.getenv("PGPORT")
    pg_db   = os.getenv("PGDB")

    if pg_user or pg_pass or pg_host or pg_port or pg_db:
        # Assume Postgres
        return ConnInfo(
            driver="postgresql+psycopg2",
            user=pg_user or "postgres",
            password=pg_pass or "",
            host=pg_host or "localhost",
            port=pg_port or "5432",
            database=pg_db or "feddata",
        )

    # Fallback to SQLite in local ETL folder
    sqlite_path = os.getenv("SQLITE_PATH", "C:/Users/asafi/Downloads/ETL/fedtools2.db")
    return ConnInfo(driver="sqlite", sqlite_path=sqlite_path)


def _conn_info_to_url(ci: ConnInfo) -> URL | str:
    if ci.driver.startswith("postgresql"):
        return URL.create(
            drivername=ci.driver,
            username=ci.user,
            password=ci.password,
            host=ci.host,
            port=int(ci.port) if ci.port else None,
            database=ci.database or "feddata",
        )
    # SQLite
    if ci.sqlite_path and not ci.sqlite_path.startswith("sqlite:///"):
        return f"sqlite:///{ci.sqlite_path}"
    return ci.sqlite_path or "sqlite:///fedtools2.db"


def _ensure_postgres_database(ci: ConnInfo) -> None:
    """
    Connect to admin DB (postgres) and create target database if missing.
    Requires CREATEDB or superuser privileges. No-op for SQLite.
    """
    if not ci.driver.startswith("postgresql"):
        return

    admin_url = URL.create(
        drivername=ci.driver,
        username=ci.user,
        password=ci.password,
        host=ci.host,
        port=int(ci.port) if ci.port else None,
        database="postgres",
    )
    target_db = ci.database or "feddata"

    try:
        admin_engine = create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :dbname"),
                {"dbname": target_db},
            ).scalar() is not None
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{target_db}"'))
                print(f"✅ Created database: {target_db}")
    except OperationalError as e:
        raise RuntimeError(
            "Cannot connect to Postgres admin database to check/create target DB. "
            "Ensure the server is running and the user has CREATEDB privilege."
        ) from e


def _ensure_log_table(engine, log_table: str) -> None:
    """Create an append-only run log table if it doesn't exist."""
    # Generic SQL (SQLite variant)
    create_sql = text(f"""
        CREATE TABLE IF NOT EXISTS {log_table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_ts TEXT,
            row_count INTEGER,
            col_count INTEGER,
            min_date TEXT,
            max_date TEXT,
            output_path TEXT,
            package TEXT,
            version TEXT
        )
    """)

    # Postgres uses SERIAL instead of AUTOINCREMENT
    if engine.url.get_backend_name().startswith("postgresql"):
        create_sql = text(f"""
            CREATE TABLE IF NOT EXISTS {log_table} (
                id SERIAL PRIMARY KEY,
                run_ts TIMESTAMP NULL,
                row_count INTEGER,
                col_count INTEGER,
                min_date TIMESTAMP NULL,
                max_date TIMESTAMP NULL,
                output_path TEXT,
                package TEXT,
                version TEXT
            )
        """)
    with engine.begin() as conn:
        conn.execute(create_sql)


def write_dataframe_and_log(
    df: pd.DataFrame,
    conn_str: str | None,
    base_table: str,
    log_table: str,
    meta: Optional[Dict] = None,
) -> None:
    """
    Write the latest DataFrame snapshot to `base_table` and append a run-log row to `log_table`.

    Behavior:
      * If `conn_str` is None, build from env/.env (PG* vars) or SQLite fallback.
      * For Postgres, auto-create the database if missing.
      * base_table is REPLACED each run (fresh snapshot).
      * log_table is APPEND-only.
    """
    # 1) Build connection
    ci = _load_conn_info_from_env()
    if conn_str:
        url = conn_str
        if conn_str.startswith("postgresql"):
            try:
                url_obj = URL.create(conn_str)
                ci = ConnInfo(
                    driver=url_obj.get_backend_name() + "+psycopg2",
                    user=url_obj.username,
                    password=url_obj.password,
                    host=url_obj.host,
                    port=str(url_obj.port) if url_obj.port else None,
                    database=url_obj.database,
                )
            except Exception:
                pass
    else:
        url = _conn_info_to_url(ci)

    # 2) Ensure DB exists (Postgres only)
    _ensure_postgres_database(ci)

    # 3) Engine
    engine = create_engine(url, future=True)

    # 4) Ensure 'date' is a column for to_sql
    df_out = df.copy()
    if df_out.index.name != "date":
        df_out.index.rename("date", inplace=True)
    df_out.reset_index(inplace=True)

    # 5) Write snapshot & log
    with engine.begin() as conn:
        df_out.to_sql(name=base_table, con=conn, if_exists="replace", index=False)

    _ensure_log_table(engine, log_table)

    meta = meta or {}
    with engine.begin() as conn:
        ins = text(f"""
            INSERT INTO {log_table} (
                run_ts, row_count, col_count, min_date, max_date,
                output_path, package, version
            ) VALUES (
                :run_ts, :row_count, :col_count, :min_date, :max_date,
                :output_path, :package, :version
            )
        """)
        conn.execute(ins, meta)

    print(f"✅ Snapshot written to '{base_table}' and log appended to '{log_table}'.")


if __name__ == "__main__":
    # Minimal smoke test
    df = pd.DataFrame({
        "date": pd.to_datetime(["2025-11-03", "2025-11-04"]),
        "TARGET_MID": [5.25, 5.50],
        "FEDFUNDS": [5.33, 5.33],
    }).set_index("date")
    write_dataframe_and_log(
        df=df,
        conn_str=None,
        base_table="fed_targets_daily",
        log_table="fed_targets_runs",
        meta={
            "run_ts": "2025-11-03T12:34:56",
            "row_count": 2,
            "col_count": 3,
            "min_date": "2025-11-03T00:00:00",
            "max_date": "2025-11-04T00:00:00",
            "output_path": "C:/tmp/FED_Merged.csv",
            "package": "fedtools2",
            "version": "0.1.0",
        },
    )
