import os, sys
from dotenv import load_dotenv
from .config import fred_api_key
from .db import connect, ensure_schema, log_run
from . import fred_api as client
from .jobs.releases import pull_releases
from .jobs.series import pull_series

def main(argv=None):
    argv = argv or sys.argv[1:]
    if not argv or argv[0] not in {"releases","series","init"}:
        print("Usage: fred [init|releases|series] [series_csv_for_series_job]", file=sys.stderr)
        sys.exit(2)

    load_dotenv()

    job = argv[0]
    conn = connect()
    try:
        if job == "init":
            ensure_schema(conn)
            print("schema ensured")
            return

        api = fred_api_key()
        if job == "releases":
            n = pull_releases(conn, api, client)
        else:
            series_csv = argv[1] if len(argv) > 1 else os.getenv("FRED_SERIES", "FEDFUNDS,DFEDTARU,DFEDTARL")
            series_list = [s.strip() for s in series_csv.split(",") if s.strip()]
            n = pull_series(conn, api, client, series_list)

        log_run(conn, job, n, "ok", "")
        print(f"{job} upserted {n} changed rows")
    except Exception as e:
        log_run(conn, job, 0, "error", str(e))
        raise
    finally:
        conn.close()
