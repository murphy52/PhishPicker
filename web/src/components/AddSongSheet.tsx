"use client";

import { useState } from "react";
import type { Song } from "@/lib/songs";
import { SongSearch } from "./SongSearch";

interface Props {
  songs: Song[];
  onAdd: (song: Song) => void;
}

export function AddSongSheet({ songs, onAdd }: Props) {
  const [open, setOpen] = useState(false);

  function handleSelect(song: Song) {
    onAdd(song);
    setOpen(false);
  }

  return (
    <>
      <button
        type="button"
        aria-label="Add song"
        onClick={() => setOpen(true)}
        className="fixed bottom-6 right-6 h-14 w-14 rounded-full bg-indigo-600 text-white text-2xl shadow-lg flex items-center justify-center"
      >
        +
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex flex-col justify-end bg-black/60">
          <div className="bg-neutral-900 rounded-t-2xl p-4 h-dvh flex flex-col">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium text-neutral-300">Add song</span>
              <button
                type="button"
                aria-label="Close sheet"
                onClick={() => setOpen(false)}
                className="text-neutral-400"
              >
                ✕
              </button>
            </div>
            <SongSearch songs={songs} onSelect={handleSelect} autoFocus />
          </div>
        </div>
      )}
    </>
  );
}
