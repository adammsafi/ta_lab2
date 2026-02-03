from psycopg2.extras import execute_values


def pull_releases(conn, api_key, client):
    rels = client.get_releases(api_key)
    rows = []
    for rel in rels:
        rows.append(
            (
                int(rel.get("id")),
                rel.get("name") or "",
                bool(rel.get("press_release", False)),
                rel.get("link") or "",
                rel.get("realtime_start") or None,
                rel.get("realtime_end") or None,
            )
        )

    changed = 0
    if rows:
        with conn.cursor() as cur:
            execute_values(
                cur,
                """
                INSERT INTO releases (release_id, name, press_release, link, realtime_start, realtime_end, updated_at)
                VALUES %s
                ON CONFLICT (release_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    press_release = EXCLUDED.press_release,
                    link = EXCLUDED.link,
                    realtime_start = EXCLUDED.realtime_start,
                    realtime_end   = EXCLUDED.realtime_end,
                    updated_at = now()
                WHERE (releases.name, releases.press_release, releases.link, releases.realtime_start, releases.realtime_end)
                      IS DISTINCT FROM
                      (EXCLUDED.name, EXCLUDED.press_release, EXCLUDED.link, EXCLUDED.realtime_start, EXCLUDED.realtime_end)
                RETURNING 1
            """,
                rows,
            )
            changed = len(cur.fetchall())
        conn.commit()
    return changed
