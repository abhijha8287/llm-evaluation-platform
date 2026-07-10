"""Phase 9: one shared place for every Prometheus metric definition, in the
same spirit as D8's shared EvaluationService — a metric name/label set
defined once, imported everywhere it's recorded, never redefined ad hoc at
each call site.

Process topology matters here and is worth being explicit about: FastAPI and
the Celery worker are separate OS processes (D1), each with its own
in-memory prometheus_client REGISTRY — there is no cross-process state to
reconcile because each process runs single-concurrency (uvicorn without
--workers, Celery with --pool=solo / --concurrency=1, the same "fine at
portfolio scale" tradeoff D1 already accepted for the asyncio-per-task
pattern). That means no prometheus_client multiprocess-mode machinery is
needed — each process just exposes its own /metrics endpoint (see
app/main.py for FastAPI's, app/workers/celery_app.py's worker_process_init
hook for the Celery worker's), and Prometheus scrapes both as separate
targets (see monitoring/prometheus.yml). A real multi-worker production
deployment would need prometheus_client's multiprocess collector instead —
out of scope for this portfolio demo, same category of deferral as TODOS.md
item 1.

Because LLMRunner/EvaluationService run inside BOTH the FastAPI process
(Phase 4's synchronous RunOrchestrator.execute() path, still used by tests
and local dev without Celery) and the Celery worker process (the live
Phase 5+ pipeline), these domain metrics are recorded from the same call
sites regardless of which process executes them — in the running app,
expect the LLM-call and judge-call metrics to show up almost entirely on the
Celery worker's /metrics, not FastAPI's, since that's where real traffic
actually flows post-Phase-5.
"""

from prometheus_client import Counter, Histogram

# --- HTTP layer (FastAPI process only — see app/main.py's middleware) ---
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds", "HTTP request duration in seconds", ["method", "path"]
)

# --- LLM provider calls (app/llm/runner.py). Labeled by the raw LiteLLM
# provider_model string (e.g. "gpt-4o", "groq/llama-3.3-70b-versatile"), not
# a separately-derived provider name — LLMRunner is deliberately DB-free and
# reusable outside a request/task context (see its docstring), so it never
# receives LLMModel.provider as a separate argument just for labeling. ---
LLM_PROVIDER_CALL_DURATION_SECONDS = Histogram(
    "llm_provider_call_duration_seconds",
    "LLM provider call duration in seconds",
    ["model", "status"],
)
LLM_PROVIDER_CALLS_TOTAL = Counter(
    "llm_provider_calls_total", "Total LLM provider calls", ["model", "status"]
)

# --- DeepEval judge metric calls (app/evaluation/scoring_service.py) ---
JUDGE_EVAL_DURATION_SECONDS = Histogram(
    "judge_eval_duration_seconds",
    "DeepEval judge metric call duration in seconds",
    ["metric_name", "status"],
)
JUDGE_EVAL_CALLS_TOTAL = Counter(
    "judge_eval_calls_total", "Total DeepEval judge metric calls", ["metric_name", "status"]
)

# --- Cost (app/services/run_orchestrator.py) — mirrors D6's cost source
# (LiteLLM's pricing map): only recorded when a response actually has a
# cost_usd, same null-vs-zero discipline as the leaderboard's averages. ---
RESPONSE_COST_USD_TOTAL = Counter(
    "response_cost_usd_total", "Total accrued provider cost in USD across all responses", ["model"]
)

# --- Celery tasks (app/workers/celery_app.py's signal handlers — one shared
# hook point covering all five task types, not per-task instrumentation
# duplicated five times). ---
CELERY_TASK_DURATION_SECONDS = Histogram(
    "celery_task_duration_seconds", "Celery task duration in seconds", ["task_name", "status"]
)
CELERY_TASKS_TOTAL = Counter(
    "celery_tasks_total", "Total Celery tasks executed", ["task_name", "status"]
)
