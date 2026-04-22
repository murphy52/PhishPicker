"use client";

const SET_SEQUENCE: Record<string, string> = { "1": "2", "2": "E" };

interface Props {
  currentSet: string;
  onAdvance: (nextSet: string) => void;
}

export function SetBoundaryButton({ currentSet, onAdvance }: Props) {
  const nextSet = SET_SEQUENCE[currentSet];
  if (!nextSet) return null;

  return (
    <button
      type="button"
      onClick={() => onAdvance(nextSet)}
      className="px-4 py-2 rounded bg-neutral-800 text-neutral-300 text-sm"
    >
      Set {currentSet} → advance to {nextSet === "E" ? "Encore" : `Set ${nextSet}`}
    </button>
  );
}
