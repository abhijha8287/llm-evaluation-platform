"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Header } from "@/components/Header";
import { ApiError, getDatasetQuestions, getProjectDatasets, getProjects } from "@/lib/api";
import type { Dataset, DatasetQuestion } from "@/lib/types";

function QuestionsPanel({ datasetId }: { datasetId: number }) {
  const [questions, setQuestions] = useState<DatasetQuestion[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDatasetQuestions(datasetId)
      .then(setQuestions)
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load questions.");
      });
  }, [datasetId]);

  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (questions === null) return <p className="text-sm text-neutral-400">Loading questions…</p>;
  if (questions.length === 0) return <p className="text-sm text-neutral-400">No questions in this dataset.</p>;

  return (
    <ul className="space-y-2">
      {questions.map((q) => (
        <li key={q.id} className="text-sm border-t border-neutral-900 pt-2">
          <div className="flex items-center gap-2">
            <span className="text-xs uppercase tracking-wide text-neutral-500">{q.type}</span>
            {q.has_retrieval_context && (
              <span className="text-xs rounded bg-neutral-800 px-1.5 py-0.5 text-neutral-300">
                has retrieval context
              </span>
            )}
          </div>
          <div className="text-neutral-200 mt-1">{q.text}</div>
        </li>
      ))}
    </ul>
  );
}

function DatasetsContent() {
  const searchParams = useSearchParams();
  const projectIdParam = searchParams.get("project_id");

  const [projectId, setProjectId] = useState<number | null>(projectIdParam ? Number(projectIdParam) : null);
  const [datasets, setDatasets] = useState<Dataset[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // No project_id in the URL — default to the demo's single seeded project
  // (D10), rather than forcing the user through /projects first.
  useEffect(() => {
    if (projectId !== null) return;
    getProjects()
      .then((projects) => {
        if (projects.length > 0) setProjectId(projects[0].id);
        else setError("No projects found.");
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load projects.");
      });
  }, [projectId]);

  useEffect(() => {
    if (projectId === null) return;
    getProjectDatasets(projectId)
      .then(setDatasets)
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load datasets.");
      });
  }, [projectId]);

  return (
    <main className="flex-1 px-6 py-8 max-w-5xl w-full mx-auto space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Datasets</h1>
        <p className="text-sm text-neutral-400 mt-1">
          Every Run pins a specific dataset version (D5) so every model in that run is scored on the
          identical question set.
        </p>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}
      {datasets === null && !error && <p className="text-sm text-neutral-400">Loading…</p>}
      {datasets && datasets.length === 0 && <p className="text-sm text-neutral-400">No datasets yet.</p>}

      <div className="grid gap-3">
        {datasets?.map((dataset) => (
          <div key={dataset.id} className="rounded border border-neutral-800 p-4">
            <button
              className="w-full text-left"
              onClick={() => setExpandedId(expandedId === dataset.id ? null : dataset.id)}
            >
              <div className="font-medium">{dataset.name}</div>
              <div className="text-xs text-neutral-500 mt-1">
                {dataset.versions.length} version{dataset.versions.length === 1 ? "" : "s"} — click to view
                questions
              </div>
            </button>

            {/* TODOS.md item 3: every version pinned by a Run (D5) or
                RegressionRun (D7) shown individually, not just a collapsed
                count — the versioning system is a real methodology
                strength, worth being visible here. */}
            <ul className="mt-3 flex flex-wrap gap-2">
              {[...dataset.versions]
                .sort((a, b) => b.version_number - a.version_number)
                .map((v) => (
                  <li
                    key={v.id}
                    className="text-xs rounded border border-neutral-800 px-2 py-1 text-neutral-400"
                  >
                    v{v.version_number} · {v.sample_size} questions · seeded{" "}
                    {new Date(v.created_at).toLocaleDateString()}
                  </li>
                ))}
              {dataset.versions.length === 0 && (
                <li className="text-xs text-neutral-500">No versions yet.</li>
              )}
            </ul>

            {expandedId === dataset.id && (
              <div className="mt-3">
                <QuestionsPanel datasetId={dataset.id} />
              </div>
            )}
          </div>
        ))}
      </div>
    </main>
  );
}

export default function DatasetsPage() {
  return (
    <>
      <Header />
      <Suspense fallback={<main className="flex-1 px-6 py-8 text-sm text-neutral-400">Loading…</main>}>
        <DatasetsContent />
      </Suspense>
    </>
  );
}
