# LLM Evaluation Platform

Internal-style platform for comparing, evaluating, and benchmarking multiple LLM
providers (OpenAI, Anthropic, Gemini, Llama, DeepSeek, Qwen) against DeepEval
metrics, with an Elo-rated blind arena and prompt regression testing.

Design and architecture decisions: see `design-llm-evaluation-platform.md`
(includes the full `/office-hours` design doc and the `/plan-eng-review`
architecture report — 13 locked-in decisions referenced throughout the code
as `D1`-`D13`).

Build order and status: see `implementation-tasks-eng-review.md` and
`TODOS.md`.

## Status

Phase 1 (schema) complete: 15 tables, hand-authored initial Alembic migration
(verified upgrade/downgrade against SQLite and real Postgres).

Phase 2 (backend core) complete: repository pattern, LiteLLM runner (D3
status isolation), JWT auth (D10 login-only/single seeded user), rate-limited
run-creation endpoint (D2).

Phase 3 (evaluation engine) complete: shared `EvaluationService` (D8) running
real DeepEval metrics (Faithfulness/Toxicity/Bias/AnswerRelevancy) with
question-type-aware selection (Premise 3) and per-metric judge-failure
isolation (D9); seeded/versioned dataset sampler (D5).

Phase 4 (minimal frontend + first end-to-end demoable milestone) complete:
`RunOrchestrator` connects the LiteLLM runner, DeepEval scoring, and cost
service; public leaderboard API; seeded demo models/dataset; Next.js 16
frontend (leaderboard, login, trigger-run panel).

Phase 5 (async layer) complete: Celery + Redis — one task per (question,
model) pair grouped under a chord (D12), not one task per Run, so worker
scaling actually parallelizes a run. `POST /runs` now dispatches and returns
immediately (`status: running`); `GET /runs/{id}` added for polling. Redis
leaderboard cache (D13), write-invalidated, fails open if Redis is down.
**Live-verified with a real Celery worker + real Redis + real Postgres**:
triggered a run over the actual API, watched the worker process every task
and fire the chord callback automatically, confirmed completion and
per-response failure isolation by querying Postgres directly — not just
mocked unit tests.

Phase 6 (Arena/Elo) complete: `elo_rating` split into `elo_rating_llm_judge`/
`elo_rating_human` tracks (office-hours design doc's original Phase 6 spec —
shown separately on the leaderboard, not blended). Blind LLM-judged
comparisons dispatch automatically once a run completes (one per unique
model pair per question among successful responses); `GET
/arena/next-comparison` + `POST /arena/vote` let a human vote too, both
writing to the same Elo tracks by voter type. Row-level locked Elo updates
(D4) verified against a **real concurrent-write race on the actual Postgres
container** — confirmed the test fails reliably with the lock removed and
passes reliably with it restored. Frontend `/arena` page for blind voting.

Phase 7 (prompt regression engine) complete: `PromptTemplate`/`PromptVersion`
CRUD with `{question}`-placeholder validation at creation time; regression
runs reuse the real `Run`/`RunOrchestrator`/Celery pipeline wholesale (a new
optional `prompt_override` param on `run_pair` was the only change needed) —
no parallel response-generation path. Diffs against a baseline prompt
version only when it shares the same `dataset_version_id` (D7); otherwise
marked `not_comparable`, deltas stay null, never silently diffed. Two real
gaps found and fixed before they could ship: the original schema had no
`model_id` on `RegressionRun` (a "regression" could otherwise have actually
been an undetected model swap), and regression responses would have leaked
into the main leaderboard's per-model averages without an explicit
exclusion filter. `api/routes/prompts.py` + `api/routes/regression.py`
(reuses the same rate-limit gate as `POST /runs`). Per the original design
doc, the "Prompt Testing"/"Regression Results" frontend pages are Phase 8
scope — this phase is backend-only. **Live-verified** with a real Celery
worker + real Postgres: created a real prompt template/version, triggered a
real regression run, watched it complete, confirmed failure isolation and
leaderboard exclusion via direct Postgres queries. 109/109 backend tests
passing.

Phase 8 (full dashboard) complete: `EvaluationResult.passed` added — captured
directly from DeepEval's own `metric.success` (verified per-metric pass/fail
direction against the installed library, not assumed) rather than
reimplemented, so a real Pass Rate chart is now possible. New read-only
list/aggregation endpoints (`api/routes/catalog.py`, `api/routes/
dashboard.py`, plus list additions to `runs.py`/`prompts.py`/
`regression.py`) — all public/no-auth (D2), consistent with every prior
read-only endpoint. `GET /dashboard/trends` is the single data source behind
every Experiment History chart: one point per (run, model) pair with
latency/cost/pass-rate/metric averages, pivoted client-side per chart. Seven
new Next.js pages — Projects, Datasets (TODOS.md item 3 resolved: every
dataset version listed individually, not collapsed into a count), Model
Comparison (Recharts radar across all four metrics + latency/cost bars),
Experiment History (runs table + four trend line charts), Prompt Testing
(template/version CRUD + regression-run trigger), Regression Results
(per-question metric/delta table, `not_comparable` rendered visibly per D7),
Settings. 124/124 backend tests passing (14 new). Frontend: clean
`tsc`/`eslint`/`next build`. **Live-verified**: every new endpoint curled
against real Postgres; the full authenticated write path (login → create
prompt template → create version → trigger regression run → list it back)
exercised end-to-end against the real backend. No browser-automation tool
was available in this environment to visually click through the new pages —
noted explicitly rather than assumed working; the data-fetching logic is the
same `useEffect`+`fetch` pattern already proven live in Phases 4/5/6.

## Running locally

Backend:
```bash
python -m venv .venv && .venv/Scripts/activate    # or source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env    # fill in real provider API keys

docker compose up -d           # postgres + redis
alembic upgrade head

uvicorn app.main:app --reload                                    # API
celery -A app.workers.celery_app worker --pool=solo --loglevel=info   # worker
# --pool=solo is a native-Windows dev convenience; the Constraints call for
# the worker to run in a Docker Linux container (Celery's prefork pool is
# unreliable on native Windows) — that's how Phase 9's Docker Compose runs it.

pytest
```

Frontend (separate terminal):
```bash
cd frontend
npm install
npm run dev
```

The frontend defaults to `NEXT_PUBLIC_API_URL=http://localhost:8000` (see
`frontend/.env.local`). The backend seeds a demo user
(`demo@llm-eval-platform.dev` / `demo-password-change-me` — change this in
`app/main.py` before any real deploy), 3 models, and a demo dataset on
startup.

## Architecture

See `design-llm-evaluation-platform.md` for the full data-flow diagram, state
machine, and rationale. Summary: FastAPI (async) + SQLAlchemy 2.0 (async,
repository pattern) + PostgreSQL + Alembic + Celery/Redis (one task per
question×model pair grouped under a chord, D12) + LiteLLM (multi-provider
abstraction + pricing, D6) + DeepEval (metrics, D8's shared
EvaluationService) + blind LLM-judged/human Elo arena (row-level locked,
D4) + prompt-version regression testing (D7, reuses the same Run pipeline)
+ Next.js frontend.
