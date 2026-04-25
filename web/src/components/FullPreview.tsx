"use client";

import type { PreviewSlot } from "@/lib/preview";

interface Props {
  slots: PreviewSlot[];
  onSlotClick: (slotIdx: number) => void;
  loading?: boolean;
}

const SET_LABELS: Record<string, string> = {
  "1": "Set 1",
  "2": "Set 2",
  E: "Encore",
};

const DEFAULT_STRUCTURE: [string, number][] = [
  ["1", 9],
  ["2", 7],
  ["E", 2],
];

export function FullPreview({ slots, onSlotClick, loading }: Props) {
  if (loading && slots.length === 0) {
    return <FullPreviewSkeleton />;
  }
  const groups: { set: string; slots: PreviewSlot[] }[] = [];
  for (const s of slots) {
    const last = groups[groups.length - 1];
    if (last && last.set === s.set_number) last.slots.push(s);
    else groups.push({ set: s.set_number, slots: [s] });
  }

  return (
    <div className="flex flex-col gap-4">
      {groups.map((g) => (
        <section key={g.set}>
          <h3 className="text-xs font-semibold uppercase tracking-widest text-neutral-500 mb-2">
            {SET_LABELS[g.set] ?? `Set ${g.set}`}
          </h3>
          <ul className="flex flex-col gap-1">
            {g.slots.map((slot) => (
              <SlotRow key={slot.slot_idx} slot={slot} onSlotClick={onSlotClick} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function HitRankIndicator({ hitRank }: { hitRank: number | null | undefined }) {
  if (hitRank === undefined) return null;
  if (hitRank === 1) {
    return (
      <svg
        data-testid="hit-rank-bullseye"
        role="img"
        aria-label="Top prediction"
        viewBox="0 0 16 16"
        className="w-3.5 h-3.5 text-emerald-400 shrink-0"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      >
        <circle cx="8" cy="8" r="6.25" />
        <circle cx="8" cy="8" r="3.5" />
        <circle cx="8" cy="8" r="1" fill="currentColor" stroke="none" />
      </svg>
    );
  }
  if (hitRank === null) {
    return (
      <span
        data-testid="hit-rank-miss"
        aria-label="Not in top ten"
        className="text-xs text-neutral-700 tabular-nums shrink-0"
      >
        —
      </span>
    );
  }
  return (
    <span
      aria-label={`Predicted at rank ${hitRank}`}
      className="text-xs text-neutral-500 tabular-nums shrink-0"
    >
      #{hitRank}
    </span>
  );
}

function SlotRow({
  slot,
  onSlotClick,
}: {
  slot: PreviewSlot;
  onSlotClick: (slotIdx: number) => void;
}) {
  if (slot.state === "entered" && slot.entered_song) {
    const pendingStyle =
      slot.pending === "adding"
        ? "bg-indigo-950/70 text-neutral-300 animate-pulse ring-1 ring-indigo-600/40"
        : slot.pending === "removing"
          ? "bg-neutral-800/60 text-neutral-500 line-through animate-pulse"
          : "bg-neutral-800 text-neutral-100";
    return (
      <li
        data-testid="slot"
        data-state="entered"
        data-pending={slot.pending ?? undefined}
        className={`flex items-center gap-3 px-3 py-2 min-h-[44px] rounded ${pendingStyle}`}
      >
        <span className="text-neutral-500 w-6 tabular-nums text-right text-xs">
          {slot.position}
        </span>
        <span className="flex-1 text-base truncate">{slot.entered_song.name}</span>
        {slot.pending === "adding" && (
          <span
            aria-label="Saving…"
            className="inline-block w-3 h-3 border-2 border-indigo-300 border-t-transparent rounded-full animate-spin shrink-0"
          />
        )}
        {slot.pending !== "adding" && <HitRankIndicator hitRank={slot.hit_rank} />}
      </li>
    );
  }

  const top = slot.top_k?.[0];
  return (
    <li
      data-testid="slot"
      data-state="predicted"
      onClick={() => onSlotClick(slot.slot_idx)}
      className="flex items-center gap-3 px-3 py-2 min-h-[44px] rounded border border-dashed border-neutral-800 text-neutral-500 cursor-pointer hover:border-indigo-700 hover:text-neutral-300"
    >
      <span className="w-6 tabular-nums text-right text-xs">{slot.position}</span>
      <span className="flex-1 text-base truncate">
        {top ? top.name : "—"}
      </span>
      {top && (
        <span className="text-xs text-neutral-600 tabular-nums shrink-0">
          {Math.round(top.probability * 100)}%
        </span>
      )}
    </li>
  );
}

function FullPreviewSkeleton() {
  return (
    <div
      data-testid="preview-skeleton"
      className="flex flex-col gap-4 animate-pulse"
    >
      {DEFAULT_STRUCTURE.map(([set, n]) => (
        <section key={set}>
          <div className="h-3 w-14 bg-neutral-800 rounded mb-2" />
          <ul className="flex flex-col gap-1">
            {Array.from({ length: n }).map((_, i) => (
              <li
                key={i}
                className="flex items-center gap-3 px-3 py-2 min-h-[44px] rounded border border-dashed border-neutral-900"
              >
                <span className="w-6 h-3 bg-neutral-800 rounded" />
                <span
                  className="flex-1 h-4 bg-neutral-800 rounded"
                  style={{ maxWidth: `${50 + ((i * 13) % 40)}%` }}
                />
                <span className="w-8 h-3 bg-neutral-800 rounded shrink-0" />
              </li>
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
