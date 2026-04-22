"use client";

import useSWR from "swr";
import type { PreviewCandidate, PreviewSlot } from "@/lib/preview";

interface Props {
  showId: string;
  slotIdx: number | null;
  onClose: () => void;
  onPick: (candidate: PreviewCandidate) => void;
}

const fetcher = (url: string) => fetch(url).then((r) => r.json());

export function SlotAltsModal({ showId, slotIdx, onClose, onPick }: Props) {
  const key =
    slotIdx !== null
      ? `/api/live/show/${showId}/slot/${slotIdx}/alternatives?top_k=10`
      : null;
  const { data: slot } = useSWR<PreviewSlot>(key, fetcher, {
    revalidateOnFocus: false,
  });

  if (slotIdx === null) return null;

  const candidates = slot?.top_k ?? [];
  const loading = !slot;

  return (
    <div
      data-testid="slot-alts-modal"
      className="fixed inset-0 z-50 flex flex-col justify-end bg-black/60"
    >
      <div className="bg-neutral-900 rounded-t-2xl p-4 max-h-[80dvh] flex flex-col">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-medium text-neutral-300">
            Slot {slotIdx} · alternatives
          </span>
          <button
            type="button"
            aria-label="Close alternatives"
            onClick={onClose}
            className="text-neutral-400"
          >
            ✕
          </button>
        </div>
        {loading ? (
          <div className="text-sm text-neutral-500 py-4">Loading…</div>
        ) : (
          <ol className="flex-1 overflow-y-auto">
            {candidates.map((c) => (
              <li
                key={c.song_id}
                onClick={() => onPick(c)}
                className="flex items-center gap-3 py-3 min-h-[44px] cursor-pointer hover:bg-neutral-800 rounded px-2"
              >
                <span className="text-neutral-500 w-6 tabular-nums text-right text-xs">
                  {c.rank}
                </span>
                <span className="flex-1 text-base">{c.name}</span>
                <span className="text-xs text-neutral-500 tabular-nums shrink-0">
                  {Math.round(c.probability * 100)}%
                </span>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
