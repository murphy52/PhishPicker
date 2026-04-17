"use client";

import { useMemo, useState } from "react";
import Fuse from "fuse.js";

export interface Song {
  song_id: number;
  name: string;
  original_artist: string | null;
}

interface Props {
  songs: Song[];
  onSelect: (song: Song) => void;
}

export function SongSearch({ songs, onSelect }: Props) {
  const [query, setQuery] = useState("");

  const fuse = useMemo(
    () => new Fuse(songs, { keys: ["name", "original_artist"], threshold: 0.4 }),
    [songs],
  );

  const results = query ? fuse.search(query).map((r) => r.item) : [];

  return (
    <div>
      <input
        type="text"
        aria-label="Search songs"
        placeholder="Search songs…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {results.length > 0 && (
        <ul>
          {results.map((song) => (
            <li key={song.song_id}>
              <button type="button" onClick={() => onSelect(song)}>
                {song.name}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
