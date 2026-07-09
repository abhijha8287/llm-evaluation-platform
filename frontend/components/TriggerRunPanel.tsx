"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuth } from "@/lib/auth";
import { ApiError, createRun, getRun, getRunContext } from "@/lib/api";
import type { RunContext } from "@/lib/types";

type PanelState =
  | { status: "loading-context" }
  | { status: "ready"; context: RunContext; selectedModelIds: number[] }
  | { status: "running"; runId: number }
  | { status: "done" }
  | { status: "error"; message: string };

const POLL_INTERVAL_MS = 2000;

export function TriggerRunPanel({ onRunComplete }: { onRunComplete: () => void }) {
  const { token } = useAuth();
  const [state, setState] = useState<PanelState>({ status: "loading-context" });
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!token) return;
    let cancelled = false;

    getRunContext(token)
      .then((context) => {
        if (cancelled) return;
        setState({
          status: "ready",
          context,
          selectedModelIds: context.models.map((m) => m.id),
        });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({
          status: "error",
          message: err instanceof ApiError ? err.message : "Failed to load run context.",
        });
      });

    return () => {
      cancelled = true;
    };
  }, [token]);

  // Extracted so the effect's dependency array is a plain variable, not a
  // conditional expression ESLint can't statically check.
  const runningRunId = state.status === "running" ? state.runId : null;

  // Phase 5: POST /runs returns immediately with status "running" — the
  // Celery chord processes it asynchronously. Poll GET /runs/{id} until it
  // reaches a terminal state, then stop.
  useEffect(() => {
    if (runningRunId === null) {
      if (pollTimer.current) {
        clearInterval(pollTimer.current);
        pollTimer.current = null;
      }
      return;
    }

    pollTimer.current = setInterval(async () => {
      try {
        const run = await getRun(runningRunId);
        if (run.status === "completed" || run.status === "failed") {
          if (pollTimer.current) clearInterval(pollTimer.current);
          setState({ status: "done" });
          onRunComplete();
        }
        // "pending"/"running" — keep polling.
      } catch (err) {
        if (pollTimer.current) clearInterval(pollTimer.current);
        setState({
          status: "error",
          message: err instanceof ApiError ? err.message : "Failed to check run status.",
        });
      }
    }, POLL_INTERVAL_MS);

    return () => {
      if (pollTimer.current) clearInterval(pollTimer.current);
    };
    // onRunComplete is a stable useCallback from the parent (HomePage's
    // refresh) — included so exhaustive-deps is satisfied without
    // suppression, and safe since a stable reference never re-arms the timer.
  }, [runningRunId, onRunComplete]);

  if (!token) {
    return (
      <div className="rounded border border-neutral-800 p-4 text-sm text-neutral-400">
        <Link href="/login" className="text-neutral-100 underline">
          Log in
        </Link>{" "}
        to trigger a new evaluation run.
      </div>
    );
  }

  if (state.status === "loading-context") {
    return <div className="text-sm text-neutral-400">Loading…</div>;
  }

  if (state.status === "error") {
    return <div className="text-sm text-red-400">{state.message}</div>;
  }

  if (state.status === "running") {
    return (
      <div className="text-sm text-neutral-400">
        Running evaluation — dispatched to the async pipeline (one task per question×model pair). This
        calls real providers and a judge model, so it can take a little while…
      </div>
    );
  }

  if (state.status === "done") {
    return (
      <div className="text-sm text-emerald-400">
        Run complete.{" "}
        <button
          className="underline"
          onClick={() => setState({ status: "loading-context" })}
        >
          Run again
        </button>
      </div>
    );
  }

  const { context, selectedModelIds } = state;

  function toggleModel(modelId: number) {
    if (state.status !== "ready") return;
    setState({
      ...state,
      selectedModelIds: state.selectedModelIds.includes(modelId)
        ? state.selectedModelIds.filter((id) => id !== modelId)
        : [...state.selectedModelIds, modelId],
    });
  }

  async function handleRun() {
    if (!token) return;
    try {
      const run = await createRun(token, {
        project_id: context.project_id,
        dataset_version_id: context.dataset_version_id,
        model_ids: selectedModelIds,
      });
      setState({ status: "running", runId: run.id });
    } catch (err) {
      setState({
        status: "error",
        message:
          err instanceof ApiError
            ? err.status === 429
              ? `Rate limited: ${err.message}`
              : err.message
            : "Failed to trigger run.",
      });
    }
  }

  return (
    <div className="rounded border border-neutral-800 p-4 space-y-3">
      <div className="text-sm font-medium">Trigger a new evaluation run</div>
      <div className="flex flex-wrap gap-3">
        {context.models.map((model) => (
          <label key={model.id} className="flex items-center gap-2 text-sm text-neutral-300">
            <input
              type="checkbox"
              checked={selectedModelIds.includes(model.id)}
              onChange={() => toggleModel(model.id)}
              className="accent-neutral-100"
            />
            {model.display_name}
          </label>
        ))}
      </div>
      <button
        onClick={handleRun}
        disabled={selectedModelIds.length === 0}
        className="rounded bg-neutral-100 text-neutral-900 px-4 py-2 text-sm font-medium disabled:opacity-40 disabled:cursor-not-allowed hover:bg-white transition-colors"
      >
        Run evaluation
      </button>
    </div>
  );
}
