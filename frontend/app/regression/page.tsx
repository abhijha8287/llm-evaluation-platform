"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Header } from "@/components/Header";
import {
  ApiError,
  getPromptTemplates,
  getProjects,
  getRegressionRun,
  getRegressionRuns,
} from "@/lib/api";
import type { PromptTemplate, RegressionRunDetail, RegressionRunResponse } from "@/lib/types";

function statusColor(status: RegressionRunResponse["status"]): string {
  switch (status) {
    case "completed":
      return "text-emerald-400";
    case "failed":
      return "text-red-400";
    case "not_comparable":
      return "text-amber-400";
    case "running":
      return "text-sky-400";
    default:
      return "text-neutral-400";
  }
}

function DeltaCell({ delta }: { delta: number | null }) {
  if (delta === null) return <span className="text-neutral-500">—</span>;
  const color = delta > 0 ? "text-emerald-400" : delta < 0 ? "text-red-400" : "text-neutral-400";
  return (
    <span className={`${color} tabular-nums`}>
      {delta > 0 ? "+" : ""}
      {delta.toFixed(3)}
    </span>
  );
}

function RegressionRunCard({ run }: { run: RegressionRunResponse }) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<RegressionRunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  function toggle() {
    if (!expanded && detail === null) {
      getRegressionRun(run.id)
        .then(setDetail)
        .catch((err: unknown) => {
          setError(err instanceof ApiError ? err.message : "Failed to load results.");
        });
    }
    setExpanded(!expanded);
  }

  return (
    <div className="rounded border border-neutral-800 p-4">
      <button className="w-full text-left flex items-center justify-between" onClick={toggle}>
        <div>
          <span className="font-medium">Regression run #{run.id}</span>{" "}
          <span className={`text-xs ${statusColor(run.status)}`}>{run.status}</span>
        </div>
        <span className="text-xs text-neutral-500">
          {run.baseline_prompt_version_id ? "vs. baseline" : "no baseline"} · {expanded ? "hide" : "show"}{" "}
          results
        </span>
      </button>

      {expanded && (
        <div className="mt-3">
          {error && <p className="text-xs text-red-400">{error}</p>}
          {detail === null && !error && <p className="text-xs text-neutral-400">Loading…</p>}
          {detail && detail.results.length === 0 && (
            <p className="text-xs text-neutral-500">No results recorded yet.</p>
          )}
          {detail && detail.results.length > 0 && (
            <table className="w-full text-xs border-collapse">
              <thead>
                <tr className="text-left text-neutral-500 border-b border-neutral-900">
                  <th className="py-1.5 pr-4 font-medium">Question</th>
                  <th className="py-1.5 pr-4 font-medium">Metric</th>
                  <th className="py-1.5 pr-4 font-medium">Score</th>
                  <th className="py-1.5 pr-4 font-medium">Δ vs. baseline</th>
                </tr>
              </thead>
              <tbody>
                {detail.results.map((r, i) => (
                  <tr key={i} className="border-b border-neutral-950">
                    <td className="py-1.5 pr-4 tabular-nums text-neutral-400">#{r.question_id}</td>
                    <td className="py-1.5 pr-4 text-neutral-300">{r.metric_name}</td>
                    <td className="py-1.5 pr-4 tabular-nums">{r.score === null ? "—" : r.score.toFixed(3)}</td>
                    <td className="py-1.5 pr-4">
                      <DeltaCell delta={r.delta_from_baseline} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function RegressionResultsContent() {
  const searchParams = useSearchParams();
  const paramTemplateId = searchParams.get("prompt_template_id");

  const [templates, setTemplates] = useState<PromptTemplate[] | null>(null);
  const [templateId, setTemplateId] = useState<number | null>(
    paramTemplateId ? Number(paramTemplateId) : null,
  );
  const [runs, setRuns] = useState<RegressionRunResponse[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getProjects()
      .then((projects) => {
        if (projects.length === 0) return;
        return getPromptTemplates(projects[0].id).then((result) => {
          setTemplates(result);
          if (templateId === null && result.length > 0) setTemplateId(result[0].id);
        });
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load prompt templates.");
      });
    // Only run once on mount — templateId is intentionally not a dependency
    // so this doesn't refetch the template list every time the user picks a
    // different template from the dropdown below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (templateId === null) return;
    getRegressionRuns(templateId)
      .then(setRuns)
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load regression runs.");
      });
  }, [templateId]);

  return (
    <main className="flex-1 px-6 py-8 max-w-5xl w-full mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Regression Results</h1>
        <p className="text-sm text-neutral-400 mt-1">
          A run whose baseline was pinned to a different dataset version is marked{" "}
          <span className="text-amber-400">not_comparable</span> (D7), never silently diffed.
        </p>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {templates && templates.length > 0 && (
        <label className="text-xs text-neutral-400 block">
          Prompt template
          <select
            value={templateId ?? ""}
            onChange={(e) => setTemplateId(Number(e.target.value))}
            className="block mt-1 rounded border border-neutral-800 bg-neutral-900 px-2 py-1.5 text-sm text-neutral-100"
          >
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
      )}

      {templates && templates.length === 0 && (
        <p className="text-sm text-neutral-400">
          No prompt templates yet — create one on the Prompt Testing page first.
        </p>
      )}

      {runs === null && templateId !== null && !error && (
        <p className="text-sm text-neutral-400">Loading…</p>
      )}
      {runs && runs.length === 0 && (
        <p className="text-sm text-neutral-400">No regression runs for this template yet.</p>
      )}

      <div className="grid gap-3">
        {runs?.map((run) => (
          <RegressionRunCard key={run.id} run={run} />
        ))}
      </div>
    </main>
  );
}

export default function RegressionResultsPage() {
  return (
    <>
      <Header />
      <Suspense fallback={<main className="flex-1 px-6 py-8 text-sm text-neutral-400">Loading…</main>}>
        <RegressionResultsContent />
      </Suspense>
    </>
  );
}
