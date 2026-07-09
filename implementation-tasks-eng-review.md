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

## Phase 4: Minimal frontend + synchronous run execution
Not in the original T-list (D1-D13 were mostly backend-architecture decisions) —
added here because Phase 4 needed real backend wiring to be an actual "first
end-to-end demoable milestone," not just a frontend shell calling
not-yet-functional endpoints (which the office-hours design doc's "no
placeholder code" rule rules out).
- [x] **T8 (P2, human: ~2h / CC: ~15min)** — cost — Cost service reading
  LiteLLM's pricing map, null (not zero) for unknown models
  - Surfaced by: D6, plus the cost-service gap noted in the failure-mode table
  - Files: `services/cost_service.py`
  - Verify: known-model test + explicit missing-model-returns-null test
  - Done: pulled forward from Phase 5 — cheap once Phase 2 already verified
    litellm.model_cost is accessible, and leaving cost_usd permanently null
    on every Response would itself have been the placeholder-code anti-pattern.
    3/3 tests pass.
- [x] **T-orchestrator (P1)** — `services/run_orchestrator.py` — connects
  LLMRunner + EvaluationService + cost_service; persists Response/
  EvaluationResult rows per (question, model) pair; structured as one unit
  of work per pair already so Phase 5's Celery migration (D12) is mechanical.
  2/2 tests pass (full persistence + D3 failure isolation at orchestration level).
- [x] **T-leaderboard (P1)** — `api/routes/leaderboard.py` — public, no-auth
  GET endpoint aggregating per-model Elo/latency/cost/metric averages,
  excluding non-SUCCESS Responses (D3) and EvaluationResults (D9) from
  averages. 4/4 tests pass. Caught a real bug: `str(MetricName.TOXICITY)`
  returns `"MetricName.TOXICITY"`, not `"toxicity"` (standard `str,Enum`
  `__str__` behavior) — fixed to use `.value`.
- [x] **T-runs-wiring (P1)** — `api/routes/runs.py` — POST /runs now actually
  executes the orchestrator synchronously and returns the completed Run;
  `LLMRunner`/`EvaluationService` moved to FastAPI dependencies
  (`get_llm_runner`/`get_evaluation_service`) so tests can override them with
  fakes instead of making real provider/judge API calls. 6/6 tests pass.
- [x] **T-context (P1)** — `api/routes/context.py` — `GET /me/run-context` so
  the frontend never hardcodes project/dataset-version/model IDs. 3/3 tests pass.
- [x] **T-schema-fix (P1, cross-cutting)** — all 6 enum columns
  (Question.type, Run.status, Response.status, EvaluationResult.status/
  metric_name, Comparison.voter_type, RegressionRun.status) were using plain
  `String(N)`, which silently loses the Python enum type on every fresh load
  from the DB (returns a raw `str` — `==` comparisons still work via str
  equality, but `.value`/`isinstance()` would break, and did break in a test
  before the fix). Switched to `sqlalchemy.Enum(..., native_enum=False,
  length=N)`, verified to produce identical DDL (no migration change needed)
  while correctly round-tripping the enum type.
- [x] **T-frontend (P1)** — `frontend/` — Next.js 16 (App Router, TypeScript,
  Tailwind v4; design doc said "15," 16 is current stable as of this build —
  see AGENTS.md's breaking-changes note, checked before writing any page
  code). Public leaderboard page, login page (D10: no registration form
  anywhere), trigger-run panel with model selection + rate-limit error
  display. `useSyncExternalStore` for the auth token (not useState+useEffect
  — the newer `react-hooks/set-state-in-effect` lint rule correctly flagged
  that pattern as an anti-pattern for external stores). Builds, type-checks,
  and lints clean. CORS switched from a hardcoded port to a localhost regex
  after discovering an unrelated pre-existing app was already squatting port
  3000 on the dev machine, which would have silently broken CORS for anyone
  hitting the same collision.
  - Verify: full live smoke test — real backend (SQLite-substituted, no
    Postgres available in this sandbox) + real frontend dev server, curl
    against `/health`, `/leaderboard`, `/auth/login` (real JWT issued),
    `/me/run-context`, and a CORS preflight check, all passing against
    actually-running processes, not just mocked unit tests.

## Phase 5: Async layer
- [ ] **T7 (P1, human: ~3h / CC: ~20min)** — workers — Celery task per
  (question, provider) pair with asyncio.run() bridge
  - Surfaced by: D1, D12
  - Files: `workers/eval_tasks.py`
  - Verify: test asserts N tasks enqueued for N pairs, not 1 per Run

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
