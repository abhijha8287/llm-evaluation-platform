# Implementation Tasks

Synthesized from /plan-eng-review (2026-07-09). Each task derives from a specific
decision above. Run with Claude Code; checkbox as you ship. jq unavailable this
session, so no JSONL artifact was written for /autoplan aggregation — install jq
if you want that later.

## Phase 1: Schema
- [x] **T1 (P1, human: ~3h / CC: ~20min)** — schema — Create all tables with
  open-domain/RAG-style Question type split, Response.status,
  EvaluationResult.status, dataset version fields
  - Surfaced by: D3, D5, D7, D9 — status fields and versioning must exist from
    the first migration, not retrofitted
  - Files: `models/*.py`, `migrations/`
  - Verify: `alembic upgrade head` runs clean; a test seeds one row per table
  - Done: 15 tables, hand-authored migration (no live Postgres in the sandbox
    to autogenerate against), upgrade+downgrade verified against SQLite,
    2/2 model tests pass. Found and fixed: eager engine creation at import
    time coupled every module import to asyncpg being installed — made lazy.

## Phase 2: Backend core
- [x] **T2 (P1, human: ~4h / CC: ~30min)** — llm — LiteLLM runner with
  per-provider Response.status transitions (success/timeout/failed)
  - Surfaced by: D3
  - Files: `llm/runner.py`, `tests/test_runner.py`
  - Verify: `pytest tests/test_runner.py` covers success/timeout/error/isolation
  - Done: 6/6 tests pass. Found and fixed a real bug: `litellm.exceptions.APIError`
    does NOT cover RateLimitError/AuthenticationError/etc (verified against the
    installed litellm 1.83.7 exception MRO directly) — a naive except clause
    would have let those propagate uncaught instead of isolating the failure.
    Fixed to catch `openai.OpenAIError`, the actual shared base.
- [x] **T3 (P1, human: ~2h / CC: ~15min)** — auth — Login-only JWT auth, single
  seeded demo user, no public registration endpoint
  - Surfaced by: D10
  - Files: `api/routes/auth.py`, `core/seed_data.py`
  - Verify: registration route returns 404/disabled; login issues valid JWT
  - Done: 4/4 tests pass. Found and fixed: `passlib` is incompatible with
    modern `bcrypt` (removed `__about__`, and passlib's internal self-test
    trips bcrypt's 72-byte limit) — replaced with direct `bcrypt` usage.
- [x] **T4 (P1, human: ~1h / CC: ~10min)** — api — Rate limit on trigger-run
  endpoint, enforced regardless of auth state
  - Surfaced by: D2
  - Files: `api/routes/runs.py`
  - Verify: test fires 4 requests, 4th is rejected
  - Done: 3/3 tests pass (401 unauthenticated, 404 unowned project, rate limit
    fires on the 3rd request against a MAX_RUNS_PER_DAY=2 override).

## Phase 3: Evaluation engine
- [x] **T5 (P1, human: ~4h / CC: ~30min)** — evaluation — Shared
  EvaluationService (question-type-aware metric selection, judge failure status)
  - Surfaced by: D8, D9
  - Files: `evaluation/scoring_service.py`, `tests/test_scoring_service.py`
  - Verify: open-domain vs RAG-style branch tests; judge-failure exclusion test
  - Done: 5/5 tests pass. Verified against the installed deepeval 4.0.7
    directly (not assumed): FaithfulnessMetric._required_params confirms
    RAG-only status; metric construction requires an API key eagerly (even
    before any network call), so the judge is built with an explicit
    GPTModel(model, api_key) rather than relying on OPENAI_API_KEY being
    present in the process environment — an implicit-env-var footgun this
    project would otherwise have shipped with.
- [x] **T6 (P2, human: ~1h / CC: ~10min)** — sampler — Seeded, versioned dataset
  sampling
  - Surfaced by: D5
  - Files: `services/dataset_sampler.py`
  - Verify: same version → identical sample across repeated calls
  - Done: 7/7 tests pass — determinism, cross-order stability, oversized
    sample_size, version auto-increment, and DatasetVersionQuestion
    materialization all verified against a real (temp-file SQLite) DB.

## Phase 5: Async layer
- [ ] **T7 (P1, human: ~3h / CC: ~20min)** — workers — Celery task per
  (question, provider) pair with asyncio.run() bridge
  - Surfaced by: D1, D12
  - Files: `workers/eval_tasks.py`
  - Verify: test asserts N tasks enqueued for N pairs, not 1 per Run
- [ ] **T8 (P2, human: ~2h / CC: ~15min)** — cost — Cost service reading
  LiteLLM's pricing map, null (not zero) for unknown models
  - Surfaced by: D6, plus the cost-service gap noted in the failure-mode table
  - Files: `services/cost_service.py`
  - Verify: known-model test + explicit missing-model-returns-null test

## Phase 6: Arena/Elo
- [ ] **T9 (P1, human: ~2h / CC: ~15min)** — elo — Row-level locked Elo updates
  - Surfaced by: D4
  - Files: `services/elo_service.py`
  - Verify: test fires N concurrent comparisons, asserts final Elo reflects all N

## Phase 7: Regression engine
- [ ] **T10 (P2, human: ~3h / CC: ~20min)** — regression — RegressionRun pins
  dataset version; mismatched versions rejected as "not comparable"
  - Surfaced by: D7
  - Files: `services/regression_service.py`
  - Verify: same-version diff test + mismatched-version rejection test

## Phase 5 (cross-cutting): Caching
- [ ] **T11 (P2, human: ~2h / CC: ~15min)** — leaderboard — Redis cache for
  leaderboard aggregates, invalidated on EvaluationResult write
  - Surfaced by: D13
  - Files: `services/leaderboard_service.py`
  - Verify: test writes a result, asserts cache invalidated and next read fresh
