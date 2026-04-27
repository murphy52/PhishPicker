interface Props {
  rank: number | null;
}

export function RankPill({ rank }: Props) {
  if (rank == null) {
    return (
      <span
        data-testid="rank-pill"
        className="text-xs px-2 py-0.5 rounded-full bg-neutral-800 text-neutral-500"
      >
        —
      </span>
    );
  }
  const color =
    rank === 1
      ? "bg-green-900/40 text-green-300"
      : rank <= 5
        ? "bg-yellow-900/40 text-yellow-300"
        : rank <= 20
          ? "bg-orange-900/40 text-orange-300"
          : "bg-red-900/40 text-red-300";
  return (
    <span
      data-testid="rank-pill"
      className={`text-xs px-2 py-0.5 rounded-full font-mono ${color}`}
    >
      #{rank}
    </span>
  );
}
