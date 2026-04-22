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
        {songs.map((song, i) => {
          const isLast = i === songs.length - 1;
          if (isLast) {
            return (
              <li key={`${song.song_id}-${i}`}>
                <button
                  type="button"
                  aria-label={`Undo ${song.name}`}
                  onClick={onUndo}
                  className="group flex flex-col items-center gap-1 rounded bg-neutral-800 px-3 py-2 min-h-[44px] min-w-[44px] whitespace-nowrap hover:bg-red-950 active:bg-red-900 transition-colors"
                >
                  <span className="text-sm text-neutral-100 group-hover:text-red-200 group-hover:line-through">
                    {song.name}
                  </span>
                  <span className="text-xs text-neutral-500 group-hover:text-red-400">
                    Undo
                  </span>
                </button>
              </li>
            );
          }
          return (
            <li key={`${song.song_id}-${i}`}>
              <div className="rounded bg-neutral-800 px-3 py-2 text-sm whitespace-nowrap min-h-[44px] min-w-[44px] flex items-center">
                {song.name}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
