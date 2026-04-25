"use client";

import type { PreviewSlot } from "@/lib/preview";

interface Props {
  slots: PreviewSlot[];
  currentSet: string;
  onSlotClick: (slotIdx: number) => void;
  onSetChange: (setKey: string) => void;
  loading?: boolean;
}

const SET_ORDER: { key: string; label: string }[] = [
  { key: "1", label: "Set 1" },
  { key: "2", label: "Set 2" },
  { key: "E", label: "Encore" },
];

const DEFAULT_STRUCTURE: [string, number][] = [
  ["1", 9],
  ["2", 7],
  ["E", 2],
];

export function FullPreview({
  slots,
  currentSet,
  onSlotClick,
  onSetChange,
  loading,
}: Props) {
  if (loading && slots.length === 0) {
    return <FullPreviewSkeleton currentSet={currentSet} />;
  }

  const slotsBySet = new Map<string, PreviewSlot[]>();
  for (const s of slots) {
    const list = slotsBySet.get(s.set_number) ?? [];
    list.push(s);
    slotsBySet.set(s.set_number, list);
  }

  return (
    <div className="flex flex-col gap-4">
      {SET_ORDER.map(({ key, label }) => {
        const setSlots = slotsBySet.get(key) ?? [];
        return (
          <section key={key}>
            <SetHeader
              label={label}
              active={key === currentSet}
              onClick={() => onSetChange(key)}
            />
            {setSlots.length > 0 && (
              <ul className="flex flex-col gap-1">
                {setSlots.map((slot) => (
                  <SlotRow
                    key={slot.slot_idx}
                    slot={slot}
                    onSlotClick={onSlotClick}
                  />
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}

function SetHeader({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      data-testid="set-header"
      data-active={active ? "true" : "false"}
      className={`flex items-center gap-2 mb-2 text-xs font-semibold uppercase tracking-widest transition-colors ${
        active
          ? "text-neutral-100"
          : "text-neutral-600 hover:text-neutral-400"
      }`}
    >
      <span
        aria-hidden="true"
        className={`inline-block w-1.5 h-1.5 rounded-full transition-colors ${
          active ? "bg-indigo-400" : "bg-transparent"
        }`}
      />
      {label}
    </button>
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
        className="w-3.5 h-3.5 shrink-0"
      >
        <circle cx="8" cy="8" r="7" fill="#ef4444" />
        <circle cx="8" cy="8" r="5" fill="#ffffff" />
        <circle cx="8" cy="8" r="3" fill="#ef4444" />
        <circle cx="8" cy="8" r="1.25" fill="#ffffff" />
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

function FullPreviewSkeleton({ currentSet }: { currentSet: string }) {
  return (
    <div
      data-testid="preview-skeleton"
      className="flex flex-col gap-4 animate-pulse"
    >
      {DEFAULT_STRUCTURE.map(([set, n]) => {
        const active = set === currentSet;
        return (
          <section key={set}>
            <div className="flex items-center gap-2 mb-2">
              <span
                className={`inline-block w-1.5 h-1.5 rounded-full ${
                  active ? "bg-indigo-400" : "bg-transparent"
                }`}
              />
              <div className="h-3 w-14 bg-neutral-800 rounded" />
            </div>
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
        );
      })}
    </div>
  );
}
