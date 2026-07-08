import os
import tempfile
import uuid

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - populates Base.metadata; must import before any create_all
from app.core.database import Base, get_session

# SQLite in-memory for schema/model tests (Task T1). Postgres-specific
# behavior (row-level locking for D4's Elo updates, etc.) is exercised
# separately once a real Postgres test fixture exists — see TODOS and
# tests/test_elo_service.py once Phase 6 lands.
#
# A temp FILE, not `:memory:` — `:memory:` + StaticPool + pytest-asyncio
# hit a real event-loop-scope gotcha here: fixture setup (async_engine's
# CREATE TABLE) and the test body ended up on different event loops, so
# aiosqlite's connection (bound to the loop it was created on) silently saw
# an empty database from the test's loop. A temp file sidesteps the whole
# class of problem since any connection can open the same file fresh.


@pytest_asyncio.fixture
async def async_engine():
    db_path = os.path.join(tempfile.gettempdir(), f"llm_eval_test_{uuid.uuid4().hex}.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest_asyncio.fixture
async def session_factory(async_engine):
    return async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)


@pytest_asyncio.fixture
async def db_session(session_factory) -> AsyncSession:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def test_client(session_factory):
    """FastAPI app wired to the SQLite test DB via a get_session override.
    Does NOT run the production lifespan (which seeds via a Postgres-backed
    engine) — see the seeded_demo_user fixture for the test-DB equivalent."""
    from app.main import app

    async def override_get_session():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded_demo_user(session_factory):
    from app.core.seed_data import seed_demo_user

    async with session_factory() as session:
        user = await seed_demo_user(session, password="test-password")
        return user
