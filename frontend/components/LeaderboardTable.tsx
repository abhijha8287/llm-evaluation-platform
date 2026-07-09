import type { LeaderboardEntry } from "@/lib/types";

function formatMetric(value: number | undefined): string {
  if (value === undefined) return "—";
  return value.toFixed(2);
}

function formatLatency(ms: number | null): string {
  if (ms === null) return "—";
  return `${Math.round(ms)}ms`;
}

function formatCost(usd: number | null): string {
  if (usd === null) return "—";
  return `$${usd.toFixed(4)}`;
}

// D6: null means "unavailable" (model missing from LiteLLM's pricing map, or
// no successful responses yet) — rendered as an em dash, never as $0, which
// would misleadingly imply the model is free to run.
export function LeaderboardTable({ entries }: { entries: LeaderboardEntry[] }) {
  if (entries.length === 0) {
    return (
      <p className="text-neutral-400 text-sm">
        No models yet. The demo seeds a few on first startup — check back shortly.
      </p>
    );
  }

  const sorted = [...entries].sort((a, b) => b.elo_rating - a.elo_rating);

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="text-left text-neutral-400 border-b border-neutral-800">
            <th className="py-2 pr-4 font-medium">Model</th>
            <th className="py-2 pr-4 font-medium">Elo</th>
            <th className="py-2 pr-4 font-medium">Runs</th>
            <th className="py-2 pr-4 font-medium">Faithfulness</th>
            <th className="py-2 pr-4 font-medium">Toxicity</th>
            <th className="py-2 pr-4 font-medium">Bias</th>
            <th className="py-2 pr-4 font-medium">Answer Relevancy</th>
            <th className="py-2 pr-4 font-medium">Avg Latency</th>
            <th className="py-2 pr-4 font-medium">Avg Cost</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((entry) => (
            <tr key={entry.model_id} className="border-b border-neutral-900">
              <td className="py-3 pr-4">
                <div className="font-medium">{entry.display_name}</div>
                <div className="text-neutral-500 text-xs">{entry.provider}</div>
              </td>
              <td className="py-3 pr-4 tabular-nums">{Math.round(entry.elo_rating)}</td>
              <td className="py-3 pr-4 tabular-nums text-neutral-400">{entry.response_count}</td>
              <td className="py-3 pr-4 tabular-nums">{formatMetric(entry.metric_averages.faithfulness)}</td>
              <td className="py-3 pr-4 tabular-nums">{formatMetric(entry.metric_averages.toxicity)}</td>
              <td className="py-3 pr-4 tabular-nums">{formatMetric(entry.metric_averages.bias)}</td>
              <td className="py-3 pr-4 tabular-nums">
                {formatMetric(entry.metric_averages.answer_relevancy)}
              </td>
              <td className="py-3 pr-4 tabular-nums">{formatLatency(entry.avg_latency_ms)}</td>
              <td className="py-3 pr-4 tabular-nums">{formatCost(entry.avg_cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
