import psycopg2
from contextlib import contextmanager
from .config import PGConfig, pg_from_env

def connect(cfg: PGConfig = None):
    cfg = cfg or pg_from_env()
    return psycopg2.connect(
        host=cfg.host, port=cfg.port, user=cfg.user, password=cfg.password, dbname=cfg.dbname
    )

def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(open(__package__.replace(".", "/") + "/sql/schema.sql").read())
    conn.commit()

def log_run(conn, job: str, rows_upserted: int, status: str = "ok", note: str = ""):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO pull_log (job, status, rows_upserted, note) VALUES (%s, %s, %s, %s)",
            (job, status, rows_upserted, note),
        )
    conn.commit()
