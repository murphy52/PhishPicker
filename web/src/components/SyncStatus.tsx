"use client";

import useSWR from "swr";

interface SyncStatusResponse {
  state: "off" | "live" | "stale" | "dead";
  sync_enabled: boolean;
  last_updated: string | null;
  last_error: string | null;
}

interface Props {
  showId: string;
  showDate: string;
}

const fetcher = (url: string) => fetch(url).then((r) => r.json());

const STATE_STYLE: Record<SyncStatusResponse["state"], string> = {
  off: "bg-neutral-800 text-neutral-400",
  live: "bg-emerald-900/60 text-emerald-300",
  stale: "bg-amber-900/60 text-amber-300",
  dead: "bg-red-900/60 text-red-300",
};

const STATE_LABEL: Record<SyncStatusResponse["state"], string> = {
  off: "sync off",
  live: "live",
  stale: "stale",
  dead: "dead",
};

export function SyncStatus({ showId, showDate }: Props) {
  const { data, mutate } = useSWR<SyncStatusResponse>(
    `/api/live/show/${showId}/sync/status`,
    fetcher,
    { refreshInterval: 5_000, revalidateOnFocus: false },
  );

  const state = data?.state ?? "off";

  async function toggle() {
    const action = state === "off" ? "start" : "stop";
    const body =
      action === "start"
        ? JSON.stringify({ show_date: showDate })
        : undefined;
    await fetch(`/api/live/show/${showId}/sync/${action}`, {
      method: "POST",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body,
    });
    mutate();
  }

  return (
    <button
      type="button"
      data-testid="sync-status"
      onClick={toggle}
      title={data?.last_error ?? undefined}
      className={`text-xs px-2 py-1 rounded-full ${STATE_STYLE[state]}`}
    >
      {STATE_LABEL[state]}
    </button>
  );
}
