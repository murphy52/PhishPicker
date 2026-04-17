"use client";

const SET_SEQUENCE: Record<string, string> = { "1": "2", "2": "e", e: "e" };

interface Props {
  currentSet: string;
  onAdvance: (nextSet: string) => void;
}

export function SetBoundaryButton({ currentSet, onAdvance }: Props) {
  const nextSet = SET_SEQUENCE[currentSet] ?? "2";

  return (
    <button
      type="button"
      onClick={() => onAdvance(nextSet)}
      className="px-4 py-2 rounded bg-neutral-800 text-neutral-300 text-sm"
    >
      Set {currentSet} → advance to {nextSet === "e" ? "Encore" : `Set ${nextSet}`}
    </button>
  );
}
