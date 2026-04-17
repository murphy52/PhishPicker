"use client";

import type { Song } from "@/lib/songs";

interface Props {
  songs: Song[];
  onUndo: () => void;
}

export function PlayedStrip({ songs, onUndo }: Props) {
  if (songs.length === 0) return null;

  return (
    <div className="flex gap-2 overflow-x-auto py-2">
      <ul className="flex gap-2 list-none p-0 m-0">
        {songs.map((song, i) => (
          <li
            key={`${song.song_id}-${i}`}
            className="flex flex-col items-center gap-1"
          >
            <div className="rounded bg-neutral-800 px-3 py-2 text-sm whitespace-nowrap min-h-[44px] min-w-[44px] flex items-center">
              {song.name}
            </div>
            {i === songs.length - 1 && (
              <button
                type="button"
                aria-label="Undo last song"
                onClick={onUndo}
                className="text-xs text-neutral-500 hover:text-red-400"
              >
                Undo
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
