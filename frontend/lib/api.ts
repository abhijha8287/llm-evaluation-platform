import type {
  ArenaComparisonOption,
  Dataset,
  DatasetQuestion,
  LeaderboardEntry,
  Project,
  PromptTemplate,
  PromptVersion,
  RegressionRunDetail,
  RegressionRunResponse,
  RunContext,
  RunListItem,
  RunResponse,
  RunTrendPoint,
  TokenResponse,
  VoteRequest,
  VoteResponse,
} from "./types";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function parseErrorDetail(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // response body wasn't JSON — fall through to the generic message
  }
  return `Request failed with status ${response.status}`;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  // POST /auth/login expects OAuth2PasswordRequestForm — form-encoded, not JSON.
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);

  const response = await fetch(`${API_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });

  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function getLeaderboard(): Promise<LeaderboardEntry[]> {
  const response = await fetch(`${API_URL}/leaderboard`, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function getRunContext(token: string): Promise<RunContext> {
  const response = await fetch(`${API_URL}/me/run-context`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function createRun(
  token: string,
  body: { project_id: number; dataset_version_id: number; model_ids: number[] },
): Promise<RunResponse> {
  // Phase 5: this returns immediately with status "running" — the Celery
  // chord dispatched by the backend hasn't finished yet. Callers must poll
  // getRun() (see TriggerRunPanel) rather than treat this response as final.
  const response = await fetch(`${API_URL}/runs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function getRun(runId: number): Promise<RunResponse> {
  const response = await fetch(`${API_URL}/runs/${runId}`, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function getNextComparison(): Promise<ArenaComparisonOption> {
  const response = await fetch(`${API_URL}/arena/next-comparison`, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function submitVote(body: VoteRequest): Promise<VoteResponse> {
  const response = await fetch(`${API_URL}/arena/vote`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function getProjects(): Promise<Project[]> {
  const response = await fetch(`${API_URL}/projects`, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function getProjectDatasets(projectId: number): Promise<Dataset[]> {
  const response = await fetch(`${API_URL}/projects/${projectId}/datasets`, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function getDatasetQuestions(datasetId: number): Promise<DatasetQuestion[]> {
  const response = await fetch(`${API_URL}/datasets/${datasetId}/questions`, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function getRuns(projectId: number): Promise<RunListItem[]> {
  const response = await fetch(`${API_URL}/runs?project_id=${projectId}`, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function getTrends(projectId: number): Promise<RunTrendPoint[]> {
  const response = await fetch(`${API_URL}/dashboard/trends?project_id=${projectId}`, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function getPromptTemplates(projectId: number): Promise<PromptTemplate[]> {
  const response = await fetch(`${API_URL}/prompt-templates?project_id=${projectId}`, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function createPromptTemplate(
  token: string,
  body: { project_id: number; name: string },
): Promise<PromptTemplate> {
  const response = await fetch(`${API_URL}/prompt-templates`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function createPromptVersion(
  token: string,
  promptTemplateId: number,
  content: string,
): Promise<PromptVersion> {
  const response = await fetch(`${API_URL}/prompt-templates/${promptTemplateId}/versions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify({ content }),
  });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function createRegressionRun(
  token: string,
  body: {
    prompt_version_id: number;
    dataset_version_id: number;
    model_id: number;
    baseline_prompt_version_id?: number | null;
  },
): Promise<RegressionRunResponse> {
  const response = await fetch(`${API_URL}/regression-runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function getRegressionRuns(promptTemplateId: number): Promise<RegressionRunResponse[]> {
  const response = await fetch(
    `${API_URL}/regression-runs?prompt_template_id=${promptTemplateId}`,
    { cache: "no-store" },
  );
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}

export async function getRegressionRun(regressionRunId: number): Promise<RegressionRunDetail> {
  const response = await fetch(`${API_URL}/regression-runs/${regressionRunId}`, { cache: "no-store" });
  if (!response.ok) {
    throw new ApiError(await parseErrorDetail(response), response.status);
  }
  return response.json();
}
