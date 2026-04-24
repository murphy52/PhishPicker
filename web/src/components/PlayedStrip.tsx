"use client";

import type { LiveSong } from "@/lib/liveShow";

interface Props {
  songs: LiveSong[];
  onUndo: () => void;
}

export function PlayedStrip({ songs, onUndo }: Props) {
  // Only show songs that haven't been reconciled against phish.net yet.
  // Once a song is confirmed by the authoritative setlist it's no longer
  // meaningful to "undo" it — the strip is strictly for managing the
  // user's own in-flight entries.
  const undoable = songs.filter((s) => s.source === "user");
  if (undoable.length === 0) return null;

  return (
    <div className="flex gap-2 overflow-x-auto py-2">
      <ul className="flex gap-2 list-none p-0 m-0">
        {undoable.map((song, i) => {
          const isLast = i === undoable.length - 1;
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
