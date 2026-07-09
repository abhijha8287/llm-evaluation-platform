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
- [x] **T-runs-wiring (P1)** — `api/routes/runs.py` — POST /runs executed the
  orchestrator synchronously via injected `LLMRunner`/`EvaluationService`
  FastAPI dependencies. **Superseded in Phase 5** — see T7 below;
  `get_llm_runner`/`get_evaluation_service` were removed from
  `core/deps.py` once nothing depended on them anymore.
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
- [x] **T7 (P1, human: ~3h / CC: ~20min)** — workers — Celery task per
  (question, provider) pair with asyncio.run() bridge
  - Surfaced by: D1, D12
  - Files: `workers/eval_tasks.py`
  - Verify: test asserts N tasks enqueued for N pairs, not 1 per Run
  - Done: `dispatch_run()` builds one `run_pair_task` signature per
    (question, model) pair under a `chord`, callback `mark_run_completed_task`
    fires only once every pair finishes. 4/4 unit tests pass (dispatch count/
    args, fresh-engine-per-task persistence, completion marking).
    `api/routes/runs.py` rewritten: POST /runs now validates, commits, and
    dispatches — returns immediately with `status: running`, no longer waits
    for execution. Added `GET /runs/{id}` for polling (D2: public, no auth).
    Also extracted `RunOrchestrator.mark_completed`/`load_sampled_questions`
    out to `RunRepository`/`QuestionRepository` — they never needed the
    LLM/eval dependencies, same smell as the earlier `mark_completed` fix,
    caught before it shipped as a `None`-dependency hack this time.
    **Verified with a real Celery worker** (`--pool=solo`, native Windows —
    Constraints' Docker-Linux-container requirement is the production
    target; solo pool is a pragmatic native smoke-test choice), real Redis,
    real Postgres: triggered a run via the live API, watched the worker log
    process 15 `run_pair` tasks (5 questions x 3 models) then fire the
    chord callback automatically, confirmed `GET /runs/1` reached
    `completed`, and queried Postgres directly to confirm all 15 Response
    rows persisted with `status=failed` (dummy API keys) and isolated,
    readable error messages — D3's failure isolation holding at the real
    infrastructure level, not just in mocks. Found and fixed along the way:
    reusing a cached async engine across separate `asyncio.run()` calls
    crashes outright (asyncpg connections are bound to the event loop that
    created them) — verified with a standalone repro before designing the
    fresh-engine-per-task pattern around it, not assumed.

## Phase 6: Arena/Elo
- [x] **T9 (P1, human: ~2h / CC: ~15min)** — elo — Row-level locked Elo updates
  - Surfaced by: D4
  - Files: `services/elo_service.py`
  - Verify: test fires N concurrent comparisons, asserts final Elo reflects all N
  - Done: 7/7 unit tests + 1 real-concurrency test against the actual
    Postgres container (SQLite's single-writer model would mask a broken
    lock, so this one specifically needs a real DB). Locks both LLMModel
    rows in ascending-id order regardless of comparison A/B order, avoiding
    a deadlock between concurrent comparisons on the same pair in reversed
    order. **Manually verified the test has teeth**: removed
    `.with_for_update()`, confirmed the concurrency test fails reliably
    (lost updates, off by 12-46 points across 3 runs), restored it, confirmed
    it passes reliably — did this twice across the session (once before, once
    after a later test-cleanup refactor accidentally introduced a bug, see
    below).
  - Schema: split `LLMModel.elo_rating` into `elo_rating_llm_judge` and
    `elo_rating_human` (new migration `ee326edbe45e`, backfills existing
    values, verified upgrade/downgrade against real Postgres) — the
    office-hours design doc's original Phase 6 spec calls for showing these
    separately, not blended.
- [x] **T-arena-judge (P1)** — `services/arena_judge.py` — blind LLM-judged
  pairwise comparison. Randomizes A/B slot assignment per call to control
  for judge position bias (a documented LLM-judge failure mode), and maps
  the verdict back through that randomization to the correct model —
  `services/arena_service.py` has 5/5 tests specifically covering all four
  swapped/unswapped × A/B combinations, since a naive implementation could
  silently misattribute wins under the swap case.
- [x] **T-arena-dispatch (P1)** — `workers/eval_tasks.py` — after a Run's
  chord completes, dispatches one `arena_judge_pair_task` per unique model
  pair per question among SUCCESSFUL responses only (C(N,2) pairs for N
  successful models on a question; 0 for a question with <2 successes).
  6/6 tests pass.
- [x] **T-arena-routes (P1)** — `api/routes/arena.py` — `GET
  /arena/next-comparison` (blind pairing, D2: public/no-auth since voting
  is zero-cost) + `POST /arena/vote` (human votes, project_id derived from
  the response's Run server-side, never trusted from the client). 6/6 tests
  pass.
  - **Verified live**: real backend + real Postgres, seeded two genuine
    successful responses, fetched a real blind comparison via curl (payload
    confirmed to carry no model_id/provider), cast a real vote, confirmed
    `elo_rating_human` moved and `elo_rating_llm_judge` didn't (D4/Phase 6
    isolation holding through the actual HTTP+DB path).
  - Found and fixed along the way: `test_concurrent_comparisons_no_lost_updates`
    runs against the real persistent dev Postgres and was leaving permanent
    debris (phantom users/models/comparisons) on every run — added
    cleanup via a `finally` block; caught via this session's live smoke
    test, which surfaced 16 accumulated phantom models. A subsequent edit
    to add that cleanup briefly left 3 lines of the test's own assertions
    dangling outside the `try/finally` structure (using a closed session) —
    caught immediately by running the test, not left in the codebase.
- [x] **T-leaderboard-elo-split (P1)** — `api/routes/leaderboard.py` +
  frontend — leaderboard shows `elo_rating_llm_judge`/`elo_rating_human`
  as two columns with comparison counts alongside (a bare Elo number with
  no sample size is misleading — one win swings it by K_FACTOR=32).
  2/2 new tests pass.
- [x] **T-frontend-arena (P1)** — `frontend/app/arena/page.tsx` — blind
  voting UI (fetch comparison → vote A/B/Tie → see result → next). Builds,
  type-checks, lints clean. Two more `set-state-in-effect`/exhaustive-deps
  issues fixed properly (split fetch-vs-reset responsibilities between the
  Effect and the button handler; extracted a derived variable instead of a
  conditional expression in a dependency array) rather than suppressed —
  same pattern as Phase 4's auth-token fix.

## Phase 7: Regression engine
- [x] **T10 (P2, human: ~3h / CC: ~20min)** — regression — RegressionRun pins
  dataset version; mismatched versions rejected as "not comparable"
  - Surfaced by: D7
  - Files: `services/regression_service.py`
  - Verify: same-version diff test + mismatched-version rejection test
  - Done: 5/5 tests pass, including the exact D7 claim (baseline from a
    different dataset_version → NOT_COMPARABLE, delta_from_baseline stays
    null, never silently diffed) and a no-prior-baseline-run case.
  - **Schema gap found and fixed before writing any service code**: the
    original Phase 1 `RegressionRun` had no `model_id` — a prompt-version
    regression comparison is only meaningful with the model held constant
    while the prompt changes; the original spec would have let a prompt
    "regression" actually be an undetected model-choice difference. Added
    `model_id` + `run_id` (migration `b141057e6263`, verified upgrade/
    downgrade against real Postgres). `run_id` was the bigger architectural
    call: rather than building a parallel response-generation path,
    RegressionRun points at a real `Run` executed through the EXISTING
    RunOrchestrator/Celery pipeline (D8/D12) — `RunOrchestrator.run_pair`
    gained an optional `prompt_override` parameter (3/3 new tests) as the
    only change needed to reuse it. `PromptService` renders `{question}`
    templates, validated at creation time, not render time (a broken
    template is caught immediately, not mid-run after real API calls have
    already been made against other questions) — 4/4 tests pass.
  - **Second correctness gap found and fixed**: reusing the real Run
    pipeline for regression means regression responses would otherwise leak
    into the main leaderboard's per-model averages — a prompt-engineering
    test's scores silently corrupting "how good is this model normally"
    stats. Added an explicit exclusion filter in `leaderboard.py`
    (`Response.run_id.not_in(select(RegressionRun.run_id))`), caught before
    any regression run ever executed, not after the pollution was observed.
  - API: `api/routes/prompts.py` (template/version CRUD, auth required but
    no rate limit — creating a template costs nothing) + `api/routes/
    regression.py` (create + poll, reusing `enforce_run_rate_limit` directly
    since RegressionService.create_run's underlying Run is counted by the
    same per-project daily cap D2 already enforces). 10/10 route tests pass.
  - Per the original design doc, the "Prompt Testing"/"Regression Results"
    **frontend pages are explicitly Phase 8 scope** ("the backend the...
    pages render") — not built this phase, backend-only.
  - **Verified live**: real backend + real Celery worker + real Postgres —
    created a real prompt template/version via the API, triggered a real
    regression run, watched the worker process `regression_pair` tasks and
    fire `mark_regression_completed`, confirmed `status: completed` with 5
    responses correctly recorded as FAILED (dummy API keys, D3 isolation
    holding) via a direct Postgres query, and confirmed the leaderboard
    shows `response_count: 0` for the affected model.
  - 109/109 backend tests passing after this phase.

## Phase 5 (cross-cutting): Caching
- [x] **T11 (P2, human: ~2h / CC: ~15min)** — leaderboard — Redis cache for
  leaderboard aggregates, invalidated on EvaluationResult write
  - Surfaced by: D13
  - Files: `services/leaderboard_cache.py`
  - Verify: test writes a result, asserts cache invalidated and next read fresh
  - Done: 4/4 cache-module tests + 1 leaderboard-serving-stale-data-from-
    cache test pass, all against the real Redis container (docker-compose),
    not mocked. Fails open (cache-miss behavior, never a 500) if Redis is
    unreachable — tested by pointing the client at a dead port. Write-
    invalidation only, no TTL yet (TODOS.md item 2 — deferred correctly,
    the trigger condition "second write path" still hasn't occurred).
    Real bug caught along the way: `str(MetricName.TOXICITY)` renders as
    `"MetricName.TOXICITY"`, not `"toxicity"` — fixed in leaderboard.py
    during this phase's cache wiring (see T-leaderboard above).

## Phase 8: Full dashboard
- [x] **T12 (P1, human: ~1h / CC: ~10min)** — schema/scoring — `EvaluationResult.passed`
  captured from DeepEval's own `metric.success`, not reimplemented
  - Surfaced by: the new Pass Rate chart needs pass/fail data this schema never
    stored — every prior phase only kept the raw score.
  - Files: `models/evaluation_result.py`, `evaluation/scoring_service.py`,
    `services/run_orchestrator.py`, migration `ac9ab3ff3011`
  - Verify: direct `inspect.getsource` on the installed DeepEval's four metric
    classes to confirm pass/fail direction per metric before writing code
    against it (not assumed)
  - Done: verified via source inspection that Faithfulness/AnswerRelevancy
    pass when `score >= threshold` but Toxicity/Bias pass when
    `score <= threshold` — captured `metric.success` directly rather than
    reimplementing that direction logic (a real place to get it backwards).
    Migration verified upgrade/downgrade/re-upgrade against real Postgres.
    6/6 scoring-service tests pass (including a dedicated
    `passed=False`-below-threshold case using a new fake with
    `self.success = False`, not just the happy path).
- [x] **T13 (P1, human: ~6h / CC: ~40min)** — api — Read-only list/aggregation
  endpoints backing every new dashboard page
  - Surfaced by: design doc Phase 8 — "remaining pages... charts" needed real
    endpoints; none of the prior phases' single-resource GETs were list shaped.
  - Files: `api/routes/catalog.py` (Projects/Datasets/Questions),
    `api/routes/dashboard.py` (`GET /dashboard/trends`), plus list additions to
    `runs.py`, `prompts.py`, `regression.py`; new `repositories/dataset_repository.py`
  - Surfaced by D2 during design: every new list endpoint is public/no-auth,
    consistent with the existing leaderboard/GET-run/GET-regression-run
    pattern — there is no per-user data isolation concern on a single-demo-user
    public deploy (D10), so gating reads behind auth here would be
    inconsistent with every prior phase's read/write split.
  - `GET /dashboard/trends?project_id=` returns one point per (run, model)
    pair — latency/cost/pass-rate/metric averages — the single data source
    every trend chart on Experiment History reads from, filtered client-side
    per chart rather than one bespoke endpoint per chart.
  - `GET /runs`, `GET /prompt-templates`, `GET /regression-runs` (list forms)
    all exclude/scope consistently with existing rules already established in
    earlier phases (regression-run-owned runs excluded from both the plain
    runs list and the trends endpoint, same rationale as leaderboard.py's
    existing exclusion filter).
  - Verify: `pytest tests/test_catalog_routes.py tests/test_dashboard_routes.py
    tests/test_runs.py tests/test_prompt_routes.py tests/test_regression_routes.py`
  - Done: 14 new route tests, all passing (124/124 full suite, zero
    regressions). Live-verified against real Postgres: every new endpoint
    curled directly, correct shapes returned; full authenticated write path
    exercised end-to-end (login → create prompt template → create version →
    trigger regression run → list it back) against the real backend, not
    mocked.
- [x] **T14 (P1, human: ~10h / CC: ~1h)** — frontend — Remaining dashboard
  pages: Projects, Datasets, Model Comparison, Experiment History, Prompt
  Testing, Regression Results, Settings; Recharts charts
  - Surfaced by: design doc Phase 8 explicitly lists these seven pages as the
    "full dashboard" scope, plus TODOS.md item 3 (dataset version UI).
  - Judgment call carried from earlier planning: "Evaluation Runs" (the
    trigger-a-run flow, already live on the homepage since Phase 4) merged
    into "Experiment History" as one page rather than two, since triggering
    and reviewing runs are the same workflow — not challenged by the user, so
    kept.
  - Files: `frontend/app/{projects,datasets,models,history,prompts,regression,
    settings}/page.tsx`, `frontend/components/Header.tsx` (nav), `frontend/lib/
    {types,api}.ts` (new endpoint bindings), `recharts` added as a dependency
  - Model Comparison: a Recharts radar chart across all four DeepEval metrics
    at once, plus latency/cost bar charts — same `metric_averages` shape the
    leaderboard already computes, visualized rather than a new backend
    concept.
  - Experiment History: runs table + four trend line charts (Latency, Cost,
    Pass Rate, Faithfulness) pivoted client-side from `GET /dashboard/trends`
    into one series per model.
  - Prompt Testing: template/version CRUD (auth-gated) plus a regression-run
    trigger form reusing `GET /me/run-context` for the model/dataset-version
    picker — no new backend concept, just a UI over Phase 7's engine.
  - Regression Results: per-template run history, expandable per-question
    metric/delta table; a `not_comparable` status renders visibly (D7), never
    silently as a diff.
  - Datasets: TODOS.md item 3 resolved here — every dataset version listed
    individually (number, sample size, seed date), not collapsed into a count.
  - Settings: kept deliberately minimal — D10 means there are no real
    per-user preferences to configure; session status, rate-limit policy
    note, and the model roster are the genuinely useful content, not filler
    controls with nothing behind them.
  - Verify: `npx tsc --noEmit`, `npx eslint .`, `npm run build`
  - Done: clean typecheck, zero lint errors/warnings, all 11 routes
    statically prerender successfully. No browser-automation tool was
    available in this environment (WebFetch cannot reach localhost) — UI
    interaction was NOT visually verified in an actual browser. Verified
    instead via: full-stack live smoke test against real Postgres/Redis/
    Celery (see T13), the exact authenticated write path every write-capable
    page uses (login → create template → create version → trigger regression
    run) exercised end-to-end via curl and confirmed to return the shapes the
    TypeScript components destructure, plus a real Celery worker run that
    surfaced a genuine dev-environment gap (no `.env`/API keys configured,
    `openai_api_key` defaults to `""`) — a pre-existing environment
    limitation unrelated to this phase's code, not a regression.
