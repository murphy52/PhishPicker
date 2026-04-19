"""Phish studio-album metadata lookup.

phish.net has no /albums endpoint, so we ship a hand-curated JSON fixture
of the ~15 studio albums through Evolve (2024). This module:

- Loads the fixture lazily.
- Maps song_name → (album_name, album_release_date).
- Given a show_date, finds the latest album released strictly before that
  date (i.e., "the current album era" at the time of the show).

We match albums to songs by exact name. phish.net occasionally renames
songs; the fixture tries to use phish.net canonical spellings but a few
will miss the lookup. Misses default to `is_from_latest_album=0` and
`days_since_last_new_album=MISSING`, which is consistent with the song
having no album entry.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

_FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "phish_albums.json"


@dataclass(frozen=True)
class Album:
    album_id: int
    name: str
    release_date: str  # YYYY-MM-DD


@lru_cache(maxsize=1)
def _load_fixture() -> tuple[list[Album], dict[str, Album]]:
    """Return (all_albums_sorted_by_release_date, {track_name: album})."""
    data = json.loads(_FIXTURE_PATH.read_text())
    albums: list[Album] = []
    track_to_album: dict[str, Album] = {}
    for entry in data.get("albums", []):
        if not entry.get("is_studio", True):
            continue
        alb = Album(
            album_id=int(entry["album_id"]),
            name=entry["name"],
            release_date=entry["release_date"],
        )
        albums.append(alb)
        for track in entry.get("tracks", []):
            # If a song appears on multiple albums (e.g., re-released), keep
            # the FIRST one encountered — earliest album is canonical for
            # "where did this song originally come from."
            track_to_album.setdefault(track, alb)
    albums.sort(key=lambda a: a.release_date)
    return albums, track_to_album


def latest_album_as_of(show_date: str) -> Album | None:
    """Most recently released studio album strictly before `show_date`."""
    albums, _ = _load_fixture()
    for alb in reversed(albums):
        if alb.release_date < show_date:
            return alb
    return None


def song_album_map(conn: sqlite3.Connection, song_ids: list[int]) -> dict[int, Album]:
    """{song_id: Album} for the subset of song_ids we can match by name."""
    if not song_ids:
        return {}
    _, track_to_album = _load_fixture()
    placeholders = ",".join("?" * len(song_ids))
    rows = conn.execute(
        f"SELECT song_id, name FROM songs WHERE song_id IN ({placeholders})",
        song_ids,
    ).fetchall()
    out: dict[int, Album] = {}
    for r in rows:
        alb = track_to_album.get(r["name"])
        if alb:
            out[r["song_id"]] = alb
    return out


def days_between(a: str, b: str) -> int:
    """Days from ISO-date `a` to ISO-date `b` (can be negative)."""
    return (date.fromisoformat(b) - date.fromisoformat(a)).days
