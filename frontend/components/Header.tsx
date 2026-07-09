"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

export function Header() {
  const { token, setToken } = useAuth();

  return (
    <header className="border-b border-neutral-800 px-6 py-4 flex items-center justify-between">
      <Link href="/" className="font-semibold tracking-tight">
        LLM Evaluation Platform
      </Link>
      <nav className="flex items-center gap-4 text-sm">
        <Link href="/arena" className="text-neutral-400 hover:text-neutral-100 transition-colors">
          Arena
        </Link>
        {token ? (
          <button
            onClick={() => setToken(null)}
            className="text-neutral-400 hover:text-neutral-100 transition-colors"
          >
            Log out
          </button>
        ) : (
          <Link href="/login" className="text-neutral-400 hover:text-neutral-100 transition-colors">
            Log in
          </Link>
        )}
      </nav>
    </header>
  );
}
