"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Fuse from "fuse.js";
import type { Song } from "@/lib/songs";

export type { Song };

interface Props {
  songs: Song[];
  onSelect: (song: Song) => void;
  autoFocus?: boolean;
  // When true, render for one-handed use: input pinned at the bottom,
  // results grow upward so the best match sits directly above the input
  // and weaker matches scroll off the top.
  reverse?: boolean;
}

export function SongSearch({ songs, onSelect, autoFocus, reverse }: Props) {
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

  const input = (
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
      className={
        reverse
          ? "w-full bg-neutral-800 text-neutral-100 placeholder-neutral-500 rounded-lg px-3 py-3 text-base outline-none ring-1 ring-neutral-700 focus:ring-indigo-500"
          : undefined
      }
    />
  );

  if (reverse) {
    return (
      <div className="flex flex-col flex-1 min-h-0">
        <ul
          data-testid="song-search-results"
          className="flex flex-col-reverse overflow-y-auto flex-1 min-h-0"
        >
          {results.map((song) => (
            <li key={song.song_id}>
              <button
                type="button"
                onClick={() => onSelect(song)}
                className="w-full text-left py-3 px-2 text-base text-neutral-100 hover:bg-neutral-800 rounded min-h-[44px]"
              >
                {song.name}
              </button>
            </li>
          ))}
        </ul>
        <div className="pt-2">{input}</div>
      </div>
    );
  }

  return (
    <div>
      {input}
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
