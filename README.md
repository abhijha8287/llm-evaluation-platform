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
