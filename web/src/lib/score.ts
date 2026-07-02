"use client";

import useSWR from "swr";

// Mirrors the JSON from GET /live/show/{id}/score (scoring_service.py).
export interface BeatenClaim {
  ledger: "foresight" | "live";
  reason: string;
  base: number;
}

export interface Attribution {
  index: number;
  song_id: number;
  set_number: string;
  position: number;
  ledger: "foresight" | "live" | null;
  base: number;
  reason: string | null;
  beaten_claim: BeatenClaim | null;
  // null = no call was captured for this reveal (a no-event for the combo)
  called_right: boolean | null;
  streak: number;
  mult: number | null;
  final: number;
  called_early: boolean;
  bustout: boolean;
  missed: boolean;
  name: string;
}

export interface ScoreTotals {
  foresight_total: number;
  live_total: number;
  combined: number;
  ppps: number;
  hit_counts: Record<string, number>;
}

export interface ScoreResponse {
  attributions: Attribution[];
  totals: ScoreTotals;
  pick_outcomes: {
    pick: { set_number: string; position: number; song_id: number };
    reason: string;
    base: number;
    actual_index: number | null;
  }[];
  model_sha: string | null;
  frozen: boolean;
}

const REASON_LABELS: Record<string, string> = {
  opener: "OPENER NAILED",
  exact: "EXACT SLOT",
  right_set: "RIGHT SET",
  somewhere: "ON THE BOARD",
  next_song: "NEXT-SONG ✓",
};

export function reasonLabel(reason: string): string {
  return REASON_LABELS[reason] ?? reason.toUpperCase();
}

/** Lowercase phrasing for the beaten-claim line. */
function reasonPhrase(reason: string): string {
  return (REASON_LABELS[reason] ?? reason).toLowerCase().replace(" ✓", "");
}

/** Multiplier the NEXT correct live catch would pay at the current streak. */
export function nextMultiplier(streak: number): number {
  if (streak >= 2) return 2;
  if (streak === 1) return 1.5;
  return 1;
}

export interface FeedEvent {
  index: number;
  name: string;
  setNumber: string;
  kind: "foresight" | "live" | "bustout" | "miss";
  headline: string;
  points: number;
  mult: number | null;
  /** e.g. "beat 🔮 on the board +5" — makes best-claim-wins self-evident. */
  beaten: string | null;
  /** Foresight bank on a correct call — the "✓ foreseen" beat. */
  foreseen: boolean;
  calledEarly: boolean;
  corrected: boolean;
}

/**
 * Attributions -> feed items, newest reveal first. Pass the previous
 * attributions to tag rows whose song changed (a phish.net correction) —
 * the ↻ marker is session-local by design; the score itself is always the
 * clean recompute.
 */
export function buildFeedEvents(
  attributions: Attribution[],
  previous?: Attribution[],
): FeedEvent[] {
  const prevByIndex = new Map((previous ?? []).map((a) => [a.index, a]));
  return attributions
    .map((a): FeedEvent => {
      const kind = a.bustout
        ? ("bustout" as const)
        : a.ledger ?? ("miss" as const);
      const headline = a.bustout
        ? "BUSTOUT"
        : a.reason
          ? reasonLabel(a.reason)
          : "MISSED";
      const beaten = a.beaten_claim
        ? `beat ${a.beaten_claim.ledger === "foresight" ? "🔮" : "⚡"} ${reasonPhrase(
            a.beaten_claim.reason,
          )} +${a.beaten_claim.base}`
        : null;
      const prev = prevByIndex.get(a.index);
      return {
        index: a.index,
        name: a.name,
        setNumber: a.set_number,
        kind,
        headline,
        points: a.final,
        mult: a.ledger === "live" ? a.mult : null,
        beaten,
        foreseen: a.ledger === "foresight" && a.called_right === true,
        calledEarly: a.called_early,
        corrected: prev !== undefined && prev.song_id !== a.song_id,
      };
    })
    .reverse();
}

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

export interface ScorecardContext {
  shows_scored: number;
  best_total: number | null;
  best_ppps: number | null;
  rank_by_total: number;
  is_best: boolean;
}

export interface FinalizeResponse {
  scorecard: Scorecard;
  context: ScorecardContext;
  result: ScoreResponse;
}

export interface RecapSections {
  foresight: Attribution[];
  live: Attribution[];
  /** The night's humbling: plain misses + bustouts. */
  beatTheApp: Attribution[];
  maxStreak: number;
}

export function recapBreakdown(result: ScoreResponse): RecapSections {
  const atts = result.attributions;
  return {
    foresight: atts.filter((a) => a.ledger === "foresight"),
    live: atts.filter((a) => a.ledger === "live"),
    beatTheApp: atts.filter((a) => a.ledger === null),
    maxStreak: Math.max(0, ...atts.map((a) => a.streak)),
  };
}

const fetcher = (url: string) => fetch(url).then((r) => r.json());

/** POST-finalize (idempotent server-side) and return the scorecard bundle. */
export function useScorecard(showId: string | null) {
  const key = showId ? `/api/live/show/${showId}/scorecard` : null;
  return useSWR<FinalizeResponse>(
    key,
    (url: string) => fetch(url, { method: "POST" }).then((r) => r.json()),
    { revalidateOnFocus: false, dedupingInterval: 30_000 },
  );
}

/**
 * Poll the recompute-on-read score. `playedCount` (when known) busts the key
 * on each entry so a fresh score lands with the song, not a poll tick later.
 */
export function useScore(showId: string | null, playedCount?: number) {
  const suffix = playedCount != null ? `?_n=${playedCount}` : "";
  const key = showId ? `/api/live/show/${showId}/score${suffix}` : null;
  return useSWR<ScoreResponse>(key, fetcher, {
    refreshInterval: 20_000,
    revalidateOnFocus: true,
    keepPreviousData: true,
  });
}
