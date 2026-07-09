"use client";

import Link from "next/link";
import { useAuth } from "@/lib/auth";

const NAV_LINKS = [
  { href: "/projects", label: "Projects" },
  { href: "/datasets", label: "Datasets" },
  { href: "/models", label: "Model Comparison" },
  { href: "/history", label: "Experiment History" },
  { href: "/arena", label: "Arena" },
  { href: "/prompts", label: "Prompt Testing" },
  { href: "/regression", label: "Regression Results" },
  { href: "/settings", label: "Settings" },
];

export function Header() {
  const { token, setToken } = useAuth();

  return (
    <header className="border-b border-neutral-800 px-6 py-4 flex flex-wrap items-center justify-between gap-3">
      <Link href="/" className="font-semibold tracking-tight">
        LLM Evaluation Platform
      </Link>
      <nav className="flex flex-wrap items-center gap-4 text-sm">
        {NAV_LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className="text-neutral-400 hover:text-neutral-100 transition-colors"
          >
            {link.label}
          </Link>
        ))}
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
