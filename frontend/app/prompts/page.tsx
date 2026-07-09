"use client";

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { Header } from "@/components/Header";
import { useAuth } from "@/lib/auth";
import {
  ApiError,
  createPromptTemplate,
  createPromptVersion,
  createRegressionRun,
  getPromptTemplates,
  getProjects,
  getRunContext,
} from "@/lib/api";
import type { PromptTemplate, RunContext } from "@/lib/types";

function NewVersionForm({ token, template, onCreated }: { token: string; template: PromptTemplate; onCreated: () => void }) {
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await createPromptVersion(token, template.id, content);
      setContent("");
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create version.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 space-y-2">
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Answer the question directly: {question}"
        rows={3}
        className="w-full rounded border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm text-neutral-100 placeholder:text-neutral-600"
      />
      {error && <p className="text-xs text-red-400">{error}</p>}
      <button
        type="submit"
        disabled={submitting || content.trim().length === 0}
        className="rounded bg-neutral-100 text-neutral-900 px-3 py-1.5 text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-white transition-colors"
      >
        Add version
      </button>
      <p className="text-xs text-neutral-500">
        Must contain the literal <code>{"{question}"}</code> placeholder — validated at creation time
        (D7/D8), not mid-run.
      </p>
    </form>
  );
}

function RunRegressionForm({
  token,
  template,
  runContext,
}: {
  token: string;
  template: PromptTemplate;
  runContext: RunContext;
}) {
  const [promptVersionId, setPromptVersionId] = useState<number | "">(
    template.versions.at(-1)?.id ?? "",
  );
  const [baselineVersionId, setBaselineVersionId] = useState<number | "">("");
  const [modelId, setModelId] = useState<number | "">(runContext.models[0]?.id ?? "");
  const [status, setStatus] = useState<"idle" | "submitting" | "done" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (promptVersionId === "" || modelId === "") return;
    setStatus("submitting");
    setMessage(null);
    try {
      await createRegressionRun(token, {
        prompt_version_id: promptVersionId,
        dataset_version_id: runContext.dataset_version_id,
        model_id: modelId,
        baseline_prompt_version_id: baselineVersionId === "" ? null : baselineVersionId,
      });
      setStatus("done");
    } catch (err) {
      setStatus("error");
      setMessage(err instanceof ApiError ? err.message : "Failed to trigger regression run.");
    }
  }

  if (template.versions.length === 0) {
    return <p className="text-xs text-neutral-500 mt-3">Add a version before running a regression test.</p>;
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 flex flex-wrap items-end gap-3">
      <label className="text-xs text-neutral-400">
        Version
        <select
          value={promptVersionId}
          onChange={(e) => setPromptVersionId(Number(e.target.value))}
          className="block mt-1 rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm text-neutral-100"
        >
          {template.versions.map((v) => (
            <option key={v.id} value={v.id}>
              v{v.version_number}
            </option>
          ))}
        </select>
      </label>
      <label className="text-xs text-neutral-400">
        Baseline (optional)
        <select
          value={baselineVersionId}
          onChange={(e) => setBaselineVersionId(e.target.value === "" ? "" : Number(e.target.value))}
          className="block mt-1 rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm text-neutral-100"
        >
          <option value="">None</option>
          {template.versions.map((v) => (
            <option key={v.id} value={v.id}>
              v{v.version_number}
            </option>
          ))}
        </select>
      </label>
      <label className="text-xs text-neutral-400">
        Model
        <select
          value={modelId}
          onChange={(e) => setModelId(Number(e.target.value))}
          className="block mt-1 rounded border border-neutral-800 bg-neutral-900 px-2 py-1 text-sm text-neutral-100"
        >
          {runContext.models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.display_name}
            </option>
          ))}
        </select>
      </label>
      <button
        type="submit"
        disabled={status === "submitting"}
        className="rounded bg-neutral-100 text-neutral-900 px-3 py-1.5 text-xs font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-white transition-colors"
      >
        Run regression test
      </button>
      {status === "done" && (
        <span className="text-xs text-emerald-400">
          Dispatched —{" "}
          <Link href={`/regression?prompt_template_id=${template.id}`} className="underline">
            view results
          </Link>
        </span>
      )}
      {status === "error" && <span className="text-xs text-red-400">{message}</span>}
    </form>
  );
}

export default function PromptTestingPage() {
  const { token } = useAuth();
  const [projectId, setProjectId] = useState<number | null>(null);
  const [templates, setTemplates] = useState<PromptTemplate[] | null>(null);
  const [runContext, setRunContext] = useState<RunContext | null>(null);
  const [newTemplateName, setNewTemplateName] = useState("");
  const [error, setError] = useState<string | null>(null);

  function reload() {
    getProjects()
      .then((projects) => {
        if (projects.length === 0) return;
        setProjectId(projects[0].id);
        return getPromptTemplates(projects[0].id).then(setTemplates);
      })
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load prompt templates.");
      });
  }

  useEffect(reload, []);

  useEffect(() => {
    if (!token) return;
    getRunContext(token)
      .then(setRunContext)
      .catch(() => {
        // Non-fatal — the regression-trigger form just stays hidden.
      });
  }, [token]);

  async function handleCreateTemplate(e: FormEvent) {
    e.preventDefault();
    if (!token || projectId === null || newTemplateName.trim().length === 0) return;
    try {
      await createPromptTemplate(token, { project_id: projectId, name: newTemplateName.trim() });
      setNewTemplateName("");
      reload();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to create template.");
    }
  }

  return (
    <>
      <Header />
      <main className="flex-1 px-6 py-8 max-w-5xl w-full mx-auto space-y-6">
        <div>
          <h1 className="text-xl font-semibold">Prompt Testing</h1>
          <p className="text-sm text-neutral-400 mt-1">
            Versioned prompt templates. A regression run re-scores a version against the same DeepEval
            metrics (D8&apos;s shared EvaluationService) and diffs it against a baseline version&apos;s
            scores (D7).
          </p>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}

        {token ? (
          <form onSubmit={handleCreateTemplate} className="flex items-center gap-2">
            <input
              value={newTemplateName}
              onChange={(e) => setNewTemplateName(e.target.value)}
              placeholder="New template name"
              className="rounded border border-neutral-800 bg-neutral-900 px-3 py-1.5 text-sm text-neutral-100 placeholder:text-neutral-600"
            />
            <button
              type="submit"
              disabled={newTemplateName.trim().length === 0}
              className="rounded bg-neutral-100 text-neutral-900 px-3 py-1.5 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-white transition-colors"
            >
              Create template
            </button>
          </form>
        ) : (
          <p className="text-sm text-neutral-400">
            <Link href="/login" className="text-neutral-100 underline">
              Log in
            </Link>{" "}
            to create prompt templates and versions.
          </p>
        )}

        {templates === null && !error && <p className="text-sm text-neutral-400">Loading…</p>}
        {templates && templates.length === 0 && (
          <p className="text-sm text-neutral-400">No prompt templates yet.</p>
        )}

        <div className="grid gap-4">
          {templates?.map((template) => (
            <div key={template.id} className="rounded border border-neutral-800 p-4">
              <div className="flex items-center justify-between">
                <div className="font-medium">{template.name}</div>
                <Link
                  href={`/regression?prompt_template_id=${template.id}`}
                  className="text-xs text-neutral-400 hover:text-neutral-100 underline"
                >
                  View regression history
                </Link>
              </div>
              <ul className="mt-2 space-y-1">
                {template.versions.map((v) => (
                  <li key={v.id} className="text-xs text-neutral-400">
                    <span className="text-neutral-300">v{v.version_number}</span>: {v.content}
                  </li>
                ))}
                {template.versions.length === 0 && (
                  <li className="text-xs text-neutral-500">No versions yet.</li>
                )}
              </ul>
              {token && <NewVersionForm token={token} template={template} onCreated={reload} />}
              {token && runContext && <RunRegressionForm token={token} template={template} runContext={runContext} />}
            </div>
          ))}
        </div>
      </main>
    </>
  );
}
