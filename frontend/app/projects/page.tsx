"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Header } from "@/components/Header";
import { ApiError, getProjects } from "@/lib/api";
import type { Project } from "@/lib/types";

// D10: the public deploy seeds exactly one project — this page still lists
// properly (not a single hardcoded card) since the schema and API are
// genuinely multi-tenant-shaped (see app/models/project.py).
export default function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getProjects()
      .then(setProjects)
      .catch((err: unknown) => {
        setError(err instanceof ApiError ? err.message : "Failed to load projects.");
      });
  }, []);

  return (
    <>
      <Header />
      <main className="flex-1 px-6 py-8 max-w-5xl w-full mx-auto space-y-6">
        <div>
          <h1 className="text-xl font-semibold">Projects</h1>
          <p className="text-sm text-neutral-400 mt-1">
            Every dataset, run, and prompt template is scoped to a project — real project-scoped
            resources even in a solo demo.
          </p>
        </div>

        {error && <p className="text-sm text-red-400">{error}</p>}
        {projects === null && !error && <p className="text-sm text-neutral-400">Loading…</p>}

        {projects && projects.length === 0 && (
          <p className="text-sm text-neutral-400">No projects yet.</p>
        )}

        <div className="grid gap-3">
          {projects?.map((project) => (
            <Link
              key={project.id}
              href={`/datasets?project_id=${project.id}`}
              className="rounded border border-neutral-800 p-4 hover:border-neutral-700 transition-colors block"
            >
              <div className="font-medium">{project.name}</div>
              <div className="text-xs text-neutral-500 mt-1">
                Created {new Date(project.created_at).toLocaleString()}
              </div>
            </Link>
          ))}
        </div>
      </main>
    </>
  );
}
