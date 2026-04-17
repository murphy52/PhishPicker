"use client";

import Link from "next/link";
import useSWR from "swr";
import { AboutMetrics, type Metrics } from "@/components/AboutMetrics";

const fetcher = async (url: string): Promise<Metrics | null> => {
  const res = await fetch(url);
  if (res.status === 503) return null; // metrics not yet produced
  if (!res.ok) throw new Error(`about ${res.status}`);
  return res.json();
};

export default function AboutPage() {
  const { data, error, isLoading } = useSWR<Metrics | null>("/api/about", fetcher);

  return (
    <div className="min-h-dvh bg-neutral-950 text-neutral-100 flex flex-col">
      <header className="px-4 pt-6 pb-4 border-b border-neutral-900">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-bold tracking-tight">About</h1>
          <Link
            href="/"
            className="text-sm text-indigo-400 hover:text-indigo-300"
          >
            ← back
          </Link>
        </div>
        <p className="text-sm text-neutral-400 mt-1">
          Walk-forward evaluation, baselines, per-slot breakdown.
        </p>
      </header>

      <main className="flex-1 px-4 py-6 max-w-4xl w-full mx-auto">
        {isLoading && <p className="text-sm text-neutral-500">Loading…</p>}
        {error && (
          <p className="text-sm text-red-400">
            Failed to load metrics — check the API.
          </p>
        )}
        {!isLoading && !error && data === null && (
          <div className="flex flex-col gap-3 py-12 items-start">
            <p className="text-base">No metrics yet.</p>
            <p className="text-sm text-neutral-500">
              The LightGBM ranker has not been trained on this deployment. The
              API is serving predictions from the heuristic scorer. Run{" "}
              <code className="text-xs bg-neutral-900 px-1.5 py-0.5 rounded">
                phishpicker train run
              </code>{" "}
              on the Mac mini to ship a model.
            </p>
          </div>
        )}
        {data && <AboutMetrics metrics={data} />}
      </main>
    </div>
  );
}
