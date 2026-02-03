import datetime as dt
from psycopg2.extras import execute_values

def _last_date(conn, sid):
    with conn.cursor() as cur:
        cur.execute("SELECT max(date) FROM fred_series_values WHERE series_id=%s", (sid,))
        return cur.fetchone()[0]

def pull_series(conn, api_key, client, series_list):
    total = 0
    for sid in series_list:
        since = _last_date(conn, sid)
        start = (since + dt.timedelta(days=1)).strftime("%Y-%m-%d") if since else None
        obs = client.get_series_observations(api_key, sid, start)
        rows = []
        for o in obs:
            v = None if o["value"] in (".", "") else float(o["value"])
            rows.append((sid, o["date"], v))
        if rows:
            with conn.cursor() as cur:
                execute_values(cur, """
                    INSERT INTO fred_series_values (series_id, date, value)
                    VALUES %s
                    ON CONFLICT (series_id, date) DO UPDATE SET value = EXCLUDED.value
                """, rows)
            conn.commit()
            total += len(rows)
    return total
