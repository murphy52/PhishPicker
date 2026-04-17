export type Candidate = {
  song_id: number;
  name: string;
  probability: number;
  score: number;
};

export function Leaderboard({ candidates }: { candidates: Candidate[] }) {
  return (
    <ol className="space-y-1">
      {candidates.map((c) => (
        <li key={c.song_id} className="flex items-center gap-3 py-3 min-h-[44px]">
          <span className="text-neutral-400 w-10 tabular-nums text-right text-sm">
            {Math.round(c.probability * 100)}%
          </span>
          <div className="flex-1">
            <div className="text-base">{c.name}</div>
            <div className="h-1 bg-neutral-800 rounded overflow-hidden mt-1">
              <div
                className="h-full bg-indigo-500"
                style={{ width: `${Math.min(100, c.probability * 100)}%` }}
              />
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}
