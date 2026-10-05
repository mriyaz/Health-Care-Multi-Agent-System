"""
db/session.py

Async SQLAlchemy engine + session management.

This module exposes helpers used by both FastAPI dependencies and Alembic.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from api.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """
    Create an async SQLAlchemy engine for PostgreSQL via asyncpg.
    """
    database_url = settings.get_async_database_url()

    # pool_pre_ping helps avoid stale connections in long-running services.
    return create_async_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """
    Create a session factory for async sessions.
    """
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_db_session(settings: Settings) -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields an AsyncSession.

    Usage:
        async def route(db: AsyncSession = Depends(get_db_session)): ...
    """
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        yield session
