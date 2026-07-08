from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> AsyncEngine:
    """Lazy, cached engine construction. Import-time engine creation would
    force every module that imports app.core.database (including test
    collection) to have the Postgres driver installed even when running
    unit tests against SQLite — see tests/conftest.py."""
    settings = get_settings()
    return create_async_engine(settings.database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency. Cached per-request, so repositories sharing this
    dependency share one session/transaction (see plan-eng-review D8 note on
    session lifecycle)."""
    async with get_session_factory()() as session:
        yield session
