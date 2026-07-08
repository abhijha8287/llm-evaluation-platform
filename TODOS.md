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

## 3. Dataset version management UI
**What:** D5 (seeded sampling) and D7 (regression snapshot pinning) introduced
dataset versioning as a backend concept. No UI exists to view, compare, or manage
dataset versions — currently only queryable directly in Postgres.
**Why:** makes the versioning system (a real eval-methodology strength) visible and
demoable, not just correct under the hood.
**Trigger:** natural fit for Phase 8 (Full dashboard) — fold into the existing
Datasets page work when that phase starts.
**Depends on:** D5/D7's versioning schema (Phase 1/7).
