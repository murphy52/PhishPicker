"use client";

import { useEffect, useRef, useState } from "react";
import { nextMultiplier } from "@/lib/score";

interface Props {
  /** Current consecutive-correct-calls streak (from the last attribution). */
  streak: number;
}

const DRAIN_MS = 900;

/**
 * Understated at ×1, escalates at ×1.5/×2, and drains with weight on reset.
 * Framed as "banking toward the next live catch" so a foreseen call's
 * unmultiplied points never read as a glowing-but-empty meter.
 */
export function ComboMeter({ streak }: Props) {
  const lit = Math.min(streak, 3);
  const mult = nextMultiplier(streak);
  const prev = useRef(streak);
  const [draining, setDraining] = useState(false);

  useEffect(() => {
    if (streak < prev.current) {
      setDraining(true);
      const t = setTimeout(() => setDraining(false), DRAIN_MS);
      prev.current = streak;
      return () => clearTimeout(t);
    }
    prev.current = streak;
  }, [streak]);

  return (
    <div
      data-testid="combo-meter"
      data-draining={draining ? "true" : "false"}
      className={`flex items-center justify-between rounded-xl border border-neutral-800/80 bg-neutral-900/40 px-4 py-2.5 ${
        draining ? "motion-safe:animate-[combo-drain_0.9s_ease-out]" : ""
      }`}
    >
      <div className="flex items-center gap-1.5">
        {[1, 2, 3].map((seg) => (
          <span
            key={seg}
            data-testid="combo-segment"
            data-lit={seg <= lit ? "true" : "false"}
            aria-hidden="true"
            className={`font-score text-lg leading-none transition-all duration-300 ${
              seg <= lit
                ? seg === 3
                  ? "text-live drop-shadow-[0_0_8px_rgba(251,191,36,0.8)]"
                  : "text-live/90"
                : "text-neutral-800"
            }`}
          >
            ⚡
          </span>
        ))}
        <span className="ml-2 text-xs text-neutral-500">
          {streak > 0 ? `${streak} in a row` : "combo"}
        </span>
      </div>
      <span
        data-testid="combo-mult"
        className={`font-score text-xl font-extrabold ${
          mult >= 2
            ? "text-live drop-shadow-[0_0_10px_rgba(251,191,36,0.6)]"
            : mult > 1
              ? "text-live/90"
              : "text-neutral-600"
        }`}
      >
        next catch ×{mult}
      </span>
    </div>
  );
}
