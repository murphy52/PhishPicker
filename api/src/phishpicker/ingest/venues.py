import sqlite3


def upsert_venues(conn: sqlite3.Connection, rows: list[dict]) -> int:
    count = 0
    for r in rows:
        conn.execute(
            """
            INSERT INTO venues (venue_id, name, city, state, country)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(venue_id) DO UPDATE SET
                name = excluded.name,
                city = excluded.city,
                state = excluded.state,
                country = excluded.country
            """,
            (r["venueid"], r["venuename"], r.get("city"), r.get("state"), r.get("country")),
        )
        count += 1
    conn.commit()
    return count
