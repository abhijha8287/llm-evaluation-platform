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

export interface Project {
  id: number;
  owner_id: number;
  name: string;
  created_at: string;
}

export interface DatasetVersionSummary {
  id: number;
  version_number: number;
  sample_size: number;
  created_at: string;
}

export interface Dataset {
  id: number;
  project_id: number;
  name: string;
  created_at: string;
  versions: DatasetVersionSummary[];
}

export type QuestionType = "open_domain" | "rag";

export interface DatasetQuestion {
  id: number;
  dataset_id: number;
  type: QuestionType;
  text: string;
  has_retrieval_context: boolean;
  expected_output: string | null;
}

export interface RunListItem {
  id: number;
  project_id: number;
  dataset_version_id: number;
  status: RunStatus;
  created_at: string;
  completed_at: string | null;
  response_count: number;
}

export interface RunTrendPoint {
  run_id: number;
  created_at: string;
  model_id: number;
  display_name: string;
  avg_latency_ms: number | null;
  avg_cost_usd: number | null;
  pass_rate: number | null;
  metric_averages: Record<string, number>;
}

export interface PromptVersion {
  id: number;
  prompt_template_id: number;
  version_number: number;
  content: string;
}

export interface PromptTemplate {
  id: number;
  project_id: number;
  name: string;
  versions: PromptVersion[];
}

export type RegressionStatus = "pending" | "running" | "completed" | "failed" | "not_comparable";

export interface RegressionRunResponse {
  id: number;
  prompt_version_id: number;
  baseline_prompt_version_id: number | null;
  dataset_version_id: number;
  model_id: number;
  run_id: number;
  status: RegressionStatus;
  completed_at: string | null;
}

export interface RegressionResultItem {
  question_id: number;
  metric_name: string;
  score: number | null;
  delta_from_baseline: number | null;
}

export interface RegressionRunDetail extends RegressionRunResponse {
  results: RegressionResultItem[];
}
