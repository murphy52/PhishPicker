"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Fuse from "fuse.js";
import type { Song } from "@/lib/songs";

export type { Song };

interface Props {
  songs: Song[];
  onSelect: (song: Song) => void;
  autoFocus?: boolean;
}

export function SongSearch({ songs, onSelect, autoFocus }: Props) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (autoFocus) inputRef.current?.focus();
  }, [autoFocus]);

  const fuse = useMemo(
    () => new Fuse(songs, { keys: ["name", "original_artist"], threshold: 0.4 }),
    [songs],
  );

  const results = query ? fuse.search(query).map((r) => r.item) : [];

  return (
    <div>
      <input
        ref={inputRef}
        type="text"
        aria-label="Search songs"
        placeholder="Search songs…"
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        enterKeyHint="search"
        inputMode="search"
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
