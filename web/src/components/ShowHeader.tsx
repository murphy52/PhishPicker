"use client";

import { useEffect, useState } from "react";
import { formatCountdown, hoursUntilShow } from "@/lib/time";

export interface UpcomingShow {
  show_id: number;
  show_date: string;
  venue: string;
  city: string;
  state: string;
  timezone: string;
  start_time_local: string;
}

interface Props {
  show: UpcomingShow;
  // Injectable clock for tests; defaults to live browser time.
  now?: Date;
}

export function ShowHeader({ show, now }: Props) {
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
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-neutral-100 truncate">
            {show.venue}
          </div>
          <div className="text-xs text-neutral-500 truncate">
            {dateLabel}
            {location && <> · {location}</>}
          </div>
        </div>
        <div
          className="text-xs font-medium text-indigo-300 tabular-nums shrink-0"
          data-testid="show-countdown"
        >
          {countdown}
        </div>
      </div>
    </div>
  );
}
