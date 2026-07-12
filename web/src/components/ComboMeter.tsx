"use client";

import { useEffect, useRef, useState } from "react";
import { nextMultiplier } from "@/lib/score";

interface Props {
  /** Current consecutive-correct-calls streak (from the last attribution). */
  streak: number;
  /**
   * The show is over (a finalized/past board, or no next slot remains), so
   * the streak can't advance. Suppresses the forward "next catch ×N" tease —
   * it would dangle a multiplier the show can never pay.
   */
  closed?: boolean;
}

const DRAIN_MS = 900;

/** The multiplier the streak's final catch actually paid (past tense). */
function achievedMultiplier(streak: number): number {
  if (streak >= 3) return 2;
  if (streak === 2) return 1.5;
  return 1;
}

/**
 * Understated at ×1, escalates at ×1.5/×2, and drains with weight on reset.
 * Framed as "banking toward the next live catch" so a foreseen call's
 * unmultiplied points never read as a glowing-but-empty meter.
 */
export function ComboMeter({ streak, closed = false }: Props) {
  const lit = Math.min(streak, 3);
  const mult = nextMultiplier(streak);
  const achieved = achievedMultiplier(streak);
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
                  ? "drop-shadow-[0_0_8px_rgba(251,191,36,0.8)]"
                  : ""
                : "grayscale opacity-25"
            }`}
          >
            ⚡
          </span>
        ))}
        <span className="ml-2 text-xs text-neutral-500">
          {streak > 0 ? `${streak} in a row` : "combo"}
        </span>
      </div>
      {closed ? (
        // Show is over: no forward tease. If the run reached a real combo,
        // note the multiplier it earned (past tense); otherwise stay quiet.
        achieved > 1 ? (
          <span
            data-testid="combo-mult"
            className="font-score text-lg font-bold text-live/70"
          >
            ✓ ×{achieved} combo
          </span>
        ) : (
          <span data-testid="combo-mult" className="text-xs text-neutral-600">
            {streak > 0 ? "combo ended" : "no combo"}
          </span>
        )
      ) : (
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
      )}
    </div>
  );
}
