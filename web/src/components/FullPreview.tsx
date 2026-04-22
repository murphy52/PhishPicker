"use client";

import type { PreviewSlot } from "@/lib/preview";

interface Props {
  slots: PreviewSlot[];
  onSlotClick: (slotIdx: number) => void;
}

const SET_LABELS: Record<string, string> = {
  "1": "Set 1",
  "2": "Set 2",
  E: "Encore",
};

export function FullPreview({ slots, onSlotClick }: Props) {
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

function SlotRow({
  slot,
  onSlotClick,
}: {
  slot: PreviewSlot;
  onSlotClick: (slotIdx: number) => void;
}) {
  if (slot.state === "entered" && slot.entered_song) {
    return (
      <li
        data-testid="slot"
        data-state="entered"
        className="flex items-center gap-3 px-3 py-2 min-h-[44px] rounded bg-neutral-800 text-neutral-100"
      >
        <span className="text-neutral-500 w-6 tabular-nums text-right text-xs">
          {slot.position}
        </span>
        <span className="flex-1 text-base truncate">{slot.entered_song.name}</span>
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
