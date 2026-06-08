"""Alembic environment configuration - async-aware for the SaaS layer."""

import asyncio
import re

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

target_metadata = None
# TODO: Set to your SQLAlchemy Base.metadata for auto-detection.
#   from saas.database import Base
#   target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    context.configure(
        url=context.config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine."""
    asyncio.run(run_async_migrations_online())


async def run_async_migrations_online() -> None:
    """Create an async engine and run migrations."""
    url = context.config.get_main_option("sqlalchemy.url")
    # The alembic.ini ships with a sync postgresql:// URL.  Convert it to
    # postgresql+asyncpg:// so that create_async_engine can use asyncpg
    # without requiring psycopg2.
    if url.startswith("postgresql://") and "+" not in url:
        url = re.sub(r"^postgresql://", "postgresql+asyncpg://", url, count=1)
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        await conn.run_sync(do_run_migrations)
    await engine.dispose()


def do_run_migrations(connection) -> None:
    """Configure the migration context with a live connection."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()