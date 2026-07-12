import type { ShowMeta } from "@/lib/score";

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/** Format an ISO date (YYYY-MM-DD) without timezone drift. */
function formatShowDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

/**
 * Compact venue · run · date · city line under the scoreboard / bracket
 * title. Every field degrades gracefully: an unresolved venue or a one-off
 * (no residency) simply renders less.
 */
export function ShowMetaBar({ show }: { show: ShowMeta }) {
  const location = [show.city, show.state].filter(Boolean).join(", ");
  const hasRun =
    !!show.run_position && !!show.run_length && show.run_length > 1;

  return (
    <div
      data-testid="show-meta"
      className="flex flex-col items-center gap-0.5 px-4 pt-1 pb-2 text-center"
    >
      {show.venue && (
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold text-neutral-200">
            {show.venue}
          </span>
          {hasRun && (
            <span
              data-testid="run-badge"
              className="text-xs font-normal text-neutral-500 tabular-nums"
            >
              Run {show.run_position}/{show.run_length}
            </span>
          )}
        </div>
      )}
      <div className="text-xs text-neutral-500">
        {formatShowDate(show.show_date)}
        {location && <> · {location}</>}
      </div>
    </div>
  );
}
