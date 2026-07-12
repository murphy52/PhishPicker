import { useCallback, useEffect, useState } from "react";
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

export interface SortState {
  key: SortKey;
  dir: SortDir;
}

const SORT_LS_KEY = "phishpicker:history_sort";
const DEFAULT_SORT: SortState = { key: "date", dir: "desc" };

function isSortState(v: unknown): v is SortState {
  if (typeof v !== "object" || v === null) return false;
  const { key, dir } = v as Record<string, unknown>;
  return (
    (key === "date" || key === "score") && (dir === "asc" || dir === "desc")
  );
}

/**
 * The history table's sort, persisted to localStorage so it survives a
 * refresh and navigating away and back. `toggle(key)` flips direction when
 * the same column is re-selected, else switches to that column (desc).
 *
 * Hydration is a one-shot effect (SSR-safe: the server render always uses the
 * default, then the client swaps in the stored preference on mount).
 */
export function useSortPreference(): [SortState, (key: SortKey) => void] {
  const [sort, setSort] = useState<SortState>(DEFAULT_SORT);

  useEffect(() => {
    const raw = localStorage.getItem(SORT_LS_KEY);
    if (!raw) return;
    try {
      const parsed: unknown = JSON.parse(raw);
      // eslint-disable-next-line react-hooks/set-state-in-effect -- one-shot SSR-safe hydration
      if (isSortState(parsed)) setSort(parsed);
    } catch {
      // Corrupt/stale value — ignore and keep the default.
    }
  }, []);

  const toggle = useCallback((nextKey: SortKey) => {
    setSort((cur) => {
      const next: SortState =
        nextKey === cur.key
          ? { key: cur.key, dir: cur.dir === "desc" ? "asc" : "desc" }
          : { key: nextKey, dir: "desc" };
      localStorage.setItem(SORT_LS_KEY, JSON.stringify(next));
      return next;
    });
  }, []);

  return [sort, toggle];
}

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
