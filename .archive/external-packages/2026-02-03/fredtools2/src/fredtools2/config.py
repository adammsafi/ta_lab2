import os
from dataclasses import dataclass

@dataclass
class PGConfig:
    host: str
    port: int
    user: str
    password: str
    dbname: str

def pg_from_env() -> PGConfig:
    return PGConfig(
        host=os.getenv("PGHOST", "127.0.0.1"),
        port=int(os.getenv("PGPORT", "5432")),
        user=os.getenv("PGUSER", "postgres"),
        password=os.getenv("PGPASSWORD", ""),
        dbname=os.getenv("PGDATABASE", "freddata"),
    )

def fred_api_key() -> str:
    key = os.getenv("FRED_API_KEY")
    if not key:
        raise RuntimeError("FRED_API_KEY is not set")
    return key
