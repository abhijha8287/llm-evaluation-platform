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
85/85 backend tests passing.

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
D4) + Next.js frontend.
