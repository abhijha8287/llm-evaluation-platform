"use client";

import { useCallback, useEffect, useState } from "react";
import { Header } from "@/components/Header";
import { LeaderboardTable } from "@/components/LeaderboardTable";
import { TriggerRunPanel } from "@/components/TriggerRunPanel";
import { ApiError, getLeaderboard } from "@/lib/api";
import type { LeaderboardEntry } from "@/lib/types";

// D2: the leaderboard itself is public, read-only, no login required — this
// is what a recruiter sees the moment they open the demo link.
export default function HomePage() {
  const [entries, setEntries] = useState<LeaderboardEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    getLeaderboard()
      .then(setEntries)
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load leaderboard.");
      });
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return (
    <>
      <Header />
      <main className="flex-1 px-6 py-8 max-w-5xl w-full mx-auto space-y-8">
        <div>
          <h1 className="text-xl font-semibold">Leaderboard</h1>
          <p className="text-sm text-neutral-400 mt-1">
            GPT / Claude / Llama compared on faithfulness, toxicity, bias, answer relevancy, latency, and
            cost — see the design doc for methodology (D5&apos;s seeded sampling, D9&apos;s judge-failure
            exclusion).
          </p>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}
        {entries === null && !error ? (
          <p className="text-sm text-neutral-400">Loading…</p>
        ) : (
          <LeaderboardTable entries={entries ?? []} />
        )}

        <TriggerRunPanel onRunComplete={refresh} />
      </main>
    </>
  );
}
