import json

from redis import asyncio as aioredis
from redis import exceptions as redis_exceptions

from app.core.config import get_settings

# eng-review D13: leaderboard is read-heavy (D2's rate limit caps writes to a
# handful/day) and Redis is already deployed for Celery's broker — caching
# the aggregate here is a real Redis use beyond message brokering, not just
# an idle service.
_CACHE_KEY = "leaderboard:v1"


def _get_client() -> aioredis.Redis:
    return aioredis.from_url(get_settings().redis_url)


async def get_cached_leaderboard() -> list[dict] | None:
    """Redis is a performance layer, not the source of truth — if it's
    unreachable, this degrades to "cache miss" (caller falls back to a
    direct DB query) rather than failing the whole leaderboard request."""
    client = _get_client()
    try:
        raw = await client.get(_CACHE_KEY)
    except redis_exceptions.RedisError:
        return None
    finally:
        await client.aclose()
    if raw is None:
        return None
    return json.loads(raw)


async def set_cached_leaderboard(entries: list[dict]) -> None:
    client = _get_client()
    try:
        await client.set(_CACHE_KEY, json.dumps(entries))
    except redis_exceptions.RedisError:
        pass
    finally:
        await client.aclose()


async def invalidate_leaderboard_cache() -> None:
    """Called after every new EvaluationResult write (D13's write-
    invalidation) — see app/workers/eval_tasks.py. No TTL backstop yet: the
    only write path is this one, so a TTL would be redundant insurance
    against a bug that doesn't have anywhere to hide yet. Add one (TODOS.md
    item 2) once a second write path to EvaluationResults exists."""
    client = _get_client()
    try:
        await client.delete(_CACHE_KEY)
    except redis_exceptions.RedisError:
        pass
    finally:
        await client.aclose()
