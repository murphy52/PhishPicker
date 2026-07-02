"use client";

import { useEffect, useRef, useState } from "react";
import type { FeedEvent } from "@/lib/score";

export interface PendingCall {
  name: string;
  setNumber: string;
  position: number;
}

interface Props {
  /** The model's current #1 pick for the next slot (from the preview). */
  call: PendingCall | null;
  /** True before the first song — the call is the pre-show opener pick. */
  isOpener: boolean;
  /** Newest resolved reveal; a change flips the card to its hit/miss face. */
  lastEvent?: FeedEvent;
}

const FLASH_MS = 4500;

function setLabel(setNumber: string): string {
  if (setNumber === "E") return "Encore";
  if (setNumber.startsWith("E")) return `Encore ${setNumber.slice(1)}`;
  return `Set ${setNumber}`;
}

/**
 * The next-song card — the moment to nail. Face-up pending call with a slow
 * breathing ring; when a reveal lands it flips to a hit snap / miss deflate
 * for a few seconds, then returns to the new pending call.
 */
export function NextCallCard({ call, isOpener, lastEvent }: Props) {
  const [flash, setFlash] = useState<FeedEvent | null>(null);
  const seenIndex = useRef<number | null>(null);

  useEffect(() => {
    if (!lastEvent) return;
    const isFirstRender = seenIndex.current === null;
    if (seenIndex.current === lastEvent.index) return;
    seenIndex.current = lastEvent.index;
    if (isFirstRender) return; // don't replay history on page load
    setFlash(lastEvent);
    const t = setTimeout(() => setFlash(null), FLASH_MS);
    return () => clearTimeout(t);
  }, [lastEvent]);

  if (flash) {
    const hit = flash.kind === "live" || flash.foreseen;
    const bustout = flash.kind === "bustout";
    return (
      <div
        data-testid="next-call-card"
        data-face={hit ? "hit" : bustout ? "bustout" : "miss"}
        className={`relative flex flex-col items-center gap-1 rounded-2xl border px-6 py-5 text-center ${
          hit
            ? `motion-safe:animate-[call-hit_0.9s_ease-out] ${
                flash.foreseen
                  ? "border-foresight/60 bg-indigo-950/40"
                  : "border-live/60 bg-amber-950/30"
              }`
            : bustout
              ? "border-bustout/60 bg-yellow-950/30"
              : "border-neutral-800 bg-neutral-900/60 motion-safe:animate-[call-miss_0.8s_ease-out_forwards]"
        }`}
      >
        <span
          className={`font-score text-sm font-semibold uppercase tracking-[0.25em] ${
            hit
              ? flash.foreseen
                ? "text-foresight"
                : "text-live"
              : bustout
                ? "text-bustout"
                : "text-neutral-500"
          }`}
        >
          {bustout
            ? "🎸 Bustout!"
            : flash.foreseen
              ? "🔮 Foreseen"
              : hit
                ? "⚡ Called it"
                : "Missed"}
        </span>
        <span className="font-score text-3xl font-extrabold text-neutral-50">
          {flash.name}
        </span>
        {flash.points > 0 ? (
          <span
            className={`font-score text-xl font-semibold ${
              flash.kind === "live" ? "text-live" : "text-foresight"
            }`}
          >
            +{flash.points}
            {flash.mult != null && flash.mult > 1 ? ` ×${flash.mult}` : ""}
          </span>
        ) : (
          <span className="text-xs text-neutral-500">
            {bustout ? "nobody saw it coming — no penalty" : "no points banked"}
          </span>
        )}
      </div>
    );
  }

  if (!call) {
    return (
      <div
        data-testid="next-call-card"
        data-face="empty"
        className="rounded-2xl border border-dashed border-neutral-800 px-6 py-5 text-center text-sm text-neutral-600"
      >
        no call on the board
      </div>
    );
  }

  return (
    <div
      data-testid="next-call-card"
      data-face="pending"
      className="relative flex flex-col items-center gap-1 rounded-2xl border border-neutral-800 bg-neutral-900/60 px-6 py-5 text-center motion-safe:animate-[call-breathe_3.2s_ease-in-out_infinite]"
    >
      <span
        className={`font-score text-sm font-semibold uppercase tracking-[0.25em] ${
          isOpener ? "text-foresight" : "text-live"
        }`}
      >
        {isOpener ? "🔮 Predicted opener" : "⚡ The call"}
      </span>
      <span className="font-score text-3xl font-extrabold text-neutral-50">
        {call.name}
      </span>
      <span className="text-xs text-neutral-500">
        {setLabel(call.setNumber)} · slot {call.position}
        {isOpener ? " · locked pre-show" : " · next song, says the model"}
      </span>
    </div>
  );
}
