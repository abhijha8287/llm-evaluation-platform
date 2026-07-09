"use client";

import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Header } from "@/components/Header";
import { ApiError, getLeaderboard } from "@/lib/api";
import type { LeaderboardEntry } from "@/lib/types";

const METRIC_LABELS: Record<string, string> = {
  faithfulness: "Faithfulness",
  toxicity: "Toxicity",
  bias: "Bias",
  answer_relevancy: "Answer Relevancy",
};

const SERIES_COLORS = ["#f5f5f5", "#38bdf8", "#a78bfa", "#fb923c", "#34d399", "#f87171"];

function buildRadarData(entries: LeaderboardEntry[]) {
  const metricNames = Object.keys(METRIC_LABELS);
  return metricNames.map((metric) => {
    const row: Record<string, string | number> = { metric: METRIC_LABELS[metric] };
    for (const entry of entries) {
      row[entry.display_name] = entry.metric_averages[metric] ?? 0;
    }
    return row;
  });
}

export default function ModelComparisonPage() {
  const [entries, setEntries] = useState<LeaderboardEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getLeaderboard()
      .then(setEntries)
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load leaderboard.");
      });
  }, []);

  return (
    <>
      <Header />
      <main className="flex-1 px-6 py-8 max-w-5xl w-full mx-auto space-y-10">
        <div>
          <h1 className="text-xl font-semibold">Model Comparison</h1>
          <p className="text-sm text-neutral-400 mt-1">
            Same metric averages as the leaderboard (D9: judge failures excluded, never counted as a real
            0), visualized across all four DeepEval metrics at once.
          </p>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}
        {entries === null && !error && <p className="text-sm text-neutral-400">Loading…</p>}
        {entries && entries.length === 0 && <p className="text-sm text-neutral-400">No models yet.</p>}

        {entries && entries.length > 0 && (
          <>
            <section>
              <h2 className="text-sm font-medium text-neutral-300 mb-3">Metric radar</h2>
              <div className="h-96 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <RadarChart data={buildRadarData(entries)}>
                    <PolarGrid stroke="#404040" />
                    <PolarAngleAxis dataKey="metric" tick={{ fill: "#a3a3a3", fontSize: 12 }} />
                    <PolarRadiusAxis tick={{ fill: "#737373", fontSize: 10 }} />
                    {entries.map((entry, i) => (
                      <Radar
                        key={entry.model_id}
                        name={entry.display_name}
                        dataKey={entry.display_name}
                        stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                        fill={SERIES_COLORS[i % SERIES_COLORS.length]}
                        fillOpacity={0.15}
                      />
                    ))}
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Tooltip
                      contentStyle={{ background: "#171717", border: "1px solid #404040", fontSize: 12 }}
                    />
                  </RadarChart>
                </ResponsiveContainer>
              </div>
            </section>

            <section>
              <h2 className="text-sm font-medium text-neutral-300 mb-3">Average latency (ms)</h2>
              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={entries.map((e) => ({ name: e.display_name, value: e.avg_latency_ms ?? 0 }))}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
                    <XAxis dataKey="name" tick={{ fill: "#a3a3a3", fontSize: 11 }} />
                    <YAxis tick={{ fill: "#a3a3a3", fontSize: 11 }} />
                    <Tooltip
                      contentStyle={{ background: "#171717", border: "1px solid #404040", fontSize: 12 }}
                    />
                    <Bar dataKey="value" fill="#38bdf8" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </section>

            <section>
              <h2 className="text-sm font-medium text-neutral-300 mb-3">Average cost (USD)</h2>
              <div className="h-64 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={entries.map((e) => ({ name: e.display_name, value: e.avg_cost_usd ?? 0 }))}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
                    <XAxis dataKey="name" tick={{ fill: "#a3a3a3", fontSize: 11 }} />
                    <YAxis tick={{ fill: "#a3a3a3", fontSize: 11 }} />
                    <Tooltip
                      contentStyle={{ background: "#171717", border: "1px solid #404040", fontSize: 12 }}
                    />
                    <Bar dataKey="value" fill="#34d399" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </section>
          </>
        )}
      </main>
    </>
  );
}
