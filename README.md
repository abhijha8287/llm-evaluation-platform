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
(verified upgrade/downgrade against SQLite; targets Postgres via asyncpg in
real use), full model test suite passing.

Phase 2 (backend core) complete: repository pattern, LiteLLM runner (D3
status isolation), JWT auth (D10 login-only/single seeded user), rate-limited
run-creation endpoint (D2).

Phase 3 (evaluation engine) complete: shared `EvaluationService` (D8) running
real DeepEval metrics (Faithfulness/Toxicity/Bias/AnswerRelevancy) with
question-type-aware selection (Premise 3) and per-metric judge-failure
isolation (D9); seeded/versioned dataset sampler (D5).

Phase 4 (minimal frontend + first end-to-end demoable milestone) complete:
`RunOrchestrator` connects the LiteLLM runner, DeepEval scoring, and cost
service into one synchronous run-execution path; public leaderboard API;
seeded demo models/dataset; Next.js 16 frontend (leaderboard, login,
trigger-run panel). 45/45 backend tests passing. Live-smoke-tested end to
end: real backend + real frontend dev server, curl-verified against
`/health`, `/leaderboard`, `/auth/login`, `/me/run-context`, and CORS.

## Running locally

Backend:
```bash
python -m venv .venv && .venv/Scripts/activate    # or source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env    # fill in real provider API keys
docker compose up -d postgres
alembic upgrade head
uvicorn app.main:app --reload
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

## Local setup

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -e ".[dev]"

cp .env.example .env          # fill in real values, especially provider keys

docker compose up -d postgres
alembic upgrade head

pytest
```

## Architecture

See `design-llm-evaluation-platform.md` for the full data-flow diagram, state
machine, and rationale. Summary: FastAPI (async) + SQLAlchemy 2.0 (async,
repository pattern) + PostgreSQL + Alembic + Celery/Redis (one task per
question×provider pair, D12) + LiteLLM (multi-provider abstraction + pricing,
D6) + DeepEval (metrics, D8's shared EvaluationService) + Next.js frontend.
