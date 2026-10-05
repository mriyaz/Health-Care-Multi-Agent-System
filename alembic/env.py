"""
alembic/env.py

Alembic environment configured for SQLAlchemy 2.x async engines.

This enables:
- asyncpg connectivity
- autogenerate based on SQLAlchemy metadata
- pulling DATABASE_URL from environment (Docker-friendly)
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig
from typing import Optional

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from api.settings import Settings
from db.base import Base

# Import models so Base.metadata is populated for autogenerate
import db.models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    """
    Resolve the database URL for Alembic.

    Priority:
    - DATABASE_URL environment variable (recommended for Docker)
    - Derived from Settings (POSTGRES_* vars)
    """
    env_url: Optional[str] = os.getenv("DATABASE_URL")
    if env_url:
        return env_url

    settings = Settings()
    return settings.get_async_database_url()


def run_migrations_offline() -> None:
    """
    Run migrations in offline mode (no DB connection).
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,  # detect type changes
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """
    Configure Alembic context and run migrations for a live connection.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """
    Run migrations in online mode using an async engine.
    """
    # Inject the dynamically resolved URL into Alembic's config dict.
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
