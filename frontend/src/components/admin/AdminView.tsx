"use client";

import { useEffect, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { RequireAuth } from "@/components/auth/AuthProvider";
import { getLatency, type LatencyReport } from "@/lib/api";

export function AdminView() {
  return (
    <RequireAuth>
      <div className="flex min-h-screen flex-col">
        <AppHeader />
        <Admin />
      </div>
    </RequireAuth>
  );
}

const ms = (v: number | null | undefined) =>
  v == null ? "–" : v >= 1000 ? `${(v / 1000).toFixed(2)} s` : `${Math.round(v)} ms`;

function Admin() {
  const [days, setDays] = useState(7);
  const [data, setData] = useState<LatencyReport | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getLatency(days)
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [days]);

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Latency</h1>
          <p className="text-sm text-muted">
            Per-answer timings across all users. Only timings and question types are shown, never what was said.
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm">
          Period
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-lg border border-black/15 bg-background px-2 py-1.5 dark:border-white/15"
          >
            <option value={1}>Last 24 hours</option>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
          </select>
        </label>
      </div>

      {error && <p role="alert" className="text-red-600 dark:text-red-400">{error}</p>}
      {data && (
        <>
          <p className="text-sm text-muted">
            {data.answers} answers ·{" "}
            {Object.entries(data.statuses)
              .map(([k, v]) => `${v} ${k}`)
              .join(" · ") || "none yet"}
          </p>

          <section className="overflow-x-auto rounded-xl border border-black/10 bg-surface dark:border-white/10">
            <table className="w-full text-sm">
              <thead className="text-left text-muted">
                <tr className="border-b border-black/10 dark:border-white/10">
                  <th className="px-4 py-2 font-medium">Stage</th>
                  <th className="px-4 py-2 font-medium">Median</th>
                  <th className="px-4 py-2 font-medium">p90</th>
                  <th className="px-4 py-2 font-medium">p95</th>
                  <th className="px-4 py-2 font-medium">Max</th>
                  <th className="px-4 py-2 font-medium">Samples</th>
                </tr>
              </thead>
              <tbody>
                {data.metrics.map((m) => (
                  <tr key={m.key} className="border-b border-black/5 last:border-0 dark:border-white/5">
                    <td className="px-4 py-2 font-medium">{m.label}</td>
                    <td className="px-4 py-2">{ms(m.summary?.p50)}</td>
                    <td className="px-4 py-2">{ms(m.summary?.p90)}</td>
                    <td className="px-4 py-2">{ms(m.summary?.p95)}</td>
                    <td className="px-4 py-2">{ms(m.summary?.max)}</td>
                    <td className="px-4 py-2 text-muted">{m.summary?.count ?? 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          {data.daily.length > 0 && (
            <section className="flex flex-col gap-2">
              <h2 className="font-semibold">Question end → first words, by day</h2>
              <ul className="flex flex-col gap-1 text-sm">
                {data.daily.map((d) => (
                  <li key={d.day} className="flex flex-wrap gap-x-4">
                    <span className="w-28 font-medium">{d.day}</span>
                    <span>median {ms(d.p50)}</span>
                    <span>p95 {ms(d.p95)}</span>
                    <span className="text-muted">{d.count} answers</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="flex flex-col gap-2">
            <h2 className="font-semibold">Most recent answers</h2>
            <div className="overflow-x-auto rounded-xl border border-black/10 bg-surface dark:border-white/10">
              <table className="w-full text-sm">
                <thead className="text-left text-muted">
                  <tr className="border-b border-black/10 dark:border-white/10">
                    <th className="px-4 py-2 font-medium">When</th>
                    <th className="px-4 py-2 font-medium">Type</th>
                    <th className="px-4 py-2 font-medium">Status</th>
                    <th className="px-4 py-2 font-medium">End → words</th>
                    <th className="px-4 py-2 font-medium">STT</th>
                    <th className="px-4 py-2 font-medium">AI first token</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent.map((r, i) => (
                    <tr key={i} className="border-b border-black/5 last:border-0 dark:border-white/5">
                      <td className="px-4 py-2">{new Date(r.at).toLocaleString()}</td>
                      <td className="px-4 py-2">{r.question_type ?? "–"}</td>
                      <td className="px-4 py-2">{r.status}</td>
                      <td className="px-4 py-2">{ms(r.speech_end_to_first_token_ms)}</td>
                      <td className="px-4 py-2">{ms(r.stt_ms)}</td>
                      <td className="px-4 py-2">{ms(r.llm_first_token_ms)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </main>
  );
}
