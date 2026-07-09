"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ApiError, login } from "@/lib/api";
import { useAuth } from "@/lib/auth";

// D10: there is no registration form anywhere in this app on purpose — the
// backend has no public registration endpoint (single seeded demo user).
export default function LoginPage() {
  const router = useRouter();
  const { setToken } = useAuth();
  const [email, setEmail] = useState("demo@llm-eval-platform.dev");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      const { access_token } = await login(email, password);
      setToken(access_token);
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Login failed.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="flex-1 flex items-center justify-center px-6">
      <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-4">
        <h1 className="text-lg font-semibold">Log in</h1>
        <p className="text-sm text-neutral-400">
          This is a single-seeded-user demo (see the design doc&apos;s D10) — there&apos;s no signup.
        </p>
        <div className="space-y-1">
          <label className="text-sm text-neutral-400" htmlFor="email">
            Email
          </label>
          <input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm"
            required
          />
        </div>
        <div className="space-y-1">
          <label className="text-sm text-neutral-400" htmlFor="password">
            Password
          </label>
          <input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded border border-neutral-800 bg-neutral-900 px-3 py-2 text-sm"
            required
          />
        </div>
        {error && <p className="text-sm text-red-400">{error}</p>}
        <button
          type="submit"
          disabled={isSubmitting}
          className="w-full rounded bg-neutral-100 text-neutral-900 px-4 py-2 text-sm font-medium disabled:opacity-40 hover:bg-white transition-colors"
        >
          {isSubmitting ? "Logging in…" : "Log in"}
        </button>
      </form>
    </main>
  );
}
