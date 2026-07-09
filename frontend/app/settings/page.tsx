"use client";

import { useEffect, useState } from "react";
import { Header } from "@/components/Header";
import { useAuth } from "@/lib/auth";
import { getLeaderboard } from "@/lib/api";
import type { LeaderboardEntry } from "@/lib/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export default function SettingsPage() {
  const { token, setToken } = useAuth();
  const [entries, setEntries] = useState<LeaderboardEntry[] | null>(null);

  useEffect(() => {
    getLeaderboard()
      .then(setEntries)
      .catch(() => {
        // Non-fatal on this page — the models list is supplementary info.
      });
  }, []);

  return (
    <>
      <Header />
      <main className="flex-1 px-6 py-8 max-w-2xl w-full mx-auto space-y-8">
        <div>
          <h1 className="text-xl font-semibold">Settings</h1>
          <p className="text-sm text-neutral-400 mt-1">
            D10: login-only with a single seeded demo user for the public deploy — there&apos;s no
            self-registration or per-user preferences to configure here.
          </p>
        </div>

        <section className="rounded border border-neutral-800 p-4 space-y-2">
          <h2 className="text-sm font-medium text-neutral-300">Session</h2>
          {token ? (
            <div className="flex items-center justify-between text-sm">
              <span className="text-emerald-400">Logged in</span>
              <button
                onClick={() => setToken(null)}
                className="rounded border border-neutral-700 px-3 py-1.5 text-xs text-neutral-300 hover:border-neutral-500 transition-colors"
              >
                Log out
              </button>
            </div>
          ) : (
            <p className="text-sm text-neutral-400">Not logged in — read-only access only.</p>
          )}
        </section>

        <section className="rounded border border-neutral-800 p-4 space-y-2">
          <h2 className="text-sm font-medium text-neutral-300">Abuse prevention</h2>
          <p className="text-sm text-neutral-400">
            Triggering a new evaluation or regression run is rate-limited per project regardless of auth
            (D2) — this protects the public demo from runaway provider costs.
          </p>
        </section>

        <section className="rounded border border-neutral-800 p-4 space-y-2">
          <h2 className="text-sm font-medium text-neutral-300">Models under evaluation</h2>
          {entries === null ? (
            <p className="text-sm text-neutral-400">Loading…</p>
          ) : (
            <ul className="text-sm text-neutral-400 space-y-1">
              {entries.map((e) => (
                <li key={e.model_id}>
                  {e.display_name} <span className="text-neutral-600">({e.provider})</span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded border border-neutral-800 p-4 space-y-2">
          <h2 className="text-sm font-medium text-neutral-300">Environment</h2>
          <p className="text-sm text-neutral-400 font-mono text-xs break-all">API_URL = {API_URL}</p>
        </section>
      </main>
    </>
  );
}
