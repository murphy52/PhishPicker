import useSWR from "swr";

export interface LikelySong {
  song_id: number;
  name: string;
  probability: number;
}

interface LikelyResponse {
  candidates: LikelySong[];
}

const fetcher = (url: string) =>
  fetch(url).then((r) => {
    if (r.status === 503) return { candidates: [] } as LikelyResponse; // model not deployed yet
    if (!r.ok) throw new Error(`likely-tonight ${r.status}`);
    return r.json() as Promise<LikelyResponse>;
  });

/** Ranked P(appears anywhere tonight) for a show. Null showId → no request. */
export function useLikelyTonight(showId: number | string | null) {
  const key = showId != null ? `/api/likely-tonight/${showId}` : null;
  const { data, error, isLoading } = useSWR<LikelyResponse>(key, fetcher, {
    revalidateOnFocus: false,
  });
  return { candidates: data?.candidates ?? [], error, isLoading };
}

/**
 * Bar width (0–100) for a probability, scaled so the top song fills the bar.
 * Relative scaling keeps a set of ~0.2 probabilities visually legible.
 */
export function barWidthPct(probability: number, max: number): number {
  if (max <= 0) return 0;
  return Math.max(4, Math.round((probability / max) * 100));
}
