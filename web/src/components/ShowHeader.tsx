"use client";

import { useEffect, useState } from "react";
import { formatCountdown, hoursUntilShow } from "@/lib/time";
import { PushToggle } from "./PushToggle";
import { SyncStatus } from "./SyncStatus";

export interface UpcomingShow {
  show_id: number;
  show_date: string;
  venue: string;
  city: string;
  state: string;
  timezone: string;
  start_time_local: string;
  // Position / length within the residency (same venue + tour). Null when
  // the show isn't in the canonical DB or it's a one-off — no badge then.
  run_position?: number | null;
  run_length?: number | null;
}

interface Props {
  show: UpcomingShow;
  // When set, the live status pills (push, phish.net sync) appear in the
  // header's right column. Omitted before a live show is started.
  liveShowId?: string | null;
  // Injectable clock for tests; defaults to live browser time.
  now?: Date;
}

export function ShowHeader({ show, liveShowId, now }: Props) {
  const [tick, setTick] = useState(() => now ?? new Date());

  useEffect(() => {
    if (now) return; // tests pass a fixed now; don't self-update
    const id = setInterval(() => setTick(new Date()), 30_000);
    return () => clearInterval(id);
  }, [now]);

  const hours = hoursUntilShow(
    tick,
    show.show_date,
    show.start_time_local,
    show.timezone,
  );
  const countdown = formatCountdown(hours);

  // "Thu, Apr 23" — concise; year omitted to reduce visual noise.
  const dateLabel = new Date(`${show.show_date}T12:00:00Z`).toLocaleDateString(
    undefined,
    { weekday: "short", month: "short", day: "numeric", timeZone: show.timezone },
  );

  const location = [show.city, show.state].filter(Boolean).join(", ");

  return (
    <div
      data-testid="show-header"
      className="px-4 pt-4 pb-2 border-b border-neutral-900"
    >
      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-1 items-center">
        <div className="text-sm font-semibold text-neutral-100 flex items-baseline gap-2 min-w-0">
          <span className="truncate">{show.venue}</span>
          {show.run_position && show.run_length && (
            <span
              data-testid="run-badge"
              className="text-xs font-normal text-neutral-500 tabular-nums shrink-0"
            >
              Run: {show.run_position}|{show.run_length}
            </span>
          )}
        </div>
        <div
          className="text-xs font-medium text-indigo-300 tabular-nums shrink-0 justify-self-end"
          data-testid="show-countdown"
        >
          {countdown}
        </div>

        <div className="text-xs text-neutral-500 truncate">
          {dateLabel}
          {location && <> · {location}</>}
        </div>
        {liveShowId ? (
          <div className="flex items-center gap-2 shrink-0 justify-self-end">
            <PushToggle />
            <SyncStatus showId={liveShowId} showDate={show.show_date} />
          </div>
        ) : (
          <div />
        )}
      </div>
    </div>
  );
}
