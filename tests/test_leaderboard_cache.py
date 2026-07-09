"""Tests against the real Redis container (docker-compose) — verifies the
actual round-trip and D13's fail-open behavior when Redis is unreachable,
not just mocked calls. Requires `docker compose up -d redis`; skipped
automatically if Redis isn't reachable so the rest of the suite still runs
without Docker."""

import pytest
import redis.exceptions

from app.services import leaderboard_cache


@pytest.fixture(autouse=True)
async def _require_redis():
    try:
        client = leaderboard_cache._get_client()
        await client.ping()
        await client.aclose()
    except redis.exceptions.RedisError:
        pytest.skip("Redis not reachable — run `docker compose up -d redis`")


@pytest.fixture(autouse=True)
async def _clean_cache():
    yield
    await leaderboard_cache.invalidate_leaderboard_cache()


async def test_cache_miss_returns_none():
    await leaderboard_cache.invalidate_leaderboard_cache()
    assert await leaderboard_cache.get_cached_leaderboard() is None


async def test_set_then_get_round_trips():
    entries = [{"model_id": 1, "display_name": "GPT-4o mini", "metric_averages": {"toxicity": 0.05}}]
    await leaderboard_cache.set_cached_leaderboard(entries)
    cached = await leaderboard_cache.get_cached_leaderboard()
    assert cached == entries


async def test_invalidate_clears_the_cache():
    await leaderboard_cache.set_cached_leaderboard([{"model_id": 1, "display_name": "X"}])
    await leaderboard_cache.invalidate_leaderboard_cache()
    assert await leaderboard_cache.get_cached_leaderboard() is None


async def test_unreachable_redis_fails_open_not_closed(monkeypatch):
    """D13: Redis is a performance layer, not the source of truth — an
    unreachable cache must degrade to a cache miss, never raise and break
    the leaderboard endpoint."""
    from redis import asyncio as aioredis

    def broken_client(url: str) -> aioredis.Redis:
        return aioredis.from_url("redis://localhost:1/0", socket_connect_timeout=1)

    monkeypatch.setattr(leaderboard_cache, "_get_client", lambda: broken_client(""))

    assert await leaderboard_cache.get_cached_leaderboard() is None
    await leaderboard_cache.set_cached_leaderboard([{"x": 1}])  # must not raise
    await leaderboard_cache.invalidate_leaderboard_cache()  # must not raise
