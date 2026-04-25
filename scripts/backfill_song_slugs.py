"""One-shot: refetch the songs.json feed and write slugs into the songs
table. Existing rows keep their song_id / name; the upsert's ON CONFLICT
clause overwrites slug to whatever phish.net currently has.

Run from `api/` so Settings picks up .env:
    cd api && uv run python ../scripts/backfill_song_slugs.py

On the NAS, exec inside the api container so the in-volume DB is picked up:
    docker compose -f /home/Murphy52/docker/apps/phishpicker/docker-compose.yml \\
        exec -T api python /app/scripts/backfill_song_slugs.py
(the scripts dir is mounted into /app via the api build context).
"""

from phishpicker.config import Settings
from phishpicker.db.connection import apply_schema, open_db
from phishpicker.ingest.songs import upsert_songs
from phishpicker.phishnet.client import PhishNetClient


def main() -> None:
    settings = Settings()  # type: ignore[call-arg]
    with PhishNetClient(api_key=settings.phishnet_api_key) as client:
        rows = client.fetch_songs()
    print(f"fetched {len(rows)} songs from phish.net")
    with_slug = sum(1 for r in rows if r.get("slug"))
    print(f"  of those, {with_slug} have slug populated")

    with open_db(settings.db_path) as conn:
        # Ensure the slug column exists on already-deployed DBs that pre-date
        # the schema change. apply_schema is idempotent.
        apply_schema(conn)
        before = conn.execute(
            "SELECT COUNT(*) FROM songs WHERE slug IS NOT NULL"
        ).fetchone()[0]
        n = upsert_songs(conn, rows)
        after = conn.execute(
            "SELECT COUNT(*) FROM songs WHERE slug IS NOT NULL"
        ).fetchone()[0]
    print(f"upserted {n} rows; songs.slug populated {before} -> {after}")


if __name__ == "__main__":
    main()
