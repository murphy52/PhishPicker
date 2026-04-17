import Fuse from "fuse.js";

export type Song = { song_id: number; name: string; original_artist?: string | null };

let _lastSongs: Song[] | null = null;
let _lastFuse: Fuse<Song> | null = null;

function getFuse(songs: Song[]): Fuse<Song> {
  if (songs !== _lastSongs) {
    _lastFuse = new Fuse(songs, {
      keys: ["name"],
      threshold: 0.4,
      ignoreLocation: true,
    });
    _lastSongs = songs;
  }
  return _lastFuse!;
}

export function searchSongs(songs: Song[], query: string, limit = 10): Song[] {
  if (!query.trim()) return songs.slice(0, limit);
  return getFuse(songs)
    .search(query)
    .slice(0, limit)
    .map((r) => r.item);
}

const KEY_PREFIX = "phishpicker:songs:";

export function getCachedSongs(snapshotAt: string): Song[] | null {
  try {
    const raw = localStorage.getItem(KEY_PREFIX + snapshotAt);
    return raw ? (JSON.parse(raw) as Song[]) : null;
  } catch {
    return null;
  }
}

export function setCachedSongs(snapshotAt: string, songs: Song[]): void {
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k?.startsWith(KEY_PREFIX) && k !== KEY_PREFIX + snapshotAt) {
        localStorage.removeItem(k);
      }
    }
    localStorage.setItem(KEY_PREFIX + snapshotAt, JSON.stringify(songs));
  } catch {
    // quota exceeded — ignore
  }
}
