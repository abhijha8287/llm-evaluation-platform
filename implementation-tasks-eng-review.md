# Implementation Tasks

Synthesized from /plan-eng-review (2026-07-09). Each task derives from a specific
decision above. Run with Claude Code; checkbox as you ship. jq unavailable this
session, so no JSONL artifact was written for /autoplan aggregation — install jq
if you want that later.

## Phase 1: Schema
- [ ] **T1 (P1, human: ~3h / CC: ~20min)** — schema — Create all tables with
  open-domain/RAG-style Question type split, Response.status,
  EvaluationResult.status, dataset version fields
  - Surfaced by: D3, D5, D7, D9 — status fields and versioning must exist from
    the first migration, not retrofitted
  - Files: `models/*.py`, `migrations/`
  - Verify: `alembic upgrade head` runs clean; a test seeds one row per table

## Phase 2: Backend core
- [ ] **T2 (P1, human: ~4h / CC: ~30min)** — llm — LiteLLM runner with
  per-provider Response.status transitions (success/timeout/failed)
  - Surfaced by: D3
  - Files: `llm/runner.py`, `tests/test_runner.py`
  - Verify: `pytest tests/test_runner.py` covers success/timeout/error/isolation
- [ ] **T3 (P1, human: ~2h / CC: ~15min)** — auth — Login-only JWT auth, single
  seeded demo user, no public registration endpoint
  - Surfaced by: D10
  - Files: `api/routes/auth.py`, `core/seed_data.py`
  - Verify: registration route returns 404/disabled; login issues valid JWT
- [ ] **T4 (P1, human: ~1h / CC: ~10min)** — api — Rate limit on trigger-run
  endpoint, enforced regardless of auth state
  - Surfaced by: D2
  - Files: `api/routes/runs.py`
  - Verify: test fires 4 requests, 4th is rejected

## Phase 3: Evaluation engine
- [ ] **T5 (P1, human: ~4h / CC: ~30min)** — evaluation — Shared
  EvaluationService (question-type-aware metric selection, judge failure status)
  - Surfaced by: D8, D9
  - Files: `evaluation/scoring_service.py`, `tests/test_scoring_service.py`
  - Verify: open-domain vs RAG-style branch tests; judge-failure exclusion test
- [ ] **T6 (P2, human: ~1h / CC: ~10min)** — sampler — Seeded, versioned dataset
  sampling
  - Surfaced by: D5
  - Files: `services/dataset_sampler.py`
  - Verify: same version → identical sample across repeated calls

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
