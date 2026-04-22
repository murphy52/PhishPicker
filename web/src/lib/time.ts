// Timezone-aware math for show start times.
//
// Native Intl has no "construct a Date from local fields in a given tz" — so
// we compute the UTC offset at a sample instant, then shift a naive-UTC
// construction by that offset. Works for any timezone the browser knows.

function getTzOffsetMs(tz: string, utcDate: Date): number {
  // Renders `utcDate`'s wall-clock fields in `tz`, then rebuilds those fields
  // as if they were UTC — the gap is the tz offset (signed).
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(utcDate);
  const p = Object.fromEntries(
    parts.filter((x) => x.type !== "literal").map((x) => [x.type, x.value]),
  ) as Record<string, string>;
  const asUTC = Date.UTC(
    Number(p.year),
    Number(p.month) - 1,
    Number(p.day),
    Number(p.hour === "24" ? "0" : p.hour),
    Number(p.minute),
    Number(p.second),
  );
  return asUTC - utcDate.getTime();
}

export function showStartUTC(
  showDate: string,
  startLocal: string,
  tz: string,
): Date {
  const naiveUTC = new Date(`${showDate}T${startLocal}:00Z`);
  const offset = getTzOffsetMs(tz, naiveUTC);
  return new Date(naiveUTC.getTime() - offset);
}

export function hoursUntilShow(
  now: Date,
  showDate: string,
  startLocal: string,
  tz: string,
): number {
  const start = showStartUTC(showDate, startLocal, tz);
  return (start.getTime() - now.getTime()) / (1000 * 60 * 60);
}

// Formats a float hours count into a short UX string.
//   > 48h: "in 3d 4h"
//   > 1h:  "in 5h 12m"
//   > 0:   "in 42m"
//   ~= 0:  "starting now"
//   < 0:   "started 1h 15m ago"
export function formatCountdown(hours: number): string {
  const abs = Math.abs(hours);
  const totalMinutes = Math.round(abs * 60);
  if (totalMinutes < 1) return "starting now";
  const d = Math.floor(totalMinutes / (60 * 24));
  const h = Math.floor((totalMinutes % (60 * 24)) / 60);
  const m = totalMinutes % 60;

  let pieces: string;
  if (d > 0) pieces = `${d}d ${h}h`;
  else if (h > 0) pieces = `${h}h ${m}m`;
  else pieces = `${m}m`;

  return hours < 0 ? `started ${pieces} ago` : `in ${pieces}`;
}
