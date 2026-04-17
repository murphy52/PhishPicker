export type SlotMetrics = {
  top1: number;
  top5: number;
  mrr: number;
  n: number;
};

export type BaselineMetrics = {
  top1: number;
  top5: number;
  top20?: number;
  mrr: number;
};

export type Metrics = {
  trained_at: string;
  cutoff_date?: string;
  model_version: string;
  n_shows_trained_on?: number;
  n_slots: number;
  holdout_shows?: number;
  top1: number;
  top5: number;
  top20: number;
  mrr: number;
  top1_ci: [number, number];
  top5_ci: [number, number];
  top20_ci: [number, number];
  mrr_ci: [number, number];
  by_slot: Record<string, SlotMetrics>;
  baselines: Record<string, BaselineMetrics>;
  feature_columns: string[];
  ship_gate_passed: boolean;
};

function pct(v: number, places = 1): string {
  return `${(v * 100).toFixed(places)}%`;
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function AboutMetrics({ metrics }: { metrics: Metrics }) {
  const headline: Array<{
    label: string;
    value: number;
    ci: [number, number];
  }> = [
    { label: "Top-1", value: metrics.top1, ci: metrics.top1_ci },
    { label: "Top-5", value: metrics.top5, ci: metrics.top5_ci },
    { label: "Top-20", value: metrics.top20, ci: metrics.top20_ci },
    { label: "MRR", value: metrics.mrr, ci: metrics.mrr_ci },
  ];

  const baselines = Object.entries(metrics.baselines);
  const slots = Object.entries(metrics.by_slot).sort(
    (a, b) => Number(a[0]) - Number(b[0]),
  );

  return (
    <div className="flex flex-col gap-8">
      <section>
        <h2 className="text-xs font-semibold uppercase tracking-widest text-neutral-500 mb-3">
          Headline metrics (walk-forward)
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {headline.map((m) => (
            <div
              key={m.label}
              className="bg-neutral-900/50 border border-neutral-800 rounded-lg px-4 py-3"
            >
              <div className="text-sm text-neutral-400">{m.label}</div>
              <div className="text-2xl font-semibold tabular-nums mt-1">
                {m.label === "MRR" ? m.value.toFixed(3) : pct(m.value)}
              </div>
              <div className="text-xs text-neutral-500 tabular-nums mt-1">
                {m.label === "MRR"
                  ? `${m.ci[0].toFixed(3)}–${m.ci[1].toFixed(3)}`
                  : `${pct(m.ci[0])}–${pct(m.ci[1])}`}
              </div>
            </div>
          ))}
        </div>
        <p className="text-xs text-neutral-500 mt-2">
          95% bootstrap CI · {metrics.n_slots} held-out slots ·{" "}
          {metrics.holdout_shows ?? "?"} holdout shows
        </p>
        {!metrics.ship_gate_passed && (
          <p className="text-xs text-red-400 mt-2">
            Ship gate failed — this model is deployed with --override.
          </p>
        )}
      </section>

      <section>
        <h2 className="text-xs font-semibold uppercase tracking-widest text-neutral-500 mb-3">
          Baseline comparison
        </h2>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-neutral-400 border-b border-neutral-800">
                <th className="py-2 pr-4">Model</th>
                <th className="py-2 px-4 text-right">Top-1</th>
                <th className="py-2 px-4 text-right">Top-5</th>
                <th className="py-2 px-4 text-right">MRR</th>
              </tr>
            </thead>
            <tbody>
              <tr className="border-b border-neutral-900 font-medium">
                <td className="py-2 pr-4">LightGBM (current)</td>
                <td className="py-2 px-4 text-right tabular-nums">
                  {pct(metrics.top1)}
                </td>
                <td className="py-2 px-4 text-right tabular-nums">
                  {pct(metrics.top5)}
                </td>
                <td className="py-2 px-4 text-right tabular-nums">
                  {metrics.mrr.toFixed(3)}
                </td>
              </tr>
              {baselines.map(([name, b]) => (
                <tr key={name} className="border-b border-neutral-900">
                  <td className="py-2 pr-4 text-neutral-400 capitalize">
                    {name}
                  </td>
                  <td className="py-2 px-4 text-right tabular-nums">
                    {pct(b.top1)}
                  </td>
                  <td className="py-2 px-4 text-right tabular-nums">
                    {pct(b.top5)}
                  </td>
                  <td className="py-2 px-4 text-right tabular-nums">
                    {b.mrr.toFixed(3)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {slots.length > 0 && (
        <section>
          <h2 className="text-xs font-semibold uppercase tracking-widest text-neutral-500 mb-3">
            By slot position
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-neutral-400 border-b border-neutral-800">
                  <th className="py-2 pr-4">Slot</th>
                  <th className="py-2 px-4 text-right">n</th>
                  <th className="py-2 px-4 text-right">Top-1</th>
                  <th className="py-2 px-4 text-right">Top-5</th>
                  <th className="py-2 px-4 text-right">MRR</th>
                </tr>
              </thead>
              <tbody>
                {slots.map(([slot, m]) => (
                  <tr key={slot} className="border-b border-neutral-900">
                    <td className="py-2 pr-4">Slot {slot}</td>
                    <td className="py-2 px-4 text-right tabular-nums text-neutral-500">
                      {m.n}
                    </td>
                    <td className="py-2 px-4 text-right tabular-nums">
                      {pct(m.top1)}
                    </td>
                    <td className="py-2 px-4 text-right tabular-nums">
                      {pct(m.top5)}
                    </td>
                    <td className="py-2 px-4 text-right tabular-nums">
                      {m.mrr.toFixed(3)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section>
        <h2 className="text-xs font-semibold uppercase tracking-widest text-neutral-500 mb-3">
          Training details
        </h2>
        <dl className="text-sm text-neutral-300 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1">
          <div>
            <dt className="inline text-neutral-500">Version: </dt>
            <dd className="inline">{metrics.model_version}</dd>
          </div>
          <div>
            <dt className="inline text-neutral-500">Trained: </dt>
            <dd className="inline">{fmtDate(metrics.trained_at)}</dd>
          </div>
          <div>
            <dt className="inline text-neutral-500">Data: </dt>
            <dd className="inline">{metrics.n_shows_trained_on ?? "?"} shows</dd>
          </div>
          <div>
            <dt className="inline text-neutral-500">Features: </dt>
            <dd className="inline">{metrics.feature_columns.length} columns</dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
