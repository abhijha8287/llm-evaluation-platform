"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Header } from "@/components/Header";
import { ApiError, getProjects, getRuns, getTrends } from "@/lib/api";
import type { RunListItem, RunTrendPoint } from "@/lib/types";

const SERIES_COLORS = ["#f5f5f5", "#38bdf8", "#a78bfa", "#fb923c", "#34d399", "#f87171"];

function formatRunLabel(createdAt: string): string {
  return new Date(createdAt).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// One row per run, one column per model display_name — the shape recharts'
// LineChart wants for "N series over the same x-axis," pivoted from the
// (run, model) point list GET /dashboard/trends returns.
function pivotTrends(points: RunTrendPoint[], valueOf: (p: RunTrendPoint) => number | null) {
  const runOrder: number[] = [];
  const rows = new Map<number, Record<string, string | number>>();
  const modelNames = new Set<string>();

  for (const point of points) {
    if (!rows.has(point.run_id)) {
      rows.set(point.run_id, { run_id: point.run_id, label: formatRunLabel(point.created_at) });
      runOrder.push(point.run_id);
    }
    const value = valueOf(point);
    if (value !== null) {
      rows.get(point.run_id)![point.display_name] = value;
    }
    modelNames.add(point.display_name);
  }

  return {
    data: runOrder.map((id) => rows.get(id)!),
    modelNames: [...modelNames],
  };
}

function TrendChart({
  title,
  points,
  valueOf,
}: {
  title: string;
  points: RunTrendPoint[];
  valueOf: (p: RunTrendPoint) => number | null;
}) {
  const { data, modelNames } = useMemo(() => pivotTrends(points, valueOf), [points, valueOf]);

  if (data.length === 0) {
    return (
      <section>
        <h2 className="text-sm font-medium text-neutral-300 mb-3">{title}</h2>
        <p className="text-sm text-neutral-500">No completed runs with data yet.</p>
      </section>
    );
  }

  return (
    <section>
      <h2 className="text-sm font-medium text-neutral-300 mb-3">{title}</h2>
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
            <XAxis dataKey="label" tick={{ fill: "#a3a3a3", fontSize: 11 }} />
            <YAxis tick={{ fill: "#a3a3a3", fontSize: 11 }} />
            <Tooltip contentStyle={{ background: "#171717", border: "1px solid #404040", fontSize: 12 }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {modelNames.map((name, i) => (
              <Line
                key={name}
                type="monotone"
                dataKey={name}
                stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                connectNulls
                dot={{ r: 3 }}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function statusColor(status: RunListItem["status"]): string {
  switch (status) {
    case "completed":
      return "text-emerald-400";
    case "failed":
      return "text-red-400";
    case "running":
      return "text-sky-400";
    default:
      return "text-neutral-400";
  }
}

export default function ExperimentHistoryPage() {
  const [runs, setRuns] = useState<RunListItem[] | null>(null);
  const [trends, setTrends] = useState<RunTrendPoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getProjects()
      .then(async (projects) => {
        if (projects.length === 0) {
          setRuns([]);
          setTrends([]);
          return;
        }
        const projectId = projects[0].id;
        const [runsResult, trendsResult] = await Promise.all([getRuns(projectId), getTrends(projectId)]);
        setRuns(runsResult);
        setTrends(trendsResult);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load experiment history.");
      });
  }, []);

  return (
    <>
      <Header />
      <main className="flex-1 px-6 py-8 max-w-5xl w-full mx-auto space-y-10">
        <div>
          <h1 className="text-xl font-semibold">Experiment History</h1>
          <p className="text-sm text-neutral-400 mt-1">
            Every evaluation run for this project, plus trend charts across runs. Regression runs are
            excluded (see Regression Results) — they intentionally vary the prompt, not the model, so
            they&apos;d be noise here.
          </p>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}
        {runs === null && !error && <p className="text-sm text-neutral-400">Loading…</p>}

        {runs && (
          <section>
            <h2 className="text-sm font-medium text-neutral-300 mb-3">Runs</h2>
            {runs.length === 0 ? (
              <p className="text-sm text-neutral-400">
                No runs yet — trigger one from the leaderboard&apos;s &quot;Trigger a new evaluation
                run&quot; panel.
              </p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm border-collapse">
                  <thead>
                    <tr className="text-left text-neutral-400 border-b border-neutral-800">
                      <th className="py-2 pr-4 font-medium">Run</th>
                      <th className="py-2 pr-4 font-medium">Status</th>
                      <th className="py-2 pr-4 font-medium">Responses</th>
                      <th className="py-2 pr-4 font-medium">Created</th>
                      <th className="py-2 pr-4 font-medium">Completed</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((run) => (
                      <tr key={run.id} className="border-b border-neutral-900">
                        <td className="py-3 pr-4 tabular-nums">#{run.id}</td>
                        <td className={`py-3 pr-4 ${statusColor(run.status)}`}>{run.status}</td>
                        <td className="py-3 pr-4 tabular-nums text-neutral-400">{run.response_count}</td>
                        <td className="py-3 pr-4 text-neutral-400">
                          {new Date(run.created_at).toLocaleString()}
                        </td>
                        <td className="py-3 pr-4 text-neutral-400">
                          {run.completed_at ? new Date(run.completed_at).toLocaleString() : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        )}

        {trends && (
          <>
            <TrendChart title="Latency Trend (ms)" points={trends} valueOf={(p) => p.avg_latency_ms} />
            <TrendChart title="Cost Analysis (USD)" points={trends} valueOf={(p) => p.avg_cost_usd} />
            <TrendChart
              title="Pass Rate"
              points={trends}
              valueOf={(p) => (p.pass_rate === null ? null : p.pass_rate * 100)}
            />
            <TrendChart
              title="Faithfulness Trend"
              points={trends}
              valueOf={(p) => p.metric_averages.faithfulness ?? null}
            />
          </>
        )}
      </main>
    </>
  );
}
