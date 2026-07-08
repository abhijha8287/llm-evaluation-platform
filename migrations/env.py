import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings
from app.core.database import Base

# Import every model module so Base.metadata is fully populated before
# autogenerate compares it against the live database — a bare `from
# app.models import *` at module scope is easy to accidentally miss a new
# model file, so this list is explicit and mirrors app/models/__init__.py.
from app.models import (  # noqa: F401
    comparison,
    dataset,
    evaluation_result,
    llm_model,
    project,
    prompt,
    question,
    regression,
    response,
    run,
    user,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    # Source of truth is app.core.config.Settings (env vars / .env), never a
    # URL hardcoded in alembic.ini.
    return get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable: AsyncEngine = create_async_engine(get_url())
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
