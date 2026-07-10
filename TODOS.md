# TODOs

Deferred work captured during `/plan-eng-review` (2026-07-09). Not blocking — revisit
when the trigger condition below is met.

## 1. Shared/distributed event loop for Celery workers
**What:** D1's `asyncio.run()`-per-task pattern spins a fresh event loop for every
Celery task. Fine at solo-portfolio scale; wasteful at real production volume.
**Why:** if this project ever handled real concurrent load, a shared event loop
(async-native Celery worker, or a different task-execution model) would cut overhead.
**Trigger:** revisit only if this moves beyond a portfolio demo into something with
real concurrent traffic.
**Depends on:** nothing — purely additive later, no current code needs to change to
support it.

## 2. Redis TTL as safety net for leaderboard cache
**What:** D13 chose write-invalidation only for the leaderboard cache (invalidate on
new EvaluationResult write). No time-based expiry as a backstop.
**Why:** if a future write path (e.g. a bulk-import feature) forgets to invalidate,
the cache could go stale indefinitely with no self-correction.
**Trigger:** add once a second write path to EvaluationResults exists beyond the
Phase 5 eval pipeline.
**Depends on:** D13's write-invalidation cache landing first (Phase 5).

## 3. Dataset version management UI — DONE (Phase 8)
Resolved: the Datasets page (`frontend/app/datasets/page.tsx`) lists every version of
each dataset individually (version number, sample size, seeded date), not just a
collapsed count. Comparing versions' *scores* (not just metadata) is naturally covered
by Experiment History / Regression Results instead, since D5/D7 already scope
Runs/RegressionRuns to one dataset_version_id each.

## 4. `run_pair_task` constructs the judge model before the provider call — DONE (fixed 2026-07-10)
**Fix applied:** `EvaluationService.__init__` no longer constructs `GPTModel` eagerly —
construction is now deferred to `_get_judge()`, called lazily inside `score_response`'s
existing per-metric try/except (`app/evaluation/scoring_service.py`). A construction
failure (bad/empty judge key) now degrades to `EvaluationStatus.FAILED` for every
applicable metric, exactly like any other judge-call failure, instead of raising out of
`__init__` and crashing the whole Celery task before `LLMRunner.run()` ever executes.
Construction is attempted at most once per `EvaluationService` instance (success or
failure both cached via `self._judge`/`self._judge_construction_error`) so a
persistently bad key doesn't retry `GPTModel` construction once per metric — verified
by a dedicated test that patches `GPTModel` and asserts it's called exactly once across
4 applicable metrics.
**Verified live, not just in unit tests**: restarted the real Celery worker with no
`OPENAI_API_KEY` set (the exact broken state from before) and dispatched a real
`run_pair` task. Before the fix this produced a `ChordError` wrapping `DeepEvalError`
with zero `llm_provider_calls_total` samples ever recorded. After the fix: `LiteLLM
completion()` was actually attempted, the task completed `SUCCESS` at the Celery level,
`llm_provider_calls_total{model="gpt-4o-mini",status="failed"}` recorded correctly, and
a real `Response` row was persisted with `status=FAILED` and a real
`AuthenticationError` message — proving D3's provider-isolation guarantee now holds
even when the judge key is missing, instead of the whole run silently never producing
any responses at all.
**Tests:** 3 new tests in `tests/test_scoring_service.py`
(`test_construction_with_empty_api_key_does_not_raise`,
`test_empty_api_key_degrades_every_applicable_metric_to_failed_not_a_crash`,
`test_judge_construction_failure_is_cached_not_retried_per_metric`) — 135/135 full
backend suite passing, `ruff check` clean.

<details>
<summary>Original finding (superseded by the fix above)</summary>

**What:** found via Phase 9's live metrics verification (not a hypothetical). In
`app/workers/eval_tasks.py`'s `_run_pair_async`/`_regression_pair_async`,
`EvaluationService(...)` (which eagerly constructs DeepEval's `GPTModel` and raises
`DeepEvalError` immediately if `judge_api_key` is empty/invalid at construction time —
see Phase 3's eng-review note) is built *before* `orchestrator.run_pair()` — and
therefore before `LLMRunner.run()` — ever executes. A judge-model construction failure
currently crashes the whole Celery task before any provider call happens, taking down
every other (question, model) pair in the same chord with a `ChordError` — confirmed
live: an empty `openai_api_key` produced a `ChordError` wrapping `DeepEvalError`, and
zero `llm_provider_calls_total` metric samples were ever recorded, because
`LLMRunner.run()` was never reached.
**Why this matters:** it's a real violation of this project's own stated isolation
philosophy — D3 says one failed provider call must never block the others; D9 says one
failed judge call must never block the others. But a *judge construction* failure
currently blocks *everything*, including responses that would have succeeded and never
needed the judge to construct successfully at that point in the flow. The fix is
straightforward: construct `LLMRunner`/call `orchestrator.run_pair`'s provider step
before constructing `EvaluationService`, or construct `EvaluationService` lazily
(only right before `score_response` is actually called, which `run_pair` already skips
entirely when `result.status != SUCCESS`) — see `app/services/run_orchestrator.py`'s
`run_pair`.
**Confirmed the metrics/fix-adjacent parts DO work correctly once this ordering isn't
in the way**: dispatching a task directly against a worker process with a non-empty
(dummy) `OPENAI_API_KEY` let `LLMRunner.run()` execute and fail gracefully against the
real provider (`llm_provider_calls_total{model="claude-haiku-4-5",status="failed"}`),
with the Celery task itself completing `SUCCESS` — D3's isolation holds correctly once
judge construction isn't gating it.
**Trigger:** worth fixing independent of Phase 9/10 — this is a live-run reliability
bug, not a monitoring or deployment concern. Flagged to the user at the end of Phase 9
rather than fixed silently, since it changes production orchestration behavior.
**Depends on:** nothing — isolated to `run_orchestrator.py`/`eval_tasks.py`.

</details>
