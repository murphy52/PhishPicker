import useSWR from "swr";

/** One finalized show's scorecard — mirrors GET /scorecards (scoring_service). */
export interface Scorecard {
  show_id: string;
  show_date: string;
  finalized_at: string;
  combined: number;
  foresight_total: number;
  live_total: number;
  ppps: number;
  max_streak: number;
}

export type SortKey = "date" | "score";
export type SortDir = "asc" | "desc";

const fetcher = (url: string) =>
  fetch(url).then((r) => {
    if (!r.ok) throw new Error(`scorecards ${r.status}`);
    return r.json() as Promise<{ scorecards: Scorecard[] }>;
  });

export function useScorecards() {
  const { data, error, isLoading } = useSWR("/api/scorecards", fetcher, {
    revalidateOnFocus: false,
  });
  return { scorecards: data?.scorecards ?? [], error, isLoading };
}

/**
 * Pure, stable sort of scorecards by date or combined score. Ties break on
 * show_date descending so the order is deterministic across re-renders.
 */
export function sortScorecards(
  rows: Scorecard[],
  key: SortKey,
  dir: SortDir,
): Scorecard[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const primary =
      key === "score"
        ? a.combined - b.combined
        : a.show_date.localeCompare(b.show_date);
    if (primary !== 0) return sign * primary;
    // Deterministic tiebreak: newest first, regardless of primary direction.
    return b.show_date.localeCompare(a.show_date);
  });
}
