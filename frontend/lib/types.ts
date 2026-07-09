// Mirrors the Pydantic response_model schemas in app/api/routes/*.py.
// Kept as one file since the "shared type" surface is small at this phase —
// split per-resource if it grows past a screenful.

export interface LeaderboardEntry {
  model_id: number;
  display_name: string;
  provider: string;
  elo_rating: number;
  response_count: number;
  avg_latency_ms: number | null;
  avg_cost_usd: number | null;
  metric_averages: Record<string, number>;
}

export interface ModelOption {
  id: number;
  display_name: string;
  provider: string;
}

export interface RunContext {
  project_id: number;
  dataset_version_id: number;
  models: ModelOption[];
}

export type RunStatus = "pending" | "running" | "completed" | "failed";

export interface RunResponse {
  id: number;
  project_id: number;
  dataset_version_id: number;
  status: RunStatus;
  completed_at: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}
