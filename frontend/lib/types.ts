// Mirrors the Pydantic response_model schemas in app/api/routes/*.py.
// Kept as one file since the "shared type" surface is small at this phase —
// split per-resource if it grows past a screenful.

export interface LeaderboardEntry {
  model_id: number;
  display_name: string;
  provider: string;
  // office-hours design doc Phase 6: LLM-judged and human-judged Elo are
  // shown separately, not blended into one number.
  elo_rating_llm_judge: number;
  elo_rating_human: number;
  llm_judge_comparison_count: number;
  human_comparison_count: number;
  response_count: number;
  avg_latency_ms: number | null;
  avg_cost_usd: number | null;
  metric_averages: Record<string, number>;
}

export interface ArenaComparisonOption {
  question_id: number;
  question_text: string;
  response_1_id: number;
  response_1_text: string;
  response_2_id: number;
  response_2_text: string;
}

export interface VoteRequest {
  question_id: number;
  response_1_id: number;
  response_2_id: number;
  winner_response_id: number | null;
}

export interface VoteResponse {
  comparison_id: number;
  winner_model_id: number | null;
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
