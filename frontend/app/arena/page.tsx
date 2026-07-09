"use client";

import { useCallback, useEffect, useState } from "react";
import { Header } from "@/components/Header";
import { ApiError, getNextComparison, submitVote } from "@/lib/api";
import type { ArenaComparisonOption } from "@/lib/types";

type ArenaState =
  | { status: "loading" }
  | { status: "voting"; comparison: ArenaComparisonOption }
  | { status: "submitting"; comparison: ArenaComparisonOption }
  | { status: "result"; comparison: ArenaComparisonOption; winnerResponseId: number | null }
  | { status: "empty" }
  | { status: "error"; message: string };

// office-hours design doc Phase 6: a human voting UI alongside the LLM
// judge's automatic votes (see the leaderboard's two Elo columns). The
// backend never reveals which model produced which response before a vote
// is cast — "Response A"/"Response B" only, matching the blind arena format.
export default function ArenaPage() {
  const [state, setState] = useState<ArenaState>({ status: "loading" });

  // Split in two: fetchComparison never calls setState synchronously (only
  // inside its .then()/.catch() callbacks, which run in a later microtask —
  // that's what makes it safe to call from an Effect body). loadNext is the
  // version event handlers (the "Next comparison" button) use, which resets
  // to "loading" synchronously before the button's own click handler exits —
  // fine there since only Effect bodies are restricted, not event handlers.
  const fetchComparison = useCallback(() => {
    getNextComparison()
      .then((comparison) => setState({ status: "voting", comparison }))
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 404) {
          setState({ status: "empty" });
          return;
        }
        setState({
          status: "error",
          message: err instanceof ApiError ? err.message : "Failed to load a comparison.",
        });
      });
  }, []);

  useEffect(() => {
    fetchComparison();
  }, [fetchComparison]);

  function loadNext() {
    setState({ status: "loading" });
    fetchComparison();
  }

  async function vote(winnerResponseId: number | null) {
    if (state.status !== "voting") return;
    const comparison = state.comparison;
    setState({ status: "submitting", comparison });
    try {
      await submitVote({
        question_id: comparison.question_id,
        response_1_id: comparison.response_1_id,
        response_2_id: comparison.response_2_id,
        winner_response_id: winnerResponseId,
      });
      setState({ status: "result", comparison, winnerResponseId });
    } catch (err) {
      setState({
        status: "error",
        message: err instanceof ApiError ? err.message : "Failed to submit vote.",
      });
    }
  }

  return (
    <>
      <Header />
      <main className="flex-1 px-6 py-8 max-w-3xl w-full mx-auto space-y-6">
        <div>
          <h1 className="text-xl font-semibold">Arena</h1>
          <p className="text-sm text-neutral-400 mt-1">
            Blind pairwise comparison — vote for the better response without knowing which model wrote
            it. Your votes feed the &quot;Elo (Human)&quot; column on the leaderboard, separate from the
            LLM judge&apos;s automatic votes.
          </p>
        </div>

        {state.status === "loading" && <p className="text-sm text-neutral-400">Loading a comparison…</p>}

        {state.status === "empty" && (
          <p className="text-sm text-neutral-400">
            No comparisons available yet — trigger an evaluation run with at least two models first.
          </p>
        )}

        {state.status === "error" && <p className="text-sm text-red-400">{state.message}</p>}

        {(state.status === "voting" || state.status === "submitting") && (
          <div className="space-y-4">
            <div className="rounded border border-neutral-800 p-4">
              <div className="text-xs text-neutral-500 mb-1">Question</div>
              <div className="text-sm">{state.comparison.question_text}</div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <ResponseCard label="Response A" text={state.comparison.response_1_text} />
              <ResponseCard label="Response B" text={state.comparison.response_2_text} />
            </div>
            <div className="flex gap-3">
              <button
                onClick={() => vote(state.comparison.response_1_id)}
                disabled={state.status === "submitting"}
                className="flex-1 rounded bg-neutral-100 text-neutral-900 px-4 py-2 text-sm font-medium disabled:opacity-40 hover:bg-white transition-colors"
              >
                A is better
              </button>
              <button
                onClick={() => vote(null)}
                disabled={state.status === "submitting"}
                className="rounded border border-neutral-700 px-4 py-2 text-sm font-medium disabled:opacity-40 hover:bg-neutral-900 transition-colors"
              >
                Tie
              </button>
              <button
                onClick={() => vote(state.comparison.response_2_id)}
                disabled={state.status === "submitting"}
                className="flex-1 rounded bg-neutral-100 text-neutral-900 px-4 py-2 text-sm font-medium disabled:opacity-40 hover:bg-white transition-colors"
              >
                B is better
              </button>
            </div>
          </div>
        )}

        {state.status === "result" && (
          <div className="space-y-4">
            <div className="rounded border border-emerald-900 bg-emerald-950/30 p-4 text-sm text-emerald-300">
              Vote recorded.{" "}
              {state.winnerResponseId === null
                ? "You called it a tie."
                : `You picked ${state.winnerResponseId === state.comparison.response_1_id ? "Response A" : "Response B"}.`}
            </div>
            <button
              onClick={loadNext}
              className="rounded bg-neutral-100 text-neutral-900 px-4 py-2 text-sm font-medium hover:bg-white transition-colors"
            >
              Next comparison
            </button>
          </div>
        )}
      </main>
    </>
  );
}

function ResponseCard({ label, text }: { label: string; text: string }) {
  return (
    <div className="rounded border border-neutral-800 p-4">
      <div className="text-xs text-neutral-500 mb-2">{label}</div>
      <div className="text-sm whitespace-pre-wrap">{text}</div>
    </div>
  );
}
